#!/usr/bin/env python3
"""
Configuration validation and management using Pydantic.

Provides:
- Environment variable validation
- Type checking and conversion
- Default values
- Configuration schema documentation
"""

from typing import Optional, List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application configuration with validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Required configuration
    google_api_key: str = Field(
        ...,
        description="Google Gemini API key for TTS synthesis",
        min_length=10
    )

    # Recommended for production
    voice_server_token: Optional[str] = Field(
        None,
        description="Shared secret token for API authentication"
    )

    flask_env: str = Field(
        default="development",
        description="Flask environment (development/production)"
    )

    @field_validator("flask_env")
    @classmethod
    def validate_flask_env(cls, v: str) -> str:
        """Validate Flask environment value."""
        valid_envs = {"development", "production", "testing"}
        if v.lower() not in valid_envs:
            raise ValueError(f"FLASK_ENV must be one of {valid_envs}")
        return v.lower()

    # Optional API keys
    shodan_api_key: Optional[str] = Field(
        None,
        description="Shodan API key for OSINT lookups"
    )

    # Server configuration
    port: int = Field(
        default=5001,
        description="Server port number",
        ge=1,
        le=65535
    )

    host: str = Field(
        default="127.0.0.1",
        description="Server bind address"
    )

    allow_network_binding: bool = Field(
        default=False,
        description="Allow binding to non-loopback addresses (unsafe)"
    )

    @field_validator("allow_network_binding")
    @classmethod
    def warn_network_binding(cls, v: bool, info) -> bool:
        """Warn about network binding security implications."""
        if v and info.data.get("flask_env") == "production":
            import warnings
            warnings.warn(
                "ALLOW_NETWORK_BINDING=1 in production is a security risk!",
                RuntimeWarning
            )
        return v

    # CORS configuration
    allowed_origins: List[str] = Field(
        default=["http://127.0.0.1:5001", "http://localhost:5001"],
        description="Allowed CORS origins"
    )

    # TTS configuration
    google_tts_model: str = Field(
        default="gemini-2.5-flash-preview-tts",
        description="Google TTS model to use"
    )

    tts_max_text_length: int = Field(
        default=2000,
        description="Maximum text length for TTS",
        ge=1,
        le=10000
    )

    # Request signing configuration
    enable_request_signing: bool = Field(
        default=False,
        description="Enable HMAC signature validation for replay protection"
    )

    signing_tolerance_seconds: int = Field(
        default=300,
        description="Signature timestamp tolerance in seconds",
        ge=30,
        le=3600
    )

    # Rate limiting
    rate_limit_per_minute: int = Field(
        default=200,
        description="Default rate limit per minute",
        ge=1,
        le=1000
    )

    tts_rate_limit_per_minute: int = Field(
        default=30,
        description="TTS-specific rate limit per minute",
        ge=1,
        le=500
    )

    # File upload configuration
    max_content_length_mb: int = Field(
        default=50,
        description="Maximum file upload size in MB",
        ge=1,
        le=500
    )

    # Logging configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()

    def validate_production_config(self) -> List[str]:
        """Validate production-specific configuration requirements."""
        warnings = []
        
        if self.flask_env == "production":
            if not self.voice_server_token:
                warnings.append("VOICE_SERVER_TOKEN is required in production")
            
            if self.allow_network_binding:
                warnings.append("ALLOW_NETWORK_BINDING=1 is unsafe in production")
            
            if not self.google_api_key or len(self.google_api_key) < 20:
                warnings.append("GOOGLE_API_KEY should be a strong, production-grade key")
        
        return warnings

    def get_safe_config(self) -> dict:
        """Return configuration with sensitive values masked."""
        config = self.model_dump()
        
        # Mask sensitive values
        sensitive_keys = ["google_api_key", "voice_server_token", "shodan_api_key"]
        for key in sensitive_keys:
            if config.get(key):
                config[key] = f"{config[key][:8]}...{config[key][-4:]}" if len(config[key]) > 12 else "***"
        
        return config


# Global configuration instance
config = AppConfig()


def validate_config() -> bool:
    """
    Validate the current configuration.
    
    Returns:
        bool: True if configuration is valid
        
    Raises:
        ValueError: If configuration is invalid
    """
    warnings = config.validate_production_config()
    
    if warnings:
        import sys
        print("Configuration warnings:", file=sys.stderr)
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)
    
    return True


if __name__ == "__main__":
    """Test configuration validation."""
    import json
    
    print("Testing configuration validation...")
    print("=" * 50)
    
    try:
        validate_config()
        print("✓ Configuration is valid")
        print("\nSafe configuration:")
        print(json.dumps(config.get_safe_config(), indent=2))
    except Exception as e:
        print(f"✗ Configuration validation failed: {e}")
        import sys
        sys.exit(1)