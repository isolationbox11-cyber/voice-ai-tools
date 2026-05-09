/* popup.js - Voice AI Tools v2.2 - safe storage fix */

const DEFAULT_SERVER='http://127.0.0.1:5000';
let serverUrl=DEFAULT_SERVER,token='',activePreset='default',logs=[];
let mediaRecorder=null,recordedChunks=[],trainClips=[];

// Safe storage wrapper - works inside extension AND as plain HTML
const store={
  get(keys,cb){
    try{
      if(typeof chrome!=='undefined'&&chrome.storage&&chrome.storage.local){
        chrome.storage.local.get(keys,cb);
      } else {
        const res={};
        keys.forEach(k=>{ const v=localStorage.getItem(k); if(v!==null)res[k]=v; });
        cb(res);
      }
    }catch(e){ cb({}); }
  },
  set(obj){
    try{
      if(typeof chrome!=='undefined'&&chrome.storage&&chrome.storage.local){
        chrome.storage.local.set(obj);
      } else {
        Object.entries(obj).forEach(([k,v])=>localStorage.setItem(k,v));
      }
    }catch(e){}
  }
};

document.addEventListener('DOMContentLoaded',async()=>{
  await loadSettings();
  initTabs();initVoice();initTrain();initTrack();initLog();
  animateBars();checkConnection();
});

async function loadSettings(){
  return new Promise(r=>store.get(['serverUrl','token'],res=>{
    serverUrl=res.serverUrl||DEFAULT_SERVER;
    token=res.token||'';
    r();
  }));
}

// --- TABS
function initTabs(){
  document.querySelectorAll('.tab').forEach(tab=>{
    tab.addEventListener('click',()=>{
      document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('panel-'+tab.dataset.tab).classList.add('active');
    });
  });
}

// --- VOICE
function initVoice(){
  const btn=document.getElementById('btn-speak');
  const txt=document.getElementById('voice-text');
  const preset=document.getElementById('preset-select');
  const status=document.getElementById('voice-status');
  if(!btn)return;
  loadPresets(preset);
  btn.addEventListener('click',async()=>{
    const text=txt.value.trim();
    if(!text){status.textContent='Enter text first.';return;}
    status.textContent='Speaking...';
    btn.disabled=true;
    try{
      const r=await fetch(serverUrl+'/speak',{method:'POST',
        headers:{'Content-Type':'application/json','X-Token':token},
        body:JSON.stringify({text,preset:preset.value||activePreset})});
      const d=await r.json();
      status.textContent=d.status||'Done';
      addLog('voice','Spoke: '+text.substring(0,40));
    }catch(e){
      status.textContent='Error - Is Flask running?';
      addLog('warn','Voice error: '+e.message);
    }
    btn.disabled=false;
  });
}

async function loadPresets(sel){
  if(!sel)return;
  try{
    const r=await fetch(serverUrl+'/presets',{headers:{'X-Token':token}});
    const d=await r.json();
    sel.innerHTML='';
    (d.presets||[]).forEach(p=>{
      const o=document.createElement('option');
      o.value=o.textContent=p;
      sel.appendChild(o);
    });
  }catch(e){sel.innerHTML='<option>default</option>';}
}

// --- TRAIN
function initTrain(){
  const startBtn=document.getElementById('btn-train-start');
  const stopBtn=document.getElementById('btn-train-stop');
  const submitBtn=document.getElementById('btn-train-submit');
  const status=document.getElementById('train-status');
  const voiceName=document.getElementById('train-voice-name');
  if(!startBtn)return;

  startBtn.addEventListener('click',async()=>{
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:true});
      mediaRecorder=new MediaRecorder(stream);
      recordedChunks=[];
      mediaRecorder.ondataavailable=e=>recordedChunks.push(e.data);
      mediaRecorder.start();
      startBtn.disabled=true;
      stopBtn.disabled=false;
      status.textContent='Recording...';
      addLog('train','Recording started');
    }catch(e){
      status.textContent='Mic error: '+e.message;
      addLog('warn','Mic error: '+e.message);
    }
  });

  stopBtn.addEventListener('click',()=>{
    if(mediaRecorder&&mediaRecorder.state==='recording'){
      mediaRecorder.stop();
      mediaRecorder.onstop=()=>{
        const blob=new Blob(recordedChunks,{type:'audio/webm'});
        trainClips.push(blob);
        status.textContent='Clip saved ('+trainClips.length+' total). Record more or submit.';
        addLog('train','Clip '+trainClips.length+' saved');
      };
      startBtn.disabled=false;
      stopBtn.disabled=true;
    }
  });

  submitBtn.addEventListener('click',async()=>{
    if(!trainClips.length){status.textContent='Record at least one clip first.';return;}
    const name=(voiceName&&voiceName.value.trim())||'my_voice';
    status.textContent='Uploading '+trainClips.length+' clip(s)...';
    submitBtn.disabled=true;
    let ok=0;
    for(let i=0;i<trainClips.length;i++){
      const fd=new FormData();
      fd.append('audio',trainClips[i],'clip_'+i+'.webm');
      fd.append('voice_name',name);
      try{
        const r=await fetch(serverUrl+'/train',{method:'POST',
          headers:{'X-Token':token},body:fd});
        const d=await r.json();
        if(d.status==='ok')ok++;
      }catch(e){ addLog('warn','Upload error clip '+i+': '+e.message); }
    }
    status.textContent=ok+'/'+trainClips.length+' clips uploaded. Training queued for: '+name;
    addLog('train','Submitted '+ok+' clips for voice: '+name);
    trainClips=[];
    submitBtn.disabled=false;
  });
}

// --- TRACK
function initTrack(){
  const scanBtn=document.getElementById('btn-scan');
  const pdfBtn=document.getElementById('btn-analyze-pdf');
  const pdfInput=document.getElementById('pdf-input');
  const ipInput=document.getElementById('ip-input');
  const trackBox=document.getElementById('track-output');
  if(!scanBtn)return;

  scanBtn.addEventListener('click',async()=>{
    const ip=ipInput.value.trim();
    if(!ip){trackBox.textContent='Enter an IP.';return;}
    trackBox.textContent='Scanning...';
    try{
      const r=await fetch(serverUrl+'/shodan',{method:'POST',
        headers:{'Content-Type':'application/json','X-Token':token},
        body:JSON.stringify({ip})});
      const d=await r.json();
      const lines=['IP: '+d.ip_str,'Org: '+(d.org||'N/A'),'Country: '+(d.country_name||'N/A')];
      if(d.ports&&d.ports.length)lines.push('Ports: '+d.ports.join(', '));
      trackBox.textContent=lines.join('\n');
      addLog('track','Scanned IP: '+ip);
    }catch(e){
      trackBox.textContent='Scan failed. Is Flask running?';
      addLog('warn','Scan error: '+e.message);
    }
  });

  if(pdfBtn&&pdfInput){
    pdfBtn.addEventListener('click',()=>pdfInput.click());
    pdfInput.addEventListener('change',async()=>{
      const file=pdfInput.files[0];
      if(!file)return;
      trackBox.textContent='Analyzing PDF: '+file.name+'...';
      const fd=new FormData();
      fd.append('pdf',file);
      try{
        const r=await fetch(serverUrl+'/analyze_pdf',{method:'POST',
          headers:{'X-Token':token},body:fd});
        const d=await r.json();
        const lines=['PDF: '+file.name,'Pages: '+(d.pages||'?'),'Author: '+(d.metadata&&d.metadata.Author||'N/A')];
        if(d.metadata)Object.entries(d.metadata).forEach(([k,v])=>lines.push('  '+k+': '+v));
        if(d.links&&d.links.length){lines.push('','Links ('+d.links.length+'):');d.links.forEach(l=>lines.push(' '+l));}
        if(d.ips&&d.ips.length){lines.push('','Embedded IPs:');d.ips.forEach(i=>lines.push(' '+i));}
        if(d.suspicious)lines.push('','\u26A0 SUSPICIOUS CONTENT DETECTED');
        trackBox.textContent=lines.join('\n');
        addLog('ok','PDF done: '+file.name);
      }catch{trackBox.textContent='PDF analysis failed. Is Flask running?';addLog('warn','PDF failed');}
    });
  }
}

// --- LOG MODE
function initLog(){
  document.getElementById('btn-clear-log').addEventListener('click',()=>{
    logs=[];renderLog();
    fetch(serverUrl+'/log',{method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify({action:'clear'})}).catch(()=>{});
  });
}

function addLog(type,message){
  const e={type,message,time:new Date().toLocaleTimeString()};
  logs.unshift(e);if(logs.length>200)logs.pop();
  fetch(serverUrl+'/log',{method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify({...e,time:Date.now()})}).catch(()=>{});
  renderLog();
}

function renderLog(){
  const list=document.getElementById('log-list');
  if(!list)return;
  if(!logs.length){list.innerHTML='<div class="log-empty">No activity logged yet.</div>';return;}
  const c={voice:'#4CC9F0',train:'#06D6A0',track:'#7B2FBE',pdf:'#F72585',ok:'#06D6A0',warn:'#F72585',info:'#4CC9F0'};
  list.innerHTML=logs.map(l=>`<div class="log-item"><span class="log-type" style="color:${c[l.type]||'#e0e0e0'}">[${l.type.toUpperCase()}]</span> <span class="log-time">${l.time}</span> ${esc(l.message)}</div>`).join('');
}

function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

// --- SETTINGS
document.addEventListener('DOMContentLoaded',()=>{
  const sUrl=document.getElementById('server-url');
  const sTok=document.getElementById('api-token');
  const saveBtn=document.getElementById('btn-save-settings');
  if(sUrl)sUrl.value=serverUrl;
  if(sTok)sTok.value=token;
  if(saveBtn)saveBtn.addEventListener('click',()=>{
    serverUrl=sUrl.value.trim()||DEFAULT_SERVER;
    token=sTok.value.trim();
    store.set({serverUrl,token});
    checkConnection();
    addLog('info','Settings saved');
  });
});

async function checkConnection(){
  const dot=document.getElementById('conn-dot');
  const label=document.getElementById('conn-label');
  if(!dot)return;
  try{
    const r=await fetch(serverUrl+'/status',{headers:{'X-Token':token}});
    if(r.ok){dot.style.background='#06D6A0';if(label)label.textContent='Connected';}
    else{dot.style.background='#F72585';if(label)label.textContent='Server Error';}
  }catch{
    dot.style.background='#888';if(label)label.textContent='Offline';
  }
}

function animateBars(){
  const bars=document.querySelectorAll('.bar');
  if(!bars.length)return;
  setInterval(()=>{
    bars.forEach(b=>{
      const h=Math.floor(Math.random()*80)+10;
      b.style.height=h+'%';
    });
  },200);
}
