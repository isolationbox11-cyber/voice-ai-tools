#!/usr/bin/env python3
"""
Voice AI Tools - Flask Backend
Endpoints: /health /tts /presets /log /shodan /analyze_pdf /train /model_status

Env vars:
  GOOGLE_API_KEY      - Gemini API key (for TTS)
  VOICE_SERVER_TOKEN  - shared secret (X-Token header)
  SHODAN_API_KEY      - Shodan API key (optional)
  ALLOWED_ORIGINS     - comma-separated extra CORS origins
  HOST / PORT         - bind address (default 127.0.0.1:5100)
"""

# trigger pr-screenshots workflow
import functools
import hmac
import io
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=4)
from typing import Any, Dict, Tuple

from dotenv import load_dotenv

from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# ── PDF analysis constants ─────────────────────────────────────────────
IP_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
)
URL_PATTERN = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+', re.I)
SUSPICIOUS_KEYWORDS = [
    "eval(",
    "javascript:",
    "/launch",
    "/aa",
    "/openaction",
    "cmd.exe",
    "powershell",
]

# ── optional heavy deps ───────────────────────────────────────────────
try:
    import requests as _requests
except ImportError:
    _requests = None

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from tts_engine import synthesize_speech
    from voice_config import get_voice_for_context
except ImportError:
    synthesize_speech = None
    get_voice_for_context = None

# ── config ────────────────────────────────────────────────────────────
VOICE_SERVER_TOKEN = os.environ.get("VOICE_SERVER_TOKEN", "")

SHODAN_API_KEY = os.environ.get("SHODAN_API_KEY", "")
MAX_TEXT_LENGTH = 2000
DB_PATH = Path("app.db")
SAMPLES_DIR = Path("voice_samples")

# ── Shodan security ─────────────────────────────────────────────────────
# Compiled regex for valid IPv4 dotted-quad or bare IPv6 address
_IP_RE = re.compile(
    r"^(?:"
    r"(?:\d{1,3}\.){3}\d{1,3}"  # IPv4
    r"|"
    r"[0-9a-fA-F:]+:[0-9a-fA-F:]+"  # IPv6
    r")$"
)

# Compiled regex to block RFC-1918 private ranges, loopback, and IPv6 ULA
_PRIVATE_IP_RE = re.compile(
    r"^(?:"
    r"10\.|"  # 10.0.0.0/8
    r"172\.(?:1[6-9]|2[0-9]|3[0-1])\.|"  # 172.16.0.0/12
    r"192\.168\.|"  # 192.168.0.0/16
    r"127\.|"  # Loopback
    r"::1$|"  # IPv6 loopback
    r"fc00:"  # IPv6 ULA fc00::/7
    r")"
)

# Field specification for Shodan response validation
SHODAN_FIELD_SPEC = {
    "ip_str": (str, 256),
    "ports": (list, 100),
    "org": (str, 512),
    "country_name": (str, 512),
    "city": (str, 256),
    "region_code": (str, 16),
    "country_code": (str, 8),
    "asn": (str, 64),
    "isp": (str, 512),
    "hostnames": (list, 50),
    "vulns": (list, 100),
    "tags": (list, 50),
    "os": (str, 128),
    "latitude": (float, None),
    "longitude": (float, None),
}
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR = Path("voice_model")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

import sqlite3


def init_db():
    with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""CREATE TABLE IF NOT EXISTS presets (
                            name TEXT PRIMARY KEY,
                            data TEXT
                        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS logs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            timestamp TEXT,
                            data TEXT
                        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS manifest (
                            id INTEGER PRIMARY KEY CHECK (id = 1),
                            data TEXT
                        )""")
        conn.commit()


init_db()


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


_extra_origins = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]
ALLOWED_ORIGINS = [
    "chrome-extension://*",
    "http://localhost:*",
    "http://127.0.0.1:*",
] + _extra_origins

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB max upload
CORS(app, origins=ALLOWED_ORIGINS, allow_headers=["Content-Type", "X-Token"])
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per minute"])


# ── security headers ──────────────────────────────────────────────────
@app.after_request
def add_security_headers(response: Response) -> Response:
    """
    Add strict security headers to an HTTP response.

    Returns:
        response (Response): The same Response object with
            `X-Content-Type-Options`, `X-Frame-Options`, and
            `Strict-Transport-Security` headers applied.
    """
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    return response


# ── utilities ─────────────────────────────────────────────────────────
def _check_token() -> bool:
    """
    Validate the incoming request using the configured shared-secret token.

    If no server token is configured, authorization is not enforced and the function permits the request.

    Returns:
        bool: `True` if the request is authorized (or no server token is configured), `False` otherwise.
    """
    if not VOICE_SERVER_TOKEN:
        return True
    provided_token = request.headers.get("X-Token", "")
    return hmac.compare_digest(provided_token, VOICE_SERVER_TOKEN)


def _is_valid_ip(ip: str) -> bool:
    """
    Determine whether a string is a valid IPv4 or IPv6 address and not a private/internal IP.

    Returns:
        True if `ip` is a valid public IP address (not RFC-1918, loopback, or IPv6 ULA), False otherwise.
    """
    if not ip:
        return False

    # Check if it matches valid IP format (IPv4 or IPv6)
    if not _IP_RE.match(ip):
        return False

    # Block private/internal IP ranges to prevent SSRF
    if _PRIVATE_IP_RE.match(ip):
        return False

    return True


def _filter_shodan_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Filter and validate Shodan API response to enforce type and length constraints.

    Args:
        data: Raw Shodan API response dictionary

    Returns:
        Filtered dictionary with only allowed fields, type-coerced and length-limited
    """
    filtered = {}

    for field, (expected_type, max_length) in SHODAN_FIELD_SPEC.items():
        if field not in data:
            continue

        value = data[field]

        # Type coercion and validation
        try:
            if expected_type is str:
                if not isinstance(value, str):
                    value = str(value)
                # Apply length limit
                if max_length and len(value) > max_length:
                    value = value[:max_length]
                filtered[field] = value

            elif expected_type is list:
                if not isinstance(value, list):
                    continue
                # Filter list items to primitives only and apply size limit
                filtered_list = []
                for item in value[:max_length] if max_length else value:
                    if isinstance(item, (str, int, float, bool)):
                        filtered_list.append(item)
                filtered[field] = filtered_list

            elif expected_type is float:
                if isinstance(value, (int, float)):
                    filtered[field] = float(value)

        except (ValueError, TypeError):
            # Skip field if type coercion fails
            continue

    return filtered


def _analyze_text_content(text: str, raw_bytes: bytes) -> Dict[str, Any]:
    """
    Analyze text and raw bytes to extract IPv4 addresses, URLs, and detect suspicious keywords.

    Parameters:
        text (str): Extracted textual content to search for IPs and URLs using the module regex patterns.
        raw_bytes (bytes): Original raw bytes (e.g., PDF file bytes) decoded and checked for presence of configured suspicious keywords.

    Returns:
        result (Dict[str, Any]): Dictionary with keys:
            - "ips" (List[str]): Unique IPv4 addresses found in `text`.
            - "links" (List[str]): Unique URLs found in `text`.
            - "suspicious" (bool): `true` if any configured suspicious keyword appears in the decoded `raw_bytes`, `false` otherwise.
    """
    raw_lower = raw_bytes.lower().decode("latin-1", errors="ignore")
    return {
        "ips": list(set(IP_PATTERN.findall(text))),
        "links": list(set(URL_PATTERN.findall(text))),
        "suspicious": any(kw in raw_lower for kw in SUSPICIOUS_KEYWORDS),
    }


def _parse_with_pdfplumber(raw: bytes) -> Dict[str, Any]:
    """
    Extracts metadata, links, IP addresses, page count, and a suspicious-content flag from PDF data.

    Processes the provided PDF bytes and returns a dictionary with the following keys:
    - `metadata` (Dict[str, str]): PDF metadata entries converted to strings.
    - `links` (List[str]): unique URLs found from page hyperlinks and inline text.
    - `ips` (List[str]): unique IPv4 addresses detected in the document text.
    - `suspicious` (bool): `true` if any suspicious keywords appear in the raw content, `false` otherwise.
    - `pages` (int): number of pages in the PDF.

    Parameters:
        raw (bytes): Raw bytes of a PDF file.

    Returns:
        Dict[str, Any]: Analysis result containing metadata, links, ips, suspicious flag, and pages count.
    """
    result: Dict[str, Any] = {
        "metadata": {},
        "links": [],
        "ips": [],
        "suspicious": False,
        "pages": 0,
    }

    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        result["pages"] = len(pdf.pages)
        meta = pdf.metadata or {}
        result["metadata"] = {k: str(v) for k, v in meta.items() if v}
        full_text = "".join(page.extract_text() or "" for page in pdf.pages)
        for page in pdf.pages:
            for href in page.hyperlinks or []:
                if uri := href.get("uri", ""):
                    result["links"].append(uri)

        text_analysis = _analyze_text_content(full_text, raw)
        result["ips"] = text_analysis["ips"]
        extra_links = URL_PATTERN.findall(full_text)
        result["links"] = list(set(result["links"] + extra_links))
        result["suspicious"] = text_analysis["suspicious"]

    return result


def _parse_with_pypdf2(raw: bytes) -> Dict[str, Any]:
    """
    Extract metadata, detected links, IPv4 addresses, and a suspicious-content flag from PDF bytes using PyPDF2.

    Returns:
        result (Dict[str, Any]): Analysis dictionary with keys:
            - metadata (Dict[str, str]): PDF metadata fields mapped to their string values.
            - links (List[str]): Unique URLs found in the document text.
            - ips (List[str]): Unique IPv4 addresses found in the document text.
            - suspicious (bool): `true` if any configured suspicious keywords appear in the raw PDF bytes, `false` otherwise.
            - pages (int): Number of pages in the PDF.
    """
    result: Dict[str, Any] = {
        "metadata": {},
        "links": [],
        "ips": [],
        "suspicious": False,
        "pages": 0,
    }

    reader = PyPDF2.PdfReader(io.BytesIO(raw))
    result["pages"] = len(reader.pages)
    info = reader.metadata or {}
    result["metadata"] = {str(k).lstrip("/"): str(v) for k, v in info.items() if v}
    full_text = "".join(page.extract_text() or "" for page in reader.pages)

    text_analysis = _analyze_text_content(full_text, raw)
    result["ips"] = text_analysis["ips"]
    result["links"] = text_analysis["links"]
    result["suspicious"] = text_analysis["suspicious"]

    return result


def _parse_raw_text(raw: bytes) -> Dict[str, Any]:
    """
    Fallback PDF text extraction from raw bytes when no PDF parsing libraries are available.

    Parameters:
        raw (bytes): Raw file bytes (typically a PDF) to scan with simple text-based heuristics.

    Returns:
        dict: Analysis with keys:
            - metadata (dict): note advising installation of PDF libraries for full extraction.
            - ips (list[str]): unique IPv4-like substrings found in the raw text.
            - links (list[str]): unique URL-like substrings found in the raw text.
            - suspicious (bool): `True` if any configured suspicious keywords appear (case-insensitive), `False` otherwise.
            - pages (int): page count placeholder (always 0 for the fallback).
    """
    raw_lower = raw.lower().decode("latin-1", errors="ignore")
    raw_str = raw.decode("latin-1", errors="ignore")

    return {
        "metadata": {"note": "Install pdfplumber or PyPDF2 for full extraction"},
        "ips": list(set(IP_PATTERN.findall(raw_str))),
        "links": list(set(URL_PATTERN.findall(raw_str))),
        "suspicious": any(kw in raw_lower for kw in SUSPICIOUS_KEYWORDS),
        "pages": 0,
    }


def _extract_pdf_analysis(raw: bytes) -> Dict[str, Any]:
    """
    Analyze PDF bytes and return extracted metadata, links, IPs, page count, and suspicious-content flag.

    Attempts available PDF parsers in preferred order and falls back to a raw-text extraction when parser libraries are unavailable or fail. On unrecoverable parse errors the result may contain an `"error"` key describing the failure.

    Parameters:
        raw (bytes): Raw bytes of the uploaded PDF file.

    Returns:
        Dict[str, Any]: An analysis dictionary that includes, at minimum, the keys:
            - `ips`: list of extracted IPv4 addresses
            - `links`: list of extracted URLs
            - `suspicious`: boolean indicating presence of suspicious keywords
            - `pages`: integer page count (0 when only raw-text fallback was used)
          The dictionary may also contain `metadata`, `full_text`, or an `error` key when parsing failed.
    """
    # Try pdfplumber first
    if pdfplumber:
        try:
            return _parse_with_pdfplumber(raw)
        except Exception as e:
            logger.warning(f"pdfplumber analysis failed: {e}")

    # Fallback: PyPDF2
    if PyPDF2:
        try:
            return _parse_with_pypdf2(raw)
        except Exception as e:
            logger.warning(f"PyPDF2 analysis failed: {e}")
            return {"error": "Failed to parse PDF document"}

    # Raw fallback - no PDF lib installed
    return _parse_raw_text(raw)


def _read_json_safe(file_path: Path, default: Any) -> Any:
    """
    Read JSON from the given path and return a fallback on failure; the caller is responsible for any locking.

    Parameters:
        file_path (Path): Path to the JSON file to read.
        default (Any): Value to return if the file does not exist or cannot be read/parsed.

    Returns:
        Any: The parsed JSON content from the file, or `default` if the file is missing or an error occurs while reading/parsing.
    """
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read {file_path}: {e}")
    return default


def _locked_read_json(file_path: Path, lock: threading.Lock, default: Any) -> Any:
    """
    Read JSON from the given path while holding the provided lock.

    Parameters:
        file_path (Path): Path to the JSON file to read.
        lock (threading.Lock): Lock to acquire during the read to ensure thread safety.
        default (Any): Value to return if the file does not exist or cannot be read/parsed.

    Returns:
        Any: The parsed JSON content from `file_path`, or `default` if reading or parsing fails.
    """
    with lock:
        return _read_json_safe(file_path, default)


def _atomic_write_json(file_path: Path, data: Any) -> None:
    """
    Atomically write JSON-serializable `data` to `file_path`.

    Writes `data` to a temporary file, ensures on-disk flush, and atomically replaces the target file so the destination is never left in a partially written state if an error occurs.

    Parameters:
        file_path (Path): Destination path for the JSON file.
        data (Any): JSON-serializable object to write.
    """
    tmp_path = file_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            # Force OS to write buffers to physical disk
            os.fsync(f.fileno())
        # os.replace is an atomic operation on POSIX systems
        os.replace(tmp_path, file_path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {tmp_path}: {e}")
        raise


@functools.lru_cache(maxsize=256)
def _cached_shodan_lookup(ip: str, api_key: str) -> Tuple[Dict[str, Any], int]:
    """
    Perform a Shodan host lookup and return the response payload together with an HTTP-like status code.

    Returns:
        (dict, int): A tuple where the first element is either the parsed JSON response from the Shodan API
        or an error dictionary (e.g., {"error": "..."}), and the second element is an HTTP-like status code:
        200 on successful JSON response, 503 if the `requests` library is not available, 500 for internal
        communication or JSON-parsing errors, or the Shodan API's non-200 status code on failure.
    """
    if _requests is None:
        return {"error": "requests library not installed"}, 503
    try:
        r = _requests.get(
            f"https://api.shodan.io/shodan/host/{ip}",
            params={"key": api_key},
            timeout=(5, 10),  # 5s connect, 10s read timeout
        )
        if r.status_code != 200:
            logger.error(f"Shodan API returned status {r.status_code}")
            return {"error": "Shodan lookup failed"}, 502
        try:
            data = r.json()
            # Filter and validate response to enforce type/length constraints
            filtered_data = _filter_shodan_response(data)
            return filtered_data, 200
        except ValueError:
            logger.error("Shodan API returned invalid JSON")
            return {"error": "Shodan lookup failed"}, 500
    except Exception:
        logger.exception("Shodan lookup error")
        return {"error": "Shodan lookup failed"}, 500


def _clear_shodan_cache() -> None:
    """Clear the Shodan lookup cache. Call this if API key changes."""
    _cached_shodan_lookup.cache_clear()
    logger.info("Shodan lookup cache cleared")


# ── / (root) ─────────────────────────────────────────────────────────────
@app.route("/")
def index() -> Response:
    """
    Provide a JSON overview of the service and its available endpoints.

    Returns:
        Response: A Flask Response containing a JSON object with the service status, name, and a mapping of endpoint descriptions.
    """
    return jsonify(
        {
            "status": "ok",
            "service": "Voice AI Tools Flask Backend",
            "endpoints": {
                "health": "GET /health - Check server status",
                "tts": "POST /tts - Text-to-speech synthesis",
                "presets": "GET/POST /presets - Voice presets management",
                "log": "GET/POST /log - Activity logging",
                "shodan": "GET /shodan - IP intelligence lookup",
                "analyze_pdf": "POST /analyze_pdf - PDF analysis",
                "train": "POST /train - Voice training",
                "model_status": "GET /model_status - Voice model status",
            },
        }
    )


# ── /health ───────────────────────────────────────────────────────────
@app.route("/health")
def health() -> Response:
    """
    Report overall service health and the current voice model status.

    Returns:
        A JSON response containing:
          - `status` (str): `"ok"` when the service is healthy.
          - `model` (dict): The model status object returned by `_model_status()`.
    """
    return jsonify({"status": "ok", "model": _model_status()})


# ── /tts ──────────────────────────────────────────────────────────────
@app.route("/tts", methods=["POST"])
@limiter.limit("30 per minute")
def tts() -> Response | Tuple[Response, int]:
    """
    Synthesize speech from provided text and return the resulting audio response.

    Accepts a JSON body with the following optional keys:
    - `text` (string, required): The text to synthesize.
    - `voice_id` (string, optional): Voice identifier to use; the special value `"cloned"` maps to the default cloned voice.
    - `speed` (string, optional): One of `"fast"`, `"slow"`, or other; maps to a speaking rate.

    Behavior and error responses:
    - Requires a valid `X-Token` when the service is configured with `VOICE_SERVER_TOKEN`; otherwise responds 401.
    - Returns 400 if `text` is missing/empty or if `text` exceeds the maximum allowed length.
    - Returns 503 if the TTS engine is not available.
    - Returns 500 with an error message if the TTS engine reports an error or an internal exception occurs.

    Returns:
    - On success: a Response whose body is the raw audio bytes with an appropriate MIME type (e.g., `audio/wav` or `audio/mpeg`).
    - On failure: a JSON error object and the corresponding HTTP status code (400, 401, 500, or 503).
    """
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()

    if not text:
        return jsonify({"error": "No text provided"}), 400
    if len(text) > MAX_TEXT_LENGTH:
        return jsonify({"error": "Text too long"}), 400
    if synthesize_speech is None:
        return jsonify({"error": "TTS engine not available"}), 503

    try:
        voice_context = get_voice_for_context(data) if get_voice_for_context else {}
        voice_settings: Dict[str, Any] = {"voice_id": "Kore"}

        if voice_context:
            voice_settings |= voice_context

        if data.get("voice_id"):
            requested_voice = data.get("voice_id")
            if requested_voice == "cloned":
                voice_settings["voice_id"] = "cloned"
                # Fetch cloned voice metadata from the database manifest
                try:
                    conn = get_db_connection()
                    row = conn.execute(
                        "SELECT data FROM manifest WHERE id = 1"
                    ).fetchone()
                    conn.close()
                    if row:
                        manifest_data = json.loads(row["data"])
                        # voice_id contains the JSON string returned by train_from_samples
                        if manifest_data.get(
                            "status"
                        ) == "trained" and manifest_data.get("voice_id"):
                            ref_data = json.loads(manifest_data["voice_id"])
                            voice_settings["ref_audio"] = ref_data.get("ref_audio")
                            voice_settings["ref_text"] = ref_data.get("ref_text")
                except Exception as e:
                    logger.warning(f"Failed to load cloned voice metadata: {e}")
            else:
                voice_settings["voice_id"] = requested_voice

        if data.get("speed"):
            if data.get("speed") == "fast":
                voice_settings["speaking_rate"] = 1.5
            elif data.get("speed") == "slow":
                voice_settings["speaking_rate"] = 0.8
            else:
                voice_settings["speaking_rate"] = 1.0

        audio_bytes, mime_type, error_msg, _ = synthesize_speech(text, voice_settings)
        if error_msg:
            return jsonify({"error": error_msg}), 500

        return Response(audio_bytes, mimetype=mime_type)

    except Exception as e:
        logger.error(f"TTS endpoint error: {e}")
        return jsonify({"error": "Internal server error"}), 500


# ── /presets ──────────────────────────────────────────────────────────
@app.route("/presets", methods=["GET", "POST"])
@limiter.limit("60 per minute")
def presets() -> Response | Tuple[Response, int]:
    """
    Handle retrieval and creation or update of saved voice presets.

    GET returns the stored presets. POST expects a JSON object containing a "name" field (and any other preset fields); it creates a new preset or replaces an existing preset with the same name and persists the updated presets to disk.

    Returns:
    - On GET: a JSON object with a "presets" list.
    - On successful POST: a JSON object `{"ok": True}`.
    - On error: a JSON object with an "error" message and one of the HTTP status codes 400 (bad request), 401 (unauthorized), or 500 (server error).
    """
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    if request.method == "GET":
        rows = conn.execute("SELECT data FROM presets").fetchall()
        presets_list = [json.loads(row["data"]) for row in rows]
        conn.close()
        return jsonify({"presets": presets_list})

    data = request.get_json(silent=True)
    if not data or not data.get("name"):
        conn.close()
        return jsonify({"error": "Preset needs a name"}), 400

    try:
        conn.execute(
            "INSERT INTO presets (name, data) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET data=excluded.data",
            (data["name"], json.dumps(data)),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Failed to save preset: {e}")
        conn.close()
        return jsonify({"error": "Failed to save preset"}), 500


# ── /log ──────────────────────────────────────────────────────────────
@app.route("/log", methods=["GET", "POST"])
@limiter.limit("120 per minute")
def log_endpoint() -> Response | Tuple[Response, int]:
    """
    Handle retrieval and submission of session log entries.

    GET returns the stored log JSON object (contains an "entries" list).
    POST accepts a JSON log entry from the request body; if the entry's "action" is "clear" the log is emptied, otherwise a timestamp is added if missing, the entry is prepended to the entries list, the list is truncated to at most 500 items, and the updated log is written atomically.

    Returns:
    - For GET: the stored log object (dict with "entries" list).
    - For POST: `{"ok": True}` on successful save, `{"error": "Failed to save log"}` with HTTP 500 on write failure, or `{"error": "Unauthorized"}` with HTTP 401 when authentication fails.
    """
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    if request.method == "GET":
        rows = conn.execute(
            "SELECT data FROM logs ORDER BY id DESC LIMIT 500"
        ).fetchall()
        entries = [json.loads(row["data"]) for row in rows]
        conn.close()
        return jsonify({"entries": entries})

    entry = request.get_json(silent=True) or {}

    try:
        if entry.get("action") == "clear":
            conn.execute("DELETE FROM logs")
        else:
            entry["timestamp"] = entry.get(
                "timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ")
            )
            conn.execute(
                "INSERT INTO logs (timestamp, data) VALUES (?, ?)",
                (entry["timestamp"], json.dumps(entry)),
            )
            # Keep only last 500
            conn.execute(
                "DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 500)"
            )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Failed to save log: {e}")
        conn.close()
        return jsonify({"error": "Failed to save log"}), 500


# ── /shodan ───────────────────────────────────────────────────────────
@app.route("/shodan")
@limiter.limit("10 per minute")
def shodan() -> Response | Tuple[Response, int]:
    """
    Handle a Shodan host lookup for the IPv4 address provided in the request query.

    Expects an `ip` query parameter containing an IPv4 address. Enforces the service token via the `X-Token` header, validates the IP format, and requires the server to be configured with `SHODAN_API_KEY`. Returns appropriate JSON error responses for authorization failure (401), missing/invalid `ip` (400), or missing API key (503).

    Returns:
        A Flask `Response` with JSON. On success returns the Shodan host data and the HTTP status code returned by the Shodan lookup; on error returns a JSON object with an `error` message and the corresponding HTTP status (401, 400, or 503).
    """
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    ip = request.args.get("ip", "").strip()
    if not ip:
        return jsonify({"error": "ip param required"}), 400
    if not _is_valid_ip(ip):
        return jsonify({"error": "Invalid IP address format"}), 400
    if not SHODAN_API_KEY:
        return jsonify({"error": "SHODAN_API_KEY not set on server"}), 503

    data, status_code = _cached_shodan_lookup(ip, SHODAN_API_KEY)
    return jsonify(data), status_code


# ── /analyze_pdf ──────────────────────────────────────────────────────
@app.route("/analyze_pdf", methods=["POST"])
@limiter.limit("10 per minute")
def analyze_pdf() -> Response | Tuple[Response, int]:
    """
    Analyze an uploaded PDF and return extracted metadata, text links, IP addresses, page count, and a suspicious-content flag.

    Accepts a multipart file upload under the form key "file". Performs request authorization and validates that the uploaded file is a PDF. On success returns a JSON object with keys such as `metadata`, `pages`, `links`, `ips`, and `suspicious`. If the parser fails the response contains an `error` field.

    Returns:
        A Flask `Response` containing JSON:
          - On success: analysis object with `metadata`, `pages`, `links`, `ips`, `suspicious`, etc.
          - If parsing failed: object with an `error` key and HTTP status 500.
          - For validation/auth failures: an error object and an appropriate 4xx status (e.g., 400 for missing/invalid file, 401 for unauthorized).
    """
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]

    if not f or not f.filename:
        return jsonify({"error": "Invalid file upload"}), 400

    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Uploaded file must be a PDF"}), 400

    raw = f.read()
    result = _extract_pdf_analysis(raw)

    return (jsonify(result), 500) if "error" in result else jsonify(result)


# ── /train ────────────────────────────────────────────────────────────
@app.route("/train", methods=["POST"])
@limiter.limit("5 per minute")
def train() -> Response | Tuple[Response, int]:
    """
    Handle uploaded WAV files: save valid .wav uploads to the samples directory, write an initial manifest, attempt to train a voice model from the saved samples (if training code is available), update the manifest with training results, and return a summary.

    Returns:
        JSON response containing:
          - ok (bool): true on successful processing.
          - saved (list[str]): filenames that were saved to the samples directory.
          - samples (list[str]): same as `saved`.
          - sample_dir (str): filesystem path where samples were stored.
          - trained_at (str): UTC timestamp when samples were recorded in the manifest.
          - count (int): number of saved samples.
          - status (str, optional): one of `"samples_saved"`, `"trained"`, or `"training_failed"`.
          - voice_id (str, optional): identifier returned by the training step when status is `"trained"`.
          - note (str, optional): explanatory note when training was not attempted.
          - error (str, optional): error message when training failed.

    Possible HTTP responses:
        - 200 OK: processing succeeded and a JSON body with manifest and `ok: True` is returned.
        - 400 Bad Request: no files uploaded or no valid `.wav` files were saved.
        - 401 Unauthorized: request lacked a valid `X-Token`.
        - 500 Internal Server Error: failed to write the initial manifest to disk.
    """
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No audio files uploaded"}), 400

    saved = []
    import subprocess
    from pathlib import Path

    for f in files:
        if not f or not f.filename:
            continue

        fname = f.filename
        if not fname.lower().endswith((".wav", ".webm")):
            continue

        safe_fname = (
            secure_filename(fname)
            or f"clip_{int(time.time())}_{len(saved)}{Path(fname).suffix}"
        )

        dest = SAMPLES_DIR / safe_fname

        try:
            f.save(dest)

            if dest.suffix.lower() == ".webm":
                wav_dest = dest.with_suffix(".wav")
                try:
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(dest),
                            "-ar",
                            "44100",
                            "-ac",
                            "1",
                            str(wav_dest),
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    dest.unlink()
                    dest = wav_dest
                    safe_fname = dest.name
                except Exception as e:
                    logger.error(f"Failed to convert {fname} to wav: {e}")
                    continue

            saved.append(safe_fname)
        except Exception as e:
            logger.warning(f"Failed to save file {fname}: {e}")

    if not saved:
        return jsonify({"error": "No valid audio files were saved"}), 400

    manifest = {
        "samples": saved,
        "sample_dir": str(SAMPLES_DIR),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(saved),
    }

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO manifest (id, data) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (json.dumps(manifest),),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to save manifest: {e}")
        conn.close()
        return jsonify({"error": "Failed to save manifest"}), 500

    try:
        from voice_training import train_from_samples

        voice_id = train_from_samples([str(SAMPLES_DIR / s) for s in saved])
        manifest["status"] = "trained"
        manifest["voice_id"] = voice_id
    except ImportError:
        manifest["status"] = "samples_saved"
        manifest["note"] = "voice_training.py not installed — samples saved only"
    except Exception as e:
        manifest["status"] = "training_failed"
        manifest["error"] = str(e)

    try:
        conn.execute(
            "INSERT INTO manifest (id, data) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (json.dumps(manifest),),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to update manifest after training: {e}")
    conn.close()

    return jsonify({"ok": True, "saved": saved, **manifest})


# ── /model_status ─────────────────────────────────────────────────────
@app.route("/model_status")
def model_status() -> Response | Tuple[Response, int]:
    """
    Return the current voice model training status as a JSON response.

    Returns:
        response (Response | Tuple[Response, int]): On success, a JSON object with:
            - `trained` (bool): True if a model manifest indicates training has occurred.
            - `count` (int, optional): Number of training samples recorded.
            - `trained_at` (str, optional): UTC timestamp when samples were recorded (format YYYY-MM-DDTHH:MM:SSZ).
            - `status` (str, optional): Manifest status such as "trained", "samples_saved", or "training_failed".
            - `voice_id` (str, optional): Identifier of the trained voice when available.
            - `error` (str, optional): Error message when training failed.
        If the request is unauthorized, returns a JSON error and HTTP status 401.
    """
    if not _check_token():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(_model_status())


def _model_status() -> Dict[str, Any]:
    """
    Return the current voice model status based on the model manifest file.

    Reads the manifest at MODEL_DIR / "manifest.json" (using the module's locked reader) and returns a dictionary describing whether a model is trained and related metadata.

    Returns:
        status (dict): If a manifest exists, a dict with keys:
            - "trained" (bool): True.
            - "count" (int): Number of samples recorded in the manifest (defaults to 0).
            - "trained_at" (str): Timestamp when training was run (or "unknown").
            - "status" (str): Manifest's status field (or "unknown").
            - "voice_id" (Optional[str]): Trained voice identifier, if present.
            - "error" (Optional[str]): Error message from training, if present.
          If no manifest exists, returns {"trained": False}.
    """
    conn = get_db_connection()
    row = conn.execute("SELECT data FROM manifest WHERE id = 1").fetchone()
    conn.close()

    if row:
        manifest = json.loads(row["data"])
        return {
            "trained": True,
            "count": manifest.get("count", 0),
            "trained_at": manifest.get("trained_at", "unknown"),
            "status": manifest.get("status", "unknown"),
            "voice_id": manifest.get("voice_id"),
            "error": manifest.get("error"),
        }
    return {"trained": False}


# ── run ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5100))
    app.run(host=host, port=port, debug=False)
