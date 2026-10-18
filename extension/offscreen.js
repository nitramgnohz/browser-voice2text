let session = null;
const emit = (current,type,data={}) => chrome.runtime.sendMessage({target:'background',type,tabId:current.tabId,sessionId:current.id,...data}).catch(()=>{});

function status(current,state,error='') {
  current.state=state;
  current.error=error;
  emit(current,'STATUS',{state,error});
}

async function release(current) {
  clearTimeout(current.stopTimer);
  clearTimeout(current.startTimer);
  current.released=true;
  current.stream?.getTracks().forEach(track=>track.stop());
  try { current.source?.disconnect(); current.monitor?.disconnect(); current.worklet?.disconnect(); } catch {}
  await Promise.allSettled([current.context?.close(),current.monitorContext?.close()]);
  current.ws?.close();
}

async function fail(current,message) {
  if (current.released) return;
  status(current,'error',message);
  await release(current);
}

async function start({streamId,tabId,token,language}) {
  if (session && !session.released) throw new Error('A tab is already being transcribed. Stop it first.');
  const current={tabId,id:null,state:'starting',released:false};
  session=current;
  status(current,'starting');
  try {
    // Consume the single-use stream ID before it expires.
    current.stream=await navigator.mediaDevices.getUserMedia({audio:{mandatory:{chromeMediaSource:'tab',chromeMediaSourceId:streamId}},video:false});
    current.monitorContext=new AudioContext();
    current.monitor=current.monitorContext.createMediaStreamSource(current.stream);
    current.monitor.connect(current.monitorContext.destination);
    await current.monitorContext.resume();
    current.context=new AudioContext({sampleRate:16000});
    if (current.context.sampleRate !== 16000) throw new Error('This browser cannot capture at 16 kHz.');
    await current.context.audioWorklet.addModule(chrome.runtime.getURL('audio-worklet.js'));
    current.source=current.context.createMediaStreamSource(current.stream);
    current.worklet=new AudioWorkletNode(current.context,'voice2text-audio',{numberOfOutputs:0});
    const ws=new WebSocket('ws://127.0.0.1:8766/ws');
    current.ws=ws;
    current.startTimer=setTimeout(()=>fail(current,'Local service did not respond. Start Voice2Text and try again.'),10000);
    ws.onopen=()=>ws.send(JSON.stringify({type:'start',version:1,token,language:language||'auto',sample_rate:16000,channels:1,format:'s16le'}));
    ws.onmessage=async ({data})=>{
      if (current.released) return;
      let event;
      try { event=JSON.parse(data); } catch { await fail(current,'Invalid response from local service.'); return; }
      if(event.type==='ready') {
        clearTimeout(current.startTimer);
        current.id=event.session_id;
        if(current.state==='stopping') { ws.send(JSON.stringify({type:'stop'})); return; }
        current.source.connect(current.worklet);
        await current.context.resume();
        status(current,'recording');
      } else if(event.type==='transcript' && event.session_id===current.id) {
        emit(current,'TRANSCRIPT',{event});
      } else if(event.type==='error') await fail(current,event.message || 'Recognition failed.');
      else if(event.type==='stopped') { status(current,'stopped'); await release(current); }
    };
    ws.onerror=()=>fail(current,'Cannot reach Voice2Text. Start the local service and check your connection key.');
    ws.onclose=()=>{ if(!current.released) fail(current,'Connection lost. Transcription stopped; your text is still available.'); };
    current.worklet.port.onmessage=({data})=>{
      if(current.released || ws.readyState!==WebSocket.OPEN) return;
      if(data.type==='AUDIO') {
        if(ws.bufferedAmount>640000) { fail(current,'Audio is arriving faster than it can be sent. Please restart.'); return; }
        ws.send(data.pcm.buffer);
      } else if(data.type==='FLUSHED') ws.send(JSON.stringify({type:'stop'}));
    };
    current.stream.getAudioTracks()[0].onended=()=>{ if(!current.released) stop(); };
  } catch(error) { await fail(current,error.message); throw error; }
  return {ok:true};
}

async function stop() {
  const current=session;
  if(!current || current.released || current.state==='stopping') return {ok:true};
  const wasRecording=current.state==='recording';
  status(current,'stopping');
  if(!wasRecording) { status(current,'stopped'); await release(current); return {ok:true}; }
  current.worklet.port.postMessage({type:'FLUSH'});
  current.stopTimer=setTimeout(()=>fail(current,'Stopped, but the final audio could not be completed.'),15000);
  return {ok:true};
}

chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(message.target!=='offscreen' || sender.id!==chrome.runtime.id) return;
  if(message.type==='GET_STATUS') {reply(session?{state:session.state,tabId:session.tabId,sessionId:session.id,error:session.error,released:session.released}:{state:'idle'});return;}
  const work=message.type==='START'?start(message):message.type==='STOP'?stop():Promise.resolve({ok:false});
  work.then(reply,error=>reply({ok:false,error:error.message}));
  return true;
});
