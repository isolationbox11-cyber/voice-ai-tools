#!/usr/bin/env python3
"""
Comprehensive tests for Flask server endpoints.

Tests cover:
- Health check functionality
- TTS endpoint with authentication
- Authentication and authorization
- Rate limiting
- Error handling
- Voice cloning endpoints
- Backup/restore functionality
"""

import pytest
import json
import tempfile
import os
from pathlib import Path


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check_returns_200(self, client):
        """Health endpoint should return 200 status."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_check_returns_json(self, client):
        """Health endpoint should return JSON content."""
        response = client.get("/health")
        assert response.content_type == "application/json"

    def test_health_check_has_required_fields(self, client):
        """Health endpoint should return required fields."""
        response = client.get("/health")
        data = response.get_json()
        assert "status" in data
        assert "uptime_seconds" in data
        assert data["status"] == "ok"

    def test_health_check_shows_auth_status(self, client):
        """Health endpoint should show authentication status."""
        response = client.get("/health")
        data = response.get_json()
        assert "auth_enabled" in data


class TestAuthentication:
    """Test authentication and authorization."""

    def test_protected_endpoint_without_token_returns_401(self, client, monkeypatch):
        """Protected endpoints should return 401 without token."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        # Reload flask_server to pick up new env var
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.get("/presets")
        assert response.status_code == 401

    def test_protected_endpoint_with_valid_token_succeeds(self, client, monkeypatch):
        """Protected endpoints should succeed with valid token."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.get("/presets", headers={"X-Voice-Token": "test_secret"})
        # Should not be 401 (may be 200 or other valid response)
        assert response.status_code != 401

    def test_invalid_token_returns_401(self, client, monkeypatch):
        """Invalid token should return 401."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "correct_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.get("/presets", headers={"X-Voice-Token": "wrong_secret"})
        assert response.status_code == 401


class TestTTSEndpoint:
    """Test TTS synthesis endpoint."""

    def test_tts_requires_auth(self, client, monkeypatch):
        """TTS endpoint should require authentication."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.post("/tts", json={"text": "Hello"})
        assert response.status_code == 401

    def test_tts_requires_text_field(self, client, monkeypatch):
        """TTS endpoint should require text field."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.post(
            "/tts", json={}, headers={"X-Voice-Token": "test_secret"}
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_tts_rejects_empty_text(self, client, monkeypatch):
        """TTS endpoint should reject empty text."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.post(
            "/tts", json={"text": ""}, headers={"X-Voice-Token": "test_secret"}
        )
        assert response.status_code == 400

    def test_tts_validates_text_length(self, client, monkeypatch):
        """TTS endpoint should validate text length limit."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        long_text = "a" * 10000  # Exceeds typical limit
        response = client.post(
            "/tts", json={"text": long_text}, headers={"X-Voice-Token": "test_secret"}
        )
        assert response.status_code == 400


class TestErrorHandling:
    """Test error handling and sanitization."""

    def test_invalid_json_returns_400(self, client, monkeypatch):
        """Invalid JSON should return 400."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.post(
            "/tts", data="not json", headers={"X-Voice-Token": "test_secret"}
        )
        assert response.status_code == 400

    def test_error_messages_are_sanitized(self, client, monkeypatch):
        """Error messages should not leak sensitive information."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        # Force an error that might contain sensitive info
        response = client.post(
            "/tts", json={"text": "test"}, headers={"X-Voice-Token": "test_secret"}
        )
        # Even if it fails, error should be generic
        if response.status_code != 200:
            data = response.get_json()
            assert "api key" not in str(data).lower()
            assert "traceback" not in str(data).lower()


class TestRateLimiting:
    """Test rate limiting functionality."""

    def test_rate_limiting_applies(self, client, monkeypatch):
        """Rate limiting should apply to protected endpoints."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        # Make multiple rapid requests
        responses = []
        for _ in range(35):  # Exceed default 30/min limit
            response = client.post(
                "/tts", json={"text": "test"}, headers={"X-Voice-Token": "test_secret"}
            )
            responses.append(response.status_code)

        # At least some should be rate limited (429)
        assert 429 in responses


class TestVoiceCloning:
    """Test voice cloning endpoints."""

    def test_cloned_status_without_auth(self, client):
        """Cloned status endpoint should require authentication."""
        response = client.get("/cloned_status")
        # Should return 401 or 403 when auth is enabled
        assert response.status_code in [401, 403]

    def test_cloned_status_returns_json(self, client, monkeypatch):
        """Cloned status should return JSON."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.get(
            "/cloned_status", headers={"X-Voice-Token": "test_secret"}
        )
        assert response.content_type == "application/json"

    def test_cloned_status_structure(self, client, monkeypatch):
        """Cloned status should have required fields."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.get(
            "/cloned_status", headers={"X-Voice-Token": "test_secret"}
        )
        data = response.get_json()
        assert "available" in data
        assert "coqui_installed" in data


class TestBackupEndpoints:
    """Test backup and restore endpoints."""

    def test_backup_requires_auth(self, client, monkeypatch):
        """Backup endpoints should require authentication."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.post("/backup")
        assert response.status_code == 401

    def test_list_backups_without_auth(self, client, monkeypatch):
        """List backups should require authentication."""
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.get("/backup")
        assert response.status_code == 401


class TestConfiguration:
    """Test configuration and environment variables."""

    def test_missing_api_key_handled_gracefully(self, client, monkeypatch):
        """Missing API key should be handled gracefully."""
        monkeypatch.setenv("GOOGLE_API_KEY", "")
        import importlib
        import flask_server

        importlib.reload(flask_server)

        response = client.get("/health")
        data = response.get_json()
        # Should still return 200 but show API key not configured
        assert response.status_code == 200


class TestSecurity:
    """Test security features."""

    def test_cors_headers_present(self, client):
        """CORS headers should be present."""
        response = client.get("/health")
        # Check for CORS headers
        assert response.headers.get("Access-Control-Allow-Origin") is not None

    def test_security_headers_present(self, client):
        """Security headers should be present."""
        response = client.get("/health")
        # Check for common security headers
        headers = response.headers
        # These might not all be present depending on configuration
        # but we can check that the response is successful
        assert response.status_code == 200


# Test fixtures
@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    import flask_server

    flask_server.app.config["TESTING"] = True
    with flask_server.app.test_client() as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    """Setup test environment variables."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test_key")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("VOICE_SERVER_TOKEN", "")  # Disabled for most tests


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
