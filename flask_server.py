#!/usr/bin/env python3
"""
Flask TTS Server
Provides a local HTTP API for browser-based TTS playback via Chrome extension.

Environment variables:
  GOOGLE_API_KEY       - Google GenAI API key (required)
  VOICE_SERVER_TOKEN   - Shared secret for X-Voice-Token header (required)
  ALLOWED_ORIGINS      - Comma-separated extra origins (optional)
  HOST                 - Bind host (default: 127.0.0.1)
  PORT                 - Bind port (default: 5000)
"""

import os
import importlib
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from tts_engine import synthesize_speech
from voice_config import get_voice_for_context

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VOICE_SERVER_TOKEN = os.environ.get("VOICE_SERVER_TOKEN", "")
MAX_TEXT_LENGTH = 2000

# CORS: always allow localhost origins; caller can add extension ID via env
_extra_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
ALLOWED_ORIGINS = [
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "null",          # local file:// pages
] + _extra_origins

CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}}, supports_credentials=True)

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["60 per minute"],
    storage_uri="memory://",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_token() -> bool:
    """Return True if the request carries a valid auth token."""
    if not VOICE_SERVER_TOKEN:
        # No token configured – accept all (development mode)
        return True
    return request.headers.get("X-Voice-Token", "") == VOICE_SERVER_TOKEN


def _resolve_voice_settings(call_type: str) -> dict:
    """
    Resolve voice settings, preferring custom_voice_config when available.
    Falls back to voice_config.get_voice_for_context.
    """
    try:
        cvc = importlib.import_module("custom_voice_config")
        settings = cvc.get_custom_voice_settings(call_type)
        # Ensure voice_id is set to the custom voice
        if not settings.get("voice_id"):
            settings["voice_id"] = getattr(cvc, "CUSTOM_VOICE_ID", "en-US-Studio-O")
        return settings
    except ModuleNotFoundError:
        pass

    settings = get_voice_for_context(call_type)
    settings.setdefault("voice_id", "en-US-Studio-O")
    return settings


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@app.route("/tts", methods=["POST"])
@limiter.limit("30 per minute")
def tts():
    """
    Synthesize TTS and return raw audio bytes.

    Request JSON: { "text": string, "call_type": string }
    Response: audio/* bytes on success, JSON error on failure.
    """
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    if len(text) > MAX_TEXT_LENGTH:
        return jsonify({"error": f"text exceeds maximum length of {MAX_TEXT_LENGTH}"}), 400

    call_type = data.get("call_type", "LEGITIMATE").strip().upper()

    voice_settings = _resolve_voice_settings(call_type)
    audio_bytes, mime_type, error = synthesize_speech(text, voice_settings)

    if error:
        return jsonify({"error": error}), 502

    return Response(audio_bytes, mimetype=mime_type)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not VOICE_SERVER_TOKEN:
        print("⚠️  WARNING: VOICE_SERVER_TOKEN is not set – the server is open to any caller on localhost.")
        print("   Set it with: export VOICE_SERVER_TOKEN=<your-secret>")

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))

    print(f"🚀 Voice TTS Server starting on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
