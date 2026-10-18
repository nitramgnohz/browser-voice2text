"""Bounded audio windows and timestamp-aware caption revisions."""

from dataclasses import dataclass
import math
import numpy as np

RATE = 16000


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class AudioWindow:
    audio: np.ndarray
    start_sample: int
    end_sample: int
    endpoint: bool = False
    rollover: bool = False


class StreamSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.buffer = bytearray()
        self.offset = 0
        self.total = 0
        self.last_voice = 0
        self.has_voice = False
        self.last_snapshot = 0
        self.committed_until = 0.0
        self.segment = 0
        self.revision = 0
        self.previous = []
        self.emitted_partial = False

    @property
    def buffer_seconds(self):
        return len(self.buffer) / (2 * RATE)

    def feed(self, pcm: bytes) -> None:
        if len(pcm) % 2:
            raise ValueError('PCM must contain complete int16 samples')
        if len(self.buffer) + len(pcm) > 20 * RATE * 2:
            raise BufferError('Recognition cannot keep up. Stop and use a smaller model.')
        samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
        # Inspect 20 ms frames so a large input message cannot hide its silent tail.
        for i in range(0, len(samples), 320):
            frame = samples[i:i + 320]
            if len(frame) and float(np.sqrt(np.mean(frame * frame))) >= .004:
                self.last_voice = self.total + i + len(frame)
                self.has_voice = True
        self.buffer.extend(pcm)
        self.total += len(samples)
        if not self.has_voice and self.buffer_seconds > 1:
            self._drop(self.total - RATE)

    def _drop(self, until: int):
        until = max(self.offset, min(until, self.total))
        del self.buffer[:(until - self.offset) * 2]
        self.offset = until

    def snapshot(self, force=False) -> AudioWindow | None:
        if not self.has_voice:
            return None
        endpoint = self.total - self.last_voice >= int(.7 * RATE)
        count = self.total - self.offset
        if not force and not endpoint and (count < RATE or self.total - self.last_snapshot < int(.8 * RATE)):
            return None
        end = min(self.total, self.offset + 12 * RATE)
        rollover = end < self.total or (count >= 12 * RATE and not endpoint)
        self.last_snapshot = end
        array = np.frombuffer(bytes(self.buffer[:(end - self.offset) * 2]), dtype='<i2').astype(np.float32) / 32768
        return AudioWindow(array, self.offset, end, endpoint and end == self.total, rollover)

    def finish(self) -> AudioWindow | None:
        return self.snapshot(force=True)

    def apply(self, words: list[Word], window: AudioWindow, final=False) -> list[dict]:
        if window.start_sample != self.offset:
            raise ValueError('Stale audio window')
        for word in words:
            if not (math.isfinite(word.start) and math.isfinite(word.end) and 0 <= word.start <= word.end <= len(window.audio) / RATE + .5):
                raise ValueError('Invalid word timestamp')
        origin = window.start_sample / RATE
        candidates = [Word(w.text, origin + w.start, origin + w.end) for w in words
                      if origin + (w.start + w.end) / 2 > self.committed_until + .04]
        is_final = final or window.endpoint or window.rollover
        cutoff = (window.end_sample / RATE - 2) if window.rollover else window.end_sample / RATE
        selected = [w for w in candidates if not window.rollover or w.end <= cutoff]
        stable = []
        for old, new in zip(self.previous, selected):
            if old.text.strip() != new.text.strip():
                break
            stable.append(new.text)
        text = ''.join(w.text for w in selected).strip()
        self.revision += 1
        events = []
        # Empty final clears an earlier partial, even after an empty intermediate inference.
        if text or (is_final and self.emitted_partial):
            events.append({
                'type': 'transcript', 'session_id': self.session_id,
                'segment_id': self.segment, 'revision': self.revision,
                'text': text, 'stable_text': text if is_final else ''.join(stable).strip(),
                'final': is_final,
                'start_ms': round((selected[0].start if selected else origin) * 1000),
                'end_ms': round((selected[-1].end if selected else cutoff) * 1000),
            })
        if text and not is_final:
            self.emitted_partial = True
        self.previous = selected
        if is_final:
            if selected:
                self.committed_until = selected[-1].end
            if window.rollover:
                self._drop(window.end_sample - 4 * RATE)
            else:
                self._drop(window.end_sample)
                self.committed_until = max(self.committed_until, window.end_sample / RATE)
            self.has_voice = self.last_voice > self.offset
            self.previous = []
            self.emitted_partial = False
            self.segment += 1
            self.revision = 0
        return events
