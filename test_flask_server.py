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
"""

import pytest
import json
import tempfile
import os
from pathlib import Path


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_check_returns_json(self, client):
        response = client.get("/health")
        assert response.content_type == "application/json"

    def test_health_check_has_required_fields(self, client):
        response = client.get("/health")
        data = response.get_json()
        assert "status" in data
        assert "uptime_seconds" in data
        assert data["status"] == "ok"

    def test_health_check_shows_auth_status(self, client):
        response = client.get("/health")
        data = response.get_json()
        assert "auth_enabled" in data


class TestAuthentication:
    """Test authentication and authorization."""

    def test_protected_endpoint_without_token_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        response = client.get("/presets")
        assert response.status_code == 401

    def test_protected_endpoint_with_valid_token_succeeds(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        response = client.get("/presets", headers={"X-Voice-Token": "test_secret"})
        assert response.status_code != 401

    def test_invalid_token_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "correct_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        response = client.get("/presets", headers={"X-Voice-Token": "wrong_secret"})
        assert response.status_code == 401


class TestTTSEndpoint:
    """Test TTS synthesis endpoint."""

    def test_tts_requires_auth(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        response = client.post("/tts", json={"text": "Hello"})
        assert response.status_code == 401

    def test_tts_requires_text_field(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        response = client.post("/tts", json={}, headers={"X-Voice-Token": "test_secret"})
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_tts_rejects_empty_text(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        response = client.post("/tts", json={"text": ""}, headers={"X-Voice-Token": "test_secret"})
        assert response.status_code == 400

    def test_tts_validates_text_length(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        long_text = "a" * 10000
        response = client.post("/tts", json={"text": long_text}, headers={"X-Voice-Token": "test_secret"})
        assert response.status_code == 400


class TestErrorHandling:
    """Test error handling and sanitization."""

    def test_invalid_json_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        response = client.post("/tts", data="not json", headers={"X-Voice-Token": "test_secret"})
        assert response.status_code == 400

    def test_error_messages_are_sanitized(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        response = client.post("/tts", json={"text": "test"}, headers={"X-Voice-Token": "test_secret"})
        if response.status_code != 200:
            data = response.get_json()
            assert "api key" not in str(data).lower()
            assert "traceback" not in str(data).lower()


class TestRateLimiting:
    """Test rate limiting functionality."""

    def test_rate_limiting_applies(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        responses = []
        for _ in range(35):
            response = client.post(
                "/tts", json={"text": "test"}, headers={"X-Voice-Token": "test_secret"}
            )
            responses.append(response.status_code)
        assert 429 in responses


class TestVoiceCloning:
    """Test voice cloning endpoints."""

    def test_cloned_status_without_auth(self, client):
        response = client.get("/cloned_status")
        assert response.status_code in [401, 403]

    def test_cloned_status_returns_json(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        response = client.get("/cloned_status", headers={"X-Voice-Token": "test_secret"})
        assert response.content_type == "application/json"

    def test_cloned_status_has_available_field(self, client, monkeypatch):
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "test_secret")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        response = client.get("/cloned_status", headers={"X-Voice-Token": "test_secret"})
        data = response.get_json()
        assert "available" in data


class TestConfiguration:
    """Test configuration and environment variables."""

    def test_missing_api_key_handled_gracefully(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "")
        import importlib
        import flask_server
        importlib.reload(flask_server)
        response = client.get("/health")
        data = response.get_json()
        assert response.status_code == 200


class TestSecurity:
    """Test security features."""

    def test_cors_headers_present(self, client):
        response = client.get("/health")
        assert response.headers.get("Access-Control-Allow-Origin") is not None

    def test_response_is_successful(self, client):
        response = client.get("/health")
        assert response.status_code == 200


# Fixtures
@pytest.fixture
def client():
    import flask_server
    flask_server.app.config["TESTING"] = True
    with flask_server.app.test_client() as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test_key")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("VOICE_SERVER_TOKEN", "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
