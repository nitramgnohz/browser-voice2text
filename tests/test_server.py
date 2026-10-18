import time
import os
import numpy as np
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from voice2text.config import Config
from voice2text.server import create_app
from voice2text.streaming import Word

ORIGIN = 'chrome-extension://' + 'a' * 32
START = dict(type='start', version=1, token='test-token', language='en', sample_rate=16000, channels=1, format='s16le')


class FakeRecognizer:
    ready = True
    def load(self):
        pass
    def transcribe(self, audio, language):
        return [Word(' Hello.', .01, min(.5, len(audio)/16000))]


def client(recognizer=None, **kwargs):
    return TestClient(create_app(Config('test-token', **kwargs), recognizer or FakeRecognizer()))


def test_health_does_not_expose_token():
    with client() as c:
        r = c.get('/health')
        assert r.json()['ready']
        assert r.json()['port'] == 8766
        assert r.json()['pid'] == os.getpid()
        assert 'test-token' not in r.text


@pytest.mark.parametrize('origin', ['', 'https://example.com', 'chrome-extension://invalid'])
def test_rejects_untrusted_origin(origin):
    with client() as c, pytest.raises(WebSocketDisconnect):
        with c.websocket_connect('/ws', headers={'origin': origin}):
            pass


@pytest.mark.parametrize('field,value', [('token', 'wrong'), ('sample_rate', 48000), ('version', 2), ('language', 'not-a-language'), ('channels', 2)])
def test_rejects_invalid_start(field, value):
    with client() as c, c.websocket_connect('/ws', headers={'origin': ORIGIN}) as ws:
        ws.send_json(START | {field: value})
        assert ws.receive_json()['type'] == 'error'


def test_short_tail_and_busy_lock_release():
    with client() as c:
        with c.websocket_connect('/ws', headers={'origin': ORIGIN}) as ws:
            ws.send_json(START)
            session = ws.receive_json()['session_id']
            with c.websocket_connect('/ws', headers={'origin': ORIGIN}) as other:
                other.send_json(START)
                assert other.receive_json()['code'] == 'busy'
            ws.send_bytes(np.full(3200, 4000, dtype='<i2').tobytes())
            ws.send_json({'type': 'stop'})
            result = ws.receive_json()
            assert result['text'] == 'Hello.' and result['final']
            assert result['session_id'] == session
            assert ws.receive_json()['type'] == 'stopped'
        with c.websocket_connect('/ws', headers={'origin': ORIGIN}) as ws:
            ws.send_json(START)
            assert ws.receive_json()['type'] == 'ready'
            ws.send_json({'type': 'stop'})
            assert ws.receive_json()['type'] == 'stopped'


def test_oversized_message_closes_session():
    with client() as c, c.websocket_connect('/ws', headers={'origin': ORIGIN}) as ws:
        ws.send_json(START)
        ws.receive_json()
        ws.send_bytes(b'0' * 65538)
        assert ws.receive_json()['code'] == 'invalid_audio'


def test_auth_timeout():
    with client(auth_timeout=.02) as c, c.websocket_connect('/ws', headers={'origin': ORIGIN}) as ws:
        assert ws.receive_json()['code'] == 'invalid_start'


def test_model_failure_is_visible():
    class Broken(FakeRecognizer):
        def transcribe(self, audio, language):
            raise RuntimeError('sensitive internal error')
    with client(Broken()) as c, c.websocket_connect('/ws', headers={'origin': ORIGIN}) as ws:
        ws.send_json(START)
        ws.receive_json()
        ws.send_bytes(np.full(3200, 4000, dtype='<i2').tobytes())
        ws.send_json({'type': 'stop'})
        result = ws.receive_json()
        assert result['code'] == 'recognition_failed'
        assert 'sensitive' not in str(result)
