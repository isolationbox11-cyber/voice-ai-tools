"""
Tests for flask_server.py – covers changes introduced in this PR:
  - Token header renamed from X-Token → X-Voice-Token
  - _check_token() logic (no-token dev mode, correct/wrong token)
  - _resolve_voice_settings() (custom_voice_config absent/present, voice_id injection)
  - /health endpoint (GET → 200 with status + dependency/config flags)
  - /tts endpoint (auth, validation, synthesis success/failure)
"""

import importlib
import io
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers – we need to stub heavy deps before importing flask_server
# ---------------------------------------------------------------------------

def _make_tts_stub(audio_bytes=b"FAKE_AUDIO", mime_type="audio/wav", error=None, effective_text="hello"):
    """Return a fake synthesize_speech function."""
    def _synthesize(text, voice_settings, **kwargs):
        return audio_bytes, mime_type, error, effective_text
    return _synthesize


def _make_voice_config_stub(return_value=None):
    """Return a fake get_voice_for_context function."""
    if return_value is None:
        return_value = {"emotion": "professional", "speaking_rate": 1.0}

    def _get_voice(call_type):
        return dict(return_value)
    return _get_voice


@pytest.fixture(autouse=True)
def _patch_imports(monkeypatch):
    """Stub tts_engine and voice_config before importing flask_server."""
    # Build fake tts_engine module
    tts_mod = types.ModuleType("tts_engine")
    tts_mod.synthesize_speech = _make_tts_stub()
    monkeypatch.setitem(sys.modules, "tts_engine", tts_mod)

    # Build fake voice_config module
    vc_mod = types.ModuleType("voice_config")
    vc_mod.get_voice_for_context = _make_voice_config_stub()
    monkeypatch.setitem(sys.modules, "voice_config", vc_mod)

    # Ensure custom_voice_config is NOT present by default
    monkeypatch.delitem(sys.modules, "custom_voice_config", raising=False)

    yield


@pytest.fixture()
def _clear_flask_server_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "flask_server", raising=False)
    yield
    monkeypatch.delitem(sys.modules, "flask_server", raising=False)


@pytest.fixture()
def _reload_server(_clear_flask_server_module):
    """
    Reload flask_server after env/module patches so that module-level
    VOICE_SERVER_TOKEN is re-read from the environment.
    """
    import flask_server as srv
    yield srv


# ---------------------------------------------------------------------------
# Fixture: Flask test client with no token configured (development mode)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client_no_token(monkeypatch):
    monkeypatch.delenv("VOICE_SERVER_TOKEN", raising=False)
    monkeypatch.delitem(sys.modules, "flask_server", raising=False)
    import flask_server as srv
    srv.app.config["TESTING"] = True
    with srv.app.test_client() as c:
        yield c
    monkeypatch.delitem(sys.modules, "flask_server", raising=False)


@pytest.fixture()
def client_with_token(monkeypatch):
    monkeypatch.setenv("VOICE_SERVER_TOKEN", "secret123")
    monkeypatch.delitem(sys.modules, "flask_server", raising=False)
    import flask_server as srv
    srv.VOICE_SERVER_TOKEN = "secret123"
    srv.app.config["TESTING"] = True
    with srv.app.test_client() as c:
        yield c, srv
    monkeypatch.delitem(sys.modules, "flask_server", raising=False)


# ===========================================================================
# _check_token()
# ===========================================================================

class TestCheckToken:
    def test_no_token_configured_always_passes(self, client_no_token):
        """When VOICE_SERVER_TOKEN is empty, every request is accepted."""
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        with srv.app.test_request_context("/tts", headers={}):
            assert srv._check_token() is True

    def test_correct_token_passes(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = "mysecret"
        with srv.app.test_request_context("/tts", headers={"X-Voice-Token": "mysecret"}):
            assert srv._check_token() is True

    def test_wrong_token_fails(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = "mysecret"
        with srv.app.test_request_context("/tts", headers={"X-Voice-Token": "wrongtoken"}):
            assert srv._check_token() is False

    def test_missing_header_fails_when_token_set(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = "mysecret"
        with srv.app.test_request_context("/tts", headers={}):
            assert srv._check_token() is False

    def test_old_x_token_header_rejected(self, monkeypatch):
        """Ensure the old X-Token header (pre-PR) is no longer accepted."""
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = "mysecret"
        # X-Token (old name) should NOT work; only X-Voice-Token is valid.
        with srv.app.test_request_context("/tts", headers={"X-Token": "mysecret"}):
            assert srv._check_token() is False


class TestStartupTokenEnforcement:
    def test_import_fails_in_production_without_token(self, monkeypatch, _clear_flask_server_module):
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.delenv("VOICE_SERVER_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="VOICE_SERVER_TOKEN must be set"):
            importlib.import_module("flask_server")

    def test_import_succeeds_in_production_with_token(self, monkeypatch, _clear_flask_server_module):
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "prod-secret")
        srv = importlib.import_module("flask_server")
        assert srv.VOICE_SERVER_TOKEN == "prod-secret"


# ===========================================================================
# _resolve_voice_settings()
# ===========================================================================

class TestResolveVoiceSettings:
    def test_falls_back_to_voice_config_when_no_custom_module(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        monkeypatch.delitem(sys.modules, "custom_voice_config", raising=False)
        import flask_server as srv

        result = srv._resolve_voice_settings("LEGITIMATE")
        # Must include the fallback voice_id
        assert "voice_id" in result
        assert result["voice_id"] == "Kore"

    def test_fallback_sets_default_voice_id_for_scam(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        monkeypatch.delitem(sys.modules, "custom_voice_config", raising=False)
        import flask_server as srv

        result = srv._resolve_voice_settings("SCAM_DETECTED")
        assert result["voice_id"] == "Kore"

    def test_uses_custom_voice_config_when_available(self, monkeypatch):
        custom_mod = types.ModuleType("custom_voice_config")
        custom_mod.CUSTOM_VOICE_ID = "custom-voice-abc"
        custom_mod.get_custom_voice_settings = lambda ct: {"voice_id": "custom-voice-abc", "emotion": "calm"}
        monkeypatch.setitem(sys.modules, "custom_voice_config", custom_mod)
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv

        result = srv._resolve_voice_settings("LEGITIMATE")
        assert result["voice_id"] == "custom-voice-abc"
        assert result["emotion"] == "calm"

    def test_custom_voice_config_without_voice_id_injects_custom_voice_id(self, monkeypatch):
        """When custom settings omit voice_id, CUSTOM_VOICE_ID attribute is injected."""
        custom_mod = types.ModuleType("custom_voice_config")
        custom_mod.CUSTOM_VOICE_ID = "injected-voice"
        custom_mod.get_custom_voice_settings = lambda ct: {"emotion": "firm"}  # no voice_id
        monkeypatch.setitem(sys.modules, "custom_voice_config", custom_mod)
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv

        result = srv._resolve_voice_settings("SCAM_DETECTED")
        assert result["voice_id"] == "injected-voice"

    def test_custom_voice_config_missing_custom_voice_id_attr_uses_fallback_id(self, monkeypatch):
        """If custom module has no CUSTOM_VOICE_ID, fallback string is used."""
        custom_mod = types.ModuleType("custom_voice_config")
        # No CUSTOM_VOICE_ID attribute
        custom_mod.get_custom_voice_settings = lambda ct: {}
        monkeypatch.setitem(sys.modules, "custom_voice_config", custom_mod)
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv

        result = srv._resolve_voice_settings("LEGITIMATE")
        assert result["voice_id"] == "Kore"


# ===========================================================================
# GET /health
# ===========================================================================

class TestHealthEndpoint:
    def test_returns_200_ok(self, client_no_token):
        response = client_no_token.get("/health")
        assert response.status_code == 200

    def test_returns_json_status_with_expected_fields(self, client_no_token):
        response = client_no_token.get("/health")
        data = response.get_json()
        assert data["status"] == "ok"
        assert isinstance(data["tts_engine"], bool)
        assert isinstance(data["api_key_configured"], bool)
        assert isinstance(data["auth_enabled"], bool)
        assert data["tts_engine"]
        assert isinstance(data["uptime_seconds"], int)
        assert data["uptime_seconds"] >= 0

    def test_reflects_unconfigured_env(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("VOICE_SERVER_TOKEN", raising=False)
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        try:
            import flask_server as srv
            srv.app.config["TESTING"] = True
            with srv.app.test_client() as c:
                data = c.get("/health").get_json()
                assert data["api_key_configured"] is False
                assert data["auth_enabled"] is False
        finally:
            monkeypatch.delitem(sys.modules, "flask_server", raising=False)

    def test_reflects_env_and_auth_configuration(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "abc123")
        monkeypatch.setenv("VOICE_SERVER_TOKEN", "secret123")
        original_srv = sys.modules.get("flask_server")
        try:
            monkeypatch.delitem(sys.modules, "flask_server", raising=False)
            import flask_server as srv
            srv.app.config["TESTING"] = True
            with srv.app.test_client() as c:
                data = c.get("/health").get_json()
                assert data["api_key_configured"] is True
                assert data["auth_enabled"] is True
        finally:
            if original_srv is not None:
                sys.modules["flask_server"] = original_srv
            else:
                monkeypatch.delitem(sys.modules, "flask_server", raising=False)

    def test_reports_tts_engine_unavailable(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv

        try:
            monkeypatch.setattr(srv, "synthesize_speech", None)
            srv.app.config["TESTING"] = True
            with srv.app.test_client() as c:
                data = c.get("/health").get_json()
                assert data["tts_engine"] is False
        finally:
            monkeypatch.delitem(sys.modules, "flask_server", raising=False)

    def test_content_type_json(self, client_no_token):
        response = client_no_token.get("/health")
        assert "application/json" in response.content_type


# ===========================================================================
# /presets
# ===========================================================================

class TestPresetsEndpoint:
    def test_post_then_get_round_trip(self, monkeypatch, tmp_path):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.PRESET_PATH = tmp_path / "voice_presets.json"
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/presets", json={"name": "Default", "voice_id": "kore"})
            assert resp.status_code == 200
            assert resp.get_json() == {"ok": True}

            get_resp = c.get("/presets")
            assert get_resp.status_code == 200
            assert get_resp.get_json() == {"presets": [{"name": "Default", "voice_id": "kore"}]}

    def test_post_uses_preset_write_lock(self, monkeypatch, tmp_path):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.PRESET_PATH = tmp_path / "voice_presets.json"
        srv.app.config["TESTING"] = True

        class _TrackingLock:
            def __init__(self):
                self.enter_count = 0
                self.exit_count = 0

            def __enter__(self):
                self.enter_count += 1
                return self

            def __exit__(self, exc_type, exc, tb):
                self.exit_count += 1
                return False

        tracking_lock = _TrackingLock()
        srv.PRESET_WRITE_LOCK = tracking_lock

        with srv.app.test_client() as c:
            resp = c.post("/presets", json={"name": "Locked"})
            assert resp.status_code == 200

        assert tracking_lock.enter_count == 1
        assert tracking_lock.exit_count == 1


# ===========================================================================
# POST /tts
# ===========================================================================

class TestTtsEndpoint:
    # ── Authentication ──────────────────────────────────────────────────────

    def test_no_token_configured_accepts_request(self, monkeypatch):
        """Dev mode: no token set → all requests accepted."""
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello"})
            # May succeed (200) or fail on tts engine, but NOT 401
            assert resp.status_code != 401

    def test_missing_token_header_returns_401(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = "secret"
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello"})
            assert resp.status_code == 401

    def test_wrong_token_returns_401(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = "secret"
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello"},
                          headers={"X-Voice-Token": "wrong"})
            assert resp.status_code == 401

    def test_correct_token_proceeds_past_auth(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = "secret"
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello"},
                          headers={"X-Voice-Token": "secret"})
            assert resp.status_code != 401

    # ── Request validation ───────────────────────────────────────────────────

    def test_non_json_body_returns_400(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", data="not json",
                          content_type="text/plain")
            assert resp.status_code == 400
            assert "error" in resp.get_json()

    def test_empty_json_object_returns_400(self, monkeypatch):
        """An empty JSON object {} is falsy; server rejects it as invalid body."""
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={})
            assert resp.status_code == 400
            # Empty dict is falsy → "Invalid JSON body" (not "text is required")
            assert "error" in resp.get_json()

    def test_explicit_empty_text_returns_400(self, monkeypatch):
        """Sending {"text": ""} should return 400 with 'text is required'."""
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": ""})
            assert resp.status_code == 400
            assert resp.get_json()["error"] == "text is required"

    def test_whitespace_only_text_returns_400(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "   "})
            assert resp.status_code == 400

    def test_text_at_max_length_accepted(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = _make_tts_stub()
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "a" * 2000})
            assert resp.status_code == 200

    def test_text_exceeding_max_length_returns_400(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "a" * 2001})
            assert resp.status_code == 400
            assert "maximum length" in resp.get_json()["error"]

    def test_flask_and_tts_max_text_length_are_aligned(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        tts_path = Path(srv.__file__).with_name("tts_engine.py")
        spec = importlib.util.spec_from_file_location("real_tts_engine_for_test", tts_path)
        assert spec is not None
        assert spec.loader is not None
        tts_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tts_module)
        assert srv.MAX_TEXT_LENGTH == tts_module.MAX_TEXT_LENGTH

    # ── call_type handling ───────────────────────────────────────────────────

    def test_call_type_defaults_to_legitimate(self, monkeypatch):
        """When call_type is absent, LEGITIMATE is used (no error)."""
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = _make_tts_stub()
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello"})
            assert resp.status_code == 200

    def test_call_type_gets_uppercased(self, monkeypatch):
        """call_type in lowercase is uppercased before resolution."""
        captured = {}

        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = _make_tts_stub()
        vc_mod = sys.modules["voice_config"]
        original_fn = vc_mod.get_voice_for_context

        def recording_fn(call_type):
            captured["call_type"] = call_type
            return original_fn(call_type)

        vc_mod.get_voice_for_context = recording_fn

        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            c.post("/tts", json={"text": "hello", "call_type": "scam_detected"})
        assert captured.get("call_type") == "SCAM_DETECTED"

    # ── TTS synthesis results ────────────────────────────────────────────────

    def test_tts_success_returns_audio_bytes(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = _make_tts_stub(audio_bytes=b"\x00\xFF\x00\xFF",
                                                   mime_type="audio/wav")
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello"})
            assert resp.status_code == 200
            assert resp.data == b"\x00\xFF\x00\xFF"

    def test_tts_success_returns_correct_mimetype(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = _make_tts_stub(mime_type="audio/wav")
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello"})
            assert resp.status_code == 200
            assert "audio/wav" in resp.content_type

    def test_tts_engine_error_returns_502(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = _make_tts_stub(audio_bytes=None,
                                                   error="API key missing")
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello"})
            assert resp.status_code == 502
            assert resp.get_json()["error"] == "API key not configured"

    def test_tts_engine_error_message_sanitized(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = _make_tts_stub(audio_bytes=None,
                                                   error="Quota exceeded")
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello"})
            assert resp.get_json()["error"] == "Speech synthesis failed"

    def test_tts_engine_error_message_voice_model_unavailable(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = _make_tts_stub(audio_bytes=None,
                                                   error="Voice model unavailable")
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello"})
            assert resp.status_code == 502
            assert resp.get_json()["error"] == "Voice model unavailable"

    def test_tts_engine_error_message_timeout(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = _make_tts_stub(audio_bytes=None,
                                                   error="Request timed out after 30s")
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello"})
            assert resp.status_code == 502
            assert resp.get_json()["error"] == "Request timed out"

    def test_cloned_sentinel_voice_id_does_not_override_resolved_voice(self, monkeypatch):
        captured = []

        monkeypatch.delitem(sys.modules, "flask_server", raising=False)

        custom_mod = types.ModuleType("custom_voice_config")
        custom_mod.CUSTOM_VOICE_ID = "local_voice_123"
        custom_mod.get_custom_voice_settings = lambda ct: {"voice_id": "local_voice_123"}
        monkeypatch.setitem(sys.modules, "custom_voice_config", custom_mod)

        def recording_stub(text, voice_settings, **kwargs):
            captured.append(voice_settings.get("voice_id"))
            return b"FAKE_AUDIO", "audio/wav", None, text

        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = recording_stub

        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json={"text": "hello", "call_type": "cloned", "voice_id": "cloned"})
            assert resp.status_code == 200
            assert resp.data == b"FAKE_AUDIO"
            assert "audio/wav" in resp.content_type
            resp_mixed_case = c.post("/tts", json={"text": "hello", "call_type": "cloned", "voice_id": "ClOnEd"})
            assert resp_mixed_case.status_code == 200
            assert resp_mixed_case.data == b"FAKE_AUDIO"
            assert "audio/wav" in resp_mixed_case.content_type

        assert captured == ["local_voice_123", "local_voice_123"]

    # ── Boundary / regression ────────────────────────────────────────────────

    def test_json_array_body_returns_400(self, monkeypatch):
        """Body must be a JSON *object*, not an array."""
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post("/tts", json=["text", "hello"])
            assert resp.status_code == 400

    def test_x_voice_token_header_name_is_correct(self, monkeypatch):
        """Regression: X-Voice-Token must be the accepted header (not X-Token)."""
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = _make_tts_stub()
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = "token99"
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            # Old header name should fail
            resp_old = c.post("/tts", json={"text": "hi"},
                              headers={"X-Token": "token99"})
            assert resp_old.status_code == 401
            # New header name should succeed
            resp_new = c.post("/tts", json={"text": "hi"},
                              headers={"X-Voice-Token": "token99"})
            assert resp_new.status_code == 200


class TestLogEndpoint:
    def test_post_valid_entry_is_stored(self, monkeypatch, tmp_path):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.LOG_PATH = tmp_path / "session_log.json"
        srv.app.config["TESTING"] = True

        with srv.app.test_client() as c:
            resp = c.post("/log", json={"action": "info", "text": "hello", "timestamp": "2026-01-01T00:00:00Z"})
            assert resp.status_code == 200
            log_resp = c.get("/log")
            assert log_resp.status_code == 200
            assert log_resp.get_json()["entries"][0] == {
                "action": "info",
                "text": "hello",
                "timestamp": "2026-01-01T00:00:00Z",
            }

    def test_post_rejects_unknown_fields(self, monkeypatch, tmp_path):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.LOG_PATH = tmp_path / "session_log.json"
        srv.app.config["TESTING"] = True

        with srv.app.test_client() as c:
            resp = c.post("/log", json={"action": "info", "text": "hello", "extra": "nope"})
            assert resp.status_code == 400
            assert "Unknown fields" in resp.get_json()["error"]

    def test_post_rejects_oversized_entries(self, monkeypatch, tmp_path):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.LOG_PATH = tmp_path / "session_log.json"
        srv.app.config["TESTING"] = True

        with srv.app.test_client() as c:
            resp = c.post("/log", json={"action": "info", "text": "a" * 3000, "timestamp": "2026-01-01T00:00:00Z"})
            assert resp.status_code == 400
            assert "maximum size" in resp.get_json()["error"]

    def test_clear_endpoint_clears_entries(self, monkeypatch, tmp_path):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.LOG_PATH = tmp_path / "session_log.json"
        srv.app.config["TESTING"] = True

        with srv.app.test_client() as c:
            post_resp = c.post("/log", json={"action": "info", "text": "hello"})
            assert post_resp.status_code == 200
            clear_resp = c.post("/log/clear")
            assert clear_resp.status_code == 200
            log_resp = c.get("/log")
            assert log_resp.status_code == 200
            assert log_resp.get_json() == {"entries": []}

 
# ===========================================================================
# /shodan
# ===========================================================================

class TestShodanEndpoint:
    def test_returns_only_allowlisted_fields(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv

        class _Resp:
            def json(self):
                return {
                    "ip_str": "1.2.3.4",
                    "ports": [80, 443],
                    "org": "Example Org",
                    "country_name": "United States",
                    "vulns": {"CVE-2024-0001": {}},
                    "data": [{"port": 80, "banner": "Apache/2.4.1"}],
                }

        class _Requests:
            @staticmethod
            def get(*args, **kwargs):
                return _Resp()

        srv._requests = _Requests()
        srv.SHODAN_API_KEY = "dummy"
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True

        with srv.app.test_client() as c:
            resp = c.get("/shodan?ip=1.2.3.4")
            assert resp.status_code == 200
            assert resp.get_json() == {
                "ip_str": "1.2.3.4",
                "ports": [80, 443],
                "org": "Example Org",
                "country_name": "United States",
            }

    def test_non_object_shodan_payload_returns_empty_object(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv

        class _Resp:
            def json(self):
                return ["unexpected", "payload"]

        class _Requests:
            @staticmethod
            def get(*args, **kwargs):
                return _Resp()

        srv._requests = _Requests()
        srv.SHODAN_API_KEY = "dummy"
        srv.VOICE_SERVER_TOKEN = ""
        srv.app.config["TESTING"] = True

        with srv.app.test_client() as c:
            resp = c.get("/shodan?ip=1.2.3.4")
            assert resp.status_code == 200
            assert resp.get_json() == {}

# ===========================================================================
# POST /train
# ===========================================================================

class TestTrainEndpoint:
    @staticmethod
    def _wav_header_bytes():
        return b"RIFF\x24\x00\x00\x00WAVEfmt "


    @staticmethod
    def _mp42_ftyp_bytes():
        """Minimal ftyp box with mp42 major brand — generic audio-only MP4 container."""
        return (
            b'\x00\x00\x00\x18'  # box size = 24 bytes
            b'ftyp'               # box type
            b'mp42'               # major brand (not M4A /M4B, so magic-byte check alone rejects it)
            b'\x00\x00\x00\x00'  # minor version
            b'mp42'               # compatible brand
            b'isom'               # compatible brand
        )

    def test_accepts_mp4_container_when_magic_reports_video_mp4(self, tmp_path, monkeypatch):
        """Audio-only MP4s that libmagic reports as video/mp4 must be accepted."""
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv

        # Provide a fake magic module so the test is deterministic regardless of
        # whether python-magic is installed in the test environment.
        class _FakeMagic:
            @staticmethod
            def from_buffer(_buf, mime=False):
                return "video/mp4"

        monkeypatch.setattr(srv, "magic", _FakeMagic, raising=False)
        srv.VOICE_SERVER_TOKEN = ""
        srv.SAMPLES_DIR = tmp_path / "voice_samples"
        srv.MODEL_DIR = tmp_path / "voice_model"
        srv.SAMPLES_DIR.mkdir(exist_ok=True)
        srv.MODEL_DIR.mkdir(exist_ok=True)
        srv.app.config["TESTING"] = True

        with srv.app.test_client() as c:
            resp = c.post(
                "/train",
                data={"files": (io.BytesIO(self._mp42_ftyp_bytes()), "audio.m4a", "video/mp4")},
                content_type="multipart/form-data",
            )
        # Should not be rejected as invalid audio (magic + ftyp container check must combine).
        # Either the request succeeds (non-400) or it fails for a reason other than audio validation.
        if resp.status_code == 400:
            assert resp.get_json().get("error") != "Invalid audio file: audio.m4a"

    def test_multifile_no_partial_save_on_second_file_failure(self, tmp_path, monkeypatch):
        """When the second file in a multi-file upload fails validation, the first must not be saved."""
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv

        srv.VOICE_SERVER_TOKEN = ""
        srv.SAMPLES_DIR = tmp_path / "voice_samples"
        srv.MODEL_DIR = tmp_path / "voice_model"
        srv.SAMPLES_DIR.mkdir(exist_ok=True)
        srv.MODEL_DIR.mkdir(exist_ok=True)
        srv.app.config["TESTING"] = True

        with srv.app.test_client() as c:
            resp = c.post(
                "/train",
                data={
                    "files": [
                        (io.BytesIO(self._wav_header_bytes()), "good.wav", "audio/wav"),
                        (io.BytesIO(b"definitely not audio"), "bad.wav", "audio/wav"),
                    ]
                },
                content_type="multipart/form-data",
            )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Invalid audio file: bad.wav"
        # The first (valid) file must NOT have been persisted because validation failed
        assert not (srv.SAMPLES_DIR / "good.wav").exists()

    def test_training_exception_is_sanitized_in_response_and_manifest(self, monkeypatch, tmp_path):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv

        srv.VOICE_SERVER_TOKEN = ""
        srv.SAMPLES_DIR = tmp_path / "voice_samples"
        srv.MODEL_DIR = tmp_path / "voice_model"
        srv.SAMPLES_DIR.mkdir(exist_ok=True)
        srv.MODEL_DIR.mkdir(exist_ok=True)

        failing_training = types.ModuleType("voice_training")

        def _raise_training_error(_sample_paths):
            raise RuntimeError(f"failed reading {tmp_path}/very/secret/path.wav")

        failing_training.train_from_samples = _raise_training_error
        monkeypatch.setitem(sys.modules, "voice_training", failing_training)

        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            resp = c.post(
                "/train",
                data={"files": (io.BytesIO(self._wav_header_bytes()), "sample.wav", "audio/wav")},
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "training_failed"
        assert body["error"] == "Training failed. Check server logs."
        assert str(tmp_path) not in body["error"]

        manifest = json.loads((srv.MODEL_DIR / "manifest.json").read_text())
        assert manifest["status"] == "training_failed"
        assert manifest["error"] == "Training failed. Check server logs."

    def test_rejects_hidden_dotfile_name(self, tmp_path, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.SAMPLES_DIR = tmp_path / "voice_samples"
        srv.MODEL_DIR = tmp_path / "voice_model"
        srv.SAMPLES_DIR.mkdir(exist_ok=True)
        srv.MODEL_DIR.mkdir(exist_ok=True)
        srv.app.config["TESTING"] = True

        with srv.app.test_client() as c:
            resp = c.post(
                "/train",
                data={"files": (io.BytesIO(self._wav_header_bytes()), ".bashrc", "audio/wav")},
                content_type="multipart/form-data",
            )
            assert resp.status_code == 400
            assert resp.get_json()["error"] == "Invalid filename"

    def test_rejects_non_audio_magic_bytes_even_with_audio_mime(self, tmp_path, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.SAMPLES_DIR = tmp_path / "voice_samples"
        srv.MODEL_DIR = tmp_path / "voice_model"
        srv.SAMPLES_DIR.mkdir(exist_ok=True)
        srv.MODEL_DIR.mkdir(exist_ok=True)
        srv.app.config["TESTING"] = True

        with srv.app.test_client() as c:
            resp = c.post(
                "/train",
                data={"files": (io.BytesIO(b"not audio"), "clip.wav", "audio/wav")},
                content_type="multipart/form-data",
            )
            assert resp.status_code == 400
            assert resp.get_json()["error"] == "Invalid audio file: clip.wav"

    def test_multi_file_request_with_invalid_file_does_not_save_partial_files(self, tmp_path, monkeypatch):
        monkeypatch.delitem(sys.modules, "flask_server", raising=False)
        import flask_server as srv
        srv.VOICE_SERVER_TOKEN = ""
        srv.SAMPLES_DIR = tmp_path / "voice_samples"
        srv.MODEL_DIR = tmp_path / "voice_model"
        srv.SAMPLES_DIR.mkdir(exist_ok=True)
        srv.MODEL_DIR.mkdir(exist_ok=True)
        srv.app.config["TESTING"] = True

        with srv.app.test_client() as c:
            resp = c.post(
                "/train",
                data={
                    "files": [
                        (io.BytesIO(self._wav_header_bytes()), "good.wav", "audio/wav"),
                        (io.BytesIO(b"not audio"), "bad.wav", "audio/wav"),
                    ]
                },
                content_type="multipart/form-data",
            )
            assert resp.status_code == 400
            assert resp.get_json()["error"] == "Invalid audio file: bad.wav"
            assert not (srv.SAMPLES_DIR / "good.wav").exists()
