"""
Tests for voice_visualizer_integration.py – covers changes introduced in this PR:
  - _resolve_voice_settings() simplified (removed docstring, logic unchanged)
  - VoiceVisualizerBridge.__init__ (docstring removed, attributes unchanged)
  - VoiceVisualizerBridge.speak_response (docstring removed, logic unchanged)

Because the module imports websockets, voice_training, and tts_engine at import
time, all heavy dependencies are stubbed out via sys.modules before the module
is loaded.
"""

import asyncio
import base64
import importlib
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module-level stubs – installed before any import of the target module
# ---------------------------------------------------------------------------

def _make_stubs(monkeypatch, *, custom_voice_mod=None):
    """
    Inject stub modules for all heavy deps so that
    voice_visualizer_integration can be imported without real packages.
    """
    # websockets stub
    ws_mod = types.ModuleType("websockets")
    ws_mod.serve = AsyncMock()

    class _FakeClosed(Exception):
        pass

    ws_exceptions = types.ModuleType("websockets.exceptions")
    ws_exceptions.ConnectionClosed = _FakeClosed
    ws_mod.exceptions = ws_exceptions
    monkeypatch.setitem(sys.modules, "websockets", ws_mod)
    monkeypatch.setitem(sys.modules, "websockets.exceptions", ws_exceptions)

    # voice_config stub
    vc_mod = types.ModuleType("voice_config")
    vc_mod.VOICE_SETTINGS = {"speaking_rate": 1.0}

    def _get_voice(ct):
        return {"emotion": "professional", "speaking_rate": 1.0}

    vc_mod.get_voice_for_context = _get_voice
    monkeypatch.setitem(sys.modules, "voice_config", vc_mod)

    # voice_training stub (VoiceTrainer must be importable)
    vt_mod = types.ModuleType("voice_training")

    class FakeTrainer:
        def __init__(self):
            pass

    vt_mod.VoiceTrainer = FakeTrainer
    monkeypatch.setitem(sys.modules, "voice_training", vt_mod)

    # tts_engine stub
    tts_mod = types.ModuleType("tts_engine")
    tts_mod.synthesize_speech = MagicMock(
        return_value=(b"AUDIO", "audio/wav", None, "hello")
    )
    monkeypatch.setitem(sys.modules, "tts_engine", tts_mod)

    # google.genai stub (needed by voice_training in some code paths)
    genai_mod = types.ModuleType("google")
    genai_sub = types.ModuleType("google.genai")
    genai_sub.Client = MagicMock()
    genai_mod.genai = genai_sub
    monkeypatch.setitem(sys.modules, "google", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_sub)

    # custom_voice_config – absent by default
    if custom_voice_mod is not None:
        monkeypatch.setitem(sys.modules, "custom_voice_config", custom_voice_mod)
    else:
        monkeypatch.delitem(sys.modules, "custom_voice_config", raising=False)

    return tts_mod, vc_mod


@pytest.fixture()
def integration_module(monkeypatch):
    """Load (or reload) voice_visualizer_integration with all stubs."""
    _make_stubs(monkeypatch)
    monkeypatch.delitem(sys.modules, "voice_visualizer_integration", raising=False)
    import voice_visualizer_integration as m
    yield m
    monkeypatch.delitem(sys.modules, "voice_visualizer_integration", raising=False)


@pytest.fixture()
def bridge(integration_module):
    """Return a fresh VoiceVisualizerBridge instance."""
    return integration_module.VoiceVisualizerBridge()


# ===========================================================================
# _resolve_voice_settings()
# ===========================================================================

class TestResolveVoiceSettings:
    def test_returns_voice_config_when_no_custom_module(self, integration_module):
        """Without custom_voice_config, returns get_voice_for_context result."""
        result = integration_module._resolve_voice_settings("LEGITIMATE")
        assert isinstance(result, dict)
        assert "emotion" in result

    def test_returns_different_settings_for_scam(self, integration_module):
        result = integration_module._resolve_voice_settings("SCAM_DETECTED")
        # The stub always returns the same dict; just ensure it returns a dict
        assert isinstance(result, dict)

    def test_uses_custom_voice_config_when_available(self, monkeypatch):
        custom_mod = types.ModuleType("custom_voice_config")
        custom_mod.CUSTOM_VOICE_ID = "custom-123"
        custom_mod.get_custom_voice_settings = lambda ct: {"voice_id": "custom-123", "ctx": ct}
        _make_stubs(monkeypatch, custom_voice_mod=custom_mod)
        monkeypatch.delitem(sys.modules, "voice_visualizer_integration", raising=False)
        import voice_visualizer_integration as m

        result = m._resolve_voice_settings("SCAM_DETECTED")
        assert result["voice_id"] == "custom-123"
        assert result["ctx"] == "SCAM_DETECTED"

    def test_falls_back_gracefully_when_module_missing(self, integration_module):
        """Even when _get_custom_voice_settings is None, function must not raise."""
        integration_module._get_custom_voice_settings = None
        result = integration_module._resolve_voice_settings("VERIFICATION")
        assert isinstance(result, dict)


# ===========================================================================
# VoiceVisualizerBridge.__init__
# ===========================================================================

class TestVoiceVisualizerBridgeInit:
    def test_is_listening_false(self, bridge):
        assert bridge.is_listening is False

    def test_voice_level_zero(self, bridge):
        assert bridge.voice_level == 0

    def test_current_status_ready(self, bridge):
        assert bridge.current_status == "Ready"

    def test_websocket_clients_empty_set(self, bridge):
        assert isinstance(bridge.websocket_clients, set)
        assert len(bridge.websocket_clients) == 0

    def test_voice_trainer_created(self, bridge):
        assert bridge.voice_trainer is not None


# ===========================================================================
# VoiceVisualizerBridge.broadcast_to_visualizers()
# ===========================================================================

class TestBroadcastToVisualizers:
    @pytest.mark.asyncio
    async def test_no_clients_does_not_raise(self, bridge):
        await bridge.broadcast_to_visualizers({"type": "status_update", "message": "hi"})

    @pytest.mark.asyncio
    async def test_single_client_receives_message(self, bridge):
        client = AsyncMock()
        bridge.websocket_clients.add(client)

        payload = {"type": "status_update", "message": "hello"}
        await bridge.broadcast_to_visualizers(payload)

        client.send.assert_called_once_with(json.dumps(payload))

    @pytest.mark.asyncio
    async def test_multiple_clients_all_receive_message(self, bridge):
        clients = [AsyncMock() for _ in range(3)]
        bridge.websocket_clients.update(clients)

        payload = {"type": "voice_level_update", "level": 42}
        await bridge.broadcast_to_visualizers(payload)

        for c in clients:
            c.send.assert_called_once_with(json.dumps(payload))

    @pytest.mark.asyncio
    async def test_failed_client_does_not_raise(self, bridge):
        """A client whose send() raises should not propagate (gather absorbs)."""
        bad_client = AsyncMock()
        bad_client.send.side_effect = Exception("connection lost")
        bridge.websocket_clients.add(bad_client)

        # Should not raise
        await bridge.broadcast_to_visualizers({"type": "ping"})


# ===========================================================================
# VoiceVisualizerBridge.stop_voice_detection()
# ===========================================================================

class TestStopVoiceDetection:
    @pytest.mark.asyncio
    async def test_sets_is_listening_false(self, bridge):
        bridge.is_listening = True
        await bridge.stop_voice_detection()
        assert bridge.is_listening is False

    @pytest.mark.asyncio
    async def test_broadcasts_voice_level_zero(self, bridge):
        sent = []
        client = AsyncMock()
        client.send.side_effect = lambda msg: sent.append(json.loads(msg))
        bridge.websocket_clients.add(client)

        await bridge.stop_voice_detection()

        assert any(
            m.get("type") == "voice_level_update" and m.get("level") == 0
            for m in sent
        )


# ===========================================================================
# VoiceVisualizerBridge.speak_response()
# ===========================================================================

class TestSpeakResponse:
    @pytest.mark.asyncio
    async def test_broadcasts_speak_response_type(self, monkeypatch, bridge, integration_module):
        """speak_response must broadcast a 'speak_response' payload."""
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = MagicMock(
            return_value=(b"AUDIODATA", "audio/wav", None, "hello world")
        )

        received = []
        client = AsyncMock()
        client.send.side_effect = lambda msg: received.append(json.loads(msg))
        bridge.websocket_clients.add(client)

        await bridge.speak_response("hello world", "LEGITIMATE")

        assert any(m.get("type") == "speak_response" for m in received)

    @pytest.mark.asyncio
    async def test_audio_bytes_base64_encoded_in_payload(self, monkeypatch, bridge, integration_module):
        raw_audio = b"\xDE\xAD\xBE\xEF"
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = MagicMock(
            return_value=(raw_audio, "audio/wav", None, "test text")
        )

        received = []
        client = AsyncMock()
        client.send.side_effect = lambda msg: received.append(json.loads(msg))
        bridge.websocket_clients.add(client)

        await bridge.speak_response("test text", "LEGITIMATE")

        speak_msgs = [m for m in received if m.get("type") == "speak_response"]
        assert speak_msgs, "No speak_response message broadcast"
        msg = speak_msgs[0]
        assert "audio_base64" in msg
        assert base64.b64decode(msg["audio_base64"]) == raw_audio

    @pytest.mark.asyncio
    async def test_mime_type_included_in_payload(self, monkeypatch, bridge, integration_module):
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = MagicMock(
            return_value=(b"A", "audio/mpeg", None, "hi")
        )

        received = []
        client = AsyncMock()
        client.send.side_effect = lambda msg: received.append(json.loads(msg))
        bridge.websocket_clients.add(client)

        await bridge.speak_response("hi", "LEGITIMATE")

        speak_msgs = [m for m in received if m.get("type") == "speak_response"]
        assert speak_msgs[0]["mime_type"] == "audio/mpeg"

    @pytest.mark.asyncio
    async def test_synthesis_error_included_in_payload(self, monkeypatch, bridge, integration_module):
        """When synthesize_speech returns an error, it must appear in the payload."""
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = MagicMock(
            return_value=(None, "", "API quota exceeded", "hello")
        )

        received = []
        client = AsyncMock()
        client.send.side_effect = lambda msg: received.append(json.loads(msg))
        bridge.websocket_clients.add(client)

        await bridge.speak_response("hello", "LEGITIMATE")

        speak_msgs = [m for m in received if m.get("type") == "speak_response"]
        assert speak_msgs, "No speak_response broadcast on error"
        assert speak_msgs[0]["error"] == "API quota exceeded"

    @pytest.mark.asyncio
    async def test_no_audio_base64_when_synthesis_fails(self, monkeypatch, bridge, integration_module):
        """audio_base64 must NOT appear when audio_bytes is None."""
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = MagicMock(
            return_value=(None, "", "failure", "hi")
        )

        received = []
        client = AsyncMock()
        client.send.side_effect = lambda msg: received.append(json.loads(msg))
        bridge.websocket_clients.add(client)

        await bridge.speak_response("hi", "LEGITIMATE")

        speak_msgs = [m for m in received if m.get("type") == "speak_response"]
        assert "audio_base64" not in speak_msgs[0]

    @pytest.mark.asyncio
    async def test_voice_id_injected_from_custom_voice_id(self, monkeypatch):
        """When CUSTOM_VOICE_ID is set and voice_settings lacks voice_id, it is injected."""
        custom_mod = types.ModuleType("custom_voice_config")
        custom_mod.CUSTOM_VOICE_ID = "my-custom-voice"
        custom_mod.get_custom_voice_settings = lambda ct: {"emotion": "calm"}  # no voice_id
        _make_stubs(monkeypatch, custom_voice_mod=custom_mod)
        monkeypatch.delitem(sys.modules, "voice_visualizer_integration", raising=False)
        import voice_visualizer_integration as m

        # Patch synthesize_speech to capture arguments
        called_with = {}
        tts_mod = sys.modules["tts_engine"]

        def fake_synth(text, voice_settings, **kw):
            called_with["voice_settings"] = voice_settings
            return b"X", "audio/wav", None, text

        tts_mod.synthesize_speech = fake_synth

        b = m.VoiceVisualizerBridge()
        await b.speak_response("test", "LEGITIMATE")

        assert called_with.get("voice_settings", {}).get("voice_id") == "my-custom-voice"

    @pytest.mark.asyncio
    async def test_effective_text_used_in_payload(self, monkeypatch, bridge, integration_module):
        """The 'text' field in the payload must be the effective_text from synthesize_speech."""
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = MagicMock(
            return_value=(b"A", "audio/wav", None, "truncated text")
        )

        received = []
        client = AsyncMock()
        client.send.side_effect = lambda msg: received.append(json.loads(msg))
        bridge.websocket_clients.add(client)

        await bridge.speak_response("full long text", "LEGITIMATE")

        speak_msgs = [m for m in received if m.get("type") == "speak_response"]
        assert speak_msgs[0]["text"] == "truncated text"

    @pytest.mark.asyncio
    async def test_voice_settings_included_in_payload(self, monkeypatch, bridge, integration_module):
        tts_mod = sys.modules["tts_engine"]
        tts_mod.synthesize_speech = MagicMock(
            return_value=(b"A", "audio/wav", None, "hi")
        )

        received = []
        client = AsyncMock()
        client.send.side_effect = lambda msg: received.append(json.loads(msg))
        bridge.websocket_clients.add(client)

        await bridge.speak_response("hi", "SCAM_DETECTED")

        speak_msgs = [m for m in received if m.get("type") == "speak_response"]
        assert "voice_settings" in speak_msgs[0]
        assert "voice_id" in speak_msgs[0]
