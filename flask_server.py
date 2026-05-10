#!/usr/bin/env python3
"""
Voice AI Tools - Flask Backend
Endpoints: /health /tts /presets /log /shodan /analyze_pdf /train /model_status

Env vars:
  GOOGLE_API_KEY        - Gemini API key (for TTS) [required]
  VOICE_SERVER_TOKEN    - shared secret (X-Token header) [required]
  SHODAN_API_KEY        - Shodan API key (optional)
  ALLOWED_ORIGINS       - comma-separated extra CORS origins (e.g. extension IDs)
  PORT                  - bind port (default 5000)
  ALLOW_NETWORK_BINDING - set to "1" to allow non-loopback HOST (unsafe; logs a warning)
  HOST                  - bind address, only honoured when ALLOW_NETWORK_BINDING=1
"""

import os, io, re, json, time, wave, tempfile, importlib, sys
from pathlib import Path
from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ── optional heavy deps ───────────────────────────────────────────────
try:
    import requests as _requests
except ImportError:
    _requests = None

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from tts_engine import synthesize_speech
except ImportError:
    synthesize_speech = None

try:
    from voice_config import get_voice_for_context as _default_voice_fn
except ImportError:
    _default_voice_fn = None

# ── config ────────────────────────────────────────────────────────────
VOICE_SERVER_TOKEN = os.environ.get("VOICE_SERVER_TOKEN", "")
SHODAN_API_KEY     = os.environ.get("SHODAN_API_KEY", "")
MAX_TEXT_LENGTH    = 2000
PRESET_PATH        = Path("voice_presets.json")
LOG_PATH           = Path("session_log.json")
MODEL_DIR          = Path("voice_model")
SAMPLES_DIR        = Path("voice_samples")
SAMPLES_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

# ── token guard ───────────────────────────────────────────────────────
# Require a token for all protected endpoints.  An empty token is treated as
# "not configured" and every request is rejected with 401 so the server is
# secure by default.
if not VOICE_SERVER_TOKEN:
    print(
        "WARNING: VOICE_SERVER_TOKEN is not set.  All requests to protected "
        "endpoints will be rejected with HTTP 401.  Set the env var before "
        "starting the server:\n"
        "  export VOICE_SERVER_TOKEN='choose-a-strong-random-secret'",
        file=sys.stderr,
    )

# ── CORS ──────────────────────────────────────────────────────────────
# Exact localhost origins only.  No wildcard patterns, no "null" origin.
# Users who need to allow a specific Chrome extension can add its origin
# (e.g. "chrome-extension://abcdef...") via the ALLOWED_ORIGINS env var.
_extra_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5000",
    "http://localhost:5000",
] + _extra_origins

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB max upload
CORS(app, origins=ALLOWED_ORIGINS, allow_headers=["Content-Type", "X-Token"])
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per minute"])

# ── auth ──────────────────────────────────────────────────────────────
def _check_token() -> bool:
    """Return True only when a token is configured AND the request supplies it."""
    if not VOICE_SERVER_TOKEN:
        # No token configured → always deny protected endpoints.
        return False
    return request.headers.get("X-Token", "") == VOICE_SERVER_TOKEN

# ── voice-settings resolution ─────────────────────────────────────────
def _resolve_voice_settings(call_type: str) -> dict:
    """Return a voice-settings dict for *call_type*.

    Resolution order:
    1. ``custom_voice_config.get_custom_voice_settings(call_type)`` – written by
       voice_training.py when the user trains a custom voice.
    2. ``voice_config.get_voice_for_context(call_type)`` – built-in presets.
    3. Hard-coded default (Kore).

    Any exception from user-supplied config is caught so a malformed
    ``custom_voice_config.py`` never crashes ``/tts``.
    """
    # 1. Try custom voice config
    try:
        custom = importlib.import_module("custom_voice_config")
        fn = getattr(custom, "get_custom_voice_settings", None)
        if callable(fn):
            result = fn(call_type)
            if isinstance(result, dict) and result:
                return result
    except Exception:
        pass

    # 2. Fall back to built-in voice config
    try:
        if callable(_default_voice_fn):
            result = _default_voice_fn(call_type)
            if isinstance(result, dict) and result:
                return result
    except Exception:
        pass

    # 3. Hard-coded default
    return {"voice_id": "Kore"}

# ── /health ───────────────────────────────────────────────────────────
@app.route("/health")
def health():
    # /health is intentionally open (no token required) so monitoring tools
    # and the extension's connection check can reach it.
    return jsonify({"status": "ok", "model": _model_status()})

# ── /tts ──────────────────────────────────────────────────────────────
@app.route("/tts", methods=["POST"])
@limiter.limit("30 per minute")
def tts():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400
    if len(text) > MAX_TEXT_LENGTH:
        return jsonify({"error": "Text too long"}), 400
    if synthesize_speech is None:
        return jsonify({"error": "TTS engine not available"}), 503
    try:
        call_type = data.get("call_type", "LEGITIMATE")
        voice_settings = _resolve_voice_settings(call_type)
        audio_bytes, mime_type, error, _ = synthesize_speech(text, voice_settings)
        if error:
            return jsonify({"error": error}), 500
        return Response(audio_bytes, mimetype=mime_type or "audio/wav")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── /presets ──────────────────────────────────────────────────────────
@app.route("/presets", methods=["GET", "POST"])
@limiter.limit("60 per minute")
def presets():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    if request.method == "GET":
        try:
            with open(PRESET_PATH) as f:
                return jsonify(json.load(f))
        except Exception:
            return jsonify({"presets": []})
    data = request.get_json(silent=True)
    if not data or not data.get("name"):
        return jsonify({"error": "Preset needs a name"}), 400
    presets_list = []
    if PRESET_PATH.exists():
        with open(PRESET_PATH) as f:
            presets_list = json.load(f).get("presets", [])
    existing = next((i for i, p in enumerate(presets_list) if p.get("name") == data["name"]), None)
    if existing is not None:
        presets_list[existing] = data
    else:
        presets_list.append(data)
    with open(PRESET_PATH, "w") as f:
        json.dump({"presets": presets_list}, f, indent=2)
    return jsonify({"ok": True})

# ── /log ──────────────────────────────────────────────────────────────
@app.route("/log", methods=["GET", "POST"])
@limiter.limit("120 per minute")
def log_endpoint():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    if request.method == "GET":
        try:
            with open(LOG_PATH) as f:
                return jsonify(json.load(f))
        except Exception:
            return jsonify({"entries": []})
    entry = request.get_json(silent=True) or {}
    entries = []
    if LOG_PATH.exists():
        try:
            with open(LOG_PATH) as f:
                entries = json.load(f).get("entries", [])
        except Exception:
            pass
    if entry.get("action") == "clear":
        entries = []
    else:
        entry["timestamp"] = entry.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ"))
        entries.insert(0, entry)
        if len(entries) > 500:
            entries = entries[:500]
    with open(LOG_PATH, "w") as f:
        json.dump({"entries": entries}, f, indent=2)
    return jsonify({"ok": True})

# ── /shodan ───────────────────────────────────────────────────────────
@app.route("/shodan")
@limiter.limit("10 per minute")
def shodan():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    ip = request.args.get("ip", "").strip()
    if not ip:
        return jsonify({"error": "ip param required"}), 400
    if not SHODAN_API_KEY:
        return jsonify({"error": "SHODAN_API_KEY not set on server"}), 503
    if _requests is None:
        return jsonify({"error": "requests library not installed"}), 503
    try:
        r = _requests.get(
            f"https://api.shodan.io/shodan/host/{ip}",
            params={"key": SHODAN_API_KEY},
            timeout=10
        )
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── /analyze_pdf ──────────────────────────────────────────────────────
@app.route("/analyze_pdf", methods=["POST"])
@limiter.limit("10 per minute")
def analyze_pdf():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    raw = f.read()
    result = {"metadata": {}, "links": [], "ips": [], "suspicious": False, "pages": 0}
    ip_pattern = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
    url_pattern = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+', re.I)
    suspicious_keywords = ["eval(", "javascript:", "/launch", "/aa", "/openaction", "cmd.exe", "powershell"]

    # Try pdfplumber first (better)
    if pdfplumber:
        try:
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                result["pages"] = len(pdf.pages)
                meta = pdf.metadata or {}
                result["metadata"] = {k: str(v) for k, v in meta.items() if v}
                full_text = ""
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    full_text += t
                    for href in (page.hyperlinks or []):
                        uri = href.get("uri", "")
                        if uri:
                            result["links"].append(uri)
                result["ips"] = list(set(ip_pattern.findall(full_text)))
                extra_links = url_pattern.findall(full_text)
                result["links"] = list(set(result["links"] + extra_links))
                raw_lower = raw.lower().decode("latin-1", errors="ignore")
                result["suspicious"] = any(kw in raw_lower for kw in suspicious_keywords)
                return jsonify(result)
        except Exception:
            pass

    # Fallback: PyPDF2
    if PyPDF2:
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(raw))
            result["pages"] = len(reader.pages)
            info = reader.metadata or {}
            result["metadata"] = {str(k).lstrip("/"): str(v) for k, v in info.items() if v}
            full_text = ""
            for page in reader.pages:
                full_text += (page.extract_text() or "")
            result["ips"] = list(set(ip_pattern.findall(full_text)))
            result["links"] = list(set(url_pattern.findall(full_text)))
            raw_lower = raw.lower().decode("latin-1", errors="ignore")
            result["suspicious"] = any(kw in raw_lower for kw in suspicious_keywords)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Raw fallback - no PDF lib installed
    raw_lower = raw.lower().decode("latin-1", errors="ignore")
    raw_str = raw.decode("latin-1", errors="ignore")
    result["ips"] = list(set(ip_pattern.findall(raw_str)))
    result["links"] = list(set(url_pattern.findall(raw_str)))
    result["suspicious"] = any(kw in raw_lower for kw in suspicious_keywords)
    result["metadata"] = {"note": "Install pdfplumber or PyPDF2 for full extraction"}
    return jsonify(result)

# ── /train ────────────────────────────────────────────────────────────
@app.route("/train", methods=["POST"])
@limiter.limit("5 per minute")
def train():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No audio files uploaded"}), 400
    saved = []
    for f in files:
        fname = f.filename or f"clip_{int(time.time())}.wav"
        # Sanitize: strip non-safe chars, then strip any directory components
        safe = re.sub(r'[^\w.\-]', '_', fname)
        safe = Path(safe).name  # prevent path traversal
        dest = SAMPLES_DIR / safe
        f.save(dest)
        saved.append(safe)
    manifest = {
        "samples": saved,
        "sample_dir": str(SAMPLES_DIR),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(saved)
    }
    with open(MODEL_DIR / "manifest.json", "w") as mf:
        json.dump(manifest, mf, indent=2)
    # Call voice_training if available — surface real errors
    voice_id = None
    try:
        from voice_training import train_from_samples
        voice_id = train_from_samples([str(SAMPLES_DIR / s) for s in saved])
        manifest["status"] = "trained"
        manifest["voice_id"] = voice_id
    except ImportError:
        manifest["status"] = "samples_saved"
        manifest["note"] = "voice_training.py not installed — samples saved only"
    except Exception as e:
        manifest["status"] = "training_failed"
        manifest["error"] = str(e)
    with open(MODEL_DIR / "manifest.json", "w") as mf:
        json.dump(manifest, mf, indent=2)
    return jsonify({"ok": True, "saved": saved, **manifest})

# ── /model_status ─────────────────────────────────────────────────────
@app.route("/model_status")
def model_status():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(_model_status())

def _model_status():
    manifest_path = MODEL_DIR / "manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path) as f:
                m = json.load(f)
            return {
                "trained": True,
                "count": m.get("count", 0),
                "trained_at": m.get("trained_at", "unknown"),
                "status": m.get("status", "unknown"),
                "voice_id": m.get("voice_id"),
                "error": m.get("error")
            }
        except Exception:
            pass
    return {"trained": False}

# ── run ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _loopback = {"127.0.0.1", "::1", "localhost"}
    _allow_network = os.environ.get("ALLOW_NETWORK_BINDING", "").strip() == "1"
    _requested_host = os.environ.get("HOST", "127.0.0.1").strip()

    if _requested_host not in _loopback and not _allow_network:
        print(
            f"ERROR: HOST={_requested_host!r} is not a loopback address.  "
            "Binding to non-loopback addresses exposes this server to the "
            "network, which contradicts its privacy-first design.\n"
            "Set ALLOW_NETWORK_BINDING=1 if you understand the risk and "
            "explicitly want network exposure.",
            file=sys.stderr,
        )
        sys.exit(1)

    if _allow_network and _requested_host not in _loopback:
        print(
            f"WARNING: ALLOW_NETWORK_BINDING=1 is set.  Binding to "
            f"{_requested_host!r} — this server is reachable from the network.",
            file=sys.stderr,
        )

    host = _requested_host if _allow_network else "127.0.0.1"
    port = int(os.environ.get("PORT", 5000))
    app.run(host=host, port=port, debug=False)
