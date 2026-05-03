/* popup.js – runs inside popup.html */

const SCAM_TEXT = "Warning: This call appears to be fraudulent. Authorities will be notified.";
const LEGIT_TEXT = "Thank you for calling. How can I assist you today?";

const DEFAULT_SERVER_URL = "http://127.0.0.1:5000";

let serverUrl = DEFAULT_SERVER_URL;
let token = "";

// ---------------------------------------------------------------------------
// Load/save settings
// ---------------------------------------------------------------------------
function loadSettings() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["serverUrl", "token"], (result) => {
      serverUrl = result.serverUrl || DEFAULT_SERVER_URL;
      token = result.token || "";
      document.getElementById("setting-url").value = serverUrl;
      document.getElementById("setting-token").value = token;
      resolve();
    });
  });
}

function saveSettings() {
  serverUrl = document.getElementById("setting-url").value.trim() || DEFAULT_SERVER_URL;
  token = document.getElementById("setting-token").value.trim();
  chrome.storage.local.set({ serverUrl, token }, () => {
    setStatus("✅ Settings saved.");
  });
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------
function setStatus(msg) {
  document.getElementById("status").textContent = msg;
}

function setButtonsEnabled(enabled) {
  ["btn-speak", "btn-scam", "btn-legit"].forEach((id) => {
    document.getElementById(id).disabled = !enabled;
  });
}

// ---------------------------------------------------------------------------
// TTS request + playback
// ---------------------------------------------------------------------------
async function speak(text, callType) {
  if (!text.trim()) {
    setStatus("⚠️ Please enter text first.");
    return;
  }

  setStatus("⏳ Synthesizing…");
  setButtonsEnabled(false);

  try {
    const headers = { "Content-Type": "application/json" };
    if (token) {
      headers["X-Voice-Token"] = token;
    }

    const response = await fetch(`${serverUrl}/tts`, {
      method: "POST",
      headers,
      body: JSON.stringify({ text, call_type: callType }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ error: response.statusText }));
      setStatus(`❌ Error: ${err.error || response.statusText}`);
      return;
    }

    const audioBlob = await response.blob();
    const audioUrl = URL.createObjectURL(audioBlob);

    // Send the blob URL to the background service worker to play via offscreen API
    chrome.runtime.sendMessage({ type: "PLAY_AUDIO", audioUrl }, (reply) => {
      if (chrome.runtime.lastError) {
        // Fallback: play directly in popup context
        const audio = new Audio(audioUrl);
        audio.addEventListener("ended", () => URL.revokeObjectURL(audioUrl));
        audio.addEventListener("error", () => URL.revokeObjectURL(audioUrl));
        audio.play().catch((e) => {
          URL.revokeObjectURL(audioUrl);
          setStatus(`❌ Playback error: ${e.message}`);
        });
      }
    });

    setStatus("🔊 Playing…");
  } catch (err) {
    setStatus(`❌ ${err.message}`);
  } finally {
    setButtonsEnabled(true);
  }
}

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  await loadSettings();

  document.getElementById("btn-speak").addEventListener("click", () => {
    const text = document.getElementById("text-input").value;
    const callType = document.getElementById("call-type").value;
    speak(text, callType);
  });

  document.getElementById("btn-scam").addEventListener("click", () => {
    document.getElementById("text-input").value = SCAM_TEXT;
    document.getElementById("call-type").value = "SCAM_DETECTED";
    speak(SCAM_TEXT, "SCAM_DETECTED");
  });

  document.getElementById("btn-legit").addEventListener("click", () => {
    document.getElementById("text-input").value = LEGIT_TEXT;
    document.getElementById("call-type").value = "LEGITIMATE";
    speak(LEGIT_TEXT, "LEGITIMATE");
  });

  document.getElementById("btn-settings").addEventListener("click", () => {
    const panel = document.getElementById("settings-panel");
    panel.classList.toggle("open");
  });

  document.getElementById("btn-save-settings").addEventListener("click", saveSettings);
});
