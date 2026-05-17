"""
Tests for voice_training.py
- train_from_samples: calls _write_voice_config on successful Coqui training
- train_from_samples: calls _write_voice_config in fallback (no model) path
- train_from_samples: returns None for empty input
- train_from_samples: rejects disallowed file extensions
- synthesize_with_cloned_voice: returns None when no embedding found
"""
import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Stub out heavy deps (TTS / torch / soundfile) before importing the module
# ---------------------------------------------------------------------------
def _make_stubs():
    # TTS stub
    tts_pkg = types.ModuleType("TTS")
    tts_api = types.ModuleType("TTS.api")
    tts_api.TTS = MagicMock()
    sys.modules.setdefault("TTS", tts_pkg)
    sys.modules.setdefault("TTS.api", tts_api)

    # torch stub
    torch_mod = types.ModuleType("torch")
    torch_mod.tensor = lambda x: x
    sys.modules.setdefault("torch", torch_mod)

    # soundfile stub
    sf_mod = types.ModuleType("soundfile")
    sf_mod.write = MagicMock()
    sys.modules.setdefault("soundfile", sf_mod)


_make_stubs()

import voice_training  # noqa: E402  (must be after stubs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wav(tmp_path, name="clip.wav") -> Path:
    """Write a minimal valid WAV file."""
    p = tmp_path / name
    # 44-byte WAV header with 0 data bytes
    header = (
        b"RIFF" + (36).to_bytes(4, "little") +
        b"WAVE" +
        b"fmt " + (16).to_bytes(4, "little") +
        (1).to_bytes(2, "little") +   # PCM
        (1).to_bytes(2, "little") +   # mono
        (22050).to_bytes(4, "little") +
        (44100).to_bytes(4, "little") +
        (2).to_bytes(2, "little") +
        (16).to_bytes(2, "little") +
        b"data" + (0).to_bytes(4, "little")
    )
    p.write_bytes(header)
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTrainFromSamples:

    def test_returns_none_for_empty_input(self):
        assert voice_training.train_from_samples([]) is None

    def test_rejects_disallowed_extension(self, tmp_path):
        bad = tmp_path / "clip.exe"
        bad.write_bytes(b"MZ")
        result = voice_training.train_from_samples([str(bad)])
        assert result is None

    def test_fallback_writes_voice_config(self, tmp_path, monkeypatch):
        """When Coqui is unavailable, _write_voice_config must still be called."""
        wav = _make_wav(tmp_path)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "voice_embeddings").mkdir(exist_ok=True)

        monkeypatch.setattr(voice_training, "_get_coqui_model", lambda: None)

        written = []
        monkeypatch.setattr(
            voice_training, "_write_voice_config",
            lambda vid, paths, engine: written.append((vid, engine))
        )

        vid = voice_training.train_from_samples([str(wav)])
        assert vid is not None
        assert vid.startswith("local_voice_")
        assert len(written) == 1
        assert written[0][1] == "fallback"

    def test_successful_coqui_training_writes_voice_config(self, tmp_path, monkeypatch):
        """
        BUG FIX TEST: When Coqui successfully extracts a speaker embedding,
        _write_voice_config must be called with engine='coqui_xtts_v2'.
        Before the fix this call was missing in the success path.
        """
        wav = _make_wav(tmp_path)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "voice_embeddings").mkdir(exist_ok=True)

        # Build a fake model whose latents are plain Python lists (no real torch)
        fake_latent = [[0.1, 0.2]]
        fake_embedding = [[0.3, 0.4]]
        fake_model = MagicMock()
        fake_model.synthesizer.tts_model.get_conditioning_latents.return_value = (
            MagicMock(cpu=lambda: MagicMock(tolist=lambda: fake_latent)),
            MagicMock(cpu=lambda: MagicMock(tolist=lambda: fake_embedding)),
        )
        monkeypatch.setattr(voice_training, "_get_coqui_model", lambda: fake_model)

        written = []
        monkeypatch.setattr(
            voice_training, "_write_voice_config",
            lambda vid, paths, engine: written.append((vid, engine))
        )

        vid = voice_training.train_from_samples([str(wav)])

        assert vid is not None
        assert vid.startswith("local_voice_")
        # THE KEY ASSERTION: config must be written on the happy path
        assert len(written) == 1, (
            "_write_voice_config was NOT called after successful Coqui training "
            "(regression of bug fixed in commit 9edc544)"
        )
        assert written[0][1] == "coqui_xtts_v2"

        # Embedding JSON should also exist
        embedding_file = tmp_path / "voice_embeddings" / f"{vid}.json"
        assert embedding_file.exists()
        data = json.loads(embedding_file.read_text())
        assert data["engine"] == "coqui_xtts_v2"


class TestSynthesizeWithClonedVoice:

    def test_returns_none_when_no_embedding(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "voice_embeddings").mkdir()
        result = voice_training.synthesize_with_cloned_voice("hello", "local_voice_0")
        assert result is None

    def test_returns_none_in_fallback_mode(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        emb_dir = tmp_path / "voice_embeddings"
        emb_dir.mkdir()
        (emb_dir / "local_voice_1.json").write_text(
            json.dumps({"engine": "fallback", "voice_id": "local_voice_1"})
        )
        monkeypatch.setattr(voice_training, "_get_coqui_model", lambda: None)
        result = voice_training.synthesize_with_cloned_voice("hello", "local_voice_1")
        assert result is None
