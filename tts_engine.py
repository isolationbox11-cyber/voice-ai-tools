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
        Dict with optional keys ``voice_id``, ``speaking_rate``, ``pitch``.
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
        from google import genai
        from google.genai import types as genai_types

        api_key = os.environ.get("GOOGLE_API_KEY")
        client = genai.Client(api_key=api_key) if api_key else genai.Client()

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
