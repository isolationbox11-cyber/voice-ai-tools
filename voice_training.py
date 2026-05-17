import os
import subprocess
import time
from pathlib import Path

# Allowed audio extensions for voice training clips
_ALLOWED_AUDIO_SUFFIXES = {".webm", ".wav", ".mp3", ".ogg", ".flac", ".m4a"}

# ── Coqui XTTS v2 lazy loader ───────────────────────────────────────
_tts_model = None

def _get_coqui_model():
    """Lazy-load Coqui XTTS v2 on first use (downloads ~2GB once)."""
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
    """Convert audio file to wav using subprocess (no shell=True).

    Uses subprocess.run with a list of args so no shell injection is possible
    regardless of what the filename contains.
    """
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


# ── train_from_samples ────────────────────────────────────────────
# Called by flask_server.py /train endpoint.
# Takes the recorded audio clips and trains a real Coqui XTTS v2
# speaker embedding. No API key required — runs 100% locally.
def train_from_samples(sample_paths: list) -> str | None:
    """Train a Coqui XTTS v2 speaker embedding from recorded clips.

    Args:
        sample_paths: List of .webm/.wav file paths from the recorder.

    Returns:
        voice_id string on success, or None on failure.
    """
    if not sample_paths:
        return None

    wav_paths = []
    for path in sample_paths:
        p = Path(path)
        # Validate extension before touching the file
        if p.suffix.lower() not in _ALLOWED_AUDIO_SUFFIXES:
            print(f"Rejected file with disallowed extension: {p.name}")
            continue
        if p.suffix.lower() == ".wav":
            wav_paths.append(str(p))
        else:
            # Convert to wav using subprocess list-form (no shell injection possible)
            wav_path = p.with_suffix(".wav")
            if _convert_to_wav(p, wav_path):
                wav_paths.append(str(wav_path))
            else:
                print(f"Conversion failed for {p.name}, skipping.")

    if not wav_paths:
        print("No usable wav files after conversion.")
        return None

    # Generate a unique voice ID
    voice_id = f"local_voice_{int(time.time())}"
    embedding_dir = Path("voice_embeddings")
    embedding_dir.mkdir(exist_ok=True)
    embedding_path = embedding_dir / f"{voice_id}.json"

    # Load the model and compute speaker embedding from all clips
    model = _get_coqui_model()
    if model is None:
        import json
        embedding_path.write_text(json.dumps({
            "voice_id": voice_id,
            "sample_paths": wav_paths,
            "engine": "fallback"
        }))
        _write_voice_config(voice_id, wav_paths, engine="fallback")
        print(f"Coqui not available. Saved sample paths for later. Voice ID: {voice_id}")
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
        print(f"Speaker embedding saved to {embedding_path}")
        # FIX: write voice config on successful training so the cloned voice
        # is immediately available via flask_server._resolve_voice_settings()
        _write_voice_config(voice_id, wav_paths, engine="coqui_xtts_v2")
    except Exception as e:
        print(f"Embedding extraction failed ({e}), falling back to sample paths.")
        import json
        embedding_path.write_text(json.dumps({
            "voice_id": voice_id,
            "sample_paths": wav_paths,
            "engine": "fallback"
        }))
        _write_voice_config(voice_id, wav_paths, engine="coqui_xtts_v2")

    print(f"Voice training complete. Voice ID: {voice_id}")
    return voice_id


def _write_voice_config(voice_id: str, sample_paths: list = None, engine: str = "coqui_xtts_v2"):
    """Write custom_voice_config.py with the trained voice metadata."""
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


# ── synthesize_with_cloned_voice ────────────────────────────────────
def synthesize_with_cloned_voice(text: str, voice_id: str) -> bytes | None:
    """Synthesize speech using the saved Coqui speaker embedding.

    Returns raw WAV bytes, or None if synthesis fails.
    """
    import json
    embedding_path = Path("voice_embeddings") / f"{voice_id}.json"
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

        gpt_cond_latent = torch.tensor(data["gpt_cond_latent"])
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
