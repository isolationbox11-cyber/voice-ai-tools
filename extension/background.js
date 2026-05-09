/* background.js – Manifest V3 service worker */

const OFFSCREEN_URL = chrome.runtime.getURL("offscreen.html");

async function ensureOffscreenDocument() {
  const existing = await chrome.offscreen.hasDocument();
  if (!existing) {
    await chrome.offscreen.createDocument({
      url: OFFSCREEN_URL,
      reasons: [chrome.offscreen.Reason.AUDIO_PLAYBACK],
      justification: "Play TTS audio received from Flask server",
    });
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "TTS_REQUEST") {
    // Fetch audio in the background so playback survives popup closure.
    const { text, token, serverUrl, callType, speed } = message;
    const url = (serverUrl || "http://127.0.0.1:5000") + "/tts";

    ensureOffscreenDocument()
      .then(() =>
        fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Token": token || "",
          },
          body: JSON.stringify({ text, call_type: callType, speed: speed || "normal" }),
        })
      )
      .then((resp) => {
        if (!resp.ok) {
          return resp.json().then((j) => {
            throw new Error(j.error || `HTTP ${resp.status}`);
          });
        }
        return resp.arrayBuffer();
      })
      .then((audioData) => {
        // Forward raw bytes to offscreen – blob URL is created there so it
        // outlives the popup document that initiated the request.
        chrome.runtime.sendMessage({
          type: "PLAY_AUDIO_OFFSCREEN",
          audioData,
        });
        sendResponse({ ok: true });
      })
      .catch((err) => {
        sendResponse({ ok: false, error: err.message });
      });

    return true; // keep channel open for async sendResponse
  }
});
