/* offscreen.js – runs in the hidden offscreen document for audio playback */

let currentAudio = null;
let currentBlobUrl = null;

function _cleanup() {
  if (currentAudio) {
    currentAudio.onended = null;
    currentAudio.onerror = null;
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

    // ── MIME support check ──────────────────────────────────────────────────
    const probe = document.createElement('audio');
    const support = probe.canPlayType(mimeType);
    if (!support || support === '') {
      const errMsg = `Browser cannot play type '${mimeType}' (canPlayType returned '${support}').
  Supported types: audio/mpeg, audio/wav, audio/ogg, audio/webm, audio/mp4`;
      console.error(errMsg);
      chrome.runtime.sendMessage({ type: "AUDIO_PLAYBACK_ERROR", error: errMsg });
      return;
    }
    console.log(`canPlayType('${mimeType}') → '${support}'`);

    try {
      const uint8Array = new Uint8Array(message.audioData);
      const blob = new Blob([uint8Array], { type: mimeType });
      const blobUrl = URL.createObjectURL(blob);
      currentBlobUrl = blobUrl;
      console.log("Created blob URL:", blobUrl, "blob size:", uint8Array.length);

      const audio = new Audio();
      currentAudio = audio;

      audio.onended = () => {
        _cleanup();
        chrome.runtime.sendMessage({ type: "AUDIO_PLAYBACK_COMPLETE" });
      };

      // FIX: read audio.error into a local var BEFORE calling _cleanup(),
      // which nulls currentAudio – otherwise we get
      // "Cannot read properties of null (reading 'error')".
      audio.onerror = () => {
        const mediaErr = audio.error;
        const code = mediaErr ? mediaErr.code : -1;
        const msg  = mediaErr ? mediaErr.message : "Unknown MediaError";
        const codeMap = {
          1: "MEDIA_ERR_ABORTED",
          2: "MEDIA_ERR_NETWORK",
          3: "MEDIA_ERR_DECODE",
          4: "MEDIA_ERR_SRC_NOT_SUPPORTED",
        };
        const readable = `${codeMap[code] || "UNKNOWN"} (code ${code}): ${msg}`;
        console.error("Audio element error:", readable, "| mime:", mimeType, "| blobSize:", uint8Array.length);
        _cleanup();
        chrome.runtime.sendMessage({ type: "AUDIO_PLAYBACK_ERROR", error: readable });
      };

      // Set src AFTER attaching handlers to avoid firing error before onerror is wired.
      audio.src = blobUrl;
      audio.load(); // explicitly trigger decode before play()

      audio.play().catch((err) => {
        console.error("Offscreen audio playback failed:", err.name, err.message);
        _cleanup();
        chrome.runtime.sendMessage({
          type: "AUDIO_PLAYBACK_ERROR",
          error: `${err.name}: ${err.message}`,
        });
      });

    } catch (e) {
      console.error("Failed to create audio blob:", e);
      _cleanup();
      chrome.runtime.sendMessage({ type: "AUDIO_PLAYBACK_ERROR", error: "Blob creation failed: " + e.message });
    }
  }
});
