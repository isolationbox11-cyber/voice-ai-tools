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

import os
import io
import re
import json
import time
import uuid
import logging
from contextlib import suppress
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from functools import lru_cache
from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from concurrent.futures import ThreadPoolExecutor
import jwt

logger = logging.getLogger(__name__)

# Load environment variables from .env file
with suppress(ImportError):
    from dotenv import load_dotenv

    load_dotenv()

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
    from cache_manager import cache_manager
    from async_tasks import task_manager, async_task
    from voice_profiles import (
        voice_profile_manager,
        VoiceGender,
        VoiceAccent,
        VoiceEmotion,
        VoiceLanguage,
    )
    from voice_analyzer import voice_analyzer
except ImportError:
    synthesize_speech = None
    get_voice_for_context = None
    cache_manager = None
    task_manager = None
    async_task = None
    voice_profile_manager = None
    VoiceGender = None
    VoiceAccent = None
    VoiceEmotion = None
    VoiceLanguage = None
    voice_analyzer = None

# ── config ────────────────────────────────────────────────────────────
VOICE_SERVER_TOKEN = os.environ.get("VOICE_SERVER_TOKEN", "")
SHODAN_API_KEY = os.environ.get("SHODAN_API_KEY", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
MAX_TEXT_LENGTH = 1000
JWT_SECRET = os.environ.get("JWT_SECRET", "voice_ai_tools_default_secret")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

MODEL_META_PATH = os.path.join("voice_model", "manifest.json")
SAMPLES_DIR = Path("voice_samples")
MODEL_DIR = Path("voice_model")


@lru_cache(maxsize=32)
def load_model_meta():
    if not os.path.exists(MODEL_META_PATH):
        return {
            "trained": False,
            "status": "none",
            "count": 0,
            "voice_id": None,
            "trained_at": None,
            "error": None,
        }
    try:
        with open(MODEL_META_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        return {
            "trained": False,
            "status": "meta_read_error",
            "count": 0,
            "voice_id": None,
            "trained_at": None,
            "error": str(e),
        }


def save_model_meta(status, count, voice_id=None, error=None):
    os.makedirs(MODEL_DIR, exist_ok=True)
    # Preserve existing voice_id if one was already assigned
    existing = load_model_meta()
    final_voice_id = voice_id or existing.get("voice_id") or str(uuid.uuid4())
    meta = {
        "trained": True,
        "status": status,
        "count": count,
        "voice_id": final_voice_id,
        "trained_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "error": error,
    }
    with open(MODEL_META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
    return meta


PRESET_PATH = Path("voice_presets.json")
LOG_PATH = Path("session_log.json")
MODEL_DIR = Path("voice_model")
SAMPLES_DIR = Path("voice_samples")
SAMPLES_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

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

# Thread pool for async processing
executor = ThreadPoolExecutor(max_workers=4)


# ── auth ──────────────────────────────────────────────────────────────
def generate_jwt_token(user_id: str) -> str:
    """Generate JWT token for authentication"""
    try:
        payload = {
            "user_id": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
            "iat": datetime.now(timezone.utc),
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    except Exception as e:
        logger.error(f"JWT generation failed: {e}")
        return ""


def verify_jwt_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception as e:
        logger.error(f"JWT verification failed: {e}")
        return None


def _check_token():
    """Check authentication token (supports both simple token and JWT)"""
    if not VOICE_SERVER_TOKEN:
        return True

    received_token = request.headers.get("X-Token", "")

    # Try JWT token first
    if received_token.startswith("eyJ"):
        jwt_payload = verify_jwt_token(received_token)
        if jwt_payload:
            return True

    # Fall back to simple token
    return received_token == VOICE_SERVER_TOKEN


# ── /health ───────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok", "model": load_model_meta()})


# ── /auth/token ────────────────────────────────────────────────────────
@app.route("/auth/token", methods=["POST"])
@limiter.limit("10 per minute")
def generate_token():
    """Generate JWT token for authentication"""
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id", "default_user")

    token = generate_jwt_token(user_id)
    if not token:
        return jsonify({"error": "Token generation failed"}), 500

    return jsonify(
        {"token": token, "expires_in": JWT_EXPIRATION_HOURS * 3600, "user_id": user_id}
    )


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

    # Check cache first if available
    cache_key_data = {
        "text": text,
        "voice_id": data.get("voice_id"),
        "model_meta": load_model_meta(),
    }

    if cache_manager and (
        cached_result := cache_manager.get("tts_response", **cache_key_data)
    ):
        return Response(cached_result["audio"], mimetype=cached_result["mime_type"])

    try:
        # Handle both UUID and legacy 'cloned' voice IDs
        requested_voice_id = data.get("voice_id")

        # Load model metadata to validate UUID
        meta = load_model_meta()

        if requested_voice_id == "cloned":
            # Legacy fallback - use trained model if available
            voice_id = meta.get("voice_id") if meta.get("trained") else None
        elif requested_voice_id:
            # Validate UUID matches trained model, fallback to default if not
            if meta.get("voice_id") == requested_voice_id and meta.get("trained"):
                voice_id = requested_voice_id
            else:
                # Invalid or untrained voice_id - use default voice instead of error
                voice_id = None
        else:
            voice_id = None

        voice_settings = {"voice_id": voice_id} if voice_id else {}
        audio_bytes, mime_type, error, effective_text = synthesize_speech(
            text, voice_settings=voice_settings
        )
        if error:
            return jsonify({"error": error}), 500

        # Cache the result
        if cache_manager and audio_bytes:
            cache_manager.set(
                "tts_response",
                {"audio": audio_bytes, "mime_type": mime_type},
                mime_type,
                **cache_key_data,
            )

        return Response(audio_bytes, mimetype=mime_type)
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
    existing = next(
        (i for i, p in enumerate(presets_list) if p.get("name") == data["name"]), None
    )
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
        with suppress(Exception):
            with open(LOG_PATH) as f:
                entries = json.load(f).get("entries", [])
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
            timeout=10,
        )
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── /analyze_pdf ──────────────────────────────────────────────────────
def _extract_pdf_metadata(pdf_obj):
    """Extract and normalize PDF metadata."""
    meta = pdf_obj.metadata or {}
    return {k: str(v) for k, v in meta.items() if v}


def _analyze_text_content(text, ip_pattern, url_pattern, suspicious_keywords):
    """Analyze text content for IPs, URLs, and suspicious content."""
    ips = list(set(ip_pattern.findall(text)))
    links = list(set(url_pattern.findall(text)))
    raw_lower = text.lower()
    suspicious = any(kw in raw_lower for kw in suspicious_keywords)
    return ips, links, suspicious


def _analyze_pdf_with_pdfplumber(
    raw: bytes, ip_pattern, url_pattern, suspicious_keywords
) -> Optional[dict]:
    """Analyze PDF using pdfplumber library."""
    with suppress(Exception):
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            result = {
                "pages": len(pdf.pages),
                "metadata": _extract_pdf_metadata(pdf),
                "links": [],
                "ips": [],
                "suspicious": False,
            }

            # Extract text and hyperlinks
            full_text = ""
            for page in pdf.pages:
                if t := page.extract_text() or "":
                    full_text += t
                for href in page.hyperlinks or []:
                    if uri := href.get("uri", ""):
                        result["links"].append(uri)

            # Analyze content
            ips, extra_links, suspicious = _analyze_text_content(
                full_text, ip_pattern, url_pattern, suspicious_keywords
            )
            result["ips"].extend(ips)
            result["links"].extend(extra_links)
            result["links"] = list(set(result["links"]))
            result["suspicious"] = suspicious
            return result
    return None


def _analyze_pdf_with_pypdf2(
    raw: bytes, ip_pattern, url_pattern, suspicious_keywords
) -> Optional[dict]:
    """Analyze PDF using PyPDF2 library."""
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(raw))
        result = {
            "pages": len(reader.pages),
            "metadata": {
                str(k).lstrip("/"): str(v)
                for k, v in _extract_pdf_metadata(reader).items()
                if v
            },
        }

        full_text = "".join(page.extract_text() or "" for page in reader.pages)
        ips, links, suspicious = _analyze_text_content(
            full_text, ip_pattern, url_pattern, suspicious_keywords
        )
        result["ips"] = ips
        result["links"] = links
        result["suspicious"] = suspicious
        return result
    except Exception as e:
        return {"error": str(e)}


def _analyze_pdf_raw(raw: bytes, ip_pattern, url_pattern, suspicious_keywords) -> dict:
    """Analyze PDF as raw text when no PDF libraries are available."""
    raw_str = raw.decode("latin-1", errors="ignore")
    ips, links, suspicious = _analyze_text_content(
        raw_str, ip_pattern, url_pattern, suspicious_keywords
    )
    return {
        "ips": ips,
        "links": links,
        "suspicious": suspicious,
        "metadata": {"note": "Install pdfplumber or PyPDF2 for full extraction"},
    }


@app.route("/voice_analysis", methods=["GET"])
@limiter.limit("60 per minute")
def voice_analysis():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    try:
        from simple_voice_cloner import get_voice_cloner

        cloner = get_voice_cloner()
        voices = cloner.list_available_voices()

        analysis_results = []
        for voice in voices:
            voice_id = voice.get("voice_id")
            quality_metrics = voice.get("quality_metrics", {})
            analysis_results.append(
                {
                    "voice_id": voice_id,
                    "voice_name": voice.get("voice_name", "Unknown"),
                    "sample_count": voice.get("sample_count", 0),
                    "quality_score": quality_metrics.get("quality_score", 0),
                    "clarity_score": quality_metrics.get("clarity_score", 0),
                    "naturalness_score": quality_metrics.get("naturalness_score", 0),
                    "created_at": voice.get("created_at"),
                    "recommendations": quality_metrics.get("recommendations", []),
                }
            )

        return jsonify(
            {"voices": analysis_results, "total_voices": len(analysis_results)}
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/analyze_pdf", methods=["POST"])
@limiter.limit("10 per minute")
def analyze_pdf():
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    raw = f.read()

    # Pre-compiled patterns for efficiency
    ip_pattern = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    url_pattern = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+', re.I)
    suspicious_keywords = {
        "eval(",
        "javascript:",
        "/launch",
        "/aa",
        "/openaction",
        "cmd.exe",
        "powershell",
    }

    # Try pdfplumber first (better)
    if result := _analyze_pdf_with_pdfplumber(
        raw, ip_pattern, url_pattern, suspicious_keywords
    ):
        return jsonify(result)

    # Fallback: PyPDF2
    if result := _analyze_pdf_with_pypdf2(
        raw, ip_pattern, url_pattern, suspicious_keywords
    ):
        return jsonify(result), 500 if "error" in result else jsonify(result)

    # Raw fallback - no PDF lib installed
    result = _analyze_pdf_raw(raw, ip_pattern, url_pattern, suspicious_keywords)
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
        safe = re.sub(r"[^\w.\-]", "_", fname)
        safe = Path(safe).name  # prevent path traversal
        dest = SAMPLES_DIR / safe
        f.save(dest)
        saved.append(safe)
    manifest = {
        "samples": saved,
        "sample_dir": str(SAMPLES_DIR),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(saved),
    }
    with open(MODEL_DIR / "manifest.json", "w") as mf:
        json.dump(manifest, mf, indent=2)
    # Call voice_training if available — surface real errors
    voice_id = None
    try:
        from voice_training import train_from_samples

        # Initialize progress tracking
        progress = {
            "stage": "processing",
            "message": "Starting voice training...",
            "progress": 0,
            "total_steps": 4,
        }

        # Update progress during training
        def update_progress(stage, message, progress_step):
            progress["stage"] = stage
            progress["message"] = message
            progress["progress"] = min(progress["progress"] + progress_step, 100)
            # Save progress to file for UI polling
            with open(MODEL_DIR / "training_progress.json", "w") as pf:
                json.dump(progress, pf, indent=2)

        update_progress("processing", "Analyzing voice samples...", 10)
        voice_id = train_from_samples([str(SAMPLES_DIR / s) for s in saved])

        update_progress("training", "Training voice model...", 50)
        manifest["status"] = "trained"
        manifest["voice_id"] = voice_id or str(uuid.uuid4())

        update_progress("finalizing", "Finalizing model...", 90)

        # Clean up progress file when complete
        progress_file = MODEL_DIR / "training_progress.json"
        if progress_file.exists():
            progress_file.unlink()

    except ImportError:
        manifest["status"] = "samples_saved"
        manifest["note"] = "voice_training.py not installed — samples saved only"
        manifest["voice_id"] = str(uuid.uuid4())
    except Exception as e:
        manifest["status"] = "training_failed"
        manifest["error"] = str(e)
    with open(MODEL_DIR / "manifest.json", "w") as mf:
        json.dump(manifest, mf, indent=2)
    return jsonify({"ok": True, "saved": saved, **manifest})


# ── /model_status ─────────────────────────────────────────────────────
@app.route("/model_status")
def model_status():
    meta = load_model_meta()

    # Also return training progress if available
    progress_file = MODEL_DIR / "training_progress.json"
    if progress_file.exists():
        try:
            with open(progress_file, "r") as pf:
                progress = json.load(pf)
                return jsonify({"status": "ok", "progress": progress})
        except Exception:
            return jsonify({"status": "error", "error": "Failed to load progress file"})

    return jsonify({"status": "ok", "model": meta})


# ── /task_status ─────────────────────────────────────────────────────
@app.route("/task_status/<task_id>")
def task_status(task_id):
    """Get status of an async task."""
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if not task_manager:
        return jsonify({"error": "Task manager not available"}), 503

    task = task_manager.get_task_status(task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404

    return jsonify(
        {
            "task_id": task.task_id,
            "status": task.status,
            "progress": task.progress,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at,
            "completed_at": task.completed_at,
        }
    )


# ── /cancel_task ─────────────────────────────────────────────────────
@app.route("/cancel_task/<task_id>", methods=["POST"])
def cancel_task(task_id):
    """Cancel an async task."""
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if not task_manager:
        return jsonify({"error": "Task manager not available"}), 503

    success = task_manager.cancel_task(task_id)
    return jsonify(
        {"status": "ok", "message": "Task cancelled"}
        if success
        else {"error": "Cannot cancel task - may already be running"},
        400,
    )


# ── /voice_profile/<profile_id> ───────────────────────────────────────────
@app.route("/voice_profile/<profile_id>", methods=["GET", "PUT", "DELETE"])
@limiter.limit("60 per minute")
def voice_profile_detail(profile_id):
    """Manage individual voice profile."""
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if not voice_profile_manager:
        return jsonify({"error": "Voice profile manager not available"}), 503

    profile = voice_profile_manager.get_profile(profile_id)
    if profile is None:
        return jsonify({"error": "Profile not found"}), 404

    if request.method == "GET":
        return jsonify({"profile": profile.__dict__})

    elif request.method == "PUT":
        data = request.get_json(silent=True) or {}
        success = voice_profile_manager.update_profile(profile_id, **data)
        return jsonify(
            {"status": "ok", "profile": profile.__dict__}
            if success
            else {"error": "Profile not found"},
            404,
        )

    elif request.method == "DELETE":
        success = voice_profile_manager.delete_profile(profile_id)
        return jsonify(
            {"status": "ok", "message": "Profile deleted"}
            if success
            else {"error": "Profile not found"},
            404,
        )


# ── /voice_profile_options ───────────────────────────────────────────────
@app.route("/voice_profile_options")
def voice_profile_options():
    """Get available options for voice profiles."""
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if not voice_profile_manager:
        return jsonify({"error": "Voice profile manager not available"}), 503

    return jsonify(
        {
            "genders": [
                {"value": g.value, "label": g.value.title()} for g in VoiceGender
            ],
            "accents": [
                {"value": a.value, "label": a.value.title()} for a in VoiceAccent
            ],
            "languages": [
                {"value": lang.value, "label": lang.value.upper()}
                for lang in VoiceLanguage
            ],
            "emotions": [
                {"value": e.value, "label": e.value.title()} for e in VoiceEmotion
            ],
        }
    )


# ── /analyze_voice ─────────────────────────────────────────────────────
@app.route("/analyze_voice", methods=["POST"])
@limiter.limit("20 per minute")
def analyze_voice():
    """Analyze uploaded audio file for voice quality metrics."""
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if not voice_analyzer:
        return jsonify({"error": "Voice analyzer not available"}), 503

    if "audio_file" not in request.files:
        return jsonify({"error": "No audio file uploaded"}), 400

    audio_file = request.files["audio_file"]
    if not audio_file.filename:
        return jsonify({"error": "No audio file selected"}), 400

    try:
        # Save uploaded file temporarily
        temp_path = SAMPLES_DIR / f"temp_analysis_{int(time.time())}.wav"
        temp_path.parent.mkdir(exist_ok=True)
        audio_file.save(str(temp_path))

        # Analyze the audio
        metrics = voice_analyzer.analyze_audio_file(str(temp_path))

        # Clean up temporary file
        temp_path.unlink(missing_ok=True)

        # Cache the analysis result
        if cache_manager:
            cache_manager.set(
                "voice_analysis",
                metrics.__dict__,
                "application/json",
                filename=audio_file.filename,
                file_size=len(audio_file.read()) if hasattr(audio_file, "read") else 0,
            )

        return jsonify({"status": "ok", "metrics": metrics.__dict__})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── /training_progress ───────────────────────────────────────────────────
@app.route("/training_progress")
def training_progress():
    """Get voice training progress and analysis."""
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if not voice_analyzer:
        return jsonify({"error": "Voice analyzer not available"}), 503

    # Get analysis history from cache
    history = cache_manager.get("analysis_history") if cache_manager else []

    # Analyze progress if we have enough data
    if len(history) >= 2:
        progress_analysis = voice_analyzer.analyze_training_progress(history)
    else:
        progress_analysis = {
            "status": "insufficient_data",
            "message": "Need at least 2 voice recordings for progress analysis",
        }

    return jsonify(
        {"status": "ok", "progress": progress_analysis, "analysis_count": len(history)}
    )


# ── run ───────────────────────────────────────────────────────────────
# ── static files ─────────────────────────────────────────────────────
@app.route("/")
def index():
    try:
        return send_file("extension/popup.html")
    except Exception:
        return "Extension files not found", 404


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5100))
    app.run(host=host, port=port, debug=False)
