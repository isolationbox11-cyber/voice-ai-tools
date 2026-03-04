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
  if (message.type === "PLAY_AUDIO") {
    ensureOffscreenDocument()
      .then(() => {
        chrome.runtime.sendMessage({
          type: "PLAY_AUDIO_OFFSCREEN",
          audioUrl: message.audioUrl,
        });
        sendResponse({ ok: true });
      })
      .catch((err) => {
        sendResponse({ ok: false, error: err.message });
      });
    return true; // keep channel open for async sendResponse
  }
});
