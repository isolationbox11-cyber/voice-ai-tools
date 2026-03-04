#!/usr/bin/env python3
"""
TTS Engine
Synthesizes speech using Google GenAI and returns raw audio bytes.
"""

import os
from google import genai
from google.genai import types


def synthesize_speech(text: str, voice_settings: dict) -> tuple[bytes | None, str | None, str | None]:
    """
    Synthesize speech from text using Google GenAI.

    Args:
        text: The text to synthesize.
        voice_settings: Dict with keys like voice_id, speaking_rate, pitch, emotion.

    Returns:
        (audio_bytes, mime_type, error) where error is None on success.
    """
    try:
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))

        voice_id = voice_settings.get("voice_id", "en-US-Studio-O")

        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice_id,
                        )
                    )
                ),
            ),
        )

        audio_bytes = response.candidates[0].content.parts[0].inline_data.data
        mime_type = response.candidates[0].content.parts[0].inline_data.mime_type or "audio/wav"

        return audio_bytes, mime_type, None

    except Exception as e:
        return None, None, str(e)
