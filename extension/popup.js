/* popup.js - Voice AI Tools v3.0 - karaoke train UI, no emoji */

const DEFAULT_SERVER = 'http://127.0.0.1:5001';
let serverUrl = DEFAULT_SERVER, token = '', logs = [];
let mediaRecorder = null, recordedChunks = [], isRecording = false;
let trainClips = [null, null, null, null];
let currentTake = 0;
let timerInterval = null;
let useClonedVoice = true;

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

async function loadSettings() {
  return new Promise(r => store.get(['serverUrl', 'token'], res => {
    serverUrl = res.serverUrl || DEFAULT_SERVER;
    token = res.token || '';
    r();
  }));
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
}

/**
 * Route TTS through background.js -> offscreen.js so playback
 * survives popup closure.
 *
 * UI state ownership:
 *   'Sending...'  — set here while the fetch is in-flight
 *   ''            — cleared here on fetch ACK (ok:true); offscreen events take over
 *   'Error: ...'  — set here on fetch failure (ok:false or lastError)
 *   'Playing...'  — set by AUDIO_PLAYBACK_COMPLETE listener below (audio started)
 *   'Done'        — set by AUDIO_PLAYBACK_COMPLETE listener below
 *   'Playback error: ...' — set by AUDIO_PLAYBACK_ERROR listener below
 */
async function speakText(cloned, silent) {
  const txt = document.getElementById('tts-text');
  const statusEl = document.getElementById('voice-status');
  const speakBtn = document.getElementById('btn-speak');
  const text = txt ? txt.value.trim() : '';
  if (!text) { if (statusEl) statusEl.textContent = 'Enter text first.'; return; }
  if (!silent && speakBtn) speakBtn.disabled = true;
  // 'Sending...' while the network request is in-flight.
  // Never 'Playing...' here — that comes from AUDIO_PLAYBACK_COMPLETE.
  if (statusEl && !silent) statusEl.textContent = 'Sending...';
  const speed = document.getElementById('voice-speed');

  return new Promise((resolve) => {
    chrome.runtime.sendMessage({
      type: 'TTS_REQUEST',
      text,
      token,
      serverUrl,
      callType: cloned ? 'cloned' : 'stock',
      voiceId: cloned ? 'cloned' : 'Kore',
      speed: speed ? speed.value : 'normal',
    }, (response) => {
      const err = chrome.runtime.lastError;
      if (err) {
        // Extension messaging error (e.g. service worker not running)
        if (statusEl && !silent) statusEl.textContent = 'Extension error: ' + err.message;
        addLog('warn', 'TTS extension error: ' + err.message);
      } else if (response && !response.ok) {
        // Fetch or HTTP error from background.js — playback will never start
        if (statusEl && !silent) statusEl.textContent = 'Error: ' + (response.error || 'unknown');
        addLog('warn', 'TTS error: ' + (response.error || 'unknown'));
      } else {
        // Fetch succeeded; audio bytes are on their way to offscreen.
        // Clear the in-flight status — AUDIO_PLAYBACK_COMPLETE will set 'Playing...'
        if (statusEl && !silent) statusEl.textContent = '';
        addLog('voice', (cloned ? '[cloned] ' : '[stock] ') + text.substring(0, 40));
      }
      if (!silent && speakBtn) speakBtn.disabled = false;
      resolve();
    });
  });
}

// Offscreen events own the final playback UI state.
// These fire whether or not the popup is the one that initiated the request.
chrome.runtime.onMessage.addListener((message) => {
  const statusEl = document.getElementById('voice-status');
  if (message.type === 'AUDIO_PLAYBACK_COMPLETE') {
    if (statusEl) statusEl.textContent = 'Done';
  } else if (message.type === 'AUDIO_PLAYBACK_ERROR') {
    if (statusEl) statusEl.textContent = 'Playback error: ' + (message.error || 'unknown');
    addLog('warn', 'Playback error: ' + (message.error || 'unknown'));
  }
});

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

  if (checkBtn) checkBtn.addEventListener('click', async () => {
    const status = document.getElementById('train-status');
    try {
      const r = await fetch(serverUrl + '/model_status', { headers: { 'X-Voice-Token': token } });
      const d = await r.json();
      const idEl = document.getElementById('trained-voice-id');
      if (d.trained) {
        if (status) status.textContent = 'Model: ' + (d.status || 'trained') + ' / ' + (d.count || '?') + ' clips / ' + (d.trained_at || '');
        if (idEl && d.voice_id) { idEl.style.display = 'block'; idEl.textContent = 'Voice ID: ' + d.voice_id; }
        if (d.note && status) status.textContent += ' -- ' + d.note;
        if (d.error && status) status.textContent += ' -- ' + d.error;
      } else {
        if (status) status.textContent = 'No model trained yet.';
        if (idEl) idEl.style.display = 'none';
      }
    } catch (e) {
      const status = document.getElementById('train-status');
      if (status) status.textContent = 'Could not reach server on port 5001.';
    }
  });
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
    scriptEl.innerHTML = p.lines.map((line, i) =>
      '<span class="kline" data-line="' + i + '">' + esc(line) + '</span>'
    ).join('<br>');
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

function startRecording() {
  navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
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
  }).catch(e => {
    const status = document.getElementById('train-status');
    if (status) status.textContent = 'Mic error: ' + e.message;
    addLog('warn', 'Mic error: ' + e.message);
  });
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
    const r = await fetch(serverUrl + '/train', { method: 'POST', headers: { 'X-Voice-Token': token }, body: fd });
    const d = await r.json();
    const idEl = document.getElementById('trained-voice-id');
    if (d.ok) {
      if (status) status.textContent = d.status === 'trained'
        ? 'Voice trained. ID: ' + (d.voice_id || 'saved')
        : (d.note || d.status || 'Samples saved.');
      if (idEl && d.voice_id) { idEl.style.display = 'block'; idEl.textContent = 'Voice ID: ' + d.voice_id; }
      if (d.error && status) status.textContent += ' -- ' + d.error;
      addLog('train', 'Training result: ' + (d.status || 'ok') + ' / ' + (d.voice_id || ''));
    } else {
      if (status) status.textContent = 'Training failed: ' + (d.error || 'unknown error');
      addLog('warn', 'Training failed: ' + (d.error || 'unknown'));
    }
  } catch (e) {
    if (status) status.textContent = 'Upload error -- is Flask running on port 5001?';
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
      const r = await fetch(serverUrl + '/shodan?ip=' + encodeURIComponent(ip), { headers: { 'X-Voice-Token': token } });
      const d = await r.json();
      if (d.error) { if (trackBox) trackBox.textContent = 'Error: ' + d.error; addLog('warn', 'Shodan: ' + d.error); return; }
      const lines = ['IP: ' + d.ip_str, 'Org: ' + (d.org || 'N/A'), 'Country: ' + (d.country_name || 'N/A')];
      if (d.ports && d.ports.length) lines.push('Ports: ' + d.ports.join(', '));
      if (d.vulns && Object.keys(d.vulns).length) lines.push('Vulns: ' + Object.keys(d.vulns).join(', '));
      if (trackBox) trackBox.textContent = lines.join('\n');
      addLog('track', 'Scanned: ' + ip);
    } catch (e) {
      if (trackBox) trackBox.textContent = 'Scan failed. Is Flask running on port 5001?';
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
    const r = await fetch(serverUrl + '/analyze_pdf', { method: 'POST', headers: { 'X-Voice-Token': token }, body: fd });
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
    if (box) box.textContent = 'PDF failed. Is Flask running on port 5001?';
    addLog('warn', 'PDF error: ' + e.message);
  }
}

// -- log tab
function initLog() {
  const clearBtn = document.getElementById('btn-clear-log');
  if (!clearBtn) return;
  clearBtn.addEventListener('click', () => {
    logs = []; renderLog();
    fetch(serverUrl + '/log', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Voice-Token': token }, body: JSON.stringify({ action: 'clear' }) }).catch(() => {});
  });
}

function addLog(type, message) {
  const e = { type, message, time: new Date().toLocaleTimeString() };
  logs.unshift(e); if (logs.length > 200) logs.pop();
  fetch(serverUrl + '/log', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Voice-Token': token }, body: JSON.stringify({ ...e, time: Date.now() }) }).catch(() => {});
  renderLog();
}

function renderLog() {
  const list = document.getElementById('log-list');
  if (!list) return;
  if (!logs.length) { list.innerHTML = '<div class="log-empty">No activity logged yet.</div>'; return; }
  const c = { voice: '#4CC9F0', train: '#06D6A0', track: '#7B2FBE', pdf: '#F72585', ok: '#06D6A0', warn: '#F72585', info: '#4CC9F0' };
  list.innerHTML = logs.map(l => '<div class="log-item"><span class="log-type" style="color:' + (c[l.type] || '#e0e0e0') + '">[' + l.type.toUpperCase() + ']</span> <span class="log-time">' + l.time + '</span> ' + esc(l.message) + '</div>').join('');
}

function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

// -- connection check
async function checkConnection() {
  const el = document.getElementById('conn-status');
  try {
    const r = await fetch(serverUrl + '/health', { headers: { 'X-Voice-Token': token } });
    if (el) el.style.color = r.ok ? '#06D6A0' : '#F72585';
  } catch {
    if (el) el.style.color = '#888';
  }
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
