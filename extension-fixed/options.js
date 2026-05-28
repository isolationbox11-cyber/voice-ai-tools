// options.js - Handle microphone permission requests

document.addEventListener('DOMContentLoaded', () => {
  checkMicrophonePermission();
  
  document.getElementById('request-mic-btn').addEventListener('click', requestMicrophonePermission);
  document.getElementById('test-mic-btn').addEventListener('click', testMicrophoneAccess);
});

async function checkMicrophonePermission() {
  const statusEl = document.getElementById('mic-status');
  const requestBtn = document.getElementById('request-mic-btn');
  
  try {
    // Check if microphone permission is granted
    const permissionStatus = await navigator.permissions.query({ name: 'microphone' });
    
    if (permissionStatus.state === 'granted') {
      statusEl.textContent = 'Microphone permission: Granted';
      statusEl.className = 'status granted';
      requestBtn.disabled = true;
      requestBtn.textContent = 'Permission Granted';
    } else if (permissionStatus.state === 'denied') {
      statusEl.textContent = 'Microphone permission: Denied. Please enable in browser settings.';
      statusEl.className = 'status denied';
      requestBtn.disabled = true;
      requestBtn.textContent = 'Permission Denied';
    } else {
      statusEl.textContent = 'Microphone permission: Not requested yet';
      statusEl.className = 'status unknown';
      requestBtn.disabled = false;
    }
    
    // Listen for permission changes
    permissionStatus.onchange = () => {
      checkMicrophonePermission();
    };
  } catch (error) {
    console.error('Error checking microphone permission:', error);
    statusEl.textContent = 'Unable to check permission status';
    statusEl.className = 'status unknown';
    requestBtn.disabled = false;
  }
}

async function requestMicrophonePermission() {
  const statusEl = document.getElementById('mic-status');
  const requestBtn = document.getElementById('request-mic-btn');
  
  try {
    // Request microphone access - this will prompt the user
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    
    // If we get here, permission was granted
    statusEl.textContent = 'Microphone permission: Granted';
    statusEl.className = 'status granted';
    requestBtn.disabled = true;
    requestBtn.textContent = 'Permission Granted';
    
    // Stop the stream immediately since we just wanted to check permission
    stream.getTracks().forEach(track => track.stop());
    
  } catch (error) {
    console.error('Error requesting microphone permission:', error);
    
    if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
      statusEl.textContent = 'Microphone permission: Denied by user';
      statusEl.className = 'status denied';
      requestBtn.disabled = true;
      requestBtn.textContent = 'Permission Denied';
    } else if (error.name === 'NotFoundError') {
      statusEl.textContent = 'No microphone found on this device';
      statusEl.className = 'status denied';
      requestBtn.disabled = true;
      requestBtn.textContent = 'No Microphone';
    } else {
      statusEl.textContent = 'Error requesting permission: ' + error.message;
      statusEl.className = 'status unknown';
    }
  }
}

async function testMicrophoneAccess() {
  const resultEl = document.getElementById('test-result');
  resultEl.textContent = 'Testing microphone access...';
  
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    resultEl.textContent = '✓ Microphone access successful!';
    resultEl.style.color = '#06D6A0';
    
    // Stop the stream
    stream.getTracks().forEach(track => track.stop());
  } catch (error) {
    console.error('Microphone test failed:', error);
    resultEl.textContent = '✗ Microphone access failed: ' + error.message;
    resultEl.style.color = '#F72585';
  }
}
