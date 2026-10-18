const status=document.querySelector('#status');
const serviceStatus=document.querySelector('#service-status');
const serviceStart=document.querySelector('#service-start');
const start=document.querySelector('#start');
const stop=document.querySelector('#stop');
const language=document.querySelector('#language');
const message=data=>chrome.runtime.sendMessage({target:'background',...data});
language.value=(await chrome.storage.local.get('language')).language||'auto';
language.onchange=()=>chrome.storage.local.set({language:language.value});
document.querySelector('#settings').onclick=()=>chrome.runtime.openOptionsPage();
let errorUntil=0;

function nativeRequest(data) {
  return new Promise((resolve,reject)=>chrome.runtime.sendNativeMessage('com.voice2text.host',data,response=>{
    const error=chrome.runtime.lastError;
    if(error) reject(new Error(error.message));
    else if(!response?.ok) reject(new Error(response?.error||'The local launcher could not start the service.'));
    else resolve(response);
  }));
}

async function refreshService() {
  try {
    const health=await fetch('http://127.0.0.1:8766/health',{signal:AbortSignal.timeout(1200)}).then(r=>r.json());
    if(health.ready) {
      serviceStatus.className='ready';
      serviceStatus.textContent=`Running · 127.0.0.1:${health.port||8766} · PID ${health.pid||'unknown'}`;
      serviceStart.disabled=true;
      serviceStart.textContent='Running';
    } else {
      serviceStatus.className='loading';
      serviceStatus.textContent=`Starting · 127.0.0.1:${health.port||8766} · PID ${health.pid||'unknown'}`;
      serviceStart.disabled=true;
      serviceStart.textContent='Starting…';
    }
  } catch {
    serviceStatus.className='';
    serviceStatus.textContent='Not running · 127.0.0.1:8766';
    serviceStart.disabled=false;
    serviceStart.textContent='Start backend';
  }
}

async function refresh() {
  const state=await message({type:'GET_STATUS'}).catch(()=>({state:'idle'}));
  const active=['starting','recording','stopping'].includes(state.state);
  start.disabled=active;stop.disabled=!active||state.state==='stopping';
  if(Date.now()<errorUntil) return;
  if(active) {status.textContent={starting:'Connecting…',recording:'Listening to your selected tab.',stopping:'Finishing the last words…'}[state.state];return;}
  if(state.error) {status.textContent=state.error;return;}
  const {token}=await chrome.storage.local.get('token');
  if(!token) {status.textContent='Add your local connection key in Settings.';return;}
  try {const health=await fetch('http://127.0.0.1:8766/health',{signal:AbortSignal.timeout(1200)}).then(r=>r.json());status.textContent=health.ready?(health.busy?'Another browser is using Voice2Text.':'Your Mac is ready. Open a video and start.'):'The speech model is loading…';}
  catch {status.textContent='Local service is offline. Start it above or run voice2text-run start.';}
}

serviceStart.onclick=async()=>{
  serviceStart.disabled=true;
  serviceStart.textContent='Starting…';
  serviceStatus.className='loading';
  serviceStatus.textContent='Starting the local speech model…';
  try {
    await nativeRequest({command:'start'});
  } catch(error) {
    serviceStatus.className='';
    serviceStatus.textContent='Launcher unavailable. Run voice2text-run and choose Install browser launcher, then restart the browser.';
    serviceStart.disabled=false;
    serviceStart.textContent='Retry';
    serviceStart.title=error.message;
    return;
  }
  await refreshService();
  await refresh();
};

start.onclick=async()=>{
  start.disabled=true;status.textContent='Connecting…';
  try {
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    const result=await message({type:'START',tabId:tab.id,language:language.value});
    if(!result?.ok) throw new Error(result?.error||'Could not start captions.');
  } catch(error) {status.textContent=error.message;errorUntil=Date.now()+6000;}
  await refresh();
};
stop.onclick=async()=>{await message({type:'STOP'});await refresh();};
await refreshService();
await refresh();
setInterval(()=>{refreshService();refresh();},2000);
