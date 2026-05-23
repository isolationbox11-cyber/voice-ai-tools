/* offscreen.js – runs in the hidden offscreen document for audio playback */

let currentAudio = null;
let currentBlobUrl = null;

function _cleanup() {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.src = '';
    currentAudio = null;
  }
  if (currentBlobUrl) {
    URL.revokeObjectURL(currentBlobUrl);
    currentBlobUrl = null;
  }
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "PLAY_AUDIO_OFFSCREEN" && message.audioData) {
    _cleanup();
    const mimeType = message.mimeType || "audio/wav";
    const blob = new Blob([message.audioData], { type: mimeType });
    currentBlobUrl = URL.createObjectURL(blob);

    currentAudio = new Audio(currentBlobUrl);
    currentAudio.onended = () => {
      _cleanup();
      chrome.runtime.sendMessage({ type: "AUDIO_PLAYBACK_COMPLETE" });
    };
    currentAudio.play().catch((err) => {
      _cleanup();
      console.error("Offscreen audio playback failed:", err);
      chrome.runtime.sendMessage({ type: "AUDIO_PLAYBACK_ERROR", error: err.message });
    });
  }
});
