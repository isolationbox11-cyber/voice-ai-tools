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

const MEDIA_ERR_LABELS = {
  1: 'MEDIA_ERR_ABORTED',
  2: 'MEDIA_ERR_NETWORK',
  3: 'MEDIA_ERR_DECODE',
  4: 'MEDIA_ERR_SRC_NOT_SUPPORTED',
};

chrome.runtime.onMessage.addListener((message) => {
  if (message.type !== 'PLAY_AUDIO_OFFSCREEN' || !message.audioData) return;

  _cleanup();

  // Default to audio/mpeg – most TTS APIs (ElevenLabs etc.) return MP3.
  // Change to audio/wav only if your backend explicitly sends WAV.
  const mimeType = message.mimeType || 'audio/mpeg';
  console.log('[offscreen] audioData bytes:', message.audioData.byteLength, 'mime:', mimeType);

  // ── MIME support pre-check ─────────────────────────────────────────
  const probe = document.createElement('audio');
  const support = probe.canPlayType(mimeType);
  if (!support || support === '') {
    const errMsg =
      `Browser cannot play '${mimeType}' (canPlayType='${support}'). ` +
      'Supported: audio/mpeg, audio/wav, audio/ogg, audio/webm, audio/mp4';
    console.error('[offscreen]', errMsg);
    chrome.runtime.sendMessage({ type: 'AUDIO_PLAYBACK_ERROR', error: errMsg });
    return;
  }
  console.log(`[offscreen] canPlayType('${mimeType}') →`, support);

  try {
    const uint8Array = new Uint8Array(message.audioData);
    const blob = new Blob([uint8Array], { type: mimeType });
    const blobUrl = URL.createObjectURL(blob);
    currentBlobUrl = blobUrl;
    console.log('[offscreen] blob URL created, size:', uint8Array.length);

    const audio = new Audio();
    currentAudio = audio;

    audio.onended = () => {
      _cleanup();
      chrome.runtime.sendMessage({ type: 'AUDIO_PLAYBACK_COMPLETE' });
    };

    // FIX: capture audio.error into a local var BEFORE calling _cleanup(),
    // which nulls currentAudio – otherwise we hit
    // "Cannot read properties of null (reading 'error')".
    audio.onerror = () => {
      const mediaErr = audio.error; // local ref – never null here
      const code = mediaErr ? mediaErr.code : -1;
      const msg = mediaErr ? mediaErr.message : 'Unknown MediaError';
      const label = MEDIA_ERR_LABELS[code] || 'UNKNOWN_ERR';
      const readable = `${label} (code ${code})${msg ? ': ' + msg : ''}`;
      console.error('[offscreen] MediaError:', readable, '| mime:', mimeType, '| bytes:', uint8Array.length);
      _cleanup();
      chrome.runtime.sendMessage({ type: 'AUDIO_PLAYBACK_ERROR', error: readable });
    };

    // Set src AFTER handlers are attached; explicit load() before play()
    // so onerror fires reliably on unsupported/corrupt sources.
    audio.src = blobUrl;
    audio.load();

    audio.play().catch((err) => {
      console.error('[offscreen] play() rejected:', err.name, err.message);
      _cleanup();
      chrome.runtime.sendMessage({
        type: 'AUDIO_PLAYBACK_ERROR',
        error: `${err.name}: ${err.message}`,
      });
    });
  } catch (e) {
    console.error('[offscreen] blob creation failed:', e);
    _cleanup();
    chrome.runtime.sendMessage({ type: 'AUDIO_PLAYBACK_ERROR', error: 'Blob creation failed: ' + e.message });
  }
});
