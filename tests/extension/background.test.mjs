import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';

test('page navigation does not stop an active tab capture', () => {
  const listeners = {updated: [], removed: []};
  const chrome = {
    runtime: {
      getURL: path => `chrome-extension://test/${path}`,
      onMessage: {addListener() {}},
    },
    tabs: {
      onUpdated: {addListener: listener => listeners.updated.push(listener)},
      onRemoved: {addListener: listener => listeners.removed.push(listener)},
    },
  };
  vm.runInNewContext(fs.readFileSync('extension/background.js', 'utf8'), {chrome, Promise});
  assert.equal(listeners.updated.length, 0);
  assert.equal(listeners.removed.length, 1);
});

test('a page can restart captions only for its own tab', async () => {
  let onMessage;
  let capturedTabId;
  const chrome = {
    runtime: {
      id: 'test',
      getURL: path => `chrome-extension://test/${path}`,
      getContexts: async () => [{contextType: 'OFFSCREEN_DOCUMENT'}],
      sendMessage: async message => message.type === 'GET_STATUS' ? {state: 'stopped'} : {ok: true},
      onMessage: {addListener: listener => {onMessage = listener;}},
    },
    tabs: {
      get: async id => {capturedTabId = id; return {url: 'https://example.com/video'};},
      sendMessage: async () => ({ok: true}),
      onRemoved: {addListener() {}},
    },
    storage: {local: {get: async () => ({token: 'local-key', language: 'zh'})}},
    scripting: {insertCSS: async () => {}, executeScript: async () => {}},
    tabCapture: {getCapturedTabs: async () => [], getMediaStreamId: async () => 'stream-id'},
  };
  vm.runInNewContext(fs.readFileSync('extension/background.js', 'utf8'), {
    chrome, Promise, AbortSignal,
    fetch: async () => ({json: async () => ({ready: true, busy: false})}),
  });
  let reply;
  const accepted = onMessage({target: 'background', type: 'START', tabId: 999},
    {tab: {id: 42}, url: 'https://example.com/video'}, result => {reply = result;});
  assert.equal(accepted, true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(capturedTabId, 42);
  assert.deepEqual(reply, {ok: true});
});

test('restart waits for the current capture to release before starting again', async () => {
  let onMessage;
  const calls = [];
  let stopped = false;
  let statusChecks = 0;
  const chrome = {
    runtime: {
      id: 'test',
      getURL: path => `chrome-extension://test/${path}`,
      getContexts: async () => [{contextType: 'OFFSCREEN_DOCUMENT'}],
      sendMessage: async message => {
        calls.push(message.type);
        if(message.type === 'STOP') {stopped = true; return {ok: true};}
        if(message.type === 'GET_STATUS') {
          if(!stopped) return {state: 'recording', tabId: 42, released: false};
          statusChecks++;
          return statusChecks === 1 ? {state: 'stopped', tabId: 42, released: false} :
            {state: 'stopped', tabId: 42, released: true};
        }
        return {ok: true};
      },
      onMessage: {addListener: listener => {onMessage = listener;}},
    },
    tabs: {
      get: async () => ({url: 'https://example.com/video'}),
      sendMessage: async () => ({ok: true}),
      onRemoved: {addListener() {}},
    },
    storage: {local: {get: async () => ({token: 'local-key', language: 'zh'})}},
    scripting: {insertCSS: async () => {}, executeScript: async () => {}},
    tabCapture: {
      getCapturedTabs: async () => {
        calls.push('CHECK_CAPTURE');
        return statusChecks < 3 ? [{tabId: 42, status: 'active'}] : [];
      },
      getMediaStreamId: async () => {calls.push('CAPTURE'); return 'stream-id';},
    },
  };
  vm.runInNewContext(fs.readFileSync('extension/background.js', 'utf8'), {
    chrome, Promise, AbortSignal, Date,
    setTimeout: callback => queueMicrotask(callback),
    fetch: async () => ({json: async () => ({ready: true, busy: false})}),
  });
  const result = await new Promise(resolve => {
    assert.equal(onMessage({target: 'background', type: 'RESTART', tabId: 999},
      {id: 'test', tab: {id: 42}}, resolve), true);
  });
  assert.deepEqual(result, {ok: true});
  assert.deepEqual(calls.filter(type => type === 'STOP' || type === 'CAPTURE'), ['STOP', 'CAPTURE']);
  assert.ok(statusChecks >= 3);
  assert.ok(calls.includes('CHECK_CAPTURE'));
  assert.ok(calls.indexOf('CHECK_CAPTURE') < calls.indexOf('CAPTURE'));
});
