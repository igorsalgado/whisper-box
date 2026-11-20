"""A06: threads configuráveis, progresso/saúde, observabilidade e migração do banco."""
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from whisper_box import worker
from whisper_box.config import (BoxError, Settings, cpu_threads, effective_config, runtime_config,
                                stall_seconds)
from whisper_box.jobs import submit, worker_health
from whisper_box.model import REPO, REQUIRED, sha256_file
from whisper_box.pipeline import transcribe
from whisper_box.store import Store


def settings_in(root: Path) -> Settings:
    settings = Settings(root / 'state', root / 'input', root / 'output', root / 'models')
    settings.initialize()
    return settings


class ConfigTest(unittest.TestCase):
    def test_cpu_threads_default_range_and_invalid_values(self):
        self.assertEqual(cpu_threads(''), (2, True))
        self.assertEqual(cpu_threads('4'), (4, True))
        self.assertEqual(cpu_threads('16'), (16, True))
        for bad in ('0', '17', '-1', 'x', '2.5'):
            self.assertEqual(cpu_threads(bad), (2, False), bad)

    def test_cpu_threads_reads_environment(self):
        with patch.dict('os.environ', {'WHISPER_BOX_CPU_THREADS': '3'}):
            self.assertEqual(cpu_threads(), (3, True))
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(cpu_threads(), (2, True))

    def test_stall_seconds_default_and_invalid(self):
        self.assertEqual(stall_seconds(''), 1200)
        self.assertEqual(stall_seconds('30'), 30)
        for bad in ('0', '-5', 'x'):
            self.assertEqual(stall_seconds(bad), 1200)

    def test_runtime_config_reads_environment(self):
        with patch.dict('os.environ', {'WHISPER_BOX_CPUS': '4'}):
            self.assertEqual(runtime_config(4), {'cpu_threads': 4, 'cpus': '4'})
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(runtime_config(), {'cpu_threads': 2, 'cpus': None})

    def test_threads_stay_in_the_fingerprint_config_and_default_keeps_old_dedup(self):
        # A06 medida: 2, 3 e 4 threads produzem textos diferentes; por isso entram na deduplicacao.
        with patch.dict('os.environ', {}, clear=True):
            default = effective_config('rev')
        self.assertEqual(default['cpu_threads'], 2)
        self.assertEqual(default['pipeline_version'], '0.1.0')  # sem bump: padrao identico ao anterior
        with patch.dict('os.environ', {'WHISPER_BOX_CPU_THREADS': '4'}):
            four = effective_config('rev')
        self.assertEqual(four['cpu_threads'], 4)
        self.assertNotEqual(four, default)
        with patch.dict('os.environ', {'WHISPER_BOX_CPU_THREADS': 'abc'}):
            self.assertEqual(effective_config('rev')['cpu_threads'], 2)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)

    def test_existing_database_gains_progress_at_and_stays_readable(self):
        old = sqlite3.connect(self.state / 'jobs.sqlite')
        old.executescript("""
            CREATE TABLE jobs (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, input_hash TEXT NOT NULL,
                input_path TEXT NOT NULL, source_name TEXT NOT NULL, config TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed')),
                created_at REAL NOT NULL, started_at REAL, finished_at REAL,
                attempts INTEGER NOT NULL DEFAULT 0, progress REAL NOT NULL DEFAULT 0,
                error_code TEXT, error_message TEXT, interruptions INTEGER NOT NULL DEFAULT 0);
            INSERT INTO jobs (id,fingerprint,input_hash,input_path,source_name,config,status,created_at,progress)
            VALUES ('old','f','h','/x','n','{}','succeeded',1.0,12.5);
        """)
        old.commit()
        old.close()
        store = Store(self.state)
        Store(self.state)  # segunda abertura não falha
        job = store.get('old')
        self.assertEqual((job['status'], job['progress']), ('succeeded', 12.5))
        self.assertIn('progress_at', job)
        self.assertIsNone(job['progress_at'])

    def test_claim_and_progress_record_the_instant(self):
        store = Store(self.state)
        store.enqueue('a' * 32, 'fp', 'h', '/x', 's', {'language': 'pt'})
        before = time.time()
        job = store.claim()
        self.assertGreaterEqual(job['progress_at'], before)
        stamp = store.progress(job['id'], 30.0)
        self.assertGreaterEqual(stamp, job['progress_at'])
        self.assertEqual(store.get(job['id'])['progress_at'], stamp)
        self.assertEqual(store.get(job['id'])['progress'], 30.0)


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = settings_in(Path(self.temp.name))
        (self.settings.state / 'heartbeat.json').write_text(json.dumps({'timestamp': time.time()}))
        self.store = Store(self.settings.state)

    def running_job(self):
        self.store.enqueue('b' * 32, 'fp', 'h', '/x', 's', {'language': 'pt'})
        return self.store.claim()

    def test_idle_worker_is_healthy(self):
        worker_health(self.settings, limit=1)

    def test_progressing_job_is_healthy_and_stalled_job_fails(self):
        job = self.running_job()
        worker_health(self.settings, limit=60)
        with self.assertRaises(BoxError) as error:
            worker_health(self.settings, limit=60, now=job['progress_at'] + 61)
        self.assertEqual(error.exception.code, 'job_stalled')
        stamp = self.store.progress(job['id'], 10.0)
        worker_health(self.settings, limit=60, now=stamp + 59)

    def test_legacy_running_job_without_progress_at_uses_started_at(self):
        job = self.running_job()
        with sqlite3.connect(self.store.path) as db:
            db.execute('UPDATE jobs SET progress_at=NULL WHERE id=?', (job['id'],))
        with self.assertRaises(BoxError):
            worker_health(self.settings, limit=10, now=job['started_at'] + 11)

    def test_dead_heartbeat_still_fails(self):
        (self.settings.state / 'heartbeat.json').write_text(json.dumps({'timestamp': time.time() - 60}))
        with self.assertRaises(BoxError) as error:
            worker_health(self.settings)
        self.assertEqual(error.exception.code, 'worker_unavailable')

    def test_stalled_job_does_not_block_submit(self):
        root = Path(self.temp.name)
        (self.settings.models / 'small').mkdir(parents=True, exist_ok=True)
        files = {}
        for name in REQUIRED:
            path = self.settings.models / 'small' / name
            path.write_bytes(b'fixture')
            files[name] = {'size': 7, 'sha256': sha256_file(path)}
        (self.settings.models / 'manifest.json').write_text(json.dumps({
            'repo': REPO, 'revision': 'rev', 'files': files}))
        job = self.running_job()
        source = root / 'a.wav'
        source.write_bytes(b'audio')
        with self.assertRaises(BoxError):
            worker_health(self.settings, limit=1, now=job['progress_at'] + 5)
        self.assertEqual(submit(self.settings, source, 'pt')['status'], 'queued')

    def test_health_command_exit_codes(self):
        env = {**os.environ, 'WHISPER_BOX_STATE': str(self.settings.state), 'WHISPER_BOX_STALL_SECONDS': '1'}

        def run():
            return subprocess.run([sys.executable, '-m', 'whisper_box', 'health'],
                                  capture_output=True, text=True, env=env)

        self.assertEqual(run().returncode, 0)
        self.running_job()
        time.sleep(1.5)
        process = run()
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)['error']['code'], 'job_stalled')


class HeartbeatTest(unittest.TestCase):
    def test_heartbeat_reports_job_and_logs_stall_once_without_restarting(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = settings_in(Path(directory))
            stop = threading.Event()
            current = {'job_id': 'j' * 32, 'progress_at': time.time() - 100}
            captured = io.StringIO()
            with redirect_stderr(captured):
                thread = threading.Thread(target=worker.heartbeat, args=(settings, stop, current, 10))
                thread.start()
                time.sleep(0.5)
                stop.set()
                thread.join(5)
            beat = json.loads((settings.state / 'heartbeat.json').read_text())
            self.assertEqual(beat['job_id'], 'j' * 32)
            self.assertAlmostEqual(beat['progress_at'], current['progress_at'], places=3)
            events = [json.loads(line) for line in captured.getvalue().splitlines()]
            self.assertEqual([e['event'] for e in events], ['job_stalled'])
            self.assertEqual(set(events[0]), {'event', 'timestamp', 'job_id', 'seconds_without_progress'})

    def test_idle_heartbeat_has_no_job(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = settings_in(Path(directory))
            stop = threading.Event()
            thread = threading.Thread(target=worker.heartbeat, args=(settings, stop, {}, 10))
            thread.start()
            time.sleep(0.3)
            stop.set()
            thread.join(5)
            beat = json.loads((settings.state / 'heartbeat.json').read_text())
            self.assertIsNone(beat['job_id'])


class ObservabilityTest(unittest.TestCase):
    def test_performance_fields_have_only_numbers(self):
        with patch.object(worker, 'peak_memory_bytes', return_value=123):
            fields = worker.performance_fields({'attempts': 2},
                                               {'processing_seconds': 30.0, 'duration_seconds': 300.0})
            self.assertEqual(fields, {'duration_seconds': 300.0, 'processing_seconds': 30.0, 'rtf': 0.1,
                                      'attempts': 2, 'peak_memory_bytes': 123})
            self.assertIsNone(worker.performance_fields(
                {'attempts': 1}, {'processing_seconds': 1.0, 'duration_seconds': 0})['rtf'])

    def test_peak_memory_falls_back_to_none(self):
        with patch.object(worker.Path, 'read_text', side_effect=OSError):
            self.assertIsNone(worker.peak_memory_bytes())

    def test_pipeline_returns_metadata_with_runtime(self):
        class Model:
            def transcribe(self, audio, **_kwargs):
                return iter([]), SimpleNamespace(language='pt', duration_after_vad=0.0)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_in(root)
            source = root / 'source.wav'
            with wave.open(str(source), 'wb') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(bytes(32000 * 2))
            job = {'id': 'job', 'fingerprint': 'fp', 'input_hash': 'hash', 'input_path': str(source),
                   'attempts': 1, 'interruptions': 0, 'config': json.dumps(effective_config('fixture'))}
            metadata = transcribe(settings, job, Model(), lambda _: None, {'cpu_threads': 4, 'cpus': '4'})
            self.assertEqual(metadata['runtime'], {'cpu_threads': 4, 'cpus': '4'})
            self.assertEqual(metadata['duration_seconds'], 2)
            published = json.loads((settings.outputs / 'job' / 'metadados.json').read_text())
            self.assertEqual(published['runtime'], {'cpu_threads': 4, 'cpus': '4'})


if __name__ == '__main__':
    unittest.main()
