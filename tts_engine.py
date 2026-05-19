#!/usr/bin/env python3
"""
TTS Engine - Text-to-Speech synthesis.

Routing logic (in priority order):
  1. voice_id starts with 'local_voice_'  -> Path A: Coqui XTTS v2 embedding
                                             (trained via /train endpoint)
  2. voice_id starts with 'wav_ref_'      -> Path B: Coqui XTTS v2 zero-shot
                                             (pre-stored WAV reference file)
  3. anything else                         -> Google Gemini TTS (prebuilt voice)

For paths A and B, Coqui runs 100% locally — no API key needed.
Both fall back to Gemini 'Kore' if Coqui synthesis fails.

Privacy-first: audio bytes returned in-memory, never written to disk
unless debug_output_path is provided.
"""

import logging
import os
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 2000
_TTS_MODEL = "gemini-2.5-flash-preview-tts"
_genai_client = None
_client_lock = threading.Lock()


def _get_client():
    global _genai_client
    if _genai_client is None:
        with _client_lock:
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

    voice_settings keys used:
      voice_id  (str) — determines routing (see module docstring)
      engine    (str) — optional hint; 'wav_reference' triggers Path B lookup
      CUSTOM_VOICE_SAMPLES[0] is used as the WAV path for Path B
    """
    if not text or not text.strip():
        return None, "", "Empty text provided", text

    if len(text) > MAX_TEXT_LENGTH:
        logger.warning("Text truncated from %d to %d characters", len(text), MAX_TEXT_LENGTH)
        text = text[:MAX_TEXT_LENGTH]

    voice_id = (voice_settings.get("voice_id") or "Kore").strip()
    engine   = (voice_settings.get("engine") or "").strip()

    # ── Path A: Coqui embedding (trained via /train) ───────────────────────
    if voice_id.startswith("local_voice_"):
        logger.info("Path A — Coqui embedding for voice: %s", voice_id)
        try:
            from voice_training import synthesize_with_cloned_voice
            audio_bytes = synthesize_with_cloned_voice(text, voice_id)
            if audio_bytes:
                if debug_output_path:
                    with open(debug_output_path, "wb") as fh:
                        fh.write(audio_bytes)
                return audio_bytes, "audio/wav", None, text
            logger.warning("Path A returned None — falling back to Gemini Kore.")
            voice_id = "Kore"
        except Exception as e:
            logger.error("Path A Coqui error: %s", e)
            voice_id = "Kore"

    # ── Path B: Coqui zero-shot from stored WAV reference ─────────────────
    elif voice_id.startswith("wav_ref_") or engine == "wav_reference":
        logger.info("Path B — WAV reference zero-shot for voice: %s", voice_id)
        wav_path = None

        # First, try to get the WAV path from custom_voice_config
        try:
            import importlib
            cvc = importlib.import_module("custom_voice_config")
            samples = getattr(cvc, "CUSTOM_VOICE_SAMPLES", [])
            if samples:
                wav_path = samples[0]
        except Exception:
            pass

        # Fallback: check voice_settings itself for a wav_path key
        if not wav_path:
            wav_path = voice_settings.get("wav_path") or voice_settings.get("sample_path")

        if wav_path:
            try:
                from voice_training import synthesize_from_wav_reference
                audio_bytes = synthesize_from_wav_reference(text, wav_path)
                if audio_bytes:
                    if debug_output_path:
                        with open(debug_output_path, "wb") as fh:
                            fh.write(audio_bytes)
                    return audio_bytes, "audio/wav", None, text
                logger.warning("Path B returned None — falling back to Gemini Kore.")
            except Exception as e:
                logger.error("Path B WAV reference error: %s", e)
        else:
            logger.warning("Path B: no WAV path found in custom_voice_config or voice_settings — falling back.")

        voice_id = "Kore"  # fall through to Gemini

    # ── Path C: Gemini TTS (prebuilt / stock voices) ───────────────────────
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
