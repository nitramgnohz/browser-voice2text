(async () => {
  try { globalThis.__voice2textCleanup?.(); } catch {}
  document.getElementById('voice2text-panel')?.remove();
  const {createTranscript,reduceTranscript,clearTranscript,transcriptText}=await import(chrome.runtime.getURL('protocol.js'));
  let state=createTranscript(null);
  let runState='idle';
  let sessionId=null;
  const root=document.createElement('section');
  root.id='voice2text-panel';
  root.setAttribute('aria-label','Voice2Text live captions');
  root.innerHTML=`<header class="v2t-header"><div class="v2t-brand"><span class="v2t-wave">▥</span> Voice2Text</div><label class="v2t-opacity" title="Panel opacity"><span aria-hidden="true">◐</span><input type="range" min="30" max="100" step="5" value="100" data-control="opacity" aria-label="Panel opacity"></label><div class="v2t-actions"><button type="button" data-action="copy">Copy</button><button type="button" data-action="clear">Clear</button><button type="button" data-action="start">Start</button><button type="button" data-action="restart">Restart</button><button type="button" data-action="stop">Stop</button><button type="button" data-action="hide" aria-label="Hide captions">Hide</button></div></header><div class="v2t-status" role="status">Ready for audio</div><div class="v2t-transcript" tabindex="0" aria-label="Transcript"><p class="v2t-empty">Your video's words will appear here.</p></div><footer class="v2t-footer"><span>ON YOUR MAC</span><span class="v2t-retention">Original speech · no translation</span></footer>`;
  const restoreButton=document.createElement('button');
  restoreButton.id='voice2text-restore';
  restoreButton.type='button';
  restoreButton.setAttribute('aria-label','Show Voice2Text captions');
  restoreButton.textContent='▥ Voice2Text';
  restoreButton.hidden=true;
  document.documentElement.append(root);
  document.documentElement.append(restoreButton);
  const body=root.querySelector('.v2t-transcript');
  const status=root.querySelector('.v2t-status');
  const retention=root.querySelector('.v2t-retention');
  const startButton=root.querySelector('[data-action="start"]');
  const restartButton=root.querySelector('[data-action="restart"]');
  const stopButton=root.querySelector('[data-action="stop"]');
  const opacity=root.querySelector('[data-control="opacity"]');
  restoreButton.addEventListener('click',()=>{
    root.hidden=false;
    restoreButton.hidden=true;
  });
  function setOpacity(value) {
    const percent=Math.max(30,Math.min(100,Number(value)||100));
    opacity.value=String(percent);
    opacity.title=`Panel opacity: ${percent}%`;
    root.style.setProperty('--v2t-panel-opacity',String(percent/100));
  }
  setOpacity(100);
  chrome.storage.local.get('panelOpacity').then(({panelOpacity})=>setOpacity(panelOpacity)).catch(()=>{});
  opacity.addEventListener('input',()=>setOpacity(opacity.value));
  opacity.addEventListener('change',()=>chrome.storage.local.set({panelOpacity:Number(opacity.value)}).catch(()=>{}));
  function setRunState(next) {
    runState=next;
    root.dataset.state=next;
    const active=['starting','recording','stopping'].includes(next);
    startButton.disabled=active;
    restartButton.disabled=!['starting','recording'].includes(next);
    stopButton.disabled=!active||next==='stopping';
  }
  setRunState('starting');
  function render() {
    const follow=body.scrollHeight-body.scrollTop-body.clientHeight<70;
    const rows=state.rows.filter(row=>row.text);
    body.replaceChildren();
    if(!rows.length) {
      const empty=document.createElement('p');empty.className='v2t-empty';empty.textContent='Your video’s words will appear here.';body.append(empty);
    }
    for(const row of rows) {
      const line=document.createElement('p');
      line.className=row.final?'v2t-final':'v2t-partial';
      line.textContent=row.text;
      body.append(line);
    }
    retention.textContent=state.dropped?`Showing the latest 2,000 lines · ${state.dropped} earlier lines removed`:'Original speech · no translation';
    if(follow) body.scrollTop=body.scrollHeight;
  }
  root.addEventListener('click',async event=>{
    const action=event.target.closest('button')?.dataset.action;
    if(action==='copy') {
      try { await navigator.clipboard.writeText(transcriptText(state));status.textContent='Transcript copied'; }
      catch { status.textContent='Select the text and press ⌘C to copy.'; }
    }
    if(action==='clear') {state=clearTranscript(state);render();}
    if(action==='hide') {
      root.hidden=true;
      restoreButton.hidden=false;
    }
    if(action==='stop') chrome.runtime.sendMessage({target:'background',type:'STOP'}).catch(()=>{});
    if(action==='restart') {
      setRunState('stopping');
      status.textContent='Restarting captions…';
      try {
        const result=await chrome.runtime.sendMessage({target:'background',type:'RESTART'});
        if(!result?.ok) throw new Error(result?.error||'Extension did not answer. Reload Voice2Text, then start once from the toolbar.');
      } catch(error) {
        setRunState('error');
        status.textContent=error.message;
      }
    }
    if(action==='start') {
      setRunState('starting');
      status.textContent='Connecting to your Mac…';
      try {
        const result=await chrome.runtime.sendMessage({target:'background',type:'START'});
        if(!result?.ok) throw new Error(result?.error||'Extension did not answer. Reload Voice2Text, then start once from the toolbar.');
      } catch(error) {
        setRunState('error');
        status.textContent=error.message;
      }
    }
  });
  const header=root.querySelector('header');
  header.addEventListener('pointerdown',event=>{
    if(event.target.closest('button,input')) return;
    const rect=root.getBoundingClientRect();
    const x=event.clientX,y=event.clientY;
    header.setPointerCapture(event.pointerId);
    const move=next=>{
      root.style.left=`${Math.max(0,Math.min(innerWidth-root.offsetWidth,rect.left+next.clientX-x))}px`;
      root.style.top=`${Math.max(0,Math.min(innerHeight-root.offsetHeight,rect.top+next.clientY-y))}px`;
      root.style.bottom='auto';root.style.right='auto';
    };
    header.addEventListener('pointermove',move);
    header.addEventListener('pointerup',()=>header.removeEventListener('pointermove',move),{once:true});
  });
  const onFullscreenChange=()=>{
    const full=document.fullscreenElement;
    const target=full && !['VIDEO','IFRAME'].includes(full.tagName)?full:document.documentElement;
    target.append(root,restoreButton);
  };
  document.addEventListener('fullscreenchange',onFullscreenChange);
  const onMessage=(message,sender,reply)=>{
    if(message.target!=='content' || sender.id!==chrome.runtime.id) return;
    if(message.type==='RESET') {state=createTranscript(null);sessionId=null;setRunState('starting');root.hidden=false;restoreButton.hidden=true;render();reply({ok:true});return;}
    if(message.type==='STATUS') {
      if(message.sessionId && !sessionId) {sessionId=message.sessionId;state=createTranscript(sessionId);}
      if(sessionId && message.sessionId && message.sessionId!==sessionId) return;
      setRunState(message.state);
      const labels={starting:'Connecting to your Mac…',recording:'Listening · words may update as you speak',stopping:'Finishing the last words…',stopped:'Stopped · your transcript is ready',error:'Transcription stopped'};
      status.textContent=message.error||labels[runState]||'Ready';
    }
    if(message.type==='TRANSCRIPT' && !['stopped','error'].includes(runState)) {
      state=reduceTranscript(state,message.event);render();
    }
  };
  chrome.runtime.onMessage.addListener(onMessage);
  globalThis.__voice2textCleanup=()=>{
    chrome.runtime.onMessage.removeListener(onMessage);
    document.removeEventListener('fullscreenchange',onFullscreenChange);
    root.remove();restoreButton.remove();
  };
})();
