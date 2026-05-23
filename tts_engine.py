#!/usr/bin/env python3
"""
TTS Engine – Text-to-Speech synthesis using espeak-ng.

Privacy-first design: audio bytes are returned in-memory and never written to
disk unless an explicit ``debug_output_path`` is provided.
"""

import logging
from typing import Optional, Tuple

import subprocess

logger = logging.getLogger(__name__)

# Maximum text length accepted for synthesis (prevents abuse / runaway requests)
MAX_TEXT_LENGTH = 1000


def synthesize_speech(
    text: str,
    voice_settings: dict,
    debug_output_path: Optional[str] = None,
) -> Tuple[Optional[bytes], str, Optional[str], str]:
    """Synthesize speech for *text* using espeak-ng.

    Parameters
    ----------
    text:
        The text to synthesize.  Truncated to ``MAX_TEXT_LENGTH`` characters.
    voice_settings:
        Dict with optional key ``voice_id`` (currently unused, kept for compatibility).
    debug_output_path:
        When provided the raw audio bytes are also written to this path.
        Disabled by default to avoid persisting audio on disk.

    Returns
    -------
    (audio_bytes, mime_type, error_message, effective_text)
        On success ``audio_bytes`` is the raw audio, ``mime_type`` describes the
        format (``"audio/wav"``), ``error_message`` is ``None``, and
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

    try:
        # Use espeak-ng for TTS
        result = subprocess.run(
            ["espeak-ng", "-v", "en", "-w", "/dev/stdout", text],
            capture_output=True,
            check=True,
        )

        audio_bytes = result.stdout
        mime_type = "audio/wav"

        logger.info(
            f"TTS audio generated: {len(audio_bytes)} bytes, mime type: {mime_type}"
        )

        if debug_output_path:
            with open(debug_output_path, "wb") as fh:
                fh.write(audio_bytes)
            logger.debug("Debug audio written to %s", debug_output_path)

        return audio_bytes, mime_type, None, text

    except Exception:  # pragma: no cover – runtime API errors
        logger.exception("TTS synthesis failed")
        return None, "", "TTS synthesis failed", text
