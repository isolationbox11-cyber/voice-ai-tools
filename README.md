# voice-ai-tools
<!-- screenshot-test -->

A locally-run Flask backend and Chrome extension for voice synthesis, voice cloning, OSINT lookups, and PDF forensics. Powered by Google Gemini for TTS and Shodan for threat intelligence.

## Features

- **Text-to-Speech** — Google Gemini-backed synthesis with configurable voice presets and call-type routing
- **Voice Cloning / Training** — Upload audio samples to train a custom voice model
- **OSINT Lookup** — Domain, IP, and phone number intelligence via `lookup_engine.py`
- **Shodan Integration** — Live host threat data proxied through `/shodan`
- **PDF Forensics** — Extract metadata, links, IPs, and detect suspicious patterns from uploaded PDFs
- **Chrome Extension** — Browser-side UI in `/extension` that connects to the local server
- **Session Logging** — Log and replay voice interactions via `/log`

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/isolationbox11-cyber/voice-ai-tools.git
cd voice-ai-tools

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env and fill in your API keys

# 5. Start the server
python flask_server.py
# Server runs at http://127.0.0.1:5001
```

## Environment Variables

See [`.env.example`](.env.example) for the full list. The only required variable is:

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | ✅ Yes | Gemini API key for TTS |
| `VOICE_SERVER_TOKEN` | Recommended | Auth token sent in `X-Voice-Token` header |
| `SHODAN_API_KEY` | Optional | Enables `/shodan` endpoint |
| `ALLOWED_ORIGINS` | Optional | Extra CORS origins (e.g. Chrome extension ID) |
| `PORT` | Optional | Bind port (default: `5001`) |
| `FLASK_ENV` | Optional | Set to `production` to enforce auth token |

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Server status and config check |
| `POST` | `/tts` | Synthesize speech from text |
| `GET/POST` | `/presets` | Read or save voice presets |
| `GET/POST` | `/log` | Read or append session log entries |
| `POST` | `/log/clear` | Clear all session logs |
| `GET` | `/shodan?ip=` | Shodan host lookup (requires `SHODAN_API_KEY`) |
| `POST` | `/analyze_pdf` | Extract metadata, IPs, links from a PDF |
| `POST` | `/train` | Upload audio samples for voice training |
| `GET` | `/model_status` | Check voice model training status |
| `POST` | `/api/lookup` | OSINT lookup for domain/IP/phone |

All endpoints except `/health` require the `X-Voice-Token` header when `VOICE_SERVER_TOKEN` is set.

## Security Notes

- The server binds to `127.0.0.1` only by default. Set `ALLOW_NETWORK_BINDING=1` only if you understand the risks.
- Always set `VOICE_SERVER_TOKEN` in any non-local deployment.
- Private/loopback IPs are blocked on `/api/lookup` to prevent SSRF.
- Error messages are sanitized before returning to clients — API keys and stack traces are never leaked.

## Requirements

See [`requirements.txt`](requirements.txt). Key dependencies:

- `flask`, `flask-cors`, `flask-limiter`
- `google-genai` — Gemini TTS
- `pdfplumber`, `PyPDF2` — PDF analysis
- `dnspython`, `python-whois`, `phonenumbers` — OSINT lookups
- `torch` — voice model training
- `python-dotenv`

All heavy dependencies degrade gracefully — the server boots even if optional packages are missing.

## Project Structure

```
voice-ai-tools/
├── flask_server.py               # Main Flask backend
├── tts_engine.py                 # Gemini TTS synthesis
├── voice_training.py             # Voice model training
├── voice_visualizer_integration.py
├── voice_visualizer_standalone.py
├── voice_config.py               # Voice context routing
├── lookup_engine.py              # OSINT lookup engine
├── interactive_voice_visualizer.html
├── extension/                    # Chrome extension
├── requirements.txt
├── .env.example
└── pytest.ini
```

## License

Private repository — all rights reserved.
