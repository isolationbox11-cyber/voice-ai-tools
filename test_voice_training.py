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


# ===========================================================================
# _is_within_root() – new helper added in this PR
# ===========================================================================

class TestIsWithinRoot:
    """Unit tests for the _is_within_root() boundary helper."""

    def test_child_path_inside_root_returns_true(self, tmp_path):
        root = tmp_path / "samples"
        root.mkdir()
        child = root / "clip.wav"
        child.write_bytes(b"")
        assert voice_training._is_within_root(child, root) is True

    def test_deeply_nested_child_inside_root_returns_true(self, tmp_path):
        root = tmp_path / "samples"
        nested = root / "a" / "b" / "c"
        nested.mkdir(parents=True)
        target = nested / "deep.wav"
        target.write_bytes(b"")
        assert voice_training._is_within_root(target, root) is True

    def test_sibling_directory_returns_false(self, tmp_path):
        root = tmp_path / "samples"
        sibling = tmp_path / "other"
        root.mkdir()
        sibling.mkdir()
        target = sibling / "clip.wav"
        target.write_bytes(b"")
        assert voice_training._is_within_root(target, root) is False

    def test_parent_directory_returns_false(self, tmp_path):
        root = tmp_path / "samples"
        root.mkdir()
        # The parent of root is tmp_path, which is outside root
        assert voice_training._is_within_root(tmp_path, root) is False

    def test_path_traversal_above_root_returns_false(self, tmp_path):
        root = tmp_path / "samples"
        root.mkdir()
        # Constructing a path that traverses above root via symlink or manual resolve
        traversal = root / ".." / "escape.wav"
        # On resolve this becomes tmp_path / "escape.wav" – outside root
        assert voice_training._is_within_root(traversal, root) is False

    def test_root_itself_returns_true(self, tmp_path):
        root = tmp_path / "samples"
        root.mkdir()
        # The root directory itself should be considered "within" root
        assert voice_training._is_within_root(root, root) is True


# ===========================================================================
# train_from_samples – path validation added in this PR
# ===========================================================================

class TestTrainFromSamplesPathValidation:
    """Tests for the new security checks in train_from_samples:
    - Rejects files outside _SAFE_SAMPLES_ROOT
    - Rejects dot-prefixed sample names
    - Rejects non-existent files
    - Uses UUID-named conversion output for non-WAV files
    """

    def _make_wav(self, directory, name="clip.wav") -> Path:
        p = directory / name
        header = (
            b"RIFF" + (36).to_bytes(4, "little") +
            b"WAVE" +
            b"fmt " + (16).to_bytes(4, "little") +
            (1).to_bytes(2, "little") +
            (1).to_bytes(2, "little") +
            (22050).to_bytes(4, "little") +
            (44100).to_bytes(4, "little") +
            (2).to_bytes(2, "little") +
            (16).to_bytes(2, "little") +
            b"data" + (0).to_bytes(4, "little")
        )
        p.write_bytes(header)
        return p

    def test_rejects_file_outside_safe_samples_root(self, tmp_path, monkeypatch):
        """Files that are not within _SAFE_SAMPLES_ROOT must be silently dropped."""
        samples_root = tmp_path / "samples"
        samples_root.mkdir()
        monkeypatch.setattr(voice_training, "_SAFE_SAMPLES_ROOT", samples_root)

        # Place the WAV file outside the samples root
        outside = tmp_path / "outside_clip.wav"
        self._make_wav(tmp_path, "outside_clip.wav")

        monkeypatch.setattr(voice_training, "_get_coqui_model", lambda: None)
        result = voice_training.train_from_samples([str(outside)])
        assert result is None

    def test_accepts_file_within_safe_samples_root(self, tmp_path, monkeypatch):
        """A valid WAV file residing inside _SAFE_SAMPLES_ROOT must be accepted."""
        samples_root = tmp_path / "samples"
        samples_root.mkdir()
        monkeypatch.setattr(voice_training, "_SAFE_SAMPLES_ROOT", samples_root)

        wav = self._make_wav(samples_root, "clip.wav")
        monkeypatch.chdir(tmp_path)
        (tmp_path / "voice_embeddings").mkdir(exist_ok=True)
        monkeypatch.setattr(voice_training, "_get_coqui_model", lambda: None)
        written = []
        monkeypatch.setattr(
            voice_training, "_write_voice_config",
            lambda vid, paths, engine: written.append((vid, engine))
        )

        result = voice_training.train_from_samples([str(wav)])
        assert result is not None
        assert result.startswith("local_voice_")

    def test_rejects_dot_prefixed_sample_name(self, tmp_path, monkeypatch):
        """Filenames starting with '.' are rejected even when inside the samples root."""
        samples_root = tmp_path / "samples"
        samples_root.mkdir()
        monkeypatch.setattr(voice_training, "_SAFE_SAMPLES_ROOT", samples_root)

        hidden = samples_root / ".hidden.wav"
        hidden.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")

        monkeypatch.setattr(voice_training, "_get_coqui_model", lambda: None)
        result = voice_training.train_from_samples([str(hidden)])
        assert result is None

    def test_rejects_nonexistent_file(self, tmp_path, monkeypatch):
        """A path that resolves within the root but does not exist on disk is rejected."""
        samples_root = tmp_path / "samples"
        samples_root.mkdir()
        monkeypatch.setattr(voice_training, "_SAFE_SAMPLES_ROOT", samples_root)

        ghost = samples_root / "nonexistent.wav"
        # Do not create the file

        monkeypatch.setattr(voice_training, "_get_coqui_model", lambda: None)
        result = voice_training.train_from_samples([str(ghost)])
        assert result is None

    def test_non_wav_audio_conversion_uses_uuid_output_name(self, tmp_path, monkeypatch):
        """Non-WAV files must be converted to a UUID-named .wav, not the original name."""
        samples_root = tmp_path / "samples"
        samples_root.mkdir()
        monkeypatch.setattr(voice_training, "_SAFE_SAMPLES_ROOT", samples_root)

        # Create a fake .mp3 file inside the samples root
        mp3_file = samples_root / "voice.mp3"
        mp3_file.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00")  # ID3 header magic bytes

        converted_paths = []

        def fake_convert(src, dst):
            converted_paths.append(dst)
            # Simulate successful conversion by creating the destination file
            dst.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
            return True

        monkeypatch.setattr(voice_training, "_convert_to_wav", fake_convert)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "voice_embeddings").mkdir(exist_ok=True)
        monkeypatch.setattr(voice_training, "_get_coqui_model", lambda: None)
        monkeypatch.setattr(
            voice_training, "_write_voice_config",
            lambda vid, paths, engine: None
        )

        result = voice_training.train_from_samples([str(mp3_file)])
        assert result is not None
        assert len(converted_paths) == 1
        dst_path = converted_paths[0]
        # Output name must not be derived from the input filename "voice"
        assert dst_path.stem != "voice", (
            "Conversion output must use a UUID name, not the original filename"
        )
        # Output name must start with "converted_"
        assert dst_path.name.startswith("converted_"), (
            f"Expected UUID-based name starting with 'converted_', got: {dst_path.name!r}"
        )
        # Output must be a .wav file
        assert dst_path.suffix == ".wav"

    def test_non_wav_conversion_output_stays_within_samples_root(self, tmp_path, monkeypatch):
        """The UUID-named conversion destination must remain inside _SAFE_SAMPLES_ROOT."""
        samples_root = tmp_path / "samples"
        samples_root.mkdir()
        monkeypatch.setattr(voice_training, "_SAFE_SAMPLES_ROOT", samples_root)

        mp3_file = samples_root / "clip.mp3"
        mp3_file.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00")

        conversion_destinations = []

        def fake_convert(src, dst):
            conversion_destinations.append(dst)
            dst.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
            return True

        monkeypatch.setattr(voice_training, "_convert_to_wav", fake_convert)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "voice_embeddings").mkdir(exist_ok=True)
        monkeypatch.setattr(voice_training, "_get_coqui_model", lambda: None)
        monkeypatch.setattr(
            voice_training, "_write_voice_config",
            lambda vid, paths, engine: None
        )

        voice_training.train_from_samples([str(mp3_file)])
        assert len(conversion_destinations) == 1
        dst = conversion_destinations[0].resolve()
        # Verify the destination is inside the samples root
        assert voice_training._is_within_root(dst, samples_root), (
            f"Conversion destination {dst} is outside samples root {samples_root}"
        )

    def test_mixed_valid_and_outside_root_files_only_uses_valid_ones(self, tmp_path, monkeypatch):
        """Files outside the root are silently skipped; files inside are still processed."""
        samples_root = tmp_path / "samples"
        samples_root.mkdir()
        monkeypatch.setattr(voice_training, "_SAFE_SAMPLES_ROOT", samples_root)

        # Valid file inside root
        good_wav = self._make_wav(samples_root, "good.wav")
        # Invalid file outside root
        bad_wav = self._make_wav(tmp_path, "bad.wav")

        monkeypatch.chdir(tmp_path)
        (tmp_path / "voice_embeddings").mkdir(exist_ok=True)
        monkeypatch.setattr(voice_training, "_get_coqui_model", lambda: None)
        written = []
        monkeypatch.setattr(
            voice_training, "_write_voice_config",
            lambda vid, paths, engine: written.append(paths)
        )

        result = voice_training.train_from_samples([str(bad_wav), str(good_wav)])
        # Result must not be None because the good file was processed
        assert result is not None
        # Only the good file should appear in the sample paths
        assert len(written) == 1
        assert any("good.wav" in p for p in written[0])
        assert all("bad.wav" not in p for p in written[0])

    def test_path_traversal_via_symlink_resolution_is_blocked(self, tmp_path, monkeypatch):
        """Even if a symlink inside the root points outside, the resolved path is rejected."""
        samples_root = tmp_path / "samples"
        samples_root.mkdir()
        outside = tmp_path / "secret.wav"
        outside.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
        monkeypatch.setattr(voice_training, "_SAFE_SAMPLES_ROOT", samples_root)

        # Create a symlink inside samples_root pointing to a file outside
        link = samples_root / "link.wav"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation not supported in this environment")

        monkeypatch.setattr(voice_training, "_get_coqui_model", lambda: None)
        result = voice_training.train_from_samples([str(link)])
        # After resolve(), the symlink target is outside samples_root → rejected
        assert result is None
