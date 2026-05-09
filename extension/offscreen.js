/* offscreen.js – runs in the hidden offscreen document for audio playback */

// Track any currently playing Audio instance so we can stop it before starting
// a new one (prevents overlapping playback and resource leaks).
let _currentAudio = null;
let _currentBlobUrl = null;

function _cleanup() {
  if (_currentAudio) {
    _currentAudio.pause();
    _currentAudio.src = "";
    _currentAudio = null;
  }
  if (_currentBlobUrl) {
    URL.revokeObjectURL(_currentBlobUrl);
    _currentBlobUrl = null;
  }
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "PLAY_AUDIO_OFFSCREEN" && message.audioData) {
    // Stop any existing playback and free its resources first.
    _cleanup();

    const blob = new Blob([message.audioData], { type: "audio/wav" });
    const blobUrl = URL.createObjectURL(blob);
    _currentBlobUrl = blobUrl;

    const audio = new Audio(blobUrl);
    _currentAudio = audio;

    const revoke = () => {
      // Only revoke if this is still the active blob URL.
      if (_currentBlobUrl === blobUrl) {
        _cleanup();
      }
    };

    audio.addEventListener("ended", revoke, { once: true });
    audio.addEventListener("error", (err) => {
      console.error("Offscreen audio playback failed:", err);
      revoke();
    }, { once: true });

    audio.play().catch((err) => {
      console.error("Offscreen audio play() rejected:", err);
      revoke();
    });
  }
});
