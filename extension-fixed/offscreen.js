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
    console.log("Received audio data, size:", message.audioData.byteLength, "mime:", mimeType);

    try {
      // Convert ArrayBuffer to Uint8Array for better Blob compatibility
      const uint8Array = new Uint8Array(message.audioData);
      const blob = new Blob([uint8Array], { type: mimeType });
      currentBlobUrl = URL.createObjectURL(blob);
      console.log("Created blob URL:", currentBlobUrl, "size:", uint8Array.length);

      currentAudio = new Audio(currentBlobUrl);
      currentAudio.onended = () => {
        _cleanup();
        chrome.runtime.sendMessage({ type: "AUDIO_PLAYBACK_COMPLETE" });
      };
      currentAudio.onerror = (err) => {
        console.error("Audio element error:", currentAudio.error);
        _cleanup();
        chrome.runtime.sendMessage({ type: "AUDIO_PLAYBACK_ERROR", error: currentAudio.error ? currentAudio.error.message : "Unknown audio error" });
      };
      currentAudio.play().catch((err) => {
        console.error("Offscreen audio playback failed:", err.name, err.message);
        _cleanup();
        chrome.runtime.sendMessage({ type: "AUDIO_PLAYBACK_ERROR", error: err.name + ": " + err.message });
      });
    } catch (e) {
      console.error("Failed to create audio blob:", e);
      chrome.runtime.sendMessage({ type: "AUDIO_PLAYBACK_ERROR", error: "Blob creation failed: " + e.message });
    }
  }
});
