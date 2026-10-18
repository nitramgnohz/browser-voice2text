"""MLX Whisper adapter. Model files must already exist locally."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import asyncio
import threading
import numpy as np
from .streaming import RATE, Word


class Recognizer:
    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.lock = threading.Lock()
        self.ready = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='voice2text-mlx')

    def load(self):
        return self.executor.submit(self._load).result()

    def _load(self):
        if not (self.model_path / 'config.json').is_file():
            raise RuntimeError('Model is missing. Run ./voice2text-run setup first.')
        from mlx_whisper.transcribe import ModelHolder
        import mlx.core as mx
        with self.lock:
            ModelHolder.get_model(str(self.model_path), mx.float16)
            self.ready = True

    async def transcribe_async(self, audio: np.ndarray, language: str | None) -> list[Word]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.transcribe, audio, language)

    def transcribe(self, audio: np.ndarray, language: str | None) -> list[Word]:
        if not self.ready:
            raise RuntimeError('Model is not ready')
        if len(audio) == 0 or float(np.sqrt(np.mean(audio * audio))) < .001:
            return []
        import mlx_whisper
        with self.lock:
            split = self._language_switch(audio) if language is None else None
            if split is None:
                return self._transcribe_chunk(mlx_whisper, audio, language)
            at, first, second = split
            quiet_at = self._speech_gap(audio, at)
            if quiet_at is not None:
                left = self._transcribe_chunk(mlx_whisper, audio[:quiet_at], first)
                right = self._transcribe_chunk(mlx_whisper, audio[quiet_at:], second)
                return left + [Word(word.text, word.start + quiet_at / RATE,
                                    word.end + quiet_at / RATE) for word in right]
            overlap = RATE // 2
            left = self._transcribe_chunk(mlx_whisper, audio[:at + overlap], first)
            right = self._transcribe_chunk(mlx_whisper, audio[at - overlap:], second)
            boundary = at / RATE
            return ([word for word in left if word.end <= boundary + .05] +
                    [Word(word.text, word.start + boundary - .5, word.end + boundary - .5)
                     for word in right if word.end + boundary - .5 > boundary + .05])

    def _detect_language(self, audio: np.ndarray) -> tuple[str, float]:
        from mlx_whisper.audio import N_FRAMES, log_mel_spectrogram, pad_or_trim
        from mlx_whisper.transcribe import ModelHolder
        import mlx.core as mx
        model = ModelHolder.get_model(str(self.model_path), mx.float16)
        mel = log_mel_spectrogram(audio, n_mels=model.dims.n_mels)
        _, probabilities = model.detect_language(pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16))
        language = max(probabilities, key=probabilities.get)
        return language, float(probabilities[language])

    def _language_switch(self, audio: np.ndarray) -> tuple[int, str, str] | None:
        if len(audio) < 4 * RATE:
            return None
        first, first_confidence = self._detect_language(audio[:RATE])
        last, last_confidence = self._detect_language(audio[-RATE:])
        if {first, last} != {'en', 'zh'} or first_confidence < .8 or last_confidence < .7:
            return None
        for second in range(1, len(audio) // RATE):
            detected, confidence = self._detect_language(audio[second * RATE:(second + 1) * RATE])
            if detected == last and confidence >= .8:
                return second * RATE, first, last
        return None

    def _speech_gap(self, audio: np.ndarray, near: int) -> int | None:
        frame = RATE // 20
        start = max(0, near - 2 * RATE)
        end = min(len(audio), near + RATE // 4)
        levels = [float(np.sqrt(np.mean(audio[i:i + frame] ** 2)))
                  for i in range(start, end - frame + 1, frame)]
        if not levels:
            return None
        threshold = max(.004, float(np.quantile(levels, .75)) * .25)
        gaps = []
        beginning = None
        for index, level in enumerate(levels + [threshold]):
            if level < threshold and beginning is None:
                beginning = index
            elif level >= threshold and beginning is not None:
                gap_end = start + index * frame
                if index - beginning >= 5 and near - RATE <= gap_end <= near + RATE // 4:
                    gaps.append((beginning, index))
                beginning = None
        if not gaps:
            return None
        beginning, ending = max(gaps, key=lambda gap: gap[1] - gap[0])
        return start + (beginning + ending) * frame // 2

    def _transcribe_chunk(self, mlx_whisper, audio: np.ndarray, language: str | None) -> list[Word]:
        result = mlx_whisper.transcribe(
            audio, path_or_hf_repo=str(self.model_path), language=language,
            word_timestamps=True, condition_on_previous_text=False,
            temperature=0.0, verbose=None, fp16=True,
        )
        words = []
        for segment in result.get('segments', []):
            if (segment.get('no_speech_prob', 0) > .6 and segment.get('avg_logprob', 0) < -1) or segment.get('compression_ratio', 0) > 2.4:
                continue
            for word in segment.get('words', []):
                words.append(Word(word['word'], float(word['start']), float(word['end'])))
        return words
