#!/usr/bin/env python3
"""
Voice AI Tools - Flask Backend
Endpoints: /health /tts /presets /log /shodan /analyze_pdf /train /model_status /api/lookup

Env vars:
  GOOGLE_API_KEY        - Gemini API key (for TTS) [required]
  VOICE_SERVER_TOKEN    - shared secret (X-Voice-Token header) [optional in dev]
  SHODAN_API_KEY        - Shodan API key (optional)
  ALLOWED_ORIGINS       - comma-separated extra CORS origins (e.g. chrome-extension://YOUR_ID)
  PORT                  - bind port (default 5001)
  ALLOW_NETWORK_BINDING - set to "1" to allow non-loopback HOST (unsafe; logs a warning)
  HOST                  - bind address, only honoured when ALLOW_NETWORK_BINDING=1
"""

import os, io, re, json, time, wave, tempfile, importlib, sys, threading
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

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
    import magic
except ImportError:
    magic = None

try:
    import tts_engine as _tts_engine
    synthesize_speech = _tts_engine.synthesize_speech
    TTS_MAX_TEXT_LENGTH = getattr(_tts_engine, "MAX_TEXT_LENGTH", 2000)
except ImportError:
    synthesize_speech = None
    TTS_MAX_TEXT_LENGTH = 2000

try:
    from voice_config import get_voice_for_context as _default_voice_fn
except ImportError:
    _default_voice_fn = None

try:
    import lookup_engine as _lookup_engine
    _LOOKUP_OK = True
except ImportError:
    _lookup_engine = None
    _LOOKUP_OK = False

# ── config ────────────────────────────────────────────────────────────
VOICE_SERVER_TOKEN = os.environ.get("VOICE_SERVER_TOKEN", "").strip()
SHODAN_API_KEY     = os.environ.get("SHODAN_API_KEY", "")
MAX_TEXT_LENGTH    = TTS_MAX_TEXT_LENGTH
MAX_LOG_ENTRY_SIZE = 2048
AUDIO_HEADER_READ_SIZE = 512
PRESET_PATH        = Path("voice_presets.json")
LOG_PATH           = Path("session_log.json")
MODEL_DIR          = Path("voice_model")
SAMPLES_DIR        = Path("voice_samples")
PRESET_WRITE_LOCK  = threading.Lock()
SHODAN_SAFE_FIELDS = ("ip_str", "ports", "org", "country_name")
SERVER_START_TIME  = time.time()
SAMPLES_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

_GEMINI_DEFAULT_VOICE = "Kore"

flask_env = os.environ.get("FLASK_ENV", "").strip().lower()
if not VOICE_SERVER_TOKEN:
    if flask_env == "production":
        raise RuntimeError("VOICE_SERVER_TOKEN must be set when FLASK_ENV=production")
    print(
        "INFO: VOICE_SERVER_TOKEN not set — running in open dev mode. "
        "All protected endpoints are accessible without a token.\n"
        "Set VOICE_SERVER_TOKEN in production to enable auth.",
        file=sys.stderr,
    )

# ── CORS ──────────────────────────────────────────────────────────────
_extra_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5001",
    "http://localhost:5001",
] + _extra_origins

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
CORS(app, origins=ALLOWED_ORIGINS, allow_headers=["Content-Type", "X-Voice-Token"])
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per minute"])


def _safe_public_error_message(raw_error) -> str:
    """Avoid returning stack traces or multi-line internals to clients."""
    msg = str(raw_error or "").strip().lower()
    if any(
        token in msg
        for token in (
            "api key missing", "missing api key", "api key not configured",
            "apikey missing", "apikey not configured", "invalid api key",
            "api key invalid", "unauthorized", "authentication failed",
        )
    ):
        return "API key not configured"
    if any(
        token in msg
        for token in (
            "voice model unavailable", "voice model not found", "voice not found",
            "model not found", "voice unavailable", "model unavailable",
            "unsupported voice", "unsupported model", "invalid voice", "invalid model",
        )
    ):
        return "Voice model unavailable"
    if any(token in msg for token in ("timeout", "timed out", "deadline exceeded")):
        return "Request timed out"
    return "Speech synthesis failed"


def _validate_log_entry(data):
    if not isinstance(data, dict):
        return None, "Invalid JSON body"
    allowed_keys = {"action", "timestamp", "text"}
    unknown_keys = set(data.keys()) - allowed_keys
    if unknown_keys:
        return None, f"Unknown fields: {', '.join(sorted(unknown_keys))}"
    action    = data.get("action")
    text      = data.get("text")
    timestamp = data.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if not isinstance(action, str) or not action.strip():
        return None, "action is required"
    if not isinstance(text, str) or not text.strip():
        return None, "text is required"
    if not isinstance(timestamp, str) or not timestamp.strip():
        return None, "timestamp must be a non-empty string"
    entry = {"action": action.strip(), "timestamp": timestamp.strip(), "text": text.strip()}
    if len(json.dumps(entry, ensure_ascii=False).encode("utf-8")) > MAX_LOG_ENTRY_SIZE:
        return None, f"log entry exceeds maximum size of {MAX_LOG_ENTRY_SIZE} bytes"
    return entry, None


# ── auth ──────────────────────────────────────────────────────────────
def _check_token() -> bool:
    if not VOICE_SERVER_TOKEN:
        return True
    return request.headers.get("X-Voice-Token", "") == VOICE_SERVER_TOKEN

def _is_audio_upload(file_storage) -> bool:
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return False
    try:
        if hasattr(stream, "seekable") and not stream.seekable():
            return False
        pos = stream.tell()
        header = stream.read(AUDIO_HEADER_READ_SIZE) or b""
        stream.seek(pos)
    except Exception:
        return False
    if not header:
        return False
    detected_mime = ""
    if magic is not None:
        try:
            detected_mime = (magic.from_buffer(header, mime=True) or "").lower()
        except Exception:
            detected_mime = ""
    if detected_mime.startswith("audio/"):
        return True
    # Fallback magic-byte checks for common training clip formats.
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return True  # WAV
    if header.startswith(b"ID3"):
        return True  # MP3 (ID3-tagged)
    if len(header) > 1 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return True  # MP3 (raw frame sync)
    if header.startswith(b"OggS"):
        return True  # OGG
    if header.startswith(b"fLaC"):
        return True  # FLAC
    if header.startswith(b"\x1A\x45\xDF\xA3"):
        return True  # WebM/Matroska (audio/webm)
    if len(header) >= 16 and header[4:8] == b"ftyp":
        major_brand = header[8:12]
        compatible_brands = {header[i:i + 4] for i in range(16, len(header) - 3, 4)}
        if major_brand in {b"M4A ", b"M4B "}:
            return True  # M4A/MP4 audio containers
        if {b"M4A ", b"M4B "} & compatible_brands:
            return True  # M4A/MP4 audio containers
    return False


# ── voice-settings resolution ─────────────────────────────────────────
def _resolve_voice_settings(call_type: str) -> dict:
    try:
        custom = importlib.import_module("custom_voice_config")
        fn = getattr(custom, "get_custom_voice_settings", None)
        if callable(fn):
            result = fn(call_type or "LEGITIMATE")
            if isinstance(result, dict):
                resolved = dict(result)
                if not resolved.get("voice_id"):
                    resolved["voice_id"] = getattr(custom, "CUSTOM_VOICE_ID", _GEMINI_DEFAULT_VOICE)
                return resolved
    except Exception:
        pass
    try:
        if callable(_default_voice_fn):
            result = _default_voice_fn(call_type or "LEGITIMATE")
            if isinstance(result, dict):
                resolved = dict(result)
                if not resolved.get("voice_id"):
                    resolved["voice_id"] = _GEMINI_DEFAULT_VOICE
                return resolved
    except Exception:
        pass
    return {"voice_id": _GEMINI_DEFAULT_VOICE}


# ── /health ───────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "tts_engine": synthesize_speech is not None,
        "api_key_configured": bool(os.environ.get("GOOGLE_API_KEY", "").strip()),
        "auth_enabled": bool(VOICE_SERVER_TOKEN),
        "uptime_seconds": int(time.time() - SERVER_START_TIME),
    })


# ── /tts ──────────────────────────────────────────────────────────────
@app.route("/tts", methods=["POST"])
@limiter.limit("30 per minute")
def tts():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    if len(text) > MAX_TEXT_LENGTH:
        return jsonify({"error": f"text exceeds maximum length of {MAX_TEXT_LENGTH} characters"}), 400
    if synthesize_speech is None:
        return jsonify({"error": "TTS engine not available — install google-genai"}), 503
    try:
        call_type = data.get("call_type")
        if isinstance(call_type, str):
            call_type = (call_type.strip() or "LEGITIMATE").upper()
        else:
            call_type = "LEGITIMATE"
        voice_settings = _resolve_voice_settings(call_type)
        explicit_voice_id = data.get("voice_id")
        if (
            isinstance(explicit_voice_id, str)
            and explicit_voice_id.strip()
            and explicit_voice_id.strip().lower() != "cloned"
        ):
            voice_settings = dict(voice_settings)
            voice_settings["voice_id"] = explicit_voice_id.strip()
        audio_bytes, mime_type, error, _ = synthesize_speech(text, voice_settings)
        if error:
            return jsonify({"error": _safe_public_error_message(error)}), 502
        return Response(audio_bytes, mimetype=mime_type or "audio/wav")
    except Exception as e:
        print(f"TTS request failed: {e}", file=sys.stderr)
        return jsonify({"error": "Failed to synthesize speech"}), 500


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
    with PRESET_WRITE_LOCK:
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
    entry, error = _validate_log_entry(request.get_json(silent=True))
    if error:
        return jsonify({"error": error}), 400
    entries = []
    if LOG_PATH.exists():
        try:
            with open(LOG_PATH) as f:
                entries = json.load(f).get("entries", [])
        except Exception:
            pass
    entries.insert(0, entry)
    if len(entries) > 500:
        entries = entries[:500]
    with open(LOG_PATH, "w") as f:
        json.dump({"entries": entries}, f, indent=2)
    return jsonify({"ok": True})


@app.route("/log/clear", methods=["POST"])
@limiter.limit("30 per minute")
def clear_log_endpoint():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    with open(LOG_PATH, "w") as f:
        json.dump({"entries": []}, f, indent=2)
    return jsonify({"ok": True})


def _filter_shodan_response(payload):
    if not isinstance(payload, dict):
        return {}
    return {k: payload[k] for k in SHODAN_SAFE_FIELDS if k in payload}


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
            timeout=10,
        )
        return jsonify(_filter_shodan_response(r.json()))
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
    ip_pattern  = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
    url_pattern = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+', re.I)
    suspicious_keywords = ["eval(", "javascript:", "/launch", "/aa", "/openaction", "cmd.exe", "powershell"]

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
                result["ips"]   = list(set(ip_pattern.findall(full_text)))
                extra_links     = url_pattern.findall(full_text)
                result["links"] = list(set(result["links"] + extra_links))
                raw_lower = raw.lower().decode("latin-1", errors="ignore")
                result["suspicious"] = any(kw in raw_lower for kw in suspicious_keywords)
                return jsonify(result)
        except Exception:
            pass

    if PyPDF2:
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(raw))
            result["pages"] = len(reader.pages)
            info = reader.metadata or {}
            result["metadata"] = {str(k).lstrip("/"): str(v) for k, v in info.items() if v}
            full_text = ""
            for page in reader.pages:
                full_text += (page.extract_text() or "")
            result["ips"]        = list(set(ip_pattern.findall(full_text)))
            result["links"]      = list(set(url_pattern.findall(full_text)))
            raw_lower = raw.lower().decode("latin-1", errors="ignore")
            result["suspicious"] = any(kw in raw_lower for kw in suspicious_keywords)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    raw_lower = raw.lower().decode("latin-1", errors="ignore")
    raw_str   = raw.decode("latin-1", errors="ignore")
    result["ips"]        = list(set(ip_pattern.findall(raw_str)))
    result["links"]      = list(set(url_pattern.findall(raw_str)))
    result["suspicious"] = any(kw in raw_lower for kw in suspicious_keywords)
    result["metadata"]   = {"note": "Install pdfplumber or PyPDF2 for full extraction"}
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
        safe  = re.sub(r'[^\w.\-]', '_', fname)
        safe  = Path(safe).name
        if not safe or safe.startswith("."):
            return jsonify({"error": "Invalid filename"}), 400
        if not _is_audio_upload(f):
            return jsonify({"error": f"Invalid audio file: {safe}"}), 400
        dest  = SAMPLES_DIR / safe
        f.save(dest)
        saved.append(safe)
    manifest = {
        "samples":    saved,
        "sample_dir": str(SAMPLES_DIR),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":      len(saved),
    }
    with open(MODEL_DIR / "manifest.json", "w") as mf:
        json.dump(manifest, mf, indent=2)
    voice_id = None
    try:
        from voice_training import train_from_samples
        voice_id = train_from_samples([str(SAMPLES_DIR / s) for s in saved])
        manifest["status"] = "trained" if voice_id else "samples_saved"
        if voice_id:
            manifest["voice_id"] = voice_id
        else:
            manifest["note"] = "Samples saved. Set GOOGLE_API_KEY and use ElevenLabs/Gemini to train a real voice model."
    except ImportError:
        manifest["status"] = "samples_saved"
        manifest["note"] = "voice_training.py not found — samples saved only"
    except Exception:
        app.logger.exception("Training failed")
        manifest["status"] = "training_failed"
        manifest["error"] = "Training failed. Check server logs."
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
                "trained":    True,
                "count":      m.get("count", 0),
                "trained_at": m.get("trained_at", "unknown"),
                "status":     m.get("status", "unknown"),
                "voice_id":   m.get("voice_id"),
                "error":      m.get("error"),
                "note":       m.get("note"),
            }
        except Exception:
            pass
    return {"trained": False}


# ── /api/lookup ───────────────────────────────────────────────────────
@app.route("/api/lookup", methods=["POST"])
@limiter.limit("20 per minute")
def api_lookup():
    """
    Real-data intelligence lookup for domains, IPs, and phone numbers.

    Request body (JSON):
        { "query": "<domain | IPv4 | phone number>" }

    Response (JSON):
        {
          "query":     "<original input>",
          "type":      "domain" | "ip" | "phone" | "unknown",
          "timestamp": "<ISO-8601 UTC>",
          ...type-specific fields
        }

    Auth:       X-Voice-Token header (when VOICE_SERVER_TOKEN is set)
    Rate-limit: 20 requests / minute per IP
    """
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if not _LOOKUP_OK:
        return jsonify({"error": "lookup_engine not available — ensure lookup_engine.py is present"}), 503

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400
    if len(query) > 253:
        return jsonify({"error": "query too long"}), 400

    # Block private/loopback ranges to prevent SSRF-style abuse
    _private = re.compile(
        r'^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|127\.|::1$|0\.0\.0\.0$)'
    )
    if _private.match(query):
        return jsonify({"error": "Private or loopback addresses are not supported"}), 400

    try:
        result = _lookup_engine.lookup(query)
        return jsonify(result)
    except Exception as exc:
        print(f"Lookup failed for {query!r}: {exc}", file=sys.stderr)
        return jsonify({"error": "Lookup failed"}), 500


# ── run ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _loopback      = {"127.0.0.1", "::1", "localhost"}
    _allow_network = os.environ.get("ALLOW_NETWORK_BINDING", "").strip() == "1"
    _requested_host = os.environ.get("HOST", "127.0.0.1").strip()

    if _requested_host not in _loopback and not _allow_network:
        print(
            f"ERROR: HOST={_requested_host!r} is not a loopback address.  "
            "Set ALLOW_NETWORK_BINDING=1 if you understand the risk.",
            file=sys.stderr,
        )
        sys.exit(1)

    if _allow_network and _requested_host not in _loopback:
        print(
            f"WARNING: ALLOW_NETWORK_BINDING=1 — binding to {_requested_host!r}, "
            "server is reachable from the network.",
            file=sys.stderr,
        )

    host = _requested_host if _allow_network else "127.0.0.1"
    port = int(os.environ.get("PORT", 5001))
    app.run(host=host, port=port, debug=False)
