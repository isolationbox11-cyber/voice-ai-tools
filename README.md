# Voice AI Tools

A browser-based voice visualizer that synthesizes speech in your cloned/custom voice and plays it back live in the browser.

---

## Quick start

### 1. Install dependencies

```bash
pip install google-genai websockets
```

### 2. (Optional) Train your custom voice

Record ten phrases (see the instructions printed by `voice_training.py`) and save them as `voice_samples/voice_sample_01.wav` … `voice_sample_10.wav`, then run:

```bash
python voice_training.py
```

This creates `custom_voice_config.py` containing your `CUSTOM_VOICE_ID`.  
If you skip this step the system falls back to the default Gemini voice.

### 3. Run the backend server

```bash
python voice_visualizer_integration.py
```

The WebSocket server starts on `ws://localhost:8765`.

### 4. Open the visualizer

Open `interactive_voice_visualizer.html` in your browser (double-click the file, or serve it with any HTTP server).

The page connects automatically to the local WebSocket server.

### 5. Test speech synthesis

- Click **▶ Start Listening** to begin voice-level simulation.  
- Click **🚨 Test Scam** or **✅ Test Legit** to trigger a synthesized speech response.  
  The audio is generated on the Python side, base64-encoded, sent over the WebSocket, and played directly in the browser.  
  If the backend is unreachable or synthesis fails the page falls back to the browser's built-in `speechSynthesis` API.

---

## Architecture

```
voice_visualizer_integration.py   ← WebSocket server + orchestrator
        │
        ├── tts_engine.py          ← Google GenAI TTS synthesis (in-memory, privacy-first)
        ├── voice_config.py        ← Default emotion/rate/pitch presets
        └── custom_voice_config.py ← (generated) CUSTOM_VOICE_ID + settings overrides

interactive_voice_visualizer.html ← Browser client (WebSocket + Web Audio)
```

### Message flow

1. Browser sends `{ type: "test_scam" }` (or similar).  
2. Server calls `VoiceVisualizerBridge.speak_response(text, call_type)`.  
3. `speak_response` loads voice settings (custom or default), calls `tts_engine.synthesize_speech()`.  
4. Audio bytes are base64-encoded and broadcast:  
   ```json
   {
     "type": "speak_response",
     "text": "...",
     "voice_settings": { ... },
     "voice_id": "...",
     "audio_base64": "<base64-encoded WAV>",
     "mime_type": "audio/wav"
   }
   ```
5. Browser decodes the payload, creates a Blob URL, and plays it via `<audio>`.

---

## Privacy & security

- The WebSocket server binds to **localhost only** by default — not accessible from the network.  
- Audio is synthesized in-memory and never written to disk unless you pass `debug_output_path` to `tts_engine.synthesize_speech()`.  
- Input text is truncated to **1,000 characters** to prevent runaway requests.

---

## File reference

| File | Purpose |
|------|---------|
| `voice_training.py` | Record voice samples → train custom voice → write `custom_voice_config.py` |
| `voice_config.py` | Default voice presets per call-type |
| `tts_engine.py` | Google GenAI TTS synthesis helper |
| `voice_visualizer_integration.py` | WebSocket server + `VoiceVisualizerBridge` |
| `voice_visualizer_standalone.py` | Lightweight standalone version (no AI dependencies) |
| `interactive_voice_visualizer.html` | Browser visualizer & audio player |
