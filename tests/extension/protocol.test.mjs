import test from 'node:test';
import assert from 'node:assert/strict';
import {createTranscript, reduceTranscript, clearTranscript, transcriptText} from '../../extension/protocol.js';

const row = (segment_id, revision, text, final = false) => ({type:'transcript',session_id:'s',segment_id,revision,text,final});
test('revisions replace a row and reject older sessions and revisions', () => {
  let state = createTranscript('s');
  state = reduceTranscript(state, row(0, 1, 'Hell'));
  state = reduceTranscript(state, row(0, 2, 'Hello', true));
  state = reduceTranscript(state, row(0, 1, 'Old'));
  state = reduceTranscript(state, {...row(1, 1, 'Wrong'), session_id:'old'});
  assert.equal(transcriptText(state), 'Hello');
  assert.equal(state.rows.length, 1);
});
test('clear hides in-flight revisions but accepts a new segment', () => {
  let state = reduceTranscript(createTranscript('s'), row(3, 1, 'Before'));
  state = clearTranscript(state);
  state = reduceTranscript(state, row(3, 2, 'Before final', true));
  state = reduceTranscript(state, row(4, 1, 'After'));
  assert.equal(transcriptText(state), 'After');
});
test('final empty result removes a hallucinated partial', () => {
  let state = reduceTranscript(createTranscript('s'), row(0, 1, 'Unwanted'));
  state = reduceTranscript(state, row(0, 2, '', true));
  assert.equal(transcriptText(state), '');
});
test('retention is bounded and reports discarded rows', () => {
  let state = createTranscript('s');
  for (let i = 0; i < 2005; i++) state = reduceTranscript(state, row(i, 1, `Line ${i}`, true));
  assert.equal(state.rows.length, 2000);
  assert.equal(state.dropped, 5);
  assert.equal(state.rows[0].text, 'Line 5');
});
