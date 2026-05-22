#!/usr/bin/env python3
"""
Voice AI Tools - Flask Backend
Endpoints: /health /tts /presets /log /shodan /analyze_pdf /train /model_status

Env vars:
  GOOGLE_API_KEY      - Gemini API key (for TTS)
  VOICE_SERVER_TOKEN  - shared secret (X-Token header)
  SHODAN_API_KEY      - Shodan API key (optional)
  ALLOWED_ORIGINS     - comma-separated extra CORS origins
  HOST / PORT         - bind address (default 127.0.0.1:5100)
"""

import functools
import hmac
import io
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

# ── PDF analysis constants ─────────────────────────────────────────────
IP_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
)
URL_PATTERN = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+', re.I)
SUSPICIOUS_KEYWORDS = [
    "eval(",
    "javascript:",
    "/launch",
    "/aa",
    "/openaction",
    "cmd.exe",
    "powershell",
]

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
    from voice_config import get_voice_for_context
except ImportError:
    synthesize_speech = None
    get_voice_for_context = None

# ── config ────────────────────────────────────────────────────────────
VOICE_SERVER_TOKEN = os.environ.get("VOICE_SERVER_TOKEN", "")

SHODAN_API_KEY = os.environ.get("SHODAN_API_KEY", "")
MAX_TEXT_LENGTH = 2000
PRESET_PATH = Path("voice_presets.json")
LOG_PATH = Path("session_log.json")
MODEL_DIR = Path("voice_model")
SAMPLES_DIR = Path("voice_samples")
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Locks for simple thread-safe file operations
_preset_lock = threading.Lock()
_log_lock = threading.Lock()
_model_lock = threading.Lock()

_extra_origins = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]
ALLOWED_ORIGINS = [
    "chrome-extension://*",
    "http://localhost:*",
    "http://127.0.0.1:*",
] + _extra_origins

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB max upload
CORS(app, origins=ALLOWED_ORIGINS, allow_headers=["Content-Type", "X-Token"])
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per minute"])


# ── security headers ──────────────────────────────────────────────────
@app.after_request
def add_security_headers(response: Response) -> Response:
    """Inject strict security headers onto every HTTP response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    return response


# ── utilities ─────────────────────────────────────────────────────────
def _check_token() -> bool:
    if not VOICE_SERVER_TOKEN:
        return True
    provided_token = request.headers.get("X-Token", "")
    return hmac.compare_digest(provided_token, VOICE_SERVER_TOKEN)


def _is_valid_ip(ip: str) -> bool:
    """Validate IPv4 address format."""
    if not ip:
        return False
    try:
        # Check if it's a valid IPv4 address
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        for part in parts:
            if not part.isdigit():
                return False
            num = int(part)
            if num < 0 or num > 255:
                return False
        return True
    except Exception:
        return False


def _analyze_text_content(text: str, raw_bytes: bytes) -> Dict[str, Any]:
    """Extract IPs, links, and check suspicious keywords from text."""
    raw_lower = raw_bytes.lower().decode("latin-1", errors="ignore")
    return {
        "ips": list(set(IP_PATTERN.findall(text))),
        "links": list(set(URL_PATTERN.findall(text))),
        "suspicious": any(kw in raw_lower for kw in SUSPICIOUS_KEYWORDS),
    }


def _parse_with_pdfplumber(raw: bytes) -> Dict[str, Any]:
    """Parse PDF using pdfplumber library."""
    result: Dict[str, Any] = {
        "metadata": {},
        "links": [],
        "ips": [],
        "suspicious": False,
        "pages": 0,
    }

    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        result["pages"] = len(pdf.pages)
        meta = pdf.metadata or {}
        result["metadata"] = {k: str(v) for k, v in meta.items() if v}
        full_text = "".join(page.extract_text() or "" for page in pdf.pages)
        for page in pdf.pages:
            for href in page.hyperlinks or []:
                if uri := href.get("uri", ""):
                    result["links"].append(uri)

        text_analysis = _analyze_text_content(full_text, raw)
        result["ips"] = text_analysis["ips"]
        extra_links = URL_PATTERN.findall(full_text)
        result["links"] = list(set(result["links"] + extra_links))
        result["suspicious"] = text_analysis["suspicious"]

    return result


def _parse_with_pypdf2(raw: bytes) -> Dict[str, Any]:
    """Parse PDF using PyPDF2 library."""
    result: Dict[str, Any] = {
        "metadata": {},
        "links": [],
        "ips": [],
        "suspicious": False,
        "pages": 0,
    }

    reader = PyPDF2.PdfReader(io.BytesIO(raw))
    result["pages"] = len(reader.pages)
    info = reader.metadata or {}
    result["metadata"] = {str(k).lstrip("/"): str(v) for k, v in info.items() if v}
    full_text = "".join(page.extract_text() or "" for page in reader.pages)

    text_analysis = _analyze_text_content(full_text, raw)
    result["ips"] = text_analysis["ips"]
    result["links"] = text_analysis["links"]
    result["suspicious"] = text_analysis["suspicious"]

    return result


def _parse_raw_text(raw: bytes) -> Dict[str, Any]:
    """Parse raw text fallback when no PDF library is installed."""
    raw_lower = raw.lower().decode("latin-1", errors="ignore")
    raw_str = raw.decode("latin-1", errors="ignore")

    return {
        "metadata": {"note": "Install pdfplumber or PyPDF2 for full extraction"},
        "ips": list(set(IP_PATTERN.findall(raw_str))),
        "links": list(set(URL_PATTERN.findall(raw_str))),
        "suspicious": any(kw in raw_lower for kw in SUSPICIOUS_KEYWORDS),
        "pages": 0,
    }


def _extract_pdf_analysis(raw: bytes) -> Dict[str, Any]:
    """Extract analysis data from PDF bytes."""
    # Try pdfplumber first
    if pdfplumber:
        try:
            return _parse_with_pdfplumber(raw)
        except Exception as e:
            logger.warning(f"pdfplumber analysis failed: {e}")

    # Fallback: PyPDF2
    if PyPDF2:
        try:
            return _parse_with_pypdf2(raw)
        except Exception as e:
            logger.warning(f"PyPDF2 analysis failed: {e}")
            return {"error": "Failed to parse PDF document"}

    # Raw fallback - no PDF lib installed
    return _parse_raw_text(raw)


def _read_json_safe(file_path: Path, default: Any) -> Any:
    """Read JSON safely without acquiring a lock (caller must lock)."""
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read {file_path}: {e}")
    return default


def _locked_read_json(file_path: Path, lock: threading.Lock, default: Any) -> Any:
    """Read JSON safely with a thread lock."""
    with lock:
        return _read_json_safe(file_path, default)


def _atomic_write_json(file_path: Path, data: Any) -> None:
    """
    Write JSON data atomically using a temporary file and os.replace().
    This guarantees that if the server crashes during serialization or disk I/O,
    the target JSON file will not be corrupted or truncated to 0 bytes.
    """
    tmp_path = file_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            # Force OS to write buffers to physical disk
            os.fsync(f.fileno())
        # os.replace is an atomic operation on POSIX systems
        os.replace(tmp_path, file_path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {tmp_path}: {e}")
        raise


@functools.lru_cache(maxsize=256)
def _cached_shodan_lookup(ip: str, api_key: str) -> Tuple[Dict[str, Any], int]:
    """Cache external Shodan queries in memory to accelerate repeated lookups."""
    if _requests is None:
        return {"error": "requests library not installed"}, 503
    try:
        r = _requests.get(
            f"https://api.shodan.io/shodan/host/{ip}",
            params={"key": api_key},
            timeout=10,
        )
        if r.status_code != 200:
            return {
                "error": f"Shodan API returned status {r.status_code}"
            }, r.status_code
        try:
            return r.json(), 200
        except ValueError:
            return {"error": "Shodan API returned invalid JSON"}, 500
    except Exception:
        return {"error": "Internal communication error"}, 500


def _clear_shodan_cache() -> None:
    """Clear the Shodan lookup cache. Call this if API key changes."""
    _cached_shodan_lookup.cache_clear()
    logger.info("Shodan lookup cache cleared")


# ── / (root) ─────────────────────────────────────────────────────────────
@app.route("/")
def index() -> Response:
    return jsonify(
        {
            "status": "ok",
            "service": "Voice AI Tools Flask Backend",
            "endpoints": {
                "health": "GET /health - Check server status",
                "tts": "POST /tts - Text-to-speech synthesis",
                "presets": "GET/POST /presets - Voice presets management",
                "log": "GET/POST /log - Activity logging",
                "shodan": "GET /shodan - IP intelligence lookup",
                "analyze_pdf": "POST /analyze_pdf - PDF analysis",
                "train": "POST /train - Voice training",
                "model_status": "GET /model_status - Voice model status",
            },
        }
    )


# ── /health ───────────────────────────────────────────────────────────
@app.route("/health")
def health() -> Response:
    return jsonify({"status": "ok", "model": _model_status()})


# ── /tts ──────────────────────────────────────────────────────────────
@app.route("/tts", methods=["POST"])
@limiter.limit("30 per minute")
def tts() -> Response | Tuple[Response, int]:
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
        voice_context = get_voice_for_context(data) if get_voice_for_context else {}
        voice_settings: Dict[str, Any] = {"voice_id": "Kore"}

        if voice_context:
            voice_settings |= voice_context

        if data.get("voice_id"):
            requested_voice = data.get("voice_id")
            if requested_voice == "cloned":
                voice_settings["voice_id"] = "kore"
            else:
                voice_settings["voice_id"] = requested_voice

        if data.get("speed"):
            if data.get("speed") == "fast":
                voice_settings["speaking_rate"] = 1.5
            elif data.get("speed") == "slow":
                voice_settings["speaking_rate"] = 0.8
            else:
                voice_settings["speaking_rate"] = 1.0

        audio_bytes, mime_type, error_msg, _ = synthesize_speech(text, voice_settings)
        if error_msg:
            return jsonify({"error": error_msg}), 500

        return Response(audio_bytes, mimetype=mime_type)

    except Exception as e:
        logger.error(f"TTS endpoint error: {e}")
        return jsonify({"error": "Internal server error"}), 500


# ── /presets ──────────────────────────────────────────────────────────
@app.route("/presets", methods=["GET", "POST"])
@limiter.limit("60 per minute")
def presets() -> Response | Tuple[Response, int]:
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if request.method == "GET":
        return jsonify(_locked_read_json(PRESET_PATH, _preset_lock, {"presets": []}))

    data = request.get_json(silent=True)
    if not data or not data.get("name"):
        return jsonify({"error": "Preset needs a name"}), 400

    with _preset_lock:
        presets_data = _read_json_safe(PRESET_PATH, {"presets": []})
        presets_list = presets_data.get("presets", [])

        existing = next(
            (i for i, p in enumerate(presets_list) if p.get("name") == data["name"]),
            None,
        )

        if existing is not None:
            presets_list[existing] = data
        else:
            presets_list.append(data)

        try:
            _atomic_write_json(PRESET_PATH, {"presets": presets_list})
            return jsonify({"ok": True})
        except Exception as e:
            logger.error(f"Failed to save preset: {e}")
            return jsonify({"error": "Failed to save preset"}), 500


# ── /log ──────────────────────────────────────────────────────────────
@app.route("/log", methods=["GET", "POST"])
@limiter.limit("120 per minute")
def log_endpoint() -> Response | Tuple[Response, int]:
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if request.method == "GET":
        return jsonify(_locked_read_json(LOG_PATH, _log_lock, {"entries": []}))

    entry = request.get_json(silent=True) or {}

    with _log_lock:
        log_data = _read_json_safe(LOG_PATH, {"entries": []})
        entries = log_data.get("entries", [])

        if entry.get("action") == "clear":
            entries = []
        else:
            entry["timestamp"] = entry.get(
                "timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ")
            )
            entries.insert(0, entry)
            if len(entries) > 500:
                entries = entries[:500]

        try:
            _atomic_write_json(LOG_PATH, {"entries": entries})
            return jsonify({"ok": True})
        except Exception as e:
            logger.error(f"Failed to save log: {e}")
            return jsonify({"error": "Failed to save log"}), 500


# ── /shodan ───────────────────────────────────────────────────────────
@app.route("/shodan")
@limiter.limit("10 per minute")
def shodan() -> Response | Tuple[Response, int]:
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    ip = request.args.get("ip", "").strip()
    if not ip:
        return jsonify({"error": "ip param required"}), 400
    if not _is_valid_ip(ip):
        return jsonify({"error": "Invalid IP address format"}), 400
    if not SHODAN_API_KEY:
        return jsonify({"error": "SHODAN_API_KEY not set on server"}), 503

    data, status_code = _cached_shodan_lookup(ip, SHODAN_API_KEY)
    return jsonify(data), status_code


# ── /analyze_pdf ──────────────────────────────────────────────────────
@app.route("/analyze_pdf", methods=["POST"])
@limiter.limit("10 per minute")
def analyze_pdf() -> Response | Tuple[Response, int]:
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]

    if not f or not f.filename:
        return jsonify({"error": "Invalid file upload"}), 400

    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Uploaded file must be a PDF"}), 400

    raw = f.read()
    result = _extract_pdf_analysis(raw)

    return (jsonify(result), 500) if "error" in result else jsonify(result)


# ── /train ────────────────────────────────────────────────────────────
@app.route("/train", methods=["POST"])
@limiter.limit("5 per minute")
def train() -> Response | Tuple[Response, int]:
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No audio files uploaded"}), 400

    saved = []
    for f in files:
        if not f or not f.filename:
            continue

        fname = f.filename
        if not fname.lower().endswith(".wav"):
            continue

        safe_fname = (
            secure_filename(fname) or f"clip_{int(time.time())}_{len(saved)}.wav"
        )

        dest = SAMPLES_DIR / safe_fname

        try:
            f.save(dest)
            saved.append(safe_fname)
        except Exception as e:
            logger.warning(f"Failed to save file {fname}: {e}")

    if not saved:
        return jsonify({"error": "No valid .wav files were saved"}), 400

    manifest = {
        "samples": saved,
        "sample_dir": str(SAMPLES_DIR),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(saved),
    }

    with _model_lock:
        try:
            _atomic_write_json(MODEL_DIR / "manifest.json", manifest)
        except Exception as e:
            logger.error(f"Failed to save manifest: {e}")
            return jsonify({"error": "Failed to save manifest"}), 500

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

    with _model_lock:
        try:
            _atomic_write_json(MODEL_DIR / "manifest.json", manifest)
        except Exception as e:
            logger.warning(f"Failed to update manifest after training: {e}")

    return jsonify({"ok": True, "saved": saved, **manifest})


# ── /model_status ─────────────────────────────────────────────────────
@app.route("/model_status")
def model_status() -> Response | Tuple[Response, int]:
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(_model_status())


def _model_status() -> Dict[str, Any]:
    manifest = _locked_read_json(MODEL_DIR / "manifest.json", _model_lock, None)
    if manifest:
        return {
            "trained": True,
            "count": manifest.get("count", 0),
            "trained_at": manifest.get("trained_at", "unknown"),
            "status": manifest.get("status", "unknown"),
            "voice_id": manifest.get("voice_id"),
            "error": manifest.get("error"),
        }
    return {"trained": False}


# ── run ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5100))
    app.run(host=host, port=port, debug=False)
