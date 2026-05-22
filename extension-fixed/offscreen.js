/* offscreen.js – runs in the hidden offscreen document for audio playback */

let currentAudio = null;
let currentBlobUrl = null;

function _cleanup() {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.onerror = null;
    currentAudio.onended = null;
    currentAudio.onloadedmetadata = null;
    currentAudio.oncanplay = null;
    currentAudio.src = '';
    currentAudio.load();
    currentAudio = null;
  }
  if (currentBlobUrl) {
    URL.revokeObjectURL(currentBlobUrl);
    currentBlobUrl = null;
  }
}

function sniffAudioFormat(bytes) {
  if (!bytes || bytes.length < 12) return { mimeType: "application/octet-stream", label: "unknown" };

  // WAV: RIFF....WAVE
  if (
    bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 &&
    bytes[8] === 0x57 && bytes[9] === 0x41 && bytes[10] === 0x56 && bytes[11] === 0x45
  ) return { mimeType: "audio/wav", label: "wav" };

  // MP3 with ID3 header
  if (bytes[0] === 0x49 && bytes[1] === 0x44 && bytes[2] === 0x33) {
    return { mimeType: "audio/mpeg", label: "mp3-id3" };
  }

  // MP3 frame sync
  if (bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0) {
    return { mimeType: "audio/mpeg", label: "mp3-frame" };
  }

  // Ogg
  if (
    bytes[0] === 0x4f && bytes[1] === 0x67 && bytes[2] === 0x67 && bytes[3] === 0x53
  ) return { mimeType: "audio/ogg", label: "ogg" };

  // WebM
  if (
    bytes[0] === 0x1a && bytes[1] === 0x45 && bytes[2] === 0xdf && bytes[3] === 0xa3
  ) return { mimeType: "audio/webm", label: "webm" };

  // MP4/M4A
  if (
    bytes[4] === 0x66 && bytes[5] === 0x74 && bytes[6] === 0x79 && bytes[7] === 0x70
  ) return { mimeType: "audio/mp4", label: "mp4/m4a" };

  return { mimeType: "application/octet-stream", label: "unknown" };
}

function firstBytesHex(bytes, count = 16) {
  return Array.from(bytes.slice(0, count))
    .map(b => b.toString(16).padStart(2, "0"))
    .join(" ");
}

function buildErrorDetails(audio, mimeType, sniffed, size) {
  const err = audio?.error || null;
  return {
    mediaErrorCode: err?.code ?? null,
    mediaErrorMessage: err?.message || "",
    mimeType,
    sniffedMimeType: sniffed?.mimeType || "",
    sniffedLabel: sniffed?.label || "",
    currentSrc: audio?.currentSrc || currentBlobUrl || "",
    networkState: audio?.networkState ?? null,
    readyState: audio?.readyState ?? null,
    size
  };
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type !== "PLAY_AUDIO_OFFSCREEN") return;

  _cleanup();

  try {
    const bytes = new Uint8Array(message.audioBytes || message.audioData || []);
    const sniffed = sniffAudioFormat(bytes);
    const mimeType = message.mimeType || sniffed.mimeType;
    const testAudio = document.createElement("audio");
    const support = testAudio.canPlayType(mimeType);

    console.log("Offscreen audio received", {
      declaredMimeType: message.mimeType || "",
      chosenMimeType: mimeType,
      sniffedMimeType: sniffed.mimeType,
      sniffedLabel: sniffed.label,
      byteLength: bytes.length,
      canPlayType: support,
      firstBytes: firstBytesHex(bytes)
    });

    if (!bytes.length) {
      chrome.runtime.sendMessage({
        type: "AUDIO_PLAYBACK_ERROR",
        error: "Empty audio payload",
        details: { byteLength: 0 }
      });
      return;
    }

    if (!support && mimeType !== "audio/wav") {
      chrome.runtime.sendMessage({
        type: "AUDIO_PLAYBACK_ERROR",
        error: `Browser reports unsupported MIME type: ${mimeType}`,
        details: {
          declaredMimeType: message.mimeType || "",
          chosenMimeType: mimeType,
          sniffedMimeType: sniffed.mimeType,
          sniffedLabel: sniffed.label,
          canPlayType: support
        }
      });
      return;
    }

    const blob = new Blob([bytes], { type: mimeType });
    currentBlobUrl = URL.createObjectURL(blob);

    currentAudio = new Audio();
    currentAudio.preload = "auto";

    currentAudio.onloadedmetadata = () => {
      console.log("loadedmetadata", {
        duration: currentAudio.duration,
        readyState: currentAudio.readyState
      });
    };

    currentAudio.oncanplay = () => {
      console.log("canplay", {
        readyState: currentAudio.readyState,
        currentSrc: currentAudio.currentSrc
      });
    };

    currentAudio.onended = () => {
      _cleanup();
      chrome.runtime.sendMessage({ type: "AUDIO_PLAYBACK_COMPLETE" });
    };

    currentAudio.onerror = () => {
      const details = buildErrorDetails(currentAudio, mimeType, sniffed, blob.size);
      console.error("Audio element error", details);
      _cleanup();
      chrome.runtime.sendMessage({
        type: "AUDIO_PLAYBACK_ERROR",
        error: `MediaError code=${details.mediaErrorCode} ${details.mediaErrorMessage || ""}`.trim(),
        details
      });
    };

    currentAudio.src = currentBlobUrl;
    currentAudio.load();

    currentAudio.play().catch((err) => {
      console.error("Audio play() failed", {
        name: err.name,
        message: err.message,
        mimeType,
        size: blob.size
      });
      _cleanup();
      chrome.runtime.sendMessage({
        type: "AUDIO_PLAYBACK_ERROR",
        error: `${err.name}: ${err.message}`,
        details: {
          mimeType,
          sniffedMimeType: sniffed.mimeType,
          sniffedLabel: sniffed.label,
          size: blob.size
        }
      });
    });
  } catch (e) {
    console.error("Offscreen blob/playback failure", e);
    _cleanup();
    chrome.runtime.sendMessage({
      type: "AUDIO_PLAYBACK_ERROR",
      error: `Playback setup failed: ${e.message}`
    });
  }
});
