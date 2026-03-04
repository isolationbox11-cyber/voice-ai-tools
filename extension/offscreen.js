/* offscreen.js – runs in the hidden offscreen document for audio playback */

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "PLAY_AUDIO_OFFSCREEN" && message.audioUrl) {
    const audio = new Audio(message.audioUrl);
    audio.play().catch((err) => {
      console.error("Offscreen audio playback failed:", err);
    });
  }
});
