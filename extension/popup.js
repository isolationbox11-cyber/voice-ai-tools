/* popup.js — Voice AI Tools unified extension */

const DEFAULT_SERVER = 'http://127.0.0.1:5000';
let serverUrl = DEFAULT_SERVER;
let token = '';
let activePreset = 'default';
let logs = [];

// ── INIT ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await loadSettings();
  initTabs();
  initVoice();
  initTrack();
  initLog();
  animateBars();
  checkConnection();
});

async function loadSettings() {
  return new Promise(resolve => {
    chrome.storage.local.get(['serverUrl', 'token'], res => {
      serverUrl = res.serverUrl || DEFAULT_SERVER;
      token = res.token || '';
      resolve();
    });
  });
}

// ── TABS ─────────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('panel-' + tab.dataset.tab).classList.add('active');
      if (tab.dataset.tab === 'log') renderLog();
    });
  });
}

// ── CONNECTION CHECK ─────────────────────────────────────────────────
async function checkConnection() {
  const dot = document.getElementById('status-dot');
  const status = document.getElementById('conn-status');
  try {
    const r = await fetch(serverUrl + '/presets', {
      headers: { 'X-Token': token }
    });
    if (r.ok) {
      dot.style.background = '#06D6A0';
      dot.style.boxShadow = '0 0 8px #06D6A0';
      status.textContent = '\u25CF connected';
      status.style.color = '#06D6A0';
      loadPresets();
    } else throw new Error();
  } catch {
    dot.style.background = '#F72585';
    dot.style.boxShadow = '0 0 8px #F72585';
    status.textContent = '\u25CF offline';
    status.style.color = '#F72585';
  }
}

// ── VOICE BAR ANIMATION ──────────────────────────────────────────────
function animateBars() {
  const bars = document.querySelectorAll('.bar');
  setInterval(() => {
    bars.forEach(b => {
      const h = Math.floor(Math.random() * 52) + 4;
      b.style.height = h + 'px';
    });
  }, 120);
}

// ── VOICE MODE ───────────────────────────────────────────────────────
function initVoice() {
  document.getElementById('btn-speak').addEventListener('click', speakText);
  document.getElementById('btn-save-preset').addEventListener('click', savePreset);
  document.getElementById('btn-clear-voice').addEventListener('click', () => {
    document.getElementById('tts-text').value = '';
  });
  document.querySelectorAll('.preset-chip').forEach(chip => {
    chip.addEventListener('click', () => applyPreset(chip.dataset.preset));
  });
}

async function speakText() {
  const text = document.getElementById('tts-text').value.trim();
  if (!text) return;
  const lang = document.getElementById('voice-lang').value;
  const speed = document.getElementById('voice-speed').value;
  addLog('voice', `Spoke: "${text.substring(0,40)}${text.length>40?'...':''}"`);
  try {
    const r = await fetch(serverUrl + '/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Token': token },
      body: JSON.stringify({ text, lang, speed, preset: activePreset })
    });
    if (!r.ok) throw new Error('TTS failed');
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.play();
  } catch (e) {
    // Fallback to browser TTS if server unavailable
    const utt = new SpeechSynthesisUtterance(text);
    utt.lang = lang;
    utt.rate = speed === 'slow' ? 0.75 : speed === 'fast' ? 1.5 : 1.0;
    speechSynthesis.speak(utt);
    addLog('info', 'Using browser TTS fallback');
  }
}

async function loadPresets() {
  try {
    const r = await fetch(serverUrl + '/presets', {
      headers: { 'X-Token': token }
    });
    const data = await r.json();
    const list = document.getElementById('preset-list');
    const saved = data.presets || [];
    saved.forEach(p => {
      if (list.querySelector(`[data-preset="${p.name}"]`)) return;
      const chip = document.createElement('div');
      chip.className = 'preset-chip';
      chip.dataset.preset = p.name;
      chip.textContent = p.name;
      chip.addEventListener('click', () => applyPreset(p.name));
      list.appendChild(chip);
    });
  } catch {}
}

async function savePreset() {
  const name = prompt('Preset name:');
  if (!name) return;
  const preset = {
    name,
    lang: document.getElementById('voice-lang').value,
    speed: document.getElementById('voice-speed').value
  };
  try {
    await fetch(serverUrl + '/presets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Token': token },
      body: JSON.stringify(preset)
    });
    addLog('ok', `Preset saved: ${name}`);
    loadPresets();
  } catch { addLog('warn', 'Could not save preset'); }
}

function applyPreset(name) {
  activePreset = name;
  document.querySelectorAll('.preset-chip').forEach(c => {
    c.style.background = c.dataset.preset === name
      ? 'rgba(123,47,190,0.55)'
      : 'rgba(123,47,190,0.2)';
  });
  addLog('info', `Preset: ${name}`);
}

// ── TRACK MODE ───────────────────────────────────────────────────────
function initTrack() {
  document.getElementById('btn-track').addEventListener('click', runShodan);
  document.getElementById('track-ip').addEventListener('keydown', e => {
    if (e.key === 'Enter') runShodan();
  });
  const drop = document.getElementById('pdf-drop');
  const fileInput = document.getElementById('pdf-file');
  drop.addEventListener('click', () => fileInput.click());
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('dragover'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
  drop.addEventListener('drop', e => {
    e.preventDefault();
    drop.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.type === 'application/pdf') analyzePDF(file);
  });
  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    if (file) analyzePDF(file);
  });
}

async function runShodan() {
  const ip = document.getElementById('track-ip').value.trim();
  if (!ip) return;
  const box = document.getElementById('track-result');
  box.textContent = 'Scanning ' + ip + '...';
  addLog('track', `Shodan scan: ${ip}`);
  try {
    const r = await fetch(serverUrl + '/shodan?ip=' + encodeURIComponent(ip), {
      headers: { 'X-Token': token }
    });
    const data = await r.json();
    if (data.error) { box.textContent = 'Error: ' + data.error; return; }
    let out = '';
    out += `IP:       ${data.ip_str || ip}\n`;
    out += `Org:      ${data.org || 'Unknown'}\n`;
    out += `Country:  ${data.country_name || '—'}\n`;
    out += `City:     ${data.city || '—'}\n`;
    out += `ISP:      ${data.isp || '—'}\n`;
    out += `Hostnames: ${(data.hostnames || []).join(', ') || 'none'}\n`;
    out += `\nOpen Ports:\n`;
    (data.ports || []).forEach(p => { out += `  ${p}\n`; });
    if (data.vulns && data.vulns.length) {
      out += `\nVulns:\n`;
      data.vulns.forEach(v => { out += `  ${v}\n`; });
    }
    box.textContent = out;
    addLog('ok', `Scan done: ${ip} — ${data.org || 'Unknown'}`);
  } catch (e) {
    box.textContent = 'Server unreachable. Check Flask is running.';
    addLog('warn', 'Shodan request failed');
  }
}

async function analyzePDF(file) {
  const box = document.getElementById('pdf-result');
  box.textContent = 'Analyzing ' + file.name + '...';
  addLog('pdf', `Analyzing: ${file.name}`);
  const form = new FormData();
  form.append('file', file);
  try {
    const r = await fetch(serverUrl + '/analyze_pdf', {
      method: 'POST',
      headers: { 'X-Token': token },
      body: form
    });
    const data = await r.json();
    let out = `File: ${file.name}\n\n`;
    if (data.metadata) {
      out += 'Metadata:\n';
      Object.entries(data.metadata).forEach(([k,v]) => { out += `  ${k}: ${v}\n`; });
    }
    if (data.links && data.links.length) {
      out += `\nLinks (${data.links.length}):\n`;
      data.links.forEach(l => { out += `  ${l}\n`; });
    }
    if (data.ips && data.ips.length) {
      out += `\nEmbedded IPs:\n`;
      data.ips.forEach(ip => { out += `  ${ip}\n`; });
    }
    if (data.suspicious) out += `\n\u26A0 SUSPICIOUS CONTENT DETECTED`;
    box.textContent = out;
    addLog('ok', `PDF done: ${file.name}`);
  } catch {
    box.textContent = 'PDF analysis failed. Is Flask running?';
    addLog('warn', 'PDF analysis failed');
  }
}

// ── LOG MODE ─────────────────────────────────────────────────────────
function initLog() {
  document.getElementById('btn-clear-log').addEventListener('click', () => {
    logs = [];
    renderLog();
    fetch(serverUrl + '/log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Token': token },
      body: JSON.stringify({ action: 'clear', timestamp: new Date().toISOString() })
    }).catch(() => {});
  });
}

function addLog(type, message) {
  const entry = { type, message, time: new Date().toLocaleTimeString() };
  logs.unshift(entry);
  if (logs.length > 200) logs.pop();
  // Also POST to server log
  fetch(serverUrl + '/log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Token': token },
    body: JSON.stringify({ ...entry, timestamp: new Date().toISOString() })
  }).catch(() => {});
}

function renderLog() {
  const list = document.getElementById('log-list');
  if (!logs.length) {
    list.innerHTML = '<div class="log-empty">No activity logged yet.</div>';
    return;
  }
  const colors = { voice:'#4CC9F0', track:'#7B2FBE', pdf:'#F72585', ok:'#06D6A0', warn:'#F72585', info:'#4CC9F0' };
  list.innerHTML = logs.map(l => `
    <div class="log-item">
      <span class="log-type" style="color:${colors[l.type]||'#e0e0e0'}">[${l.type.toUpperCase()}]</span>
      ${escHtml(l.message)}
      <div class="log-time">${l.time}</div>
    </div>
  `).join('');
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
