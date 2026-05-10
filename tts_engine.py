#!/usr/bin/env python3
"""
TTS Engine – Text-to-Speech synthesis using Google GenAI.

Privacy-first design: audio bytes are returned in-memory and never written to
disk unless an explicit ``debug_output_path`` is provided.
"""

import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Maximum text length accepted for synthesis (prevents abuse / runaway requests)
MAX_TEXT_LENGTH = 1000

# Default TTS model exposed by the Gemini API
_TTS_MODEL = "gemini-2.5-flash-preview-tts"

# Module-level client cache.  The client is created once on first use so that
# repeated /tts calls do not pay the constructor overhead each time.
_genai_client = None


def _get_client():
    """Return a cached ``genai.Client``, creating it on the first call."""
    global _genai_client
    if _genai_client is None:
        from google import genai  # imported here so the module loads without google-genai
        api_key = os.environ.get("GOOGLE_API_KEY")
        _genai_client = genai.Client(api_key=api_key) if api_key else genai.Client()
    return _genai_client


def synthesize_speech(
    text: str,
    voice_settings: dict,
    debug_output_path: Optional[str] = None,
) -> Tuple[Optional[bytes], str, Optional[str], str]:
    """Synthesize speech for *text* using *voice_settings*.

    Parameters
    ----------
    text:
        The text to synthesize.  Truncated to ``MAX_TEXT_LENGTH`` characters.
    voice_settings:
        Dict with optional key ``voice_id`` (name of the Gemini prebuilt voice
        to use; defaults to ``"Kore"`` when absent or ``"default"``).
        Additional keys such as ``speaking_rate``, ``pitch``, and ``emotion``
        are accepted but not currently forwarded to the Gemini API (the API
        does not expose those controls via the content-generation endpoint).
    debug_output_path:
        When provided the raw audio bytes are also written to this path.
        Disabled by default to avoid persisting audio on disk.

    Returns
    -------
    (audio_bytes, mime_type, error_message, effective_text)
        On success ``audio_bytes`` is the raw audio, ``mime_type`` describes the
        format (e.g. ``"audio/wav"``), ``error_message`` is ``None``, and
        ``effective_text`` is the (possibly truncated) text that was synthesized.
        On failure ``audio_bytes`` is ``None`` and ``error_message`` describes
        the problem.
    """
    if not text or not text.strip():
        return None, "", "Empty text provided", text

    # Sanitize / limit input length
    if len(text) > MAX_TEXT_LENGTH:
        logger.warning("Text truncated from %d to %d characters", len(text), MAX_TEXT_LENGTH)
        text = text[:MAX_TEXT_LENGTH]

    try:
        from google.genai import types as genai_types

        client = _get_client()

        voice_id = voice_settings.get("voice_id")

        # Build the speech config
        if voice_id and voice_id != "default":
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

    except Exception:  # pragma: no cover – runtime API errors
        logger.exception("TTS synthesis failed")
        return None, "", "TTS synthesis failed", text
