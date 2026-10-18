import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';

test('worklet clips PCM, emits 100 ms chunks, and flushes the last sample before ack', () => {
  let Processor;
  const messages = [];
  const context = vm.createContext({AudioWorkletProcessor:class { constructor(){ this.port={postMessage:m=>messages.push(m)}; } }, registerProcessor:(_,p)=>{ Processor=p; }, Int16Array, Math});
  vm.runInContext(fs.readFileSync('extension/audio-worklet.js','utf8'),context);
  const p = new Processor();
  p.process([[new Float32Array(1600).fill(2)]]);
  p.process([[new Float32Array([-.5])]]);
  p.port.onmessage({data:{type:'FLUSH'}});
  assert.equal(messages[0].pcm.length,1600);
  assert.equal(messages[0].pcm[0],32767);
  assert.equal(messages[1].pcm[0],-16384);
  assert.equal(messages[2].type,'FLUSHED');
});
