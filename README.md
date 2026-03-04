# Voice AI Tools

Local TTS playback in Chrome using your custom/cloned voice powered by Google GenAI.

## Architecture

```
voice_training.py  →  custom_voice_config.py  (your voice ID & settings)
tts_engine.py      →  synthesize_speech()       (Google GenAI TTS)
flask_server.py    →  /tts endpoint             (local HTTP API)
extension/         →  Chrome popup              (UI + audio playback)
```

---

## Quick Start

### 1. Prerequisites

- Python 3.10+
- Google Cloud project with **Gemini API** (or AI Studio) access
- Google Chrome

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Google API credentials

```bash
# AI Studio key (simplest)
export GOOGLE_API_KEY="your-google-api-key"

# ── or ──  Application Default Credentials (gcloud CLI)
# gcloud auth application-default login
```

### 4. (Optional) Train your custom voice

Record the 10 training phrases listed by the script and save them as
`voice_samples/voice_sample_01.wav` … `voice_sample_10.wav`, then run:

```bash
python voice_training.py
```

This writes `custom_voice_config.py` containing your `CUSTOM_VOICE_ID`.
The Flask server automatically detects and uses this file when present.

### 5. Set the shared secret token

```bash
export VOICE_SERVER_TOKEN="choose-a-strong-random-secret"
```

> If `VOICE_SERVER_TOKEN` is not set, the server prints a warning and
> accepts all requests.  **Always set it on a multi-user or networked machine.**

### 6. Start the Flask server

```bash
python flask_server.py
```

The server binds to `127.0.0.1:5000` by default.  Override with:

```bash
HOST=127.0.0.1 PORT=5000 python flask_server.py
```

### 7. Load the Chrome extension

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** and select the `extension/` folder in this repo

### 8. Configure the extension

1. Click the **Voice AI TTS** icon in the Chrome toolbar
2. Click **⚙️ Settings**
3. Set **Server URL** to `http://127.0.0.1:5000` (default)
4. Set **Token** to the same value as `VOICE_SERVER_TOKEN`
5. Click **💾 Save Settings**

### 9. Test

- Type any text in the popup and click **▶ Speak**
- Click **🚨 Test Scam** or **✅ Test Legitimate** for pre-set demo phrases
- Audio plays directly in the browser via the offscreen API

---

## Environment Variables (Flask server)

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | *(required)* | Google GenAI API key |
| `VOICE_SERVER_TOKEN` | *(empty = open)* | Shared secret for `X-Voice-Token` header |
| `HOST` | `127.0.0.1` | Bind host |
| `PORT` | `5000` | Bind port |
| `ALLOWED_ORIGINS` | *(empty)* | Comma-separated extra CORS origins (e.g. `chrome-extension://abc123`) |

---

## Security Notes

- The server binds to `127.0.0.1` only – not reachable from the network.
- The `X-Voice-Token` header prevents other local pages from calling the API.
- CORS is restricted to localhost origins by default.
- `custom_voice_config.py` and `voice_samples/` are excluded from git via `.gitignore`.
- Text length is capped at 2000 characters; the `/tts` endpoint is rate-limited to 30 requests/minute.

---

## File Overview

| File | Purpose |
|---|---|
| `tts_engine.py` | Google GenAI TTS synthesis |
| `flask_server.py` | Local Flask API server |
| `voice_config.py` | Default voice settings |
| `voice_training.py` | Custom voice training guide |
| `extension/manifest.json` | Chrome Extension manifest (MV3) |
| `extension/popup.html` | Extension popup UI |
| `extension/popup.js` | Popup logic (fetch + play) |
| `extension/background.js` | Service worker (offscreen doc management) |
| `extension/offscreen.html` | Hidden audio playback page |
| `extension/offscreen.js` | Audio playback script |
| `requirements.txt` | Python dependencies |
