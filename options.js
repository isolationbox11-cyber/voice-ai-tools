/* options.js - Handles one-time microphone permission request */

async function requestMicPermission() {
  const status = document.getElementById('mic-status');
  const closeBtn = document.getElementById('btn-close');

  try {
    status.textContent = 'Please click "Allow" in the browser prompt to grant microphone access...';
    status.className = '';

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach(t => t.stop());

    status.textContent = 'Success! Microphone access granted. You can now record your voice.';
    status.className = 'ok';
    closeBtn.style.display = 'inline-block';

    closeBtn.addEventListener('click', () => window.close());
  } catch (e) {
    status.textContent = `Permission failed: ${e.name} - ${e.message}. Check your browser settings or the URL lock icon to ensure microphone access is allowed.`;
  }
}

document.addEventListener('DOMContentLoaded', requestMicPermission);