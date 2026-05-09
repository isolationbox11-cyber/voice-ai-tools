/* popup.js — Voice AI Tools v2.1 */

const DEFAULT_SERVER='http://127.0.0.1:5000';
let serverUrl=DEFAULT_SERVER,token='',activePreset='default',logs=[];
let mediaRecorder=null,recordedChunks=[],trainClips=[];

document.addEventListener('DOMContentLoaded',async()=>{
  await loadSettings();
  initTabs();initVoice();initTrain();initTrack();initLog();
  animateBars();checkConnection();
});

async function loadSettings(){
  return new Promise(r=>chrome.storage.local.get(['serverUrl','token'],res=>{
    serverUrl=res.serverUrl||DEFAULT_SERVER;token=res.token||'';r();
  }));
}

// ── TABS
function initTabs(){
  document.querySelectorAll('.tab').forEach(tab=>{
    tab.addEventListener('click',()=>{
      document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('panel-'+tab.dataset.tab).classList.add('active');
      if(tab.dataset.tab==='log') renderLog();
    });
  });
}

// ── CONNECTION
async function checkConnection(){
  const dot=document.getElementById('status-dot');
  const st=document.getElementById('conn-status');
  try{
    const r=await fetch(serverUrl+'/presets',{headers:{'X-Token':token}});
    if(r.ok){
      dot.style.background='#06D6A0';dot.style.boxShadow='0 0 8px #06D6A0';
      st.textContent='\u25CF connected';st.style.color='#06D6A0';
      loadPresets();checkModelStatus();
    } else throw 0;
  } catch{
    dot.style.background='#F72585';dot.style.boxShadow='0 0 8px #F72585';
    st.textContent='\u25CF offline';st.style.color='#F72585';
  }
}

function animateBars(){
  const bars=document.querySelectorAll('.bar');
  setInterval(()=>bars.forEach(b=>{b.style.height=(Math.floor(Math.random()*52)+4)+'px';}),120);
}

// ── VOICE MODE
function initVoice(){
  document.getElementById('btn-speak').addEventListener('click',speakText);
  document.getElementById('btn-save-preset').addEventListener('click',savePreset);
  document.getElementById('btn-clear-voice').addEventListener('click',()=>{document.getElementById('tts-text').value=''});
  document.querySelectorAll('.preset-chip').forEach(c=>c.addEventListener('click',()=>applyPreset(c.dataset.preset)));
}

async function speakText(){
  const text=document.getElementById('tts-text').value.trim();
  if(!text) return;
  const lang=document.getElementById('voice-lang').value;
  const speed=document.getElementById('voice-speed').value;
  addLog('voice',`Spoke: "${text.substring(0,40)}${text.length>40?'...':''}"`);
  try{
    const r=await fetch(serverUrl+'/tts',{method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify({text,lang,speed,preset:activePreset})});
    if(!r.ok) throw 0;
    const audio=new Audio(URL.createObjectURL(await r.blob()));audio.play();
  } catch{
    const u=new SpeechSynthesisUtterance(text);
    u.lang=lang;u.rate=speed==='slow'?.75:speed==='fast'?1.5:1;
    speechSynthesis.speak(u);addLog('info','Browser TTS fallback');
  }
}

async function loadPresets(){
  try{
    const d=await(await fetch(serverUrl+'/presets',{headers:{'X-Token':token}})).json();
    const list=document.getElementById('preset-list');
    (d.presets||[]).forEach(p=>{
      if(list.querySelector(`[data-preset="${p.name}"]`)) return;
      const c=document.createElement('div');c.className='preset-chip';
      c.dataset.preset=p.name;c.textContent=p.name;
      c.addEventListener('click',()=>applyPreset(p.name));list.appendChild(c);
    });
  } catch{}
}

async function savePreset(){
  const name=prompt('Preset name:');if(!name) return;
  const p={name,lang:document.getElementById('voice-lang').value,speed:document.getElementById('voice-speed').value};
  try{
    await fetch(serverUrl+'/presets',{method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify(p)});
    addLog('ok',`Preset saved: ${name}`);loadPresets();
  } catch{addLog('warn','Could not save preset');}
}

function applyPreset(name){
  activePreset=name;
  document.querySelectorAll('.preset-chip').forEach(c=>{
    c.style.background=c.dataset.preset===name?'rgba(123,47,190,.55)':'rgba(123,47,190,.2)';
  });
  addLog('info',`Preset: ${name}`);
}

// ── TRAIN MODE
function initTrain(){
  document.getElementById('record-btn').addEventListener('click',toggleRecord);
  const drop=document.getElementById('audio-drop');
  const fi=document.getElementById('audio-file');
  drop.addEventListener('click',()=>fi.click());
  drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('dragover');});
  drop.addEventListener('dragleave',()=>drop.classList.remove('dragover'));
  drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('dragover');[...e.dataTransfer.files].forEach(addClip);});
  fi.addEventListener('change',()=>[...fi.files].forEach(addClip));
  document.getElementById('btn-train').addEventListener('click',trainVoice);
  document.getElementById('btn-clear-clips').addEventListener('click',()=>{trainClips=[];renderClips();});
  document.getElementById('btn-check-model').addEventListener('click',checkModelStatus);
}

function toggleRecord(){
  if(mediaRecorder&&mediaRecorder.state==='recording'){
    mediaRecorder.stop();
    return;
  }
  navigator.mediaDevices.getUserMedia({audio:true}).then(stream=>{
    recordedChunks=[];
    mediaRecorder=new MediaRecorder(stream);
    mediaRecorder.ondataavailable=e=>{if(e.data.size>0) recordedChunks.push(e.data);};
    mediaRecorder.onstop=()=>{
      stream.getTracks().forEach(t=>t.stop());
      const blob=new Blob(recordedChunks,{type:'audio/webm'});
      const file=new File([blob],`recording_${Date.now()}.webm`,{type:'audio/webm'});
      addClip(file);
      document.getElementById('record-btn').classList.remove('recording');
      document.getElementById('record-icon').textContent='\uD83C\uDFA7';
      document.getElementById('record-label').textContent='Tap to start recording';
    };
    mediaRecorder.start();
    document.getElementById('record-btn').classList.add('recording');
    document.getElementById('record-icon').textContent='\u23F9';
    document.getElementById('record-label').textContent='Recording... tap to stop';
    addLog('train','Recording started');
  }).catch(e=>{
    addLog('warn','Mic access denied: '+e.message);
    setTrainStatus('\u26A0 Microphone access denied. Check browser permissions.');
  });
}

function addClip(file){
  trainClips.push(file);
  renderClips();
  addLog('train',`Clip added: ${file.name}`);
}

function renderClips(){
  const el=document.getElementById('train-clips');
  if(!trainClips.length){
    el.innerHTML='<div style="font-size:.72rem;color:rgba(224,224,224,.25);text-align:center;padding:10px 0">No clips yet</div>';
    return;
  }
  el.innerHTML=trainClips.map((f,i)=>{
    const url=URL.createObjectURL(f);
    return `<div class="clip-item"><audio src="${url}" controls></audio><span>${f.name.substring(0,20)}</span><span class="clip-del" data-i="${i}">&times;</span></div>`;
  }).join('');
  el.querySelectorAll('.clip-del').forEach(btn=>{
    btn.addEventListener('click',()=>{trainClips.splice(+btn.dataset.i,1);renderClips();});
  });
}

async function trainVoice(){
  if(!trainClips.length){
    setTrainStatus('\u26A0 Add at least one audio clip first.');return;
  }
  setTrainStatus('\u23F3 Uploading clips and training...');
  showProgress();
  const form=new FormData();
  trainClips.forEach(f=>form.append('files',f));
  try{
    const r=await fetch(serverUrl+'/train',{method:'POST',headers:{'X-Token':token},body:form});
    const d=await r.json();
    if(d.error){setTrainStatus('\u274C Error: '+d.error);return;}
    const msg=`\u2705 ${d.count} clip(s) saved. Status: ${d.status}${d.note?' — '+d.note:''}`;
    setTrainStatus(msg);
    addLog('train',`Training: ${d.status}, ${d.count} clips`);
  } catch(e){
    setTrainStatus('\u274C Server unreachable. Is Flask running?');
    addLog('warn','Train failed');
  }
  hideProgress();
}

async function checkModelStatus(){
  try{
    const r=await fetch(serverUrl+'/model_status',{headers:{'X-Token':token}});
    const d=await r.json();
    if(d.trained){
      setTrainStatus(`\u2705 Model ready \u2014 ${d.count} clip(s) \u2014 trained ${d.trained_at} \u2014 ${d.status}`);
    } else {
      setTrainStatus('No voice model trained yet. Record samples or upload audio below.');
    }
  } catch{
    setTrainStatus('\u26A0 Could not reach server.');
  }
}

function setTrainStatus(msg){
  document.getElementById('train-status').textContent=msg;
}
function showProgress(){
  const w=document.getElementById('train-progress-wrap');
  const b=document.getElementById('train-progress');
  w.style.display='block';b.style.width='0%';
  let p=0;const t=setInterval(()=>{p=Math.min(p+5,90);b.style.width=p+'%';if(p>=90)clearInterval(t);},200);
}
function hideProgress(){
  const b=document.getElementById('train-progress');
  b.style.width='100%';
  setTimeout(()=>{document.getElementById('train-progress-wrap').style.display='none';},600);
}

// ── TRACK MODE
function initTrack(){
  document.getElementById('btn-track').addEventListener('click',runShodan);
  document.getElementById('track-ip').addEventListener('keydown',e=>{if(e.key==='Enter')runShodan();});
  const drop=document.getElementById('pdf-drop'),fi=document.getElementById('pdf-file');
  drop.addEventListener('click',()=>fi.click());
  drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('dragover');});
  drop.addEventListener('dragleave',()=>drop.classList.remove('dragover'));
  drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('dragover');const f=e.dataTransfer.files[0];if(f&&f.type==='application/pdf')analyzePDF(f);});
  fi.addEventListener('change',()=>{if(fi.files[0])analyzePDF(fi.files[0]);});
}

async function runShodan(){
  const ip=document.getElementById('track-ip').value.trim();if(!ip)return;
  const box=document.getElementById('track-result');
  box.textContent='Scanning '+ip+'...';
  addLog('track',`Shodan: ${ip}`);
  try{
    const d=await(await fetch(serverUrl+'/shodan?ip='+encodeURIComponent(ip),{headers:{'X-Token':token}})).json();
    if(d.error){box.textContent='Error: '+d.error;return;}
    box.textContent=`IP:       ${d.ip_str||ip}\nOrg:      ${d.org||'?'}\nCountry:  ${d.country_name||'?'}\nCity:     ${d.city||'?'}\nISP:      ${d.isp||'?'}\nHostnames:${(d.hostnames||[]).join(', ')||'none'}\n\nOpen Ports:\n${(d.ports||[]).map(p=>'  '+p).join('\n')}${d.vulns&&d.vulns.length?'\n\nVulns:\n'+(d.vulns.map(v=>'  '+v).join('\n')):''}`;
    addLog('ok',`Scan done: ${ip}`);
  } catch{box.textContent='Server unreachable.';addLog('warn','Shodan failed');}
}

async function analyzePDF(file){
  const box=document.getElementById('pdf-result');
  box.textContent='Analyzing '+file.name+'...';
  addLog('pdf',`PDF: ${file.name}`);
  const form=new FormData();form.append('file',file);
  try{
    const d=await(await fetch(serverUrl+'/analyze_pdf',{method:'POST',headers:{'X-Token':token},body:form})).json();
    let out=`File: ${file.name}\nPages: ${d.pages||'?'}\n`;
    if(d.metadata&&Object.keys(d.metadata).length){out+='\nMetadata:\n'+Object.entries(d.metadata).map(([k,v])=>`  ${k}: ${v}`).join('\n');}
    if(d.links&&d.links.length){out+=`\n\nLinks (${d.links.length}):\n`+d.links.map(l=>'  '+l).join('\n');}
    if(d.ips&&d.ips.length){out+=`\n\nEmbedded IPs:\n`+d.ips.map(i=>'  '+i).join('\n');}
    if(d.suspicious) out+='\n\n\u26A0 SUSPICIOUS CONTENT DETECTED';
    box.textContent=out;
    addLog('ok',`PDF done: ${file.name}`);
  } catch{box.textContent='PDF analysis failed. Is Flask running?';addLog('warn','PDF failed');}
}

// ── LOG MODE
function initLog(){
  document.getElementById('btn-clear-log').addEventListener('click',()=>{
    logs=[];renderLog();
    fetch(serverUrl+'/log',{method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify({action:'clear',timestamp:new Date().toISOString()})}).catch(()=>{});
  });
}

function addLog(type,message){
  const e={type,message,time:new Date().toLocaleTimeString()};
  logs.unshift(e);if(logs.length>200)logs.pop();
  fetch(serverUrl+'/log',{method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify({...e,timestamp:new Date().toISOString()})}).catch(()=>{});
}

function renderLog(){
  const list=document.getElementById('log-list');
  if(!logs.length){list.innerHTML='<div class="log-empty">No activity logged yet.</div>';return;}
  const c={voice:'#4CC9F0',train:'#06D6A0',track:'#7B2FBE',pdf:'#F72585',ok:'#06D6A0',warn:'#F72585',info:'#4CC9F0'};
  list.innerHTML=logs.map(l=>`<div class="log-item"><span class="log-type" style="color:${c[l.type]||'#e0e0e0'}">[${l.type.toUpperCase()}]</span> ${esc(l.message)}<div class="log-time">${l.time}</div></div>`).join('');
}

function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
