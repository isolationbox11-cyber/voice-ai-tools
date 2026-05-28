import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from werkzeug.utils import secure_filename

_ALLOWED_AUDIO_SUFFIXES = {".webm", ".wav", ".mp3", ".ogg", ".flac", ".m4a"}
_SAFE_SAMPLES_ROOT = Path("voice_samples").resolve()


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


_tts_model = None


def _get_coqui_model():
    global _tts_model
    if _tts_model is None:
        try:
            from TTS.api import TTS
            print("Loading Coqui XTTS v2 model (first run downloads ~2GB)...")
            _tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=False)
            print("Coqui XTTS v2 loaded.")
        except ImportError:
            print("Coqui TTS not installed. Run: pip install TTS")
            _tts_model = None
    return _tts_model


def _convert_to_wav(src: Path, dst: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-ar", "22050", "-ac", "1", str(dst)],
            capture_output=True,
            timeout=120,
        )
        return result.returncode == 0 and dst.exists()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"ffmpeg error for {src}: {e}")
        return False


def train_from_samples(sample_paths: list) -> str | None:
    if not sample_paths:
        return None

    trusted_files: dict[str, Path] = {}
    if _SAFE_SAMPLES_ROOT.is_dir():
        for entry in _SAFE_SAMPLES_ROOT.iterdir():
            resolved = entry.resolve()
            if _is_within_root(resolved, _SAFE_SAMPLES_ROOT) and resolved.is_file():
                trusted_files[entry.name] = resolved

    wav_paths = []
    for path in sample_paths:
        fname = Path(path).name
        if not fname or fname.startswith("."):
            print(f"Rejected invalid sample name: {fname!r}")
            continue
        p = trusted_files.get(fname)
        if p is None:
            print(f"Sample not found in trusted root: {fname!r}")
            continue
        if p.suffix.lower() not in _ALLOWED_AUDIO_SUFFIXES:
            print(f"Rejected file with disallowed extension: {p.name}")
            continue
        if p.suffix.lower() == ".wav":
            wav_paths.append(str(p))
        else:
            wav_path = (_SAFE_SAMPLES_ROOT / f"converted_{uuid.uuid4().hex}.wav").resolve()
            if _convert_to_wav(p, wav_path):
                wav_paths.append(str(wav_path))
            else:
                print(f"Conversion failed for {p.name}, skipping.")

    if not wav_paths:
        print("No usable wav files after conversion.")
        return None

    voice_id = f"local_voice_{int(time.time())}"
    embedding_dir = Path("voice_embeddings")
    embedding_dir.mkdir(exist_ok=True)
    embedding_path = embedding_dir / f"{voice_id}.json"

    model = _get_coqui_model()
    if model is None:
        import json
        embedding_path.write_text(json.dumps({
            "voice_id": voice_id,
            "sample_paths": wav_paths,
            "engine": "fallback"
        }))
        _write_voice_config(voice_id, wav_paths, engine="fallback")
        print(f"Coqui not available. Saved sample paths. Voice ID: {voice_id}")
        return voice_id

    try:
        import json
        gpt_cond_latent, speaker_embedding = model.synthesizer.tts_model.get_conditioning_latents(
            audio_path=wav_paths
        )
        import torch
        embedding_data = {
            "voice_id": voice_id,
            "sample_paths": wav_paths,
            "engine": "coqui_xtts_v2",
            "gpt_cond_latent": gpt_cond_latent.cpu().tolist(),
            "speaker_embedding": speaker_embedding.cpu().tolist(),
        }
        embedding_path.write_text(json.dumps(embedding_data))
        _write_voice_config(voice_id, wav_paths, engine="coqui_xtts_v2")
    except Exception as e:
        print(f"Embedding extraction failed ({e}), falling back to sample paths.")
        import json
        embedding_path.write_text(json.dumps({
            "voice_id": voice_id,
            "sample_paths": wav_paths,
            "engine": "fallback"
        }))
        _write_voice_config(voice_id, wav_paths, engine="fallback")

    print(f"Voice training complete. Voice ID: {voice_id}")
    return voice_id


def register_wav_reference(wav_path: str) -> str | None:
    p = Path(wav_path).resolve()
    if not p.exists():
        print(f"register_wav_reference: file not found: {p}")
        return None
    if p.suffix.lower() not in _ALLOWED_AUDIO_SUFFIXES:
        print(f"register_wav_reference: unsupported extension {p.suffix}")
        return None
    if p.suffix.lower() != ".wav":
        converted = p.with_suffix(".wav")
        if not _convert_to_wav(p, converted):
            print(f"register_wav_reference: ffmpeg conversion failed for {p.name}")
            return None
        p = converted
    voice_id = f"wav_ref_{int(time.time())}"
    _write_voice_config(voice_id, [str(p)], engine="wav_reference")
    print(f"WAV reference registered. voice_id={voice_id}, path={p}")
    return voice_id


def _write_voice_config(voice_id: str, sample_paths: list = None, engine: str = "coqui_xtts_v2"):
    paths_repr = repr(sample_paths or [])
    config_code = f'''# Auto-generated by voice_training.py — do not edit manually.
CUSTOM_VOICE_ID = "{voice_id}"
CUSTOM_VOICE_ENGINE = "{engine}"
CUSTOM_VOICE_SAMPLES = {paths_repr}

def get_custom_voice_settings(context):
    base = {{
        "voice_id": CUSTOM_VOICE_ID,
        "engine": CUSTOM_VOICE_ENGINE,
        "speaking_rate": 1.0,
        "pitch": 0,
        "emotion": "professional"
    }}
    if context == "SCAM_DETECTED":
        base.update({{"emotion": "firm", "speaking_rate": 0.9}})
    elif context == "VERIFICATION":
        base.update({{"emotion": "calm", "speaking_rate": 1.0}})
    elif context == "cloned":
        pass
    else:
        base.update({{"emotion": "helpful", "speaking_rate": 1.1}})
    return base
'''
    with open("custom_voice_config.py", "w") as f:
        f.write(config_code)
    print(f"custom_voice_config.py written — voice_id={voice_id}, engine={engine}")


def synthesize_with_cloned_voice(text: str, voice_id: str) -> bytes | None:
    import json
    if not isinstance(voice_id, str):
        print(f"Invalid voice_id format: {voice_id!r}")
        return None
    m = re.fullmatch(r"(local_voice_[A-Za-z0-9_-]+)", voice_id.strip())
    if not m:
        print(f"Invalid voice_id format: {voice_id!r}")
        return None
    candidate_voice_id = m.group(1)
    safe_voice_id = secure_filename(candidate_voice_id)
    if safe_voice_id != candidate_voice_id:
        print(f"Rejected non-canonical voice_id: {voice_id!r}")
        return None
    embeddings_root = Path("voice_embeddings").resolve()
    embedding_path = (embeddings_root / f"{safe_voice_id}.json").resolve()
    if not _is_within_root(embedding_path, embeddings_root):
        print(f"Rejected embedding path outside root: {embedding_path}")
        return None
    if not embedding_path.exists():
        print(f"No embedding found for {voice_id}")
        return None
    data = json.loads(embedding_path.read_text())
    engine = data.get("engine", "fallback")
    model = _get_coqui_model()
    if model is None or engine == "fallback":
        print("Coqui not available or fallback mode — cannot synthesize cloned voice.")
        return None
    try:
        import torch
        import io
        import soundfile as sf
        gpt_cond_latent  = torch.tensor(data["gpt_cond_latent"])
        speaker_embedding = torch.tensor(data["speaker_embedding"])
        out = model.synthesizer.tts_model.inference(
            text=text,
            language="en",
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
            temperature=0.7,
        )
        wav = out["wav"]
        buf = io.BytesIO()
        sf.write(buf, wav, 24000, format="WAV")
        buf.seek(0)
        return buf.read()
    except Exception as e:
        print(f"Coqui synthesis failed: {e}")
        return None


def synthesize_from_wav_reference(text: str, wav_path: str) -> bytes | None:
    ref = Path(wav_path)
    if not ref.exists():
        print(f"synthesize_from_wav_reference: reference WAV not found: {ref}")
        return None
    model = _get_coqui_model()
    if model is None:
        print("synthesize_from_wav_reference: Coqui model not available.")
        return None
    # Assign tmp_path before the try block so the except clause can always reference it
    tmp_path = None
    try:
        import tempfile
        import soundfile as sf
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        model.tts_to_file(
            text=text,
            speaker_wav=str(ref),
            language="en",
            file_path=tmp_path,
        )
        wav_bytes = Path(tmp_path).read_bytes()
        return wav_bytes
    except Exception as e:
        print(f"synthesize_from_wav_reference failed: {e}")
        return None
    finally:
        # Always clean up the temp file whether synthesis succeeded or failed
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
