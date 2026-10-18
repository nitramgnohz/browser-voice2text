"""Loopback-only live speech WebSocket service."""

import asyncio
import hmac
import json
import os
import re
import secrets

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import __version__
from .config import Config
from .streaming import StreamSession

ORIGIN = re.compile(r'^chrome-extension://[a-p]{32}$')
LANGUAGE = re.compile(r'^(auto|en|zh|ja|ko|es|fr|de)$')


def create_app(config: Config, recognizer) -> Starlette:
    busy = asyncio.Lock()

    async def health(_request):
        return JSONResponse({'name': 'Voice2Text', 'version': __version__, 'ready': recognizer.ready,
                             'model': str(config.model_path.name), 'busy': busy.locked(),
                             'port': config.port, 'pid': os.getpid()})

    async def session(ws: WebSocket):
        if not ORIGIN.fullmatch(ws.headers.get('origin', '')):
            await ws.close(code=1008)
            return
        await ws.accept()
        session_id = secrets.token_hex(12)
        async def error(code, message):
            await ws.send_json({'type': 'error', 'session_id': session_id, 'code': code, 'message': message})

        try:
            first = await asyncio.wait_for(ws.receive(), config.auth_timeout)
            if first.get('type') != 'websocket.receive' or first.get('text') is None or len(first['text']) > 4096:
                raise ValueError('Invalid start message')
            data = json.loads(first['text'])
            if not isinstance(data, dict) or data.get('type') != 'start' or data.get('version') != 1:
                raise ValueError('Invalid start message')
            if not isinstance(data.get('token'), str) or not hmac.compare_digest(data['token'], config.token):
                raise ValueError('Invalid connection key')
            if (data.get('sample_rate') != 16000 or data.get('channels') != 1 or
                    data.get('format') != 's16le' or not isinstance(data.get('language'), str) or
                    not LANGUAGE.fullmatch(data['language'])):
                raise ValueError('Invalid audio settings')
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, asyncio.TimeoutError):
            await error('invalid_start', 'Check your connection key and audio settings, then try again.')
            await ws.close(code=1008)
            return
        except WebSocketDisconnect:
            return

        if not recognizer.ready:
            await error('model_unavailable', 'The local speech model is not ready.')
            await ws.close(code=1011)
            return
        if busy.locked():
            await error('busy', 'Voice2Text is already transcribing another tab.')
            await ws.close(code=1008)
            return

        await busy.acquire()
        stream = StreamSession(session_id)
        language = None if data['language'] == 'auto' else data['language']
        job = None
        pending = False
        closed = False

        async def infer(window, final=False):
            nonlocal closed
            try:
                if hasattr(recognizer, 'transcribe_async'):
                    words = await recognizer.transcribe_async(window.audio, language)
                else:
                    words = await asyncio.to_thread(recognizer.transcribe, window.audio, language)
                if closed:
                    return
                for event in stream.apply(words, window, final=final):
                    await ws.send_json(event)
            except Exception:
                if not closed:
                    await error('recognition_failed', 'Local speech recognition failed. Restart Voice2Text and try again.')
                closed = True

        async def worker(window):
            nonlocal pending, job
            await infer(window)
            while pending and not closed:
                pending = False
                next_window = stream.snapshot(force=True)
                if not next_window:
                    break
                await infer(next_window)

        try:
            await ws.send_json({'type': 'ready', 'session_id': session_id})
            while not closed:
                message = await ws.receive()
                if message['type'] == 'websocket.disconnect':
                    break
                payload = message.get('bytes')
                if payload is not None:
                    if not payload or len(payload) > 65536 or len(payload) % 2:
                        await error('invalid_audio', 'Audio message is invalid or too large.')
                        break
                    try:
                        stream.feed(payload)
                    except (BufferError, ValueError):
                        await error('audio_overload', 'Speech recognition cannot keep up. Try a smaller model.')
                        break
                    if job and not job.done():
                        pending = True
                    else:
                        window = stream.snapshot()
                        if window:
                            job = asyncio.create_task(worker(window))
                elif message.get('text') is not None:
                    if len(message['text']) > 4096:
                        await error('invalid_message', 'Control message is too large.')
                        break
                    try:
                        control = json.loads(message['text'])
                    except json.JSONDecodeError:
                        control = None
                    if control != {'type': 'stop'}:
                        await error('invalid_message', 'Unknown control message.')
                        break
                    if job:
                        await job
                    if closed:
                        break
                    tail = stream.finish()
                    if tail:
                        await infer(tail, final=True)
                    if not closed:
                        await ws.send_json({'type': 'stopped', 'session_id': session_id})
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            closed = True
            if job and not job.done():
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)
            busy.release()
            try:
                await ws.close()
            except RuntimeError:
                pass

    return Starlette(routes=[Route('/health', health), WebSocketRoute('/ws', session)])
