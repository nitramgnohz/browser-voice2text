import asyncio
import sys
import threading
from types import SimpleNamespace

import numpy as np

from voice2text.recognizer import Recognizer


def test_model_loading_and_recognition_use_same_worker_thread():
    class Probe(Recognizer):
        def _load(self):
            self.loaded_on = threading.get_ident()
            self.ready = True

        def transcribe(self, audio, language):
            return threading.get_ident()

    probe = Probe(None)
    probe.load()
    inference_thread = asyncio.run(probe.transcribe_async(None, None))
    assert inference_thread == probe.loaded_on
    assert inference_thread != threading.get_ident()


def test_high_no_speech_score_keeps_confident_chinese_words(monkeypatch):
    segments = [
        {'no_speech_prob': .87, 'avg_logprob': -.28, 'compression_ratio': 1.0,
         'words': [{'word': '而是这种既然不完美', 'start': 0.0, 'end': 2.0}]},
        {'no_speech_prob': .87, 'avg_logprob': -1.2, 'compression_ratio': 1.0,
         'words': [{'word': 'silence', 'start': 2.0, 'end': 3.0}]},
    ]
    monkeypatch.setitem(sys.modules, 'mlx_whisper',
                        SimpleNamespace(transcribe=lambda *args, **kwargs: {'segments': segments}))
    recognizer = Recognizer(None)
    recognizer.ready = True
    words = recognizer.transcribe(np.ones(16000, dtype=np.float32), 'zh')
    assert [word.text for word in words] == ['而是这种既然不完美']


def test_auto_language_switch_does_not_transliterate_english_tail(monkeypatch):
    audio = np.concatenate((np.full(5 * 16000, .1), np.full(7 * 16000, .8))).astype(np.float32)
    calls = []

    def fake_transcribe(audio, **kwargs):
        language = kwargs['language']
        calls.append(language)
        if language == 'en':
            word = {'word': ' English tail.', 'start': 3.0, 'end': 4.0}
        elif language == 'zh':
            word = {'word': '很多人', 'start': .6, 'end': 1.2}
        else:
            word = {'word': '英文尾音的错字', 'start': 3.0, 'end': 4.0}
        return {'segments': [{'words': [word]}]}

    monkeypatch.setitem(sys.modules, 'mlx_whisper', SimpleNamespace(transcribe=fake_transcribe))
    recognizer = Recognizer(None)
    recognizer.ready = True
    monkeypatch.setattr(recognizer, '_detect_language',
                        lambda chunk: ('en', .98) if float(chunk.mean()) < .5 else ('zh', .98),
                        raising=False)
    words = recognizer.transcribe(audio, None)
    assert [word.text for word in words] == [' English tail.', '很多人']
    assert calls == ['en', 'zh']


def test_language_switch_uses_first_confident_change(monkeypatch):
    audio = np.concatenate((np.full(5 * 16000, .1), np.full(16000, .8),
                            np.full(3 * 16000, .5), np.full(3 * 16000, .8))).astype(np.float32)
    recognizer = Recognizer(None)

    def detect(chunk):
        mean = float(chunk.mean())
        if mean < .3:
            return 'en', .98
        if mean > .7:
            return 'zh', .98
        return 'ru', .4

    monkeypatch.setattr(recognizer, '_detect_language', detect)
    assert recognizer._language_switch(audio) == (5 * 16000, 'en', 'zh')


def test_language_switch_splits_at_quiet_gap():
    audio = np.concatenate((np.full(5 * 16000, .2), np.full(int(.8 * 16000), .015),
                            np.full(int(6.2 * 16000), .2))).astype(np.float32)
    recognizer = Recognizer(None)
    split = recognizer._speech_gap(audio, 6 * 16000)
    assert 5 * 16000 < split < 5.8 * 16000
    assert recognizer._speech_gap(np.full(12 * 16000, .2, dtype=np.float32), 6 * 16000) is None


def test_language_switch_accepts_moderate_final_language_confidence(monkeypatch):
    audio = np.concatenate((np.full(5 * 16000, .1), np.full(6 * 16000, .8),
                            np.full(16000, .9))).astype(np.float32)
    recognizer = Recognizer(None)

    def detect(chunk):
        mean = float(chunk.mean())
        if mean < .5:
            return 'en', .98
        return 'zh', .76 if mean > .85 else .93

    monkeypatch.setattr(recognizer, '_detect_language', detect)
    assert recognizer._language_switch(audio) == (5 * 16000, 'en', 'zh')
