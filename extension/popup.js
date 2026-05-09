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
  // popup.html uses id="tts-text"
  const txt=document.getElementById('tts-text');
  const speedSel=document.getElementById('voice-speed');
  const connStatus=document.getElementById('conn-status');
  if(!btn)return;

  // Preset chips
  document.querySelectorAll('.preset-chip').forEach(chip=>{
    chip.addEventListener('click',()=>{
      document.querySelectorAll('.preset-chip').forEach(c=>c.classList.remove('active'));
      chip.classList.add('active');
      activePreset=chip.dataset.preset||'default';
    });
  });

  btn.addEventListener('click',async()=>{
    const text=(txt&&txt.value||'').trim();
    if(!text){if(connStatus)connStatus.textContent='Enter text first.';return;}
    if(connStatus)connStatus.textContent='Speaking...';
    btn.disabled=true;
    try{
      // Delegate fetch + playback to the background service worker so audio
      // continues even if this popup closes immediately after the click.
      const resp=await chrome.runtime.sendMessage({
        type:'TTS_REQUEST',
        text,
        token,
        serverUrl,
        speed:speedSel?speedSel.value:'normal',
        callType:activePreset
      });
      if(resp&&resp.ok){
        if(connStatus)connStatus.textContent='\u25cf\u00a0playing';
        addLog('voice','Spoke: '+text.substring(0,40));
      } else {
        if(connStatus)connStatus.textContent='Error: '+(resp&&resp.error||'unknown');
        addLog('warn','Voice error: '+(resp&&resp.error||'unknown'));
      }
    }catch(e){
      if(connStatus)connStatus.textContent='Error \u2013 Is Flask running?';
      addLog('warn','Voice error: '+e.message);
    }
    btn.disabled=false;
  });
}

// --- TRAIN
function initTrain(){
  const startBtn=document.getElementById('record-btn');
  const submitBtn=document.getElementById('btn-train');
  const status=document.getElementById('train-status');
  const clipsContainer=document.getElementById('train-clips');
  if(!startBtn)return;

  let isRecording=false;

  startBtn.addEventListener('click',async()=>{
    if(!isRecording){
      try{
        const stream=await navigator.mediaDevices.getUserMedia({audio:true});
        mediaRecorder=new MediaRecorder(stream);
        recordedChunks=[];
        mediaRecorder.ondataavailable=e=>recordedChunks.push(e.data);
        mediaRecorder.start();
        isRecording=true;
        const icon=document.getElementById('record-icon');
        const label=document.getElementById('record-label');
        if(icon)icon.textContent='\u23f9';
        if(label)label.textContent='Tap to stop recording';
        startBtn.classList.add('recording');
        if(status)status.textContent='Recording...';
        addLog('train','Recording started');
      }catch(e){
        if(status)status.textContent='Mic error: '+e.message;
        addLog('warn','Mic error: '+e.message);
      }
    } else {
      if(mediaRecorder&&mediaRecorder.state==='recording'){
        mediaRecorder.stop();
        mediaRecorder.onstop=()=>{
          const blob=new Blob(recordedChunks,{type:'audio/webm'});
          trainClips.push(blob);
          if(status)status.textContent='Clip saved ('+trainClips.length+' total). Record more or submit.';
          addLog('train','Clip '+trainClips.length+' saved');
          renderClips(clipsContainer);
        };
        isRecording=false;
        const icon=document.getElementById('record-icon');
        const label=document.getElementById('record-label');
        if(icon)icon.textContent='\u{1F3A7}';
        if(label)label.textContent='Tap to start recording';
        startBtn.classList.remove('recording');
      }
    }
  });

  // Audio file drop/upload
  const audioDrop=document.getElementById('audio-drop');
  const audioFile=document.getElementById('audio-file');
  if(audioDrop){
    audioDrop.addEventListener('click',()=>audioFile&&audioFile.click());
    audioDrop.addEventListener('dragover',e=>{e.preventDefault();audioDrop.classList.add('dragover');});
    audioDrop.addEventListener('dragleave',()=>audioDrop.classList.remove('dragover'));
    audioDrop.addEventListener('drop',e=>{
      e.preventDefault();audioDrop.classList.remove('dragover');
      const files=Array.from(e.dataTransfer.files).filter(f=>f.type.startsWith('audio/'));
      files.forEach(f=>trainClips.push(f));
      if(status)status.textContent=trainClips.length+' clip(s) ready.';
      renderClips(clipsContainer);
    });
  }
  if(audioFile){
    audioFile.addEventListener('change',()=>{
      Array.from(audioFile.files).forEach(f=>trainClips.push(f));
      if(status)status.textContent=trainClips.length+' clip(s) ready.';
      renderClips(clipsContainer);
      audioFile.value='';
    });
  }

  if(submitBtn){
    submitBtn.addEventListener('click',async()=>{
      if(!trainClips.length){if(status)status.textContent='Record at least one clip first.';return;}
      if(status)status.textContent='Uploading '+trainClips.length+' clip(s)...';
      submitBtn.disabled=true;
      let ok=0;
      for(let i=0;i<trainClips.length;i++){
        const fd=new FormData();
        fd.append('files',trainClips[i],'clip_'+i+'.webm');
        try{
          const r=await fetch(serverUrl+'/train',{method:'POST',
            headers:{'X-Token':token},body:fd});
          const d=await r.json();
          if(d.ok)ok++;
        }catch(e){ addLog('warn','Upload error clip '+i+': '+e.message); }
      }
      if(status)status.textContent=ok+'/'+trainClips.length+' clips uploaded.';
      addLog('train','Submitted '+ok+' clips');
      trainClips=[];
      renderClips(clipsContainer);
      submitBtn.disabled=false;
    });
  }

  const clearBtn=document.getElementById('btn-clear-clips');
  if(clearBtn){
    clearBtn.addEventListener('click',()=>{
      trainClips=[];
      renderClips(clipsContainer);
      if(status)status.textContent='Clips cleared.';
    });
  }

  const checkBtn=document.getElementById('btn-check-model');
  if(checkBtn){
    checkBtn.addEventListener('click',async()=>{
      try{
        const r=await fetch(serverUrl+'/model_status',{headers:{'X-Token':token}});
        const d=await r.json();
        if(status)status.textContent=d.trained?'Model ready ('+d.count+' samples, trained '+d.trained_at+')':'No model trained yet.';
      }catch(e){
        if(status)status.textContent='Could not check model status.';
      }
    });
  }
}

function renderClips(container){
  if(!container)return;
  if(!trainClips.length){container.innerHTML='<div style="font-size:.72rem;color:rgba(224,224,224,.25);text-align:center;padding:10px 0">No clips yet</div>';return;}
  container.innerHTML=trainClips.map((_,i)=>`<div class="clip-item"><span style="flex:1">Clip ${i+1}</span><span class="clip-del" data-i="${i}">\u2715</span></div>`).join('');
  container.querySelectorAll('.clip-del').forEach(el=>{
    el.addEventListener('click',()=>{
      trainClips.splice(parseInt(el.dataset.i),1);
      renderClips(container);
    });
  });
}

// --- TRACK
function initTrack(){
  const scanBtn=document.getElementById('btn-track');
  const ipInput=document.getElementById('track-ip');
  const trackBox=document.getElementById('track-result');
  const pdfDrop=document.getElementById('pdf-drop');
  const pdfInput=document.getElementById('pdf-file');
  const pdfBox=document.getElementById('pdf-result');
  if(!scanBtn)return;

  scanBtn.addEventListener('click',async()=>{
    const ip=(ipInput&&ipInput.value||'').trim();
    if(!ip){if(trackBox)trackBox.textContent='Enter an IP.';return;}
    if(trackBox)trackBox.textContent='Scanning...';
    try{
      // GET /shodan?ip=...
      const r=await fetch(serverUrl+'/shodan?ip='+encodeURIComponent(ip),{
        headers:{'X-Token':token}});
      const d=await r.json();
      const lines=['IP: '+(d.ip_str||ip),'Org: '+(d.org||'N/A'),'Country: '+(d.country_name||'N/A')];
      if(d.ports&&d.ports.length)lines.push('Ports: '+d.ports.join(', '));
      if(trackBox)trackBox.textContent=lines.join('\n');
      addLog('track','Scanned IP: '+ip);
    }catch(e){
      if(trackBox)trackBox.textContent='Scan failed. Is Flask running?';
      addLog('warn','Scan error: '+e.message);
    }
  });

  if(pdfDrop&&pdfInput){
    pdfDrop.addEventListener('click',()=>pdfInput.click());
    pdfDrop.addEventListener('dragover',e=>{e.preventDefault();pdfDrop.classList.add('dragover');});
    pdfDrop.addEventListener('dragleave',()=>pdfDrop.classList.remove('dragover'));
    pdfDrop.addEventListener('drop',e=>{e.preventDefault();pdfDrop.classList.remove('dragover');if(e.dataTransfer.files[0])handlePdf(e.dataTransfer.files[0],pdfBox);});
    pdfInput.addEventListener('change',()=>{if(pdfInput.files[0])handlePdf(pdfInput.files[0],pdfBox);});
  }
}

async function handlePdf(file,box){
  if(box)box.textContent='Analyzing PDF: '+file.name+'...';
  const fd=new FormData();
  fd.append('file',file);
  try{
    const r=await fetch(serverUrl+'/analyze_pdf',{method:'POST',
      headers:{'X-Token':token},body:fd});
    const d=await r.json();
    const lines=['PDF: '+file.name,'Pages: '+(d.pages||'?')];
    if(d.metadata)Object.entries(d.metadata).forEach(([k,v])=>lines.push('  '+k+': '+v));
    if(d.links&&d.links.length){lines.push('','Links ('+d.links.length+'):');d.links.forEach(l=>lines.push(' '+l));}
    if(d.ips&&d.ips.length){lines.push('','Embedded IPs:');d.ips.forEach(i=>lines.push(' '+i));}
    if(d.suspicious)lines.push('','\u26A0 SUSPICIOUS CONTENT DETECTED');
    if(box)box.textContent=lines.join('\n');
    addLog('ok','PDF done: '+file.name);
  }catch{if(box)box.textContent='PDF analysis failed. Is Flask running?';addLog('warn','PDF failed');}
}

// --- LOG MODE
function initLog(){
  const clearBtn=document.getElementById('btn-clear-log');
  if(clearBtn)clearBtn.addEventListener('click',()=>{
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

async function checkConnection(){
  const dot=document.getElementById('status-dot');
  const label=document.getElementById('conn-status');
  if(!dot)return;
  try{
    // Use /health (not /status) – the Flask server exposes /health
    const r=await fetch(serverUrl+'/health',{headers:{'X-Token':token}});
    if(r.ok){dot.style.background='#06D6A0';if(label)label.textContent='\u25cf connected';}
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
