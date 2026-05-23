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
        Dict with optional key ``voice_id`` (name of the Gemini prebuilt voice
        to use; defaults to ``"Kore"`` when absent or ``"default"``).
        If voice_id starts with "trained_", uses voice cloning instead.
        Keys ``speaking_rate`` and ``pitch`` are not currently supported by the
        GenAI TTS API and are ignored if present.
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
        logger.warning(
            "Text truncated from %d to %d characters", len(text), MAX_TEXT_LENGTH
        )
        text = text[:MAX_TEXT_LENGTH]

    voice_id = voice_settings.get("voice_id")

    # Check if using cloned voice (starts with "trained_")
    if voice_id and voice_id.startswith("trained_"):
        logger.info(f"🎤 Using cloned voice: {voice_id}")
        try:
            # Try simple voice cloner first (Python 3.13 compatible)
            from simple_voice_cloner import synthesize_with_clone

            audio_bytes, mime_type, error = synthesize_with_clone(
                text=text,
                voice_id=voice_id,
                sample_files=None,  # Will be loaded from model info
            )

            if error:
                logger.error(f"Voice cloning failed: {error}")
                # Fall back to default voice
                logger.info("Falling back to default voice")
            else:
                if debug_output_path:
                    with open(debug_output_path, "wb") as fh:
                        fh.write(audio_bytes)
                    logger.debug("Debug audio written to %s", debug_output_path)
                return audio_bytes, mime_type, None, text

        except Exception as e:
            logger.error(f"Voice cloning error: {e}")
            logger.info("Falling back to default voice")

    # Use Google GenAI TTS (default or fallback)
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.error("GOOGLE_API_KEY environment variable not set.")
        return None, "", "Server configuration error: GOOGLE_API_KEY not set", text

    try:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=api_key)

        # Build the speech config
        if (
            voice_id
            and voice_id not in ["default", None]
            and not voice_id.startswith("trained_")
        ):
            # Use specified prebuilt voice
            voice_cfg = genai_types.VoiceConfig(
                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                    voice_name=voice_id
                )
            )
        else:
            # Default voice
            voice_cfg = genai_types.VoiceConfig(
                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name="Kore")
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
