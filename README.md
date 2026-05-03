# Voice AI Tools

Synthesized speech in your cloned/custom voice – with two integration paths:

1. **WebSocket visualizer** – Python backend + browser visualizer connected over a local WebSocket.
2. **Flask + Chrome extension** – local HTTP API consumed by a Chrome popup.

Both paths share the same `tts_engine.py` TTS core and the optional `custom_voice_config.py` custom-voice profile.

---

## Architecture

```
voice_training.py       →  custom_voice_config.py  (your voice ID & settings)
tts_engine.py           →  synthesize_speech()       (Google GenAI TTS, in-memory)

── WebSocket path ─────────────────────────────────────────────────────────────
voice_visualizer_integration.py  →  ws://localhost:8765
interactive_voice_visualizer.html  (browser client)

── Flask + Chrome path ────────────────────────────────────────────────────────
flask_server.py         →  http://127.0.0.1:5000/tts
extension/              →  Chrome popup (UI + audio playback)
```

---

## Prerequisites

- Python 3.10+
- Google Cloud project with **Gemini API** (or AI Studio) access
- Google Chrome *(only for the Chrome extension path)*

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Google API credentials

```bash
# AI Studio key (simplest)
export GOOGLE_API_KEY="your-google-api-key"

# ── or ──  Application Default Credentials (gcloud CLI)
# gcloud auth application-default login
```

### 3. (Optional) Train your custom voice

Record the 10 training phrases listed by the script and save them as
`voice_samples/voice_sample_01.wav` … `voice_sample_10.wav`, then run:

```bash
python voice_training.py
```

This writes `custom_voice_config.py` containing your `CUSTOM_VOICE_ID`.  
Both server paths automatically detect and use this file when present.  
If you skip this step the system falls back to the default Gemini voice (`Kore`).

---

## Path A – WebSocket visualizer

### 4a. Run the backend server

```bash
python voice_visualizer_integration.py
```

The WebSocket server starts on `ws://localhost:8765`.

### 5a. Open the visualizer

Open `interactive_voice_visualizer.html` in your browser (double-click the file, or serve it with any HTTP server).

The page connects automatically to the local WebSocket server.

### 6a. Test speech synthesis

- Click **▶ Start Listening** to begin voice-level simulation.
- Click **🚨 Test Scam** or **✅ Test Legit** to trigger a synthesized speech response.

Audio is generated on the Python side, base64-encoded, sent over the WebSocket, and played via `<audio>` in the browser.  
Falls back to `window.speechSynthesis` when no audio payload is present.

---

## Path B – Flask + Chrome extension

### 4b. Set the shared secret token

```bash
export VOICE_SERVER_TOKEN="choose-a-strong-random-secret"
```

> If `VOICE_SERVER_TOKEN` is not set, the server prints a warning and
> accepts all requests.  **Always set it on a multi-user or networked machine.**

### 5b. Start the Flask server

```bash
python flask_server.py
```

The server binds to `127.0.0.1:5000` by default.  Override with:

```bash
HOST=127.0.0.1 PORT=5000 python flask_server.py
```

### 6b. Load the Chrome extension

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** and select the `extension/` folder

### 7b. Configure the extension

1. Click the **Voice AI TTS** icon in the Chrome toolbar
2. Click **⚙️ Settings**
3. Set **Server URL** to `http://127.0.0.1:5000` (default)
4. Set **Token** to the same value as `VOICE_SERVER_TOKEN`
5. Click **💾 Save Settings**

### 8b. Test

- Type any text in the popup and click **▶ Speak**
- Click **🚨 Test Scam** or **✅ Test Legitimate** for pre-set demo phrases

---

## Environment variables (Flask server)

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | *(required)* | Google GenAI API key |
| `VOICE_SERVER_TOKEN` | *(empty = open)* | Shared secret for `X-Voice-Token` header |
| `HOST` | `127.0.0.1` | Bind host |
| `PORT` | `5000` | Bind port |
| `ALLOWED_ORIGINS` | *(empty)* | Comma-separated extra CORS origins |

---

## Privacy & security

- Both servers bind to `127.0.0.1` only – not reachable from the network.
- The `X-Voice-Token` header (Flask path) prevents other local pages from calling the API.
- Audio is synthesized in-memory and never written to disk unless you pass `debug_output_path` to `tts_engine.synthesize_speech()`.
- Input text is truncated to **1,000 characters** to prevent runaway requests.
- `custom_voice_config.py` and `voice_samples/` are excluded from git via `.gitignore`.

---

## File reference

| File | Purpose |
|------|---------|
| `voice_training.py` | Record voice samples → train custom voice → write `custom_voice_config.py` |
| `voice_config.py` | Default voice presets per call-type |
| `tts_engine.py` | Google GenAI TTS synthesis helper (shared by both paths) |
| `flask_server.py` | Local HTTP TTS API (Path B) |
| `extension/` | Chrome extension popup + offscreen audio player (Path B) |
| `voice_visualizer_integration.py` | WebSocket server + `VoiceVisualizerBridge` (Path A) |
| `voice_visualizer_standalone.py` | Lightweight standalone version (no AI dependencies) |
| `interactive_voice_visualizer.html` | Browser visualizer & audio player (Path A) |
| `requirements.txt` | Python dependencies |
