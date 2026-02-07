import asyncio
from google import genai


class VoiceTrainer:
    def __init__(self):
        self.client = genai.Client()

    async def create_voice_profile(self, voice_samples_path):
        """Create custom voice profile from your recordings"""

        # Required training phrases
        training_phrases = [
            "Hello, this is a legal screening service.",
            "I need to verify some information.",
            "Your call appears to be fraudulent.",
            "Thank you for calling our office.",
            "May I know who is calling and the purpose of your call?",
            "This number is being reported to the authorities.",
            "What type of legal assistance do you need?",
            "I'll need to verify this before proceeding.",
            "Do not call again.",
            "Let me connect you to our intake system.",
        ]

        print("🎙️ Voice Training Setup")
        print("Please record these phrases in your natural voice:")
        print("-" * 50)

        for i, phrase in enumerate(training_phrases, 1):
            print(f'{i}. "{phrase}"')
            print(f"   Save as: voice_sample_{i:02d}.wav")
            print()

        print("📝 Recording Instructions:")
        print("- Use a quiet environment")
        print("- Speak naturally, don't over-enunciate")
        print("- Record in .wav format, 44.1kHz")
        print("- Each phrase: 3-5 seconds long")
        print("- Save all files in:", voice_samples_path)

    async def train_custom_voice(self, voice_samples_path, voice_name="my_legal_voice"):
        """Train custom voice model"""
        try:
            # Upload voice samples
            voice_files = []
            for i in range(1, 11):  # 10 training phrases
                file_path = f"{voice_samples_path}/voice_sample_{i:02d}.wav"
                voice_files.append(file_path)

            # Create voice profile
            voice_profile = await self.client.voices.create(
                name=voice_name,
                samples=voice_files,
                description="Legal paralegal voice",
                language="en-US",
            )

            print(f"✅ Voice profile created: {voice_profile.id}")
            print("Training may take 10-30 minutes...")

            # Wait for training completion
            while voice_profile.status != "ready":
                await asyncio.sleep(30)
                voice_profile = await self.client.voices.get(voice_profile.id)
                print(f"Training status: {voice_profile.status}")

            print(f"🎉 Voice training complete! Voice ID: {voice_profile.id}")
            return voice_profile.id

        except Exception as e:
            print(f"❌ Training failed: {e}")
            return None

    def update_scam_screener_with_custom_voice(self, voice_id):
        """Update the scam screener to use your custom voice"""

        config_code = f'''
# Custom voice configuration
CUSTOM_VOICE_ID = "{voice_id}"

def get_custom_voice_settings(context):
    """Get voice settings with your custom voice"""
    base_settings = {{
        "voice_id": CUSTOM_VOICE_ID,
        "speaking_rate": 1.0,
        "pitch": 0,
        "emotion": "professional"
    }}

    # Adjust based on context
    if context == "SCAM_DETECTED":
        base_settings.update({{"emotion": "firm", "speaking_rate": 0.9}})
    elif context == "VERIFICATION":
        base_settings.update({{"emotion": "calm", "speaking_rate": 1.0}})
    else:  # LEGITIMATE
        base_settings.update({{"emotion": "helpful", "speaking_rate": 1.1}})

    return base_settings
'''

        with open("custom_voice_config.py", "w") as f:
            f.write(config_code)

        print("✅ Custom voice config created!")
        print("Import this into your scam screener to use your voice.")


async def main():
    trainer = VoiceTrainer()

    print("🎤 Custom Voice Training for Scam Screener")
    print("=" * 50)

    # Step 1: Create recording guide
    await trainer.create_voice_profile("./voice_samples")

    # Step 2: Wait for user to record
    input("\nPress Enter after recording all voice samples...")

    # Step 3: Train the voice
    voice_id = await trainer.train_custom_voice("./voice_samples")

    if voice_id:
        # Step 4: Update scam screener
        trainer.update_scam_screener_with_custom_voice(voice_id)
        print(f"\n🎉 Your scam screener will now speak with YOUR voice!")
        print(f"Voice ID: {voice_id}")


if __name__ == "__main__":
    asyncio.run(main())
