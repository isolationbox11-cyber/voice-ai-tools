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
extension/              →  Chrome popup (UI) + background service worker (fetch + audio)
                           + offscreen document (audio playback lifecycle)
```

### Extension playback architecture

Audio playback is intentionally **not** tied to the popup's lifetime:

1. The popup collects text and sends a `TTS_REQUEST` message to the **background service worker**.
2. The background worker fetches `/tts` from the Flask server and receives raw audio bytes.
3. The background worker forwards the `ArrayBuffer` to the **offscreen document**.
4. The offscreen document creates a `Blob`, generates a temporary object URL, plays the audio, and **revokes the URL** when playback ends or fails.

This means the popup can close immediately after clicking **Speak** and audio still plays to completion.

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

### 4b. Set the shared secret token (required)

```bash
export VOICE_SERVER_TOKEN="choose-a-strong-random-secret"
```

> **`VOICE_SERVER_TOKEN` is required.**  If it is not set, all requests to
> protected endpoints (`/tts`, `/presets`, `/log`, `/shodan`, `/analyze_pdf`,
> `/train`, `/model_status`) are rejected with HTTP 401.  Only `/health` is
> always accessible.

### 5b. Start the Flask server

```bash
python flask_server.py
```

The server **always** binds to `127.0.0.1:5000` – it is never reachable from
the network by default.  If you explicitly need a different bind address (e.g.
for containerised setups), set `ALLOW_NETWORK_BINDING=1` **and** `HOST`:

```bash
ALLOW_NETWORK_BINDING=1 HOST=0.0.0.0 PORT=5000 python flask_server.py
```

> Setting a non-loopback `HOST` without `ALLOW_NETWORK_BINDING=1` causes the
> server to exit immediately with a clear error message.

### 6b. Load the Chrome extension

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** and select the `extension/` folder

The extension declares `host_permissions` for `http://127.0.0.1:5000/*` and
`http://localhost:5000/*` so the background service worker can reach the local
Flask API.

### 7b. Configure the extension

1. Click the **Voice AI TTS** icon in the Chrome toolbar
2. The popup opens – make sure **Server URL** is `http://127.0.0.1:5000`
3. Paste the same value as `VOICE_SERVER_TOKEN` into the **Token** field
4. The connection indicator turns green when the server is reachable

### 8b. Test

- Type any text in the **Voice** tab and click **▶ SPEAK IN CLONED VOICE**
- The popup sends the request to the background service worker, which fetches audio from Flask and plays it in the offscreen document
- You can close the popup immediately after clicking – playback continues

---

## Environment variables (Flask server)

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | *(required)* | Google GenAI API key |
| `VOICE_SERVER_TOKEN` | *(required)* | Shared secret for `X-Token` header – all protected endpoints return 401 when unset |
| `PORT` | `5000` | Bind port |
| `HOST` | `127.0.0.1` | Bind host – only honoured when `ALLOW_NETWORK_BINDING=1` |
| `ALLOW_NETWORK_BINDING` | *(unset)* | Set to `1` to permit binding to non-loopback addresses (logs a warning) |
| `ALLOWED_ORIGINS` | *(empty)* | Comma-separated extra CORS origins (e.g. a specific extension ID like `chrome-extension://abc...`) |

---

## Privacy & security

- The Flask server binds to `127.0.0.1` only – not reachable from the network
  unless you explicitly set `ALLOW_NETWORK_BINDING=1`.
- **`VOICE_SERVER_TOKEN` is required** for all protected endpoints.  Without it
  the server still starts, but every protected request is rejected with 401.
- CORS allows only `http://127.0.0.1:5000` and `http://localhost:5000` by
  default.  No wildcard or `"null"` origins are permitted.  Add trusted
  extension origins via `ALLOWED_ORIGINS` if needed.
- The extension's `host_permissions` are scoped to the two loopback origins
  above – the extension cannot reach arbitrary remote servers.
- Audio is synthesized in-memory and never written to disk unless you pass
  `debug_output_path` to `tts_engine.synthesize_speech()`.
- Blob URLs created during audio playback are revoked immediately after the
  audio ends or errors – no object-URL leaks.
- Input text is truncated to **1,000 characters** to prevent runaway requests.
- `custom_voice_config.py` and `voice_samples/` are excluded from git via
  `.gitignore`.

---

## Voice settings

The `voice_config.py` module provides per-context voice presets.  The only
setting actively used by the Gemini TTS API today is **`voice_id`** (the name
of a Gemini prebuilt voice such as `"Kore"`).  Additional fields
(`speaking_rate`, `pitch`, `emotion`) are stored in the settings dict and may
be forwarded when the API adds support, but they do not affect synthesis output
at present.

---

## File reference

| File | Purpose |
|------|---------|
| `voice_training.py` | Record voice samples → train custom voice → write `custom_voice_config.py` |
| `voice_config.py` | Default voice presets per call-type (includes `voice_id`) |
| `tts_engine.py` | Google GenAI TTS synthesis helper – caches `genai.Client` for efficiency |
| `flask_server.py` | Local HTTP TTS API (Path B) |
| `extension/manifest.json` | Chrome MV3 manifest with `host_permissions` for localhost |
| `extension/background.js` | Service worker – owns TTS fetch + forwards audio to offscreen |
| `extension/offscreen.js` | Hidden document – plays audio and revokes blob URLs |
| `extension/popup.js` | Popup UI – delegates TTS requests to background |
| `voice_visualizer_integration.py` | WebSocket server + `VoiceVisualizerBridge` (Path A) |
| `voice_visualizer_standalone.py` | Lightweight standalone version (no AI dependencies) |
| `interactive_voice_visualizer.html` | Browser visualizer & audio player (Path A) |
| `requirements.txt` | Python dependencies |
