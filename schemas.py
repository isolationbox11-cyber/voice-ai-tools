#!/usr/bin/env python3
"""
Input validation schemas for all API endpoints using Pydantic.

Provides:
- Request validation schemas
- Response models
- Type safety
- Automatic error messages
- Schema documentation
"""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator, constr


class TTSRequestSchema(BaseModel):
    """Schema for TTS synthesis requests."""

    text: constr(min_length=1, max_length=2000) = Field(
        ..., description="Text to synthesize to speech", examples=["Hello, world!"]
    )

    voice_id: Optional[str] = Field(
        default="Kore",
        description="Voice ID or name for synthesis",
        pattern=r"^[a-zA-Z0-9_\-]+$",
        examples=["Kore", "local_voice_123456", "wav_ref_789012"],
    )

    call_type: Optional[
        Literal["LEGITIMATE", "SCAM_DETECTED", "VERIFICATION", "cloned"]
    ] = Field(default="LEGITIMATE", description="Call type for voice routing")

    explicit_voice_id: Optional[str] = Field(
        default=None,
        description="Explicit voice override",
        pattern=r"^[a-zA-Z0-9_\-]+$",
    )

    speed: Optional[Literal["slow", "normal", "fast"]] = Field(
        default="normal", description="Speech speed"
    )

    @field_validator("text")
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        """Sanitize text input."""
        # Remove potentially harmful patterns
        v = v.strip()
        # Basic XSS prevention
        dangerous_patterns = ["<script", "javascript:", "onload=", "onerror="]
        for pattern in dangerous_patterns:
            if pattern.lower() in v.lower():
                raise ValueError(
                    f"Text contains potentially harmful content: {pattern}"
                )
        return v


class TTSResponseSchema(BaseModel):
    """Schema for TTS synthesis responses."""

    success: bool = Field(..., description="Whether synthesis succeeded")
    audio_bytes: Optional[str] = Field(None, description="Base64 encoded audio data")
    mime_type: Optional[str] = Field(None, description="Audio MIME type")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    effective_text: Optional[str] = Field(None, description="Text actually synthesized")


class VoicePresetSchema(BaseModel):
    """Schema for voice preset configuration."""

    name: constr(min_length=1, max_length=100) = Field(..., description="Preset name")

    voice_id: str = Field(
        ..., description="Voice ID to use", pattern=r"^[a-zA-Z0-9_\-]+$"
    )

    call_type: Literal["LEGITIMATE", "SCAM_DETECTED", "VERIFICATION"] = Field(
        default="LEGITIMATE", description="Call type this preset applies to"
    )

    speed: Literal["slow", "normal", "fast"] = Field(
        default="normal", description="Speech speed"
    )

    description: Optional[str] = Field(
        None, max_length=500, description="Preset description"
    )


class LogEntrySchema(BaseModel):
    """Schema for log entry requests."""

    action: constr(min_length=1, max_length=50) = Field(
        ..., description="Action performed"
    )

    text: constr(min_length=1, max_length=1000) = Field(..., description="Text content")

    timestamp: Optional[str] = Field(default=None, description="ISO format timestamp")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: Optional[str]) -> str:
        """Validate timestamp format."""
        if v is None:
            from datetime import datetime

            return datetime.utcnow().isoformat()
        # Could add more strict timestamp validation here
        return v


class LogResponseSchema(BaseModel):
    """Schema for log responses."""

    entries: List[LogEntrySchema] = Field(default_factory=list)
    total: int = Field(..., description="Total number of entries")


class TrainRequestSchema(BaseModel):
    """Schema for voice training requests."""

    engine: Optional[Literal["coqui_xtts_v2", "fallback"]] = Field(
        default="coqui_xtts_v2", description="Training engine to use"
    )

    description: Optional[str] = Field(
        None, max_length=500, description="Training description"
    )


class TrainResponseSchema(BaseModel):
    """Schema for training responses."""

    voice_id: Optional[str] = Field(None, description="Generated voice ID")
    status: Literal["trained", "samples_saved", "training_failed"] = Field(
        ..., description="Training status"
    )

    samples_count: int = Field(..., description="Number of samples used")
    error: Optional[str] = Field(None, description="Error message if failed")


class BackupCreateSchema(BaseModel):
    """Schema for backup creation requests."""

    name: Optional[constr(min_length=1, max_length=100)] = Field(
        None, description="Backup name (auto-generated if not provided)"
    )


class BackupRestoreSchema(BaseModel):
    """Schema for backup restore requests."""

    backup_path: constr(min_length=1) = Field(
        ..., description="Path to backup file to restore"
    )


class BackupResponseSchema(BaseModel):
    """Schema for backup responses."""

    backup_path: Optional[str] = Field(None, description="Path to created backup")
    status: str = Field(..., description="Operation status")
    restored: List[str] = Field(default_factory=list, description="Restored items")
    skipped: List[str] = Field(default_factory=list, description="Skipped items")
    errors: List[str] = Field(default_factory=list, description="Error messages")


class PDFAnalysisSchema(BaseModel):
    """Schema for PDF analysis results."""

    pages: Optional[int] = Field(None, description="Number of pages")
    metadata: Optional[dict] = Field(None, description="PDF metadata")
    ips: List[str] = Field(default_factory=list, description="Extracted IP addresses")
    links: List[str] = Field(default_factory=list, description="Extracted URLs")
    suspicious: bool = Field(False, description="Whether suspicious content detected")
    error: Optional[str] = Field(None, description="Error message if analysis failed")


class LookupRequestSchema(BaseModel):
    """Schema for OSINT lookup requests."""

    query: constr(min_length=1, max_length=253) = Field(
        ..., description="Query string (domain, IP, or phone number)"
    )

    query_type: Optional[Literal["domain", "ip", "phone"]] = Field(
        None, description="Query type (auto-detected if not provided)"
    )

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        """Sanitize query input."""
        v = v.strip()
        # Basic validation for common patterns
        if "/" in v and "\\" in v:
            raise ValueError("Query contains potentially dangerous path characters")
        return v


class ClonedStatusSchema(BaseModel):
    """Schema for cloned voice status."""

    available: bool = Field(..., description="Whether cloned voice is available")
    engine: Optional[str] = Field(None, description="Engine being used")
    requires_coqui: bool = Field(False, description="Whether Coqui TTS is required")
    coqui_installed: bool = Field(False, description="Whether Coqui TTS is installed")
    warning: Optional[str] = Field(None, description="Warning message if applicable")


class HealthResponseSchema(BaseModel):
    """Schema for health check responses."""

    status: str = Field(..., description="Health status")
    tts_engine: bool = Field(..., description="Whether TTS engine is available")
    api_key_configured: bool = Field(..., description="Whether API key is configured")
    auth_enabled: bool = Field(..., description="Whether authentication is enabled")
    uptime_seconds: int = Field(..., description="Server uptime in seconds")

    # Optional monitoring fields
    memory_mb: Optional[float] = Field(None)
    cpu_percent: Optional[float] = Field(None)
    thread_count: Optional[int] = Field(None)
    disk_gb_free: Optional[float] = Field(None)
    disk_gb_total: Optional[float] = Field(None)
    voice_embeddings_count: Optional[int] = Field(None)
    voice_samples_count: Optional[int] = Field(None)
    coqui_model_available: Optional[bool] = Field(None)

    optional_deps: Optional[dict] = Field(
        None, description="Optional dependencies status"
    )


class ErrorResponseSchema(BaseModel):
    """Standard error response schema."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    error_code: Optional[str] = Field(None, description="Machine-readable error code")


def validate_request_schema(schema_class: type[BaseModel], data: dict) -> dict:
    """
    Validate request data against a schema.

    Args:
        schema_class: Pydantic schema class
        data: Request data to validate

    Returns:
        Validated data

    Raises:
        ValueError: If validation fails
    """
    try:
        return schema_class(**data).model_dump()
    except Exception as exc:
        raise ValueError(f"Validation error: {str(exc)}") from exc


if __name__ == "__main__":
    """Test validation schemas."""
    print("Testing input validation schemas...")
    print("=" * 50)

    # Test TTS request
    try:
        tts_data = {"text": "Hello world", "voice_id": "Kore", "speed": "normal"}
        validated = validate_request_schema(TTSRequestSchema, tts_data)
        print(f"✓ TTS request validation works: {validated}")
    except Exception as e:
        print(f"✗ TTS validation failed: {e}")

    # Test invalid TTS request
    try:
        invalid_data = {"text": "", "voice_id": "Kore"}
        validated = validate_request_schema(TTSRequestSchema, invalid_data)
        print("✗ Should have failed validation")
    except Exception as e:
        print(f"✓ Invalid request rejected: {e}")

    # Test log entry
    try:
        log_data = {"action": "speak", "text": "Sample text"}
        validated = validate_request_schema(LogEntrySchema, log_data)
        print(f"✓ Log entry validation works: {validated}")
    except Exception as e:
        print(f"✗ Log validation failed: {e}")

    print("\nValidation schema tests completed!")
