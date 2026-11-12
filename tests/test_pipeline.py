import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

import av
import numpy as np

from whisper_box.config import BoxError, Settings, effective_config
from whisper_box.jobs import complete_output
from whisper_box.pipeline import audio_chunks, timestamp, transcribe


def write_silence(path, seconds):
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        for _ in range(seconds):
            stream.writeframes(bytes(32000))


class PipelineTest(unittest.TestCase):
    def test_decoder_chunks_have_exact_offsets_and_bounded_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'silence.wav'
            write_silence(path, 7)
            chunks = [(offset, len(audio)) for offset, audio in audio_chunks(path, seconds=3)]
            self.assertEqual(chunks, [(0, 48000), (3, 48000), (6, 16000)])

    def test_invalid_media_and_video_without_audio_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / 'invalid.mp4'
            invalid.write_bytes(b'not media')
            with self.assertRaises(BoxError) as error:
                list(audio_chunks(invalid))
            self.assertEqual(error.exception.code, 'invalid_media')
            video = Path(directory) / 'video.mp4'
            with av.open(str(video), 'w') as container:
                stream = container.add_stream('mpeg4', rate=1)
                stream.width, stream.height = 32, 32
                stream.pix_fmt = 'yuv420p'
                frame = av.VideoFrame.from_ndarray(np.zeros((32, 32, 3), dtype=np.uint8), format='rgb24')
                for packet in stream.encode(frame):
                    container.mux(packet)
                for packet in stream.encode():
                    container.mux(packet)
            with self.assertRaises(BoxError) as error:
                list(audio_chunks(video))
            self.assertEqual(error.exception.code, 'no_audio')

    def test_timestamp_supports_hours_and_millisecond_rollover(self):
        self.assertEqual(timestamp(3599.9999, True), '01:00:00,000')
        self.assertEqual(timestamp(7205), '02:00:05')

    def test_pipeline_publishes_all_outputs_and_preserves_chunk_offsets(self):
        class Model:
            def transcribe(self, audio, **_kwargs):
                return iter([SimpleNamespace(start=0.1, end=0.5, text=' Exemplo ',
                                              avg_logprob=-0.2, no_speech_prob=0.01)]), \
                    SimpleNamespace(language='pt', duration_after_vad=len(audio) / 16000)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root / 'state', root / 'input', root / 'output', root / 'models')
            settings.initialize()
            source = root / 'source.wav'
            write_silence(source, 7)
            config = effective_config('fixture')
            config['chunk_seconds'] = 3
            job = {'id': 'job', 'fingerprint': 'fingerprint', 'input_hash': 'hash',
                   'input_path': str(source), 'attempts': 1, 'interruptions': 0,
                   'config': json.dumps(config)}
            transcribe(settings, job, Model(), lambda _: None)
            self.assertTrue(complete_output(settings, job))
            rows = [json.loads(line) for line in (settings.outputs / 'job' / 'segmentos.jsonl').read_text().splitlines()]
            self.assertEqual([row['inicio'] for row in rows], [0.1, 3.1, 6.1])
            metadata = json.loads((settings.outputs / 'job' / 'metadados.json').read_text())
            self.assertEqual(metadata['duration_seconds'], 7)
            self.assertEqual(metadata['segments'], 3)


if __name__ == '__main__':
    unittest.main()
