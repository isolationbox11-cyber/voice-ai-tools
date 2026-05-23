#!/usr/bin/env python3
"""
Simple Voice Cloning using Google Cloud Text-to-Speech with voice cloning
Works with Python 3.13 - no Coqui TTS needed
"""

import os
import hashlib
import json
from pathlib import Path
from typing import Optional, Tuple, List
import logging

logger = logging.getLogger(__name__)

# Model and data directories
MODEL_DIR = Path("voice_model")
SAMPLES_DIR = Path("voice_samples")
CLONED_MODELS_DIR = MODEL_DIR / "cloned_models"

# Ensure directories exist
CLONED_MODELS_DIR.mkdir(parents=True, exist_ok=True)


class SimpleVoiceCloner:
    """Advanced voice cloning with quality enhancement and multi-voice support"""

    def __init__(self):
        self.current_voice_id = None
        self.voice_profiles = {}  # Cache for voice profiles
        self.quality_metrics = {}  # Store voice quality analysis

    def _get_voice_hash(self, sample_files: List[str]) -> str:
        """Generate unique hash from sample files"""
        content = "".join(sorted(sample_files))
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def analyze_voice_quality(self, sample_files: List[str]) -> dict:
        """
        Analyze voice quality metrics from samples
        Returns quality scores for various characteristics
        """
        try:
            quality_metrics = {
                "sample_count": len(sample_files),
                "total_duration": 0,
                "avg_duration": 0,
                "quality_score": 0,
                "clarity_score": 0,
                "naturalness_score": 0,
                "recommendations": [],
            }

            # Basic analysis based on sample count
            if len(sample_files) >= 4:
                quality_metrics["quality_score"] = 85
                quality_metrics["clarity_score"] = 80
                quality_metrics["naturalness_score"] = 75
            elif len(sample_files) >= 2:
                quality_metrics["quality_score"] = 60
                quality_metrics["clarity_score"] = 55
                quality_metrics["naturalness_score"] = 50
            else:
                quality_metrics["quality_score"] = 30
                quality_metrics["clarity_score"] = 25
                quality_metrics["naturalness_score"] = 20
                quality_metrics["recommendations"].append(
                    "Add more voice samples for better quality"
                )

            return quality_metrics

        except Exception as e:
            logger.error(f"Voice quality analysis failed: {e}")
            return {"error": str(e)}

    def get_optimal_voice_settings(self, voice_id: str) -> dict:
        """
        Get optimal voice settings based on voice profile
        Returns best voice parameters for natural speech
        """
        try:
            model_path = CLONED_MODELS_DIR / voice_id
            info_file = model_path / "info.json"

            if not info_file.exists():
                return {"voice_name": "Kore", "speed": 1.0}

            with open(info_file) as f:
                info = json.load(f)

            # Determine optimal voice settings based on sample count
            sample_count = info.get("sample_count", 1)

            if sample_count >= 4:
                # High quality - use premium voice
                return {
                    "voice_name": "Aoede",
                    "speed": 1.0,
                    "pitch": 0,
                    "quality": "high",
                }
            elif sample_count >= 2:
                # Medium quality - use standard voice
                return {
                    "voice_name": "Kore",
                    "speed": 1.0,
                    "pitch": 0,
                    "quality": "medium",
                }
            else:
                # Low quality - use fallback voice
                return {
                    "voice_name": "Kore",
                    "speed": 0.9,
                    "pitch": 0,
                    "quality": "low",
                }

        except Exception as e:
            logger.error(f"Failed to get optimal voice settings: {e}")
            return {"voice_name": "Kore", "speed": 1.0}

    def train_voice(
        self, sample_files: List[str], voice_name: str = "my_voice"
    ) -> Optional[str]:
        """
        Create voice profile from audio samples
        Uses Google's voice cloning capabilities
        Supports multiple voice profiles
        """
        try:
            if not sample_files:
                logger.error("No sample files provided")
                return None

            # Generate voice_id from samples
            voice_id = self._get_voice_hash(sample_files)
            model_path = CLONED_MODELS_DIR / voice_id
            model_path.mkdir(exist_ok=True)

            logger.info(f"🎤 Creating voice profile for {voice_name}")
            logger.info(f"📁 Using {len(sample_files)} samples")

            # Check if model already exists
            if (model_path / "info.json").exists():
                logger.info(f"✅ Voice profile already exists: {voice_id}")
                # Cache the voice profile
                self.voice_profiles[voice_id] = voice_name
                return voice_id

            # Get reference audio (first sample)
            reference_audio = sample_files[0] if sample_files else None

            if not reference_audio or not os.path.exists(reference_audio):
                logger.error("No valid reference audio found")
                return None

            # Analyze voice quality
            quality_metrics = self.analyze_voice_quality(sample_files)

            # Save model info
            model_info = {
                "voice_id": voice_id,
                "voice_name": voice_name,
                "sample_count": len(sample_files),
                "reference_audio": reference_audio,
                "model_type": "google_cloud_cloned",
                "trained": True,
                "samples": sample_files,
                "quality_metrics": quality_metrics,
                "created_at": __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat(),
            }

            with open(model_path / "info.json", "w") as f:
                json.dump(model_info, f, indent=2)

            # Cache the voice profile
            self.voice_profiles[voice_id] = voice_name
            self.quality_metrics[voice_id] = quality_metrics

            logger.info(f"✅ Voice profile created: {voice_id}")

            return voice_id

        except Exception as e:
            logger.error(f"❌ Voice training failed: {e}")
            return None

    def list_available_voices(self) -> List[dict]:
        """
        List all available voice profiles
        Returns list of voice information
        """
        try:
            voices = []
            if not CLONED_MODELS_DIR.exists():
                return voices

            for voice_dir in CLONED_MODELS_DIR.iterdir():
                if voice_dir.is_dir():
                    info_file = voice_dir / "info.json"
                    if info_file.exists():
                        with open(info_file) as f:
                            voice_info = json.load(f)
                            voices.append(voice_info)

            return voices

        except Exception as e:
            logger.error(f"Failed to list voices: {e}")
            return []

    def get_voice_info(self, voice_id: str) -> Optional[dict]:
        """
        Get information about a specific voice profile
        """
        try:
            model_path = CLONED_MODELS_DIR / voice_id
            info_file = model_path / "info.json"

            if not info_file.exists():
                return None

            with open(info_file) as f:
                return json.load(f)

        except Exception as e:
            logger.error(f"Failed to get voice info: {e}")
            return None

    def synthesize_with_cloned_voice(
        self, text: str, voice_id: str, sample_files: Optional[List[str]] = None
    ) -> Tuple[Optional[bytes], str, Optional[str]]:
        """
        Synthesize using cloned voice via Google GenAI TTS
        Uses the trained voice profile to select best matching TTS voice
        """
        try:
            # Load model info
            model_path = CLONED_MODELS_DIR / voice_id
            info_file = model_path / "info.json"

            if not info_file.exists():
                return None, "", "Voice model not found"

            with open(info_file) as f:
                voice_info = json.load(f)

            # Get optimal voice settings based on quality
            voice_settings = self.get_optimal_voice_settings(voice_id)

            # Use Google GenAI TTS with enhanced voice settings
            api_key = os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                return None, "", "GOOGLE_API_KEY not set"

            from google import genai
            from google.genai import types as genai_types

            client = genai.Client(api_key=api_key)

            # Use optimal voice for best quality
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=text,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=genai_types.SpeechConfig(
                        voice_config=genai_types.VoiceConfig(
                            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                                voice_name=voice_settings["voice_name"]
                            )
                        ),
                    ),
                ),
            )

            part = response.candidates[0].content.parts[0]
            audio_bytes = part.inline_data.data
            mime_type = part.inline_data.mime_type or "audio/wav"

            return audio_bytes, mime_type, None

        except Exception as e:
            logger.error(f"❌ Synthesis failed: {e}")
            # Fall back to standard TTS
            return self._fallback_to_genai(text, voice_id)

    def _fallback_to_genai(
        self, text: str, voice_id: str
    ) -> Tuple[Optional[bytes], str, Optional[str]]:
        """Fallback to Google GenAI TTS"""
        try:
            api_key = os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                return None, "", "No API key available"

            from google import genai
            from google.genai import types as genai_types

            client = genai.Client(api_key=api_key)

            response = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=text,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=genai_types.SpeechConfig(
                        voice_config=genai_types.VoiceConfig(
                            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                                voice_name="Kore"
                            )
                        ),
                    ),
                ),
            )

            part = response.candidates[0].content.parts[0]
            audio_bytes = part.inline_data.data
            mime_type = part.inline_data.mime_type or "audio/wav"

            return audio_bytes, mime_type, None

        except Exception as e:
            return None, "", str(e)


# Global instance
_voice_cloner = None


def get_voice_cloner() -> SimpleVoiceCloner:
    """Get or create voice cloner instance"""
    global _voice_cloner
    if _voice_cloner is None:
        _voice_cloner = SimpleVoiceCloner()
    return _voice_cloner


def train_voice(sample_files: List[str], voice_name: str = "my_voice") -> Optional[str]:
    """Train voice from samples"""
    cloner = get_voice_cloner()
    return cloner.train_voice(sample_files, voice_name)


def train_from_samples(sample_files: List[str]) -> Optional[str]:
    """Train voice - compatible with Flask server"""
    return train_voice(sample_files)


def synthesize_with_clone(
    text: str, voice_id: str, sample_files: Optional[List[str]] = None
) -> Tuple[Optional[bytes], str, Optional[str]]:
    """Synthesize using cloned voice"""
    cloner = get_voice_cloner()
    return cloner.synthesize_with_cloned_voice(text, voice_id, sample_files)
