#!/usr/bin/env python3
"""
TTS Engine – Text-to-Speech synthesis using Hugging Face models.

Privacy-first design: audio bytes are returned in-memory and never written to
disk unless an explicit ``debug_output_path`` is provided.
"""

import logging
from typing import Optional, Tuple

import numpy as np
import scipy.io.wavfile as wavfile
import torch
from transformers import SpeechT5Processor, SpeechT5ForTextToSpeech, SpeechT5HifiGan

logger = logging.getLogger(__name__)

# Maximum text length accepted for synthesis (prevents abuse / runaway requests)
MAX_TEXT_LENGTH = 1000

# Hugging Face TTS model
_TTS_MODEL = "microsoft/speecht5_tts"
_VOCODER_MODEL = "microsoft/speecht5_hifigan"
_EMBEDDINGS_MODEL = "microsoft/speecht5_hifigan"

# Model cache (lazy loading)
_processor = None
_model = None
_vocoder = None
_speaker_embeddings = None


def _load_models():
    """Lazy load Hugging Face TTS models."""
    global _processor, _model, _vocoder, _speaker_embeddings
    if _processor is None:
        logger.info("Loading Hugging Face TTS models...")
        _processor = SpeechT5Processor.from_pretrained(_TTS_MODEL)
        _model = SpeechT5ForTextToSpeech.from_pretrained(_TTS_MODEL)
        _vocoder = SpeechT5HifiGan.from_pretrained(_VOCODER_MODEL)

        # Load default speaker embeddings
        import torch

        _speaker_embeddings = torch.randn(1, 512)
        logger.info("Hugging Face TTS models loaded successfully")


def synthesize_speech(
    text: str,
    voice_settings: dict,
    debug_output_path: Optional[str] = None,
) -> Tuple[Optional[bytes], str, Optional[str], str]:
    """Synthesize speech for *text* using Hugging Face models.

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
        _load_models()

        # Prepare inputs
        inputs = _processor(text=text, return_tensors="pt")

        # Generate speech
        with torch.no_grad():
            speech = _model.generate_speech(
                inputs["input_ids"], _speaker_embeddings, vocoder=_vocoder
            )

        # Convert to WAV format
        audio_array = speech.cpu().numpy().squeeze()
        audio_array = (audio_array * 32767).astype(np.int16)  # Convert to 16-bit PCM

        # Create WAV file in memory
        import io

        wav_buffer = io.BytesIO()
        wavfile.write(wav_buffer, 16000, audio_array)  # SpeechT5 uses 16kHz
        wav_buffer.seek(0)

        audio_bytes = wav_buffer.read()
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
