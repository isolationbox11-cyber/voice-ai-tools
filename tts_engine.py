#!/usr/bin/env python3
"""
TTS Engine – Text-to-Speech synthesis using pluggable strategies (F5-TTS, Google GenAI, espeak).
"""

import logging
import os
import subprocess
from typing import Optional, Tuple
from abc import ABC, abstractmethod

# Attempt to load google genai if installed
try:
    from google import genai
    HAS_GOOGLE_GENAI = True
except ImportError:
    HAS_GOOGLE_GENAI = False

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 1000
VOICE_SAMPLES_DIR = "voice_samples"
DEFAULT_REF_AUDIO = os.path.join(VOICE_SAMPLES_DIR, "take_0_calm.wav")
DEFAULT_REF_TEXT = "This is a calm voice sample for cloning."


class TTSEngine(ABC):
    @abstractmethod
    def synthesize(self, text: str, voice_settings: dict) -> Tuple[Optional[bytes], str, Optional[str]]:
        pass


class F5TTSEngine(TTSEngine):
    def __init__(self):
        self.cli_path = os.environ.get("F5_TTS_PATH", "/opt/miniconda3/envs/f5-tts/bin/f5-tts_infer-cli")
        
    def synthesize(self, text: str, voice_settings: dict) -> Tuple[Optional[bytes], str, Optional[str]]:
        ref_audio = voice_settings.get("ref_audio", DEFAULT_REF_AUDIO)
        ref_text = voice_settings.get("ref_text", DEFAULT_REF_TEXT)

        try:
            result = subprocess.run(
                [
                    self.cli_path,
                    "--model", "F5TTS_v1_Base",
                    "--ref_audio", ref_audio,
                    "--ref_text", ref_text,
                    "--gen_text", text,
                ],
                capture_output=True,
                check=False,
            )

            if result.returncode != 0:
                logger.error(f"F5-TTS failed: {result.stderr.decode()}")
                return None, "", "F5-TTS inference failed"

            return result.stdout, "audio/wav", None
        except Exception as e:
            logger.exception("F5-TTS process exception")
            return None, "", str(e)


class GoogleGenAIEngine(TTSEngine):
    def __init__(self):
        if not HAS_GOOGLE_GENAI:
            raise RuntimeError("google-genai package is not installed.")
        self.client = genai.Client()
        
    def synthesize(self, text: str, voice_settings: dict) -> Tuple[Optional[bytes], str, Optional[str]]:
        # Placeholder for actual Google GenAI TTS integration.
        # The exact implementation depends on the expected google-genai library endpoints.
        return b"", "audio/wav", "Google GenAI TTS unimplemented"


class EspeakEngine(TTSEngine):
    def synthesize(self, text: str, voice_settings: dict) -> Tuple[Optional[bytes], str, Optional[str]]:
        try:
            result = subprocess.run(
                ["espeak-ng", "-v", "en", "-w", "/dev/stdout", text],
                capture_output=True,
                check=True,
            )
            return result.stdout, "audio/wav", None
        except Exception as e:
            logger.exception("Espeak failed")
            return None, "", str(e)


def synthesize_speech(
    text: str,
    voice_settings: dict,
    debug_output_path: Optional[str] = None,
) -> Tuple[Optional[bytes], str, Optional[str], str]:
    if not text or not text.strip():
        return None, "", "Empty text provided", text

    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]

    provider = os.environ.get("TTS_PROVIDER", "f5-tts").lower()
    
    engine = None
    if provider == "google":
        try:
            engine = GoogleGenAIEngine()
        except RuntimeError:
            logger.warning("Google GenAI unavailable, falling back to espeak")
            engine = EspeakEngine()
    elif provider == "f5-tts":
        engine = F5TTSEngine()
    else:
        engine = EspeakEngine()

    audio_bytes, mime_type, error = engine.synthesize(text, voice_settings)
    
    # Fallback to espeak if primary engine fails
    if error and not isinstance(engine, EspeakEngine):
        logger.warning(f"Primary engine {provider} failed: {error}. Falling back to espeak-ng.")
        engine = EspeakEngine()
        audio_bytes, mime_type, error = engine.synthesize(text, voice_settings)

    if audio_bytes and debug_output_path:
        try:
            with open(debug_output_path, "wb") as fh:
                fh.write(audio_bytes)
        except Exception as e:
            logger.error(f"Failed to write debug audio: {e}")

    return audio_bytes, mime_type, error, text

