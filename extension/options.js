const token=document.querySelector('#token');
const status=document.querySelector('#status');
token.value=(await chrome.storage.local.get('token')).token||'';
document.querySelector('#reveal').onclick=event=>{token.type=token.type==='password'?'text':'password';event.target.textContent=token.type==='password'?'Show':'Hide';};
document.querySelector('#settings').onsubmit=async event=>{
  event.preventDefault();
  if(token.value.trim().length<24) {status.textContent='Paste the complete connection key from your Mac.';return;}
  await chrome.storage.local.set({token:token.value.trim()});
  status.textContent='Connection saved. Check the service, then open a video.';
};
document.querySelector('#check').onclick=async()=>{
  try {const health=await fetch('http://127.0.0.1:8766/health',{signal:AbortSignal.timeout(3000)}).then(r=>r.json());status.textContent=health.ready?'Local speech model is ready. The key is verified when you start captions.':'Local service is loading its speech model…';}
  catch {status.textContent='Cannot reach the local service. Run ./voice2text-run start.';}
};
