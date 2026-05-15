#!/usr/bin/env python3
"""
TTS Engine - Text-to-Speech synthesis.

Routing logic:
  - voice_id starts with 'local_voice_' -> Coqui XTTS v2 (local, no API key)
  - anything else                       -> Google Gemini TTS

Privacy-first: audio bytes returned in-memory, never written to disk
unless debug_output_path is provided.
"""

import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 1000
_TTS_MODEL = "gemini-2.5-flash-preview-tts"
_genai_client = None


def _get_client():
    global _genai_client
    if _genai_client is None:
        try:
            from google import genai
            api_key = os.environ.get("GOOGLE_API_KEY")
            _genai_client = genai.Client(api_key=api_key) if api_key else genai.Client()
        except Exception as e:
            logger.error("Failed to create GenAI client: %s", e)
            raise
    return _genai_client


def synthesize_speech(
    text: str,
    voice_settings: dict,
    debug_output_path: Optional[str] = None,
) -> Tuple[Optional[bytes], str, Optional[str], str]:
    """Synthesize speech for text using voice_settings.

    Returns (audio_bytes, mime_type, error_message, effective_text).
    On failure, audio_bytes is None and error_message describes the problem.
    """
    if not text or not text.strip():
        return None, "", "Empty text provided", text

    if len(text) > MAX_TEXT_LENGTH:
        logger.warning("Text truncated from %d to %d characters", len(text), MAX_TEXT_LENGTH)
        text = text[:MAX_TEXT_LENGTH]

    voice_id = (voice_settings.get("voice_id") or "Kore").strip()

    # ── Route to Coqui XTTS v2 for locally trained voices ──────────────────
    if voice_id.startswith("local_voice_"):
        logger.info("Routing to Coqui XTTS v2 for cloned voice: %s", voice_id)
        try:
            from voice_training import synthesize_with_cloned_voice
            audio_bytes = synthesize_with_cloned_voice(text, voice_id)
            if audio_bytes:
                if debug_output_path:
                    with open(debug_output_path, "wb") as fh:
                        fh.write(audio_bytes)
                return audio_bytes, "audio/wav", None, text
            else:
                logger.warning("Coqui synthesis returned None, falling back to Gemini Kore.")
                voice_id = "Kore"  # fall through to Gemini below
        except Exception as e:
            logger.error("Coqui synthesis error: %s", e)
            voice_id = "Kore"  # fall through to Gemini below

    # ── Gemini TTS for stock / preset voices ──────────────────────────────
    try:
        from google.genai import types as genai_types
        client = _get_client()

        if voice_id and voice_id.lower() != "default":
            voice_cfg = genai_types.VoiceConfig(
                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                    voice_name=voice_id
                )
            )
        else:
            voice_cfg = genai_types.VoiceConfig(
                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                    voice_name="Kore"
                )
            )

        response = client.models.generate_content(
            model=_TTS_MODEL,
            contents=text,
            config=genai_types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=genai_types.SpeechConfig(
                    voice_config=voice_cfg,
                ),
            ),
        )
        part = response.candidates[0].content.parts[0]
        audio_bytes: bytes = part.inline_data.data
        mime_type: str = part.inline_data.mime_type or "audio/wav"

        if debug_output_path:
            with open(debug_output_path, "wb") as fh:
                fh.write(audio_bytes)
            logger.debug("Debug audio written to %s", debug_output_path)

        return audio_bytes, mime_type, None, text

    except Exception as e:
        logger.exception("TTS synthesis failed")
        return None, "", f"TTS synthesis failed: {e}", text
