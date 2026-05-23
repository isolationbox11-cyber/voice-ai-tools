/* popup.js - Voice AI Tools v3.0 - karaoke train UI, no emoji */

const DEFAULT_SERVER = 'http://127.0.0.1:5100';
const DEFAULT_TOKEN = 'voice_ai_tools_secret_2026';
let serverUrl = DEFAULT_SERVER, token = DEFAULT_TOKEN, logs = [];
let customVoiceId = 'cloned';
let mediaRecorder = null, recordedChunks = [], isRecording = false;
let trainClips = [null, null, null, null];
let currentTake = 0;
let timerInterval = null;
let useClonedVoice = true;
let audioProcessorWASM = null;

// -- karaoke presets
const PRESETS = [
  {
    id: 'calm',
    label: 'Calm Reading',
    sub: 'relaxed tone',
    moodClass: 'calm',
    hint: 'Read this in a relaxed, even tone -- like explaining something to a friend.',
    lines: [
      'Today is quiet, and I am taking my time with my words.',
      'I am not in a rush, and nothing here is urgent.',
      'I speak clearly, but I do not push my voice.',
      'If someone were listening, they would hear that I am calm and paying attention.'
    ]
  },
  {
    id: 'rant',
    label: 'Mild Rant',
    sub: 'animated tone',
    moodClass: 'rant',
    hint: 'Read this like you are venting to someone who already agrees with you -- not yelling, just animated.',
    lines: [
      'I cannot believe how much nonsense I deal with just to get basic things done.',
      'Every time I think I have seen the last ridiculous error, another one pops up.',
      'I start out patient, but the more I repeat myself, the sharper my tone gets.',
      'I am not screaming, but you can hear in my voice that I am absolutely over it.'
    ]
  },
  {
    id: 'curious',
    label: 'Curious Questions',
    sub: 'skeptical tone',
    moodClass: 'curious',
    hint: 'Read this like you are honestly wondering the answer, with a little skepticism mixed in.',
    lines: [
      'Why does it always feel like the simple questions are the hardest to answer?',
      'What happens if I stop pretending everything makes sense?',
      'When I ask these things out loud, my voice tilts up just a bit at the end.',
      'You can hear curiosity and doubt sitting right next to each other.'
    ]
  },
  {
    id: 'singing',
    label: 'Short Song Line',
    sub: 'sung freely',
    moodClass: 'singing',
    hint: 'Sing this -- whatever melody comes to you. Do not overthink it.',
    lines: [
      'I keep singing to this little machine,',
      'hoping it learns what my voice really means.'
    ]
  }
];

// -- random tts phrases
const RANDOM_PHRASES = [
  "Hello! This is a test of the Voice AI text to speech system.",
  "Could you please repeat that? I didn't quite catch what you said.",
  "The quick brown fox jumps over the lazy dog.",
  "It's a beautiful day outside, don't you think?",
  "I wonder what would happen if we looked at this from a completely different angle?",
  "I am speaking to you live from the browser extension."
];

// -- storage wrapper
const store = {
  get(keys, cb) {
    try {
      if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
        chrome.storage.local.get(keys, cb);
      } else {
        const res = {};
        keys.forEach(k => { const v = localStorage.getItem(k); if (v !== null) res[k] = v; });
        cb(res);
      }
    } catch (e) { cb({}); }
  },
  set(obj) {
    try {
      if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
        chrome.storage.local.set(obj);
      } else {
        Object.entries(obj).forEach(([k, v]) => localStorage.setItem(k, v));
      }
    } catch (e) {}
  }
};

// -- boot
document.addEventListener('DOMContentLoaded', async () => {
  await loadSettings();
  initTabs();
  initVoice();
  initTrain();
  initTrack();
  initLog();
  animateBars();
  checkConnection();
});

// -- global extension message listener
chrome.runtime.onMessage.addListener((message) => {
  const statusEl = document.getElementById('voice-status');
  if (!statusEl) return;

  if (message.type === 'AUDIO_PLAYBACK_COMPLETE') {
    if (statusEl.textContent === 'Playing in background...') {
      statusEl.textContent = 'Done';
    }
  } else if (message.type === 'AUDIO_PLAYBACK_ERROR') {
    statusEl.textContent = 'Playback error: ' + (message.error || 'Unknown');
  }
});

async function loadSettings() {
  return new Promise(r => store.get(['serverUrl', 'token', 'customVoiceId'], res => {
    serverUrl = res.serverUrl || DEFAULT_SERVER;
    token = res.token || DEFAULT_TOKEN;
    if (res.customVoiceId) customVoiceId = res.customVoiceId;
    r();
  }));
}

// -- audio processor initialization
async function initAudioProcessor() {
  try {
    // Try to load the Rust WASM audio processor
    const AudioProcessorWASM = await import('./audio_processor_wasm.js');
    audioProcessorWASM = new AudioProcessorWASM.AudioProcessorWASM(44100);
    await audioProcessorWASM.init();
    console.log('✅ Rust audio processor loaded successfully');
  } catch (error) {
    console.log('📝 Rust audio processor not available, using JavaScript fallback');
    audioProcessorWASM = null;
  }
}

// -- tabs
function initTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('panel-' + tab.dataset.tab).classList.add('active');
    });
  });
}

// -- voice tab
function initVoice() {
  const speakBtn = document.getElementById('btn-speak');
  const clearBtn = document.getElementById('btn-clear-voice');
  const compareBtn = document.getElementById('btn-compare');
  const randomBtn = document.getElementById('btn-random-phrase');
  const clonedBtn = document.getElementById('btn-mode-cloned');
  const stockBtn = document.getElementById('btn-mode-stock');
  const statusEl = document.getElementById('voice-status');

  if (clonedBtn) clonedBtn.addEventListener('click', () => {
    useClonedVoice = true;
    clonedBtn.classList.add('active');
    if (stockBtn) stockBtn.classList.remove('active');
    if (statusEl) statusEl.textContent = 'Using your cloned voice';
  });

  if (stockBtn) stockBtn.addEventListener('click', () => {
    useClonedVoice = false;
    stockBtn.classList.add('active');
    if (clonedBtn) clonedBtn.classList.remove('active');
    if (statusEl) statusEl.textContent = 'Using stock voice';
  });

  if (clearBtn) clearBtn.addEventListener('click', () => {
    const txt = document.getElementById('tts-text');
    if (txt) txt.value = '';
  });

  if (randomBtn) randomBtn.addEventListener('click', () => {
    const txt = document.getElementById('tts-text');
    if (txt) txt.value = RANDOM_PHRASES[Math.floor(Math.random() * RANDOM_PHRASES.length)];
  });

  if (speakBtn) speakBtn.addEventListener('click', () => speakText(useClonedVoice, false));

  if (compareBtn) compareBtn.addEventListener('click', async () => {
    const txt = document.getElementById('tts-text');
    const text = txt ? txt.value.trim() : '';
    if (!text) { if (statusEl) statusEl.textContent = 'Enter text first.'; return; }
    if (statusEl) statusEl.textContent = 'AB: playing stock...';
    await speakText(false, true);
    setTimeout(async () => {
      if (statusEl) statusEl.textContent = 'AB: playing cloned...';
      await speakText(true, true);
      if (statusEl) statusEl.textContent = 'AB compare done.';
    }, 2500);
  });

  // Automatically populate the TTS text box with a preset phrase
  const txt = document.getElementById('tts-text');
  if (txt && !txt.value.trim()) {
    txt.value = "Hello! This is a test of the Voice AI text to speech system.";
  }
}

async function speakText(cloned, silent) {
  const txt = document.getElementById('tts-text');
  const statusEl = document.getElementById('voice-status');
  const speakBtn = document.getElementById('btn-speak');
  const text = txt ? txt.value.trim() : '';
  if (!text) { if (statusEl) statusEl.textContent = 'Enter text first.'; return; }
  if (!silent && speakBtn) speakBtn.disabled = true;
  if (statusEl && !silent) statusEl.textContent = 'Speaking...';
  const speed = document.getElementById('voice-speed');
  try {
    const r = await fetch(serverUrl + '/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Token': token },
      body: JSON.stringify({ text, voice_id: cloned ? customVoiceId : 'kore', speed: speed ? speed.value : 'normal' })
    });
    if (!r.ok) {
      const e = await r.json();
      if (statusEl) statusEl.textContent = 'Error: ' + (e.error || r.status);
      if (!silent && speakBtn) speakBtn.disabled = false;
      return;
    }
    const blob = await r.blob();
    const buffer = await blob.arrayBuffer();

    chrome.runtime.sendMessage({ type: 'PLAY_AUDIO', audioData: buffer, mimeType: blob.type }, (response) => {
      if (response && response.ok) {
        if (!silent && statusEl) statusEl.textContent = 'Playing in background...';
        addLog('voice', (cloned ? '[cloned] ' : '[stock] ') + text.substring(0, 40));
      } else if (statusEl) {
        statusEl.textContent = 'Playback error: ' + (response ? response.error : 'Unknown');
      }
    });
  } catch (e) {
    let errorMsg = 'TTS error: ';
    if (e.name === 'TypeError' && e.message.includes('Failed to fetch')) {
      errorMsg = 'Server unreachable. Is Flask running on port 5000?';
    } else if (e.name === 'TypeError' && e.message.includes('NetworkError')) {
      errorMsg = 'Network error. Check connection to Flask server.';
    } else {
      errorMsg = 'TTS request failed: ' + e.message;
    }
    if (statusEl) statusEl.textContent = errorMsg;
    addLog('warn', 'Voice error: ' + errorMsg);
  }
  if (!silent && speakBtn) speakBtn.disabled = false;
}

// -- train tab (karaoke)
function initTrain() {
  const recordBtn = document.getElementById('record-btn');
  const trainBtn = document.getElementById('btn-train');
  const clearBtn = document.getElementById('btn-clear-clips');
  const checkBtn = document.getElementById('btn-check-model');
  const prevBtn = document.getElementById('btn-prev-take');
  const nextBtn = document.getElementById('btn-next-take');
  const redoBtn = document.getElementById('btn-redo-take');

  if (!recordBtn) return;

  renderKaraokeStep(currentTake);

  recordBtn.addEventListener('click', () => {
    if (isRecording) stopRecording(); else startRecording();
  });

  if (prevBtn) prevBtn.addEventListener('click', () => {
    if (currentTake > 0) { currentTake--; renderKaraokeStep(currentTake); }
  });

  if (nextBtn) nextBtn.addEventListener('click', () => {
    if (currentTake < PRESETS.length - 1) { currentTake++; renderKaraokeStep(currentTake); }
  });

  if (redoBtn) redoBtn.addEventListener('click', () => {
    trainClips[currentTake] = null;
    updateTrainBtn();
    renderKaraokeStep(currentTake);
    const status = document.getElementById('train-status');
    if (status) status.textContent = 'Take ' + (currentTake + 1) + ' cleared. Record again.';
  });

  if (trainBtn) trainBtn.addEventListener('click', submitTraining);

  if (clearBtn) clearBtn.addEventListener('click', () => {
    trainClips = [null, null, null, null];
    currentTake = 0;
    renderKaraokeStep(0);
    updateTrainBtn();
    const status = document.getElementById('train-status');
    if (status) status.textContent = 'Reset. Record all 4 takes again.';
  });

  if (checkBtn) checkBtn.addEventListener('click', () => checkModelStatus(false));
}

function renderKaraokeStep(step) {
  const p = PRESETS[step];
  const moodEl = document.getElementById('karaoke-mood');
  const labelEl = document.getElementById('karaoke-mood-label');
  const subEl = document.getElementById('karaoke-take-sub');
  const hintEl = document.getElementById('karaoke-hint');
  const scriptEl = document.getElementById('karaoke-script');
  const recordLabel = document.getElementById('record-label');

  if (moodEl) moodEl.className = 'karaoke-mood ' + p.moodClass;
  if (labelEl) labelEl.textContent = p.label;
  if (subEl) subEl.textContent = p.sub;
  if (hintEl) hintEl.textContent = p.hint;

  if (scriptEl) {
    scriptEl.innerHTML = '';
    p.lines.forEach((line, i) => {
      const span = document.createElement('span');
      span.className = 'kline';
      span.dataset.line = i;
      span.textContent = line;
      scriptEl.appendChild(span);
      if (i < p.lines.length - 1) {
        scriptEl.appendChild(document.createElement('br'));
      }
    });
  }

  if (recordLabel) {
    recordLabel.textContent = trainClips[step]
      ? 'Take ' + (step + 1) + ' recorded -- tap to re-record'
      : 'Tap to record take ' + (step + 1) + ' of ' + PRESETS.length;
  }

  document.querySelectorAll('.step-dot').forEach((dot, i) => {
    dot.classList.remove('active', 'done');
    if (i < step) dot.classList.add('done');
    else if (i === step) dot.classList.add('active');
  });
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) recordedChunks.push(e.data); };
    mediaRecorder.onstop = () => {
      const blob = new Blob(recordedChunks, { type: 'audio/webm' });
      const file = new File([blob], 'take_' + currentTake + '_' + PRESETS[currentTake].id + '.webm', { type: 'audio/webm' });
      trainClips[currentTake] = file;
      updateTrainBtn();
      const label = document.getElementById('record-label');
      if (label) label.textContent = 'Take ' + (currentTake + 1) + ' saved.';
      const done = trainClips.filter(Boolean).length;
      const status = document.getElementById('train-status');
      if (status) status.textContent = done + ' of ' + PRESETS.length + ' takes recorded.';
      addLog('train', 'Take ' + (currentTake + 1) + ' saved: ' + PRESETS[currentTake].label);
      stream.getTracks().forEach(t => t.stop());
      if (currentTake < PRESETS.length - 1) {
        setTimeout(() => { currentTake++; renderKaraokeStep(currentTake); }, 600);
      }
    };
    mediaRecorder.start();
    isRecording = true;
    const ring = document.getElementById('record-btn');
    const icon = document.getElementById('record-icon');
    if (ring) ring.classList.add('recording');
    if (icon) icon.textContent = 'STOP';
    const label = document.getElementById('record-label');
    if (label) label.textContent = 'Recording -- tap to stop';
    startTimer();
    highlightLines();
  } catch (e) {
    const status = document.getElementById('train-status');

    console.error('Microphone error details:', {
      name: e?.name || 'Unknown',
      message: e?.message || 'No message',
      stack: e?.stack || 'No stack',
      toString: String(e),
      constructor: e?.constructor?.name,
      isDOMException: e instanceof DOMException,
      permissionsState: navigator.permissions ? 'available' : 'unavailable'
    });

    let errorMsg = `Mic error: ${e?.name || 'Unknown'} - ${e?.message || 'No message'}`;

    if (e?.name === 'NotAllowedError' || String(e?.message).includes('Permission denied')) {
      errorMsg = 'Microphone access is not granted yet. Opening permission page...';
      if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.openOptionsPage) {
        chrome.runtime.openOptionsPage();
      }
    } else if (e?.name === 'NotFoundError' || String(e?.message).includes('No device found')) {
      errorMsg = 'No microphone found. Connect a microphone and try again.';
    } else if (e?.name === 'NotReadableError') {
      errorMsg = 'Microphone is busy or unavailable. Close other apps using it and try again.';
    } else if (e?.name === 'SecurityError' || e?.name === 'DOMException') {
      errorMsg = 'Chrome blocked microphone access in this context. Reload the extension and request permission again.';
    }

    if (status) status.textContent = errorMsg;
    addLog('warn', errorMsg);
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
  isRecording = false;
  const ring = document.getElementById('record-btn');
  const icon = document.getElementById('record-icon');
  if (ring) ring.classList.remove('recording');
  if (icon) icon.textContent = 'REC';
  stopTimer();
  clearLineHighlight();
}

let lineInterval = null;
function highlightLines() {
  const p = PRESETS[currentTake];
  let li = 0;
  clearLineHighlight();
  const lines = document.querySelectorAll('.kline');
  if (lines[0]) lines[0].classList.add('active');
  const perLine = Math.max(2000, Math.floor(20000 / p.lines.length));
  lineInterval = setInterval(() => {
    document.querySelectorAll('.kline').forEach(l => l.classList.remove('active'));
    if (li < lines.length) lines[li].classList.add('done');
    li++;
    if (li < lines.length) lines[li].classList.add('active');
    else clearLineHighlight();
  }, perLine);
}

function clearLineHighlight() {
  if (lineInterval) { clearInterval(lineInterval); lineInterval = null; }
}

let seconds = 0;
function startTimer() {
  seconds = 0;
  const el = document.getElementById('record-timer');
  if (el) el.textContent = '0:00';
  timerInterval = setInterval(() => {
    seconds++;
    const m = Math.floor(seconds / 60);
    const s = String(seconds % 60).padStart(2, '0');
    if (el) el.textContent = m + ':' + s;
  }, 1000);
}

function stopTimer() {
  clearInterval(timerInterval);
  const el = document.getElementById('record-timer');
  if (el) el.textContent = '';
}

function updateTrainBtn() {
  const btn = document.getElementById('btn-train');
  const done = trainClips.filter(Boolean).length;
  if (!btn) return;
  btn.textContent = 'TRAIN MY VOICE (' + done + '/' + PRESETS.length + ')';
  btn.disabled = done === 0;
  if (done === PRESETS.length) {
    btn.style.background = 'linear-gradient(135deg,#06D6A0,#4CC9F0)';
    const status = document.getElementById('train-status');
    if (status) status.textContent = 'All takes recorded. Press Train My Voice.';
  }
}

async function checkModelStatus(isAuto = false) {
  const status = document.getElementById('model-status');
  const idEl = document.getElementById('trained-voice-id');
  try {
    const r = await fetch(serverUrl + '/model_status', { headers: { 'X-Token': token } });
    if (!r.ok) {
      if (status) status.textContent = 'Error checking model';
      return;
    } else {
      if (!isAuto && status) status.textContent = 'No model trained yet.';
      if (idEl) idEl.style.display = 'none';

      // Automatically switch to 'Stock' if no model exists to prevent unexpected fallbacks
      const stockBtn = document.getElementById('btn-mode-stock');
      if (stockBtn && isAuto) stockBtn.click();
    }
  } catch (e) {
    if (!isAuto && status) status.textContent = 'Could not reach server.';
  }
}

async function submitTraining() {
  const status = document.getElementById('train-status');
  const trainBtn = document.getElementById('btn-train');
  const clips = trainClips.filter(Boolean);
  if (!clips.length) { if (status) status.textContent = 'No clips recorded yet.'; return; }
  if (status) status.textContent = 'Uploading ' + clips.length + ' clip(s) and training...';
  if (trainBtn) { trainBtn.disabled = true; trainBtn.textContent = 'TRAINING...'; }
  const fd = new FormData();
  clips.forEach(f => fd.append('files', f, f.name));
  try {
    const r = await fetch(serverUrl + '/train', { method: 'POST', headers: { 'X-Token': token }, body: fd });
    const d = await r.json();
    const idEl = document.getElementById('trained-voice-id');
    if (d.ok) {
      if (status) status.textContent = d.status === 'trained'
        ? 'Voice trained. ID: ' + (d.voice_id || 'saved')
        : (d.note || d.status || 'Samples saved.');
      if (idEl && d.voice_id) {
        idEl.style.display = 'block';
        idEl.textContent = 'Voice ID: ' + d.voice_id;
        customVoiceId = d.voice_id;
        store.set({ customVoiceId: d.voice_id });
      }
      if (d.error && status) status.textContent += ' -- ' + d.error;
      addLog('train', 'Training result: ' + (d.status || 'ok') + ' / ' + (d.voice_id || ''));
    } else {
      if (status) status.textContent = 'Training failed: ' + (d.error || 'unknown error');
      addLog('warn', 'Training failed: ' + (d.error || 'unknown'));
    }
  } catch (e) {
    if (status) status.textContent = 'Upload error -- is Flask running?';
    addLog('warn', 'Train upload error: ' + e.message);
  }
  if (trainBtn) { trainBtn.disabled = false; updateTrainBtn(); }
}

// -- track tab
function initTrack() {
  const scanBtn = document.getElementById('btn-track');
  const pdfDrop = document.getElementById('pdf-drop');
  const pdfInput = document.getElementById('pdf-file');
  const ipInput = document.getElementById('track-ip');
  const trackBox = document.getElementById('track-result');
  const pdfBox = document.getElementById('pdf-result');

  if (scanBtn) scanBtn.addEventListener('click', async () => {
    const ip = ipInput ? ipInput.value.trim() : '';
    if (!ip) { if (trackBox) trackBox.textContent = 'Enter an IP or domain.'; return; }
    if (trackBox) trackBox.textContent = 'Scanning...';
    try {
      const r = await fetch(serverUrl + '/shodan?ip=' + encodeURIComponent(ip), { headers: { 'X-Token': token } });
      const d = await r.json();
      if (d.error) { if (trackBox) trackBox.textContent = 'Error: ' + d.error; addLog('warn', 'Shodan: ' + d.error); return; }
      const lines = ['IP: ' + d.ip_str, 'Org: ' + (d.org || 'N/A'), 'Country: ' + (d.country_name || 'N/A')];
      if (d.ports && d.ports.length) lines.push('Ports: ' + d.ports.join(', '));
      if (d.vulns && Object.keys(d.vulns).length) lines.push('Vulns: ' + Object.keys(d.vulns).join(', '));
      if (trackBox) trackBox.textContent = lines.join('\n');
      addLog('track', 'Scanned: ' + ip);
    } catch (e) {
      if (trackBox) trackBox.textContent = 'Scan failed. Is Flask running?';
      addLog('warn', 'Scan error: ' + e.message);
    }
  });

  if (pdfDrop) {
    pdfDrop.addEventListener('click', () => { if (pdfInput) pdfInput.click(); });
    pdfDrop.addEventListener('dragover', e => { e.preventDefault(); pdfDrop.classList.add('dragover'); });
    pdfDrop.addEventListener('dragleave', () => pdfDrop.classList.remove('dragover'));
    pdfDrop.addEventListener('drop', e => { e.preventDefault(); pdfDrop.classList.remove('dragover'); const f = e.dataTransfer.files[0]; if (f) analyzePDF(f, pdfBox); });
  }
  if (pdfInput) pdfInput.addEventListener('change', () => { const f = pdfInput.files[0]; if (f) analyzePDF(f, pdfBox); });
}

async function analyzePDF(f, box) {
  if (box) box.textContent = 'Analyzing: ' + f.name + '...';
  const fd = new FormData();
  fd.append('file', f);
  try {
    const r = await fetch(serverUrl + '/analyze_pdf', { method: 'POST', headers: { 'X-Token': token }, body: fd });
    const d = await r.json();
    if (d.error) { if (box) box.textContent = 'Error: ' + d.error; addLog('warn', 'PDF: ' + d.error); return; }
    const lines = ['PDF: ' + f.name, 'Pages: ' + (d.pages || '?')];
    if (d.metadata) Object.entries(d.metadata).forEach(([k, v]) => lines.push('  ' + k + ': ' + v));
    if (d.links && d.links.length) { lines.push('', 'Links (' + d.links.length + '):'); d.links.slice(0, 10).forEach(l => lines.push('  ' + l)); }
    if (d.ips && d.ips.length) { lines.push('', 'Embedded IPs:'); d.ips.forEach(i => lines.push('  ' + i)); }
    if (d.suspicious) lines.push('', 'WARNING: SUSPICIOUS CONTENT DETECTED');
    if (box) box.textContent = lines.join('\n');
    addLog('ok', 'PDF done: ' + f.name);
  } catch (e) {
    if (box) box.textContent = 'PDF failed. Is Flask running?';
    addLog('warn', 'PDF error: ' + e.message);
  }
}

// -- log tab
function initLog() {
  const clearBtn = document.getElementById('btn-clear-log');
  if (!clearBtn) return;
  clearBtn.addEventListener('click', () => {
    logs = []; renderLog();
    fetch(serverUrl + '/log', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Token': token }, body: JSON.stringify({ action: 'clear' }) }).catch(() => {});
  });
}

function addLog(type, message) {
  const e = { type, message, time: new Date().toLocaleTimeString() };
  logs.unshift(e);
  if (logs.length > 200) logs.pop();

  fetch(serverUrl + '/log', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Token': token }, body: JSON.stringify({ ...e, time: Date.now() }) }).catch(() => {});
  renderLog();
}

function renderLog() {
  const list = document.getElementById('log-list');
  if (!list) return;
  list.innerHTML = ''; // Safely clear contents
  if (!logs.length) {
    const empty = document.createElement('div');
    empty.className = 'log-empty';
    empty.textContent = 'No activity logged yet.';
    list.appendChild(empty);
    return;
  }
  const c = { voice: '#4CC9F0', train: '#06D6A0', track: '#7B2FBE', pdf: '#F72585', ok: '#06D6A0', warn: '#F72585', info: '#4CC9F0' };

  const fragment = document.createDocumentFragment();
  for (const l of logs) {
    const item = document.createElement('div');
    item.className = 'log-item';

    const typeSpan = document.createElement('span');
    typeSpan.className = 'log-type';
    typeSpan.style.color = c[l.type] || '#e0e0e0';
    typeSpan.textContent = `[${l.type.toUpperCase()}]`;

    const timeSpan = document.createElement('span');
    timeSpan.className = 'log-time';
    timeSpan.textContent = l.time;

    item.append(typeSpan, ' ', timeSpan, ' ', l.message);
    fragment.appendChild(item);
  }
  list.appendChild(fragment);
}

function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

// -- connection check
async function checkConnection() {
  const el = document.getElementById('conn-status');
  try {
    console.log('Checking connection to:', serverUrl + '/health');
    const r = await fetch(serverUrl + '/health', {
      headers: { 'X-Token': token },
      mode: 'cors'
    });
    console.log('Connection response:', r.status, r.ok);
    if (el) el.style.color = r.ok ? '#06D6A0' : '#F72585';
    addLog('info', 'Server connection: ' + (r.ok ? 'OK' : 'Failed'));
  } catch (e) {
    console.log('Connection error:', e);
    if (el) el.style.color = '#888';
    addLog('warn', 'Server connection failed: ' + e.message);
  }
}

async function checkMicPermission() {
  const icon = document.getElementById('mic-status-icon');
  if (!icon || !navigator.permissions) return;
  try {
    const result = await navigator.permissions.query({ name: 'microphone' });
    const updateUI = (state) => {
      if (state === 'granted') {
        icon.style.filter = 'none';
        icon.style.opacity = '1';
        icon.style.color = 'var(--ok)';
        icon.style.textShadow = '0 0 8px var(--ok)';
        icon.title = 'Microphone: Access Granted';
      } else if (state === 'denied') {
        icon.style.filter = 'none';
        icon.style.opacity = '1';
        icon.style.color = 'var(--warn)';
        icon.style.textShadow = '0 0 8px var(--warn)';
        icon.title = 'Microphone: Access Denied';
      } else {
        icon.style.filter = 'grayscale(1)';
        icon.style.opacity = '0.4';
        icon.title = 'Microphone: Permission Required';
      }
    };
    updateUI(result.state);
    result.onchange = () => updateUI(result.state);
  } catch (e) { console.warn('Permissions API error:', e); }
}

// -- visualizer
function animateBars() {
  const bars = document.querySelectorAll('.bar');
  if (!bars.length) return;
  const interval = setInterval(() => {
    if (!document.body) return clearInterval(interval);
    bars.forEach(b => { b.style.height = (Math.floor(Math.random() * 80) + 10) + '%'; });
  }, 200);
}
