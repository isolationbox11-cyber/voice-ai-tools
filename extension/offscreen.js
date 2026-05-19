/* offscreen.js – runs in the hidden offscreen document for audio playback */

let _currentAudio = null;
let _currentBlobUrl = null;

function _cleanup() {
  if (_currentAudio) {
    // Detach handlers BEFORE nulling so no stale callbacks fire
    _currentAudio.onended = null;
    _currentAudio.onerror = null;
    _currentAudio.pause();
    _currentAudio.src = '';
    _currentAudio = null;
  }
  if (_currentBlobUrl) {
    URL.revokeObjectURL(_currentBlobUrl);
    _currentBlobUrl = null;
  }
}

const MEDIA_ERR = {
  1: 'MEDIA_ERR_ABORTED',
  2: 'MEDIA_ERR_NETWORK',
  3: 'MEDIA_ERR_DECODE',
  4: 'MEDIA_ERR_SRC_NOT_SUPPORTED',
};

chrome.runtime.onMessage.addListener((message) => {
  if (message.type !== 'PLAY_AUDIO_OFFSCREEN' || !message.audioData) return;

  _cleanup();

  const mimeType = message.mimeType || 'audio/mpeg';
  console.log('[offscreen] audioData bytes:', message.audioData.byteLength, 'mime:', mimeType);

  // ── MIME support pre-check ────────────────────────────────────────────────
  const probe = document.createElement('audio');
  const support = probe.canPlayType(mimeType);
  if (!support || support === '') {
    const errMsg = `Browser cannot play '${mimeType}' (canPlayType='${support}')`;
    console.error('[offscreen]', errMsg);
    chrome.runtime.sendMessage({ type: 'AUDIO_PLAYBACK_ERROR', error: errMsg });
    return;
  }
  console.log(`[offscreen] canPlayType('${mimeType}') →`, support);

  try {
    const uint8 = new Uint8Array(message.audioData);
    const blob = new Blob([uint8], { type: mimeType });
    const blobUrl = URL.createObjectURL(blob);
    _currentBlobUrl = blobUrl;
    console.log('[offscreen] blob URL created, size:', uint8.length);

    const audio = new Audio();
    _currentAudio = audio;

    audio.onended = () => {
      _cleanup();
      chrome.runtime.sendMessage({ type: 'AUDIO_PLAYBACK_COMPLETE' });
    };

    // ── FIX: capture error BEFORE _cleanup() nulls the audio ref ─────────
    audio.onerror = () => {
      const me = audio.error;                          // local ref, never null here
      const code = me ? me.code : -1;
      const label = MEDIA_ERR[code] || 'UNKNOWN_ERR';
      const readable = `${label} (code ${code})${me && me.message ? ': ' + me.message : ''}`;
      console.error('[offscreen] MediaError:', readable, '| mime:', mimeType, '| bytes:', uint8.length);
      _cleanup();
      chrome.runtime.sendMessage({ type: 'AUDIO_PLAYBACK_ERROR', error: readable });
    };

    audio.src = blobUrl;   // set src AFTER attaching handlers
    audio.load();          // force decode attempt so onerror fires reliably

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
