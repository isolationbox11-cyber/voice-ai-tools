import subprocess
import os
from pathlib import Path

def train_from_samples(sample_paths):
    """
    Zero-Shot "Training" Bridge.
    Instead of fine-tuning, we pick the first valid sample, normalize it, 
    transcribe it, and return the path and text to be used as a reference preset.
    """
    if not sample_paths:
        raise ValueError("No samples provided")

    primary_sample = Path(sample_paths[0])
    if not primary_sample.exists():
        raise FileNotFoundError(f"Sample not found: {primary_sample}")

    out_dir = primary_sample.parent / "references"
    out_dir.mkdir(exist_ok=True, parents=True)
    
    clean_wav = out_dir / f"ref_{primary_sample.stem}.wav"

    print(f"🎙️ Preparing reference audio: {clean_wav}")
    # Convert to 24kHz mono (ideal for F5-TTS reference audio)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(primary_sample), "-ar", "24000", "-ac", "1", str(clean_wav)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    print("📝 Transcribing reference audio...")
    try:
        import os
        os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
        import whisper
        # Load the base model (you only need this briefly for the reference text)
        model = whisper.load_model("base")
        result = model.transcribe(str(clean_wav))
        ref_text = result['text'].strip()
    except ImportError:
        print("Whisper not installed. Falling back to empty text (F5-TTS may guess).")
        ref_text = ""
    except Exception as e:
        print(f"Transcription failed: {e}")
        ref_text = ""

    # Return a serialized dictionary containing the paths needed for zero-shot TTS
    import json
    return json.dumps({
        "ref_audio": str(clean_wav),
        "ref_text": ref_text
    })
