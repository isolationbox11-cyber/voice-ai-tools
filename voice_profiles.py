#!/usr/bin/env python3
"""
Voice Profiles Management for Voice AI Tools
Supports multiple voice profiles with different accents, languages, and emotions.
"""

import json
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path
from enum import Enum


class VoiceGender(Enum):
    """Voice gender options."""
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


class VoiceAccent(Enum):
    """Voice accent options."""
    AMERICAN = "american"
    BRITISH = "british"
    AUSTRALIAN = "australian"
    INDIAN = "indian"
    CANADIAN = "canadian"
    NEUTRAL = "neutral"


class VoiceEmotion(Enum):
    """Voice emotion options."""
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    EXCITED = "excited"
    CALM = "calm"
    PROFESSIONAL = "professional"
    CASUAL = "casual"


class VoiceLanguage(Enum):
    """Supported languages."""
    ENGLISH = "en"
    SPANISH = "es"
    FRENCH = "fr"
    GERMAN = "de"
    ITALIAN = "it"
    PORTUGUESE = "pt"
    CHINESE = "zh"
    JAPANESE = "ja"
    KOREAN = "ko"


@dataclass
class VoiceProfile:
    """Voice profile configuration."""
    id: str
    name: str
    description: str
    gender: VoiceGender
    accent: VoiceAccent
    language: VoiceLanguage
    emotion: VoiceEmotion
    speaking_rate: float = 1.0  # 0.25 to 4.0
    pitch: float = 0.0      # -20.0 to 20.0 semitones
    sample_rate: int = 24000
    is_custom: bool = False
    custom_voice_id: Optional[str] = None
    created_at: Optional[str] = None
    tags: List[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            from datetime import datetime, timezone
            self.created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if self.tags is None:
            self.tags = []
    
    def to_google_voice_config(self):
        """Convert to Google GenAI voice configuration."""
        # Map our enums to Google voice names
        voice_mapping = {
            (VoiceGender.FEMALE, VoiceAccent.AMERICAN, VoiceLanguage.ENGLISH): "Kore",
            (VoiceGender.MALE, VoiceAccent.AMERICAN, VoiceLanguage.ENGLISH): "Puck",
            (VoiceGender.FEMALE, VoiceAccent.BRITISH, VoiceLanguage.ENGLISH): "Charon",
            (VoiceGender.MALE, VoiceAccent.BRITISH, VoiceLanguage.ENGLISH): "Aoede",
        }
        
        # Get voice name or default to Kore
        voice_name = voice_mapping.get(
            (self.gender, self.accent, self.language), "Kore"
        )
        
        return {
            "voice_name": voice_name,
            "speaking_rate": self.speaking_rate,
            "pitch": self.pitch
        }


class VoiceProfileManager:
    """Manages multiple voice profiles."""
    
    def __init__(self, profiles_file: str = "voice_profiles.json"):
        self.profiles_file = Path(profiles_file)
        self.profiles: Dict[str, VoiceProfile] = {}
        self.load_profiles()
    
    def load_profiles(self):
        """Load profiles from file."""
        if self.profiles_file.exists():
            try:
                with open(self.profiles_file, 'r') as f:
                    data = json.load(f)
                
                for profile_data in data.get('profiles', []):
                    profile = VoiceProfile(
                        id=profile_data['id'],
                        name=profile_data['name'],
                        description=profile_data['description'],
                        gender=VoiceGender(profile_data['gender']),
                        accent=VoiceAccent(profile_data['accent']),
                        language=VoiceLanguage(profile_data['language']),
                        emotion=VoiceEmotion(profile_data['emotion']),
                        speaking_rate=profile_data.get('speaking_rate', 1.0),
                        pitch=profile_data.get('pitch', 0.0),
                        sample_rate=profile_data.get('sample_rate', 24000),
                        is_custom=profile_data.get('is_custom', False),
                        custom_voice_id=profile_data.get('custom_voice_id'),
                        created_at=profile_data.get('created_at'),
                        tags=profile_data.get('tags', [])
                    )
                    self.profiles[profile.id] = profile
            except Exception as e:
                print(f"Error loading voice profiles: {e}")
        
        # Create default profiles if none exist
        if not self.profiles:
            self._create_default_profiles()
    
    def save_profiles(self):
        """Save profiles to file."""
        data = {
            "profiles": [asdict(profile) for profile in self.profiles.values()]
        }
        
        try:
            with open(self.profiles_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving voice profiles: {e}")
    
    def _create_default_profiles(self):
        """Create default voice profiles."""
        default_profiles = [
            VoiceProfile(
                id="default_american_female",
                name="American Female",
                description="Standard American female voice",
                gender=VoiceGender.FEMALE,
                accent=VoiceAccent.AMERICAN,
                language=VoiceLanguage.ENGLISH,
                emotion=VoiceEmotion.NEUTRAL,
                tags=["default", "american", "female"]
            ),
            VoiceProfile(
                id="default_american_male",
                name="American Male",
                description="Standard American male voice",
                gender=VoiceGender.MALE,
                accent=VoiceAccent.AMERICAN,
                language=VoiceLanguage.ENGLISH,
                emotion=VoiceEmotion.NEUTRAL,
                tags=["default", "american", "male"]
            ),
            VoiceProfile(
                id="default_british_female",
                name="British Female",
                description="Standard British female voice",
                gender=VoiceGender.FEMALE,
                accent=VoiceAccent.BRITISH,
                language=VoiceLanguage.ENGLISH,
                emotion=VoiceEmotion.NEUTRAL,
                tags=["default", "british", "female"]
            ),
            VoiceProfile(
                id="professional_american_male",
                name="Professional American Male",
                description="Professional American male voice for business use",
                gender=VoiceGender.MALE,
                accent=VoiceAccent.AMERICAN,
                language=VoiceLanguage.ENGLISH,
                emotion=VoiceEmotion.PROFESSIONAL,
                speaking_rate=0.9,
                tags=["professional", "american", "male", "business"]
            ),
            VoiceProfile(
                id="casual_american_female",
                name="Casual American Female",
                description="Casual American female voice for informal conversations",
                gender=VoiceGender.FEMALE,
                accent=VoiceAccent.AMERICAN,
                language=VoiceLanguage.ENGLISH,
                emotion=VoiceEmotion.CASUAL,
                speaking_rate=1.1,
                tags=["casual", "american", "female", "informal"]
            ),
        ]
        
        for profile in default_profiles:
            self.profiles[profile.id] = profile
        
        self.save_profiles()
    
    def create_profile(self, name: str, description: str, gender: VoiceGender,
                    accent: VoiceAccent, language: VoiceLanguage, 
                    emotion: VoiceEmotion, **kwargs) -> str:
        """Create a new voice profile."""
        profile_id = str(uuid.uuid4())
        
        profile = VoiceProfile(
            id=profile_id,
            name=name,
            description=description,
            gender=gender,
            accent=accent,
            language=language,
            emotion=emotion,
            **kwargs
        )
        
        self.profiles[profile_id] = profile
        self.save_profiles()
        return profile_id
    
    def update_profile(self, profile_id: str, **kwargs) -> bool:
        """Update an existing voice profile."""
        if profile_id not in self.profiles:
            return False
        
        profile = self.profiles[profile_id]
        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        
        self.save_profiles()
        return True
    
    def delete_profile(self, profile_id: str) -> bool:
        """Delete a voice profile."""
        if profile_id not in self.profiles:
            return False
        
        del self.profiles[profile_id]
        self.save_profiles()
        return True
    
    def get_profile(self, profile_id: str) -> Optional[VoiceProfile]:
        """Get a voice profile by ID."""
        return self.profiles.get(profile_id)
    
    def list_profiles(self, filters: Dict[str, Any] = None) -> List[VoiceProfile]:
        """List all profiles, optionally filtered."""
        profiles = list(self.profiles.values())
        
        if filters:
            filtered_profiles = []
            for profile in profiles:
                matches = True
                for key, value in filters.items():
                    if hasattr(profile, key):
                        profile_value = getattr(profile, key)
                        if isinstance(profile_value, Enum):
                            if profile_value.value != value:
                                matches = False
                                break
                        elif profile_value != value:
                            matches = False
                            break
                if matches:
                    filtered_profiles.append(profile)
            profiles = filtered_profiles
        
        return profiles
    
    def search_profiles(self, query: str) -> List[VoiceProfile]:
        """Search profiles by name, description, or tags."""
        query = query.lower()
        results = []
        
        for profile in self.profiles.values():
            if (query in profile.name.lower() or 
                query in profile.description.lower() or
                any(query in tag.lower() for tag in profile.tags)):
                results.append(profile)
        
        return results
    
    def create_custom_profile(self, custom_voice_id: str, name: str, 
                          description: str, **kwargs) -> str:
        """Create a custom voice profile from trained voice."""
        profile_id = str(uuid.uuid4())
        
        profile = VoiceProfile(
            id=profile_id,
            name=name,
            description=description,
            gender=kwargs.get('gender', VoiceGender.NEUTRAL),
            accent=kwargs.get('accent', VoiceAccent.NEUTRAL),
            language=kwargs.get('language', VoiceLanguage.ENGLISH),
            emotion=kwargs.get('emotion', VoiceEmotion.NEUTRAL),
            is_custom=True,
            custom_voice_id=custom_voice_id,
            **kwargs
        )
        
        self.profiles[profile_id] = profile
        self.save_profiles()
        return profile_id


# Global voice profile manager
voice_profile_manager = VoiceProfileManager()
