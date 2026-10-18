const OFFSCREEN=chrome.runtime.getURL('offscreen.html');
let operation=Promise.resolve();

async function hasOffscreen() {
  return (await chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT'],documentUrls:[OFFSCREEN]})).length>0;
}
async function getStatus() {
  return await hasOffscreen()?chrome.runtime.sendMessage({target:'offscreen',type:'GET_STATUS'}):{state:'idle'};
}
async function waitForRelease(tabId) {
  const deadline=Date.now()+18000;
  while(Date.now()<deadline) {
    const current=await getStatus();
    const captured=await chrome.tabCapture.getCapturedTabs();
    if(current.released!==false && !captured.some(item=>item.tabId===tabId && ['pending','active'].includes(item.status))) return;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw new Error('The previous transcription is still finishing. Try again shortly.');
}
async function start(tabId,language) {
  const current=await getStatus();
  if(['starting','recording','stopping'].includes(current.state)) throw new Error('Stop the current transcription first.');
  await waitForRelease(tabId);
  const tab=await chrome.tabs.get(tabId);
  if(!/^https?:\/\//.test(tab.url||'')) throw new Error('Open a regular video webpage to start. Browser settings pages are not supported.');
  const {token}=await chrome.storage.local.get('token');
  if(!token) throw new Error('Open Settings and add your local connection key first.');
  const health=await fetch('http://127.0.0.1:8766/health',{signal:AbortSignal.timeout(3000)}).then(r=>r.json()).catch(()=>{throw new Error('Start the Voice2Text local service, then try again.');});
  if(!health.ready) throw new Error('The speech model is still loading. Try again shortly.');
  if(health.busy) throw new Error('Voice2Text is already transcribing in another browser.');
  await chrome.scripting.insertCSS({target:{tabId},files:['content.css']});
  await chrome.scripting.executeScript({target:{tabId},files:['content.js']});
  await chrome.tabs.sendMessage(tabId,{target:'content',type:'RESET'});
  if(!await hasOffscreen()) await chrome.offscreen.createDocument({url:'offscreen.html',reasons:['USER_MEDIA'],justification:'Capture selected tab audio for local live captions.'});
  const streamId=await chrome.tabCapture.getMediaStreamId({targetTabId:tabId});
  return chrome.runtime.sendMessage({target:'offscreen',type:'START',tabId,streamId,token,language});
}
async function restart(tabId,language) {
  const current=await getStatus();
  if(['starting','recording','stopping'].includes(current.state)) {
    if(current.tabId!==tabId) throw new Error('Another tab is being transcribed.');
    const result=await chrome.runtime.sendMessage({target:'offscreen',type:'STOP'});
    if(!result?.ok) throw new Error(result?.error||'Could not stop the current transcription.');
  }
  await waitForRelease(tabId);
  return start(tabId,language);
}

chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(message.target!=='background' || (sender.id && sender.id!==chrome.runtime.id)) return;
  if(sender.url===OFFSCREEN) {
    if(message.type==='STATUS') {
      chrome.action.setBadgeText({text:message.state==='recording'?'ON':''}).catch(()=>{});
      chrome.action.setBadgeBackgroundColor({color:'#236caa'}).catch(()=>{});
    }
    chrome.tabs.sendMessage(message.tabId,{...message,target:'content'}).catch(()=>{});
    return;
  }
  const extensionPage=!sender.tab && sender.url?.startsWith(chrome.runtime.getURL(''));
  const contentStop=sender.tab && message.type==='STOP';
  const contentStart=sender.tab && message.type==='START';
  const contentRestart=sender.tab && message.type==='RESTART';
  if(!extensionPage && !contentStop && !contentStart && !contentRestart) return;
  const run=async()=>{
    if(message.type==='GET_STATUS') return getStatus();
    if(message.type==='START' || message.type==='RESTART') {
      const language=sender.tab?(await chrome.storage.local.get('language')).language||'auto':message.language;
      const tabId=sender.tab?.id??message.tabId;
      return message.type==='RESTART'?restart(tabId,language):start(tabId,language);
    }
    if(message.type==='STOP') {
      const current=await getStatus();
      if(sender.tab && sender.tab.id!==current.tabId) throw new Error('This tab is not being transcribed.');
      if(await hasOffscreen()) return chrome.runtime.sendMessage({target:'offscreen',type:'STOP'});
      return {ok:true};
    }
    return {ok:false};
  };
  operation=operation.then(run,run);
  operation.then(reply,error=>{
    if(message.type==='START' || message.type==='RESTART') {
      const tabId=sender.tab?.id??message.tabId;
      chrome.tabs.sendMessage(tabId,{target:'content',type:'STATUS',state:'error',error:error.message}).catch(()=>{});
    }
    reply({ok:false,error:error.message});
  });
  return true;
});

async function stopTab(tabId) {
  const current=await getStatus();
  if(current.tabId===tabId && ['starting','recording'].includes(current.state)) await chrome.runtime.sendMessage({target:'offscreen',type:'STOP'});
}
chrome.tabs.onRemoved.addListener(tabId=>stopTab(tabId).catch(()=>{}));
