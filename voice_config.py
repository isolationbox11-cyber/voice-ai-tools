# Voice configuration for natural speech
VOICE_SETTINGS = {
    "voice_preset": "natural_professional",  # Options: natural_professional, natural_friendly, natural_firm
    "speaking_rate": 1.0,  # 0.8-1.2 for natural range
    "pitch": 0,  # -20 to 20 for natural variation
    "volume_gain_db": 0,  # Adjust volume
    "emotion": "professional_concerned",  # Can change based on context
}


# Context-aware voice adjustments
def get_voice_for_context(call_type):
    if call_type == "SCAM_DETECTED":
        return {
            "emotion": "firm_authoritative",
            "speaking_rate": 0.9,  # Slower, more deliberate
            "pitch": -2,  # Lower pitch for authority
        }
    elif call_type == "VERIFICATION":
        return {"emotion": "professional_calm", "speaking_rate": 1.0, "pitch": 0}
    else:  # LEGITIMATE
        return {"emotion": "helpful_professional", "speaking_rate": 1.1, "pitch": 2}
