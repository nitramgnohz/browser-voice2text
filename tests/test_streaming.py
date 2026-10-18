import numpy as np
import pytest

from voice2text.streaming import StreamSession, Word


def audio(seconds, value=4000):
    return np.full(round(seconds * 16000), value, dtype='<i2').tobytes()


def test_partial_revision_replaces_same_segment_and_stop_keeps_tail():
    s = StreamSession('session')
    s.feed(audio(1))
    w = s.snapshot()
    a = s.apply([Word(' Hello', .1, .5)], w)[0]
    s.feed(audio(.3))
    b = s.apply([Word(' Hello', .1, .5), Word(' world.', .5, 1.2)], s.finish(), final=True)[0]
    assert a['segment_id'] == b['segment_id']
    assert b['revision'] > a['revision']
    assert b['text'] == 'Hello world.'
    assert b['final'] is True
    assert s.buffer_seconds == 0


def test_short_tail_and_silence():
    s = StreamSession('session')
    s.feed(audio(.2))
    assert s.snapshot() is None
    assert len(s.finish().audio) == 3200
    silent = StreamSession('silent')
    silent.feed(audio(2, 0))
    assert silent.snapshot() is None
    assert silent.finish() is None


def test_window_overlap_does_not_duplicate_and_keeps_real_repetition():
    s = StreamSession('session')
    s.feed(audio(12))
    w = s.snapshot()
    assert w.rollover
    first = s.apply([Word(' Yes', 8, 8.5), Word(' yes.', 9, 9.5), Word(' Next', 10.5, 11)], w)
    assert first[0]['text'] == 'Yes yes.'
    assert first[0]['final']
    s.feed(audio(1))
    w = s.finish()
    assert w.start_sample == 8 * 16000
    second = s.apply([Word(' Yes', 0, .5), Word(' yes.', 1, 1.5), Word(' Next', 2.5, 3), Word(' word.', 4, 4.5)], w, final=True)
    assert second[0]['text'] == 'Next word.'


def test_mixed_script_and_invalid_timestamps():
    s = StreamSession('session')
    s.feed(audio(2))
    w = s.finish()
    with pytest.raises(ValueError, match='timestamp'):
        s.apply([Word('bad', 1, .2)], w)
    event = s.apply([Word('你好，', .1, .7), Word(' AI!', .7, 1.5)], w, final=True)[0]
    assert event['text'] == '你好， AI!'


def test_buffer_limit_and_odd_pcm_are_rejected():
    s = StreamSession('session')
    with pytest.raises(ValueError):
        s.feed(b'1')
    s.feed(audio(20))
    with pytest.raises(BufferError):
        s.feed(audio(.1))
    assert s.buffer_seconds <= 20


def test_final_snapshot_preserves_new_audio_received_during_inference():
    s = StreamSession('session')
    s.feed(audio(1))
    w = s.finish()
    s.feed(audio(.5))
    s.apply([Word('One.', .1, .8)], w, final=True)
    assert s.buffer_seconds == .5


def test_silence_endpoint_finalizes_and_stable_prefix_is_reported():
    s = StreamSession('session')
    s.feed(audio(1))
    words = [Word(' Hello', .1, .5)]
    s.apply(words, s.snapshot())
    s.feed(audio(.8))
    event = s.apply(words + [Word(' friend', .6, 1.4)], s.snapshot())[0]
    assert event['stable_text'] == 'Hello'
    s.feed(audio(.8, 0))
    w = s.snapshot()
    assert w.endpoint
    assert s.apply(words, w)[0]['final']


def test_final_empty_clears_earlier_partial_after_intermediate_empty():
    s = StreamSession('session')
    s.feed(audio(1))
    partial = s.apply([Word(' Guess', .1, .7)], s.snapshot())[0]
    s.feed(audio(1))
    assert s.apply([], s.snapshot()) == []
    s.feed(audio(.8, 0))
    final = s.apply([], s.snapshot())[0]
    assert final['segment_id'] == partial['segment_id']
    assert final['revision'] > partial['revision']
    assert final['text'] == ''
    assert final['final'] is True
