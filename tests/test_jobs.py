import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from whisper_box.config import BoxError, Settings, effective_config
from whisper_box.jobs import ARTIFACTS, complete_output, status, submit, wait
from whisper_box.model import REQUIRED, read_manifest, sha256_file
from whisper_box.store import Store
from whisper_box.worker import worker_lock


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(root / 'state', root / 'input', root / 'output',
                                 root / 'models', r'C:\Projetos\whisper-box')
        self.settings.initialize()
        self.settings.models.mkdir()
        (self.settings.models / 'small').mkdir()
        files = {}
        for name in REQUIRED:
            path = self.settings.models / 'small' / name
            path.write_bytes(b'fixture')
            files[name] = {'size': path.stat().st_size, 'sha256': sha256_file(path)}
        (self.settings.models / 'manifest.json').write_text(json.dumps({
            'repo': 'Systran/faster-whisper-small', 'revision': 'fixture-revision', 'files': files
        }))
        (self.settings.state / 'heartbeat.json').write_text(json.dumps({'timestamp': time.time()}))
        self.source = root / 'reunião com espaços.wav'
        self.source.write_bytes(b'audio fixture')
        self.store = Store(self.settings.state)

    def tearDown(self):
        self.temp.cleanup()

    def enqueue(self):
        return submit(self.settings, self.source, 'pt')['job_id']

    def publish(self, job_id):
        job = self.store.get(job_id)
        destination = self.settings.outputs / job_id
        destination.mkdir()
        for name in ARTIFACTS.values():
            (destination / name).write_text('fixture')
        (destination / 'manifest.json').write_text(json.dumps({
            'fingerprint': job['fingerprint'],
            'sha256': {name: sha256_file(destination / name) for name in ARTIFACTS.values()}
        }))

    def test_submission_copies_and_deduplicates_concurrently(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: submit(self.settings, self.source, 'pt'), range(4)))
        self.assertEqual(len({r['job_id'] for r in results}), 1)
        self.assertEqual(sum(not r['reused'] for r in results), 1)
        self.assertEqual(len(list(self.settings.inputs.iterdir())), 1)
        self.source.write_bytes(b'changed original')
        job = self.store.get(results[0]['job_id'])
        self.assertEqual(Path(job['input_path']).read_bytes(), b'audio fixture')
        self.assertNotIn('texto', results[0])

    def test_configuration_is_part_of_identity(self):
        first = self.enqueue()
        second = submit(self.settings, self.source, 'en')['job_id']
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads(self.store.get(first)['config']), effective_config('fixture-revision'))

    def test_claim_is_atomic_and_fifo(self):
        first = self.enqueue()
        self.source.write_bytes(b'second')
        second = self.enqueue()
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: self.store.claim(), range(4)))
        self.assertEqual({row['id'] for row in claims if row}, {first, second})
        self.assertEqual(sum(row is not None for row in claims), 2)

    def test_failed_work_can_be_resubmitted(self):
        first = self.enqueue()
        self.store.claim()
        self.store.finish(first, BoxError('invalid_media', 'Falha'))
        self.assertNotEqual(first, self.enqueue())

    def test_wait_timeout_preserves_job(self):
        job_id = self.enqueue()
        started = time.monotonic()
        response, code = wait(self.settings, job_id, 1)
        self.assertEqual(code, 2)
        self.assertTrue(response['timed_out'])
        self.assertEqual(self.store.get(job_id)['status'], 'queued')
        self.assertLess(time.monotonic() - started, 2)

    def test_wait_returns_failure_without_files(self):
        job_id = self.enqueue()
        self.store.finish(job_id, BoxError('no_audio', 'Sem áudio'))
        response, code = wait(self.settings, job_id, 1)
        self.assertEqual(code, 1)
        self.assertNotIn('files', response)

    def test_only_complete_verified_outputs_are_announced(self):
        job_id = self.enqueue()
        self.publish(job_id)
        self.store.finish(job_id)
        response, code = wait(self.settings, job_id, 1)
        self.assertEqual(code, 0)
        self.assertTrue(response['files']['text'].startswith('C:\\Projetos\\whisper-box\\saida\\'))
        (self.settings.outputs / job_id / 'transcricao.txt').write_text('altered')
        with self.assertRaisesRegex(BoxError, 'alterados'):
            status(self.settings, job_id, include_files=True)

    def test_recovery_is_bounded_and_preserves_history(self):
        job_id = self.enqueue()
        for attempt in range(1, 4):
            self.assertEqual(self.store.claim()['attempts'], attempt)
            self.store.recover(job_id)
        job = self.store.get(job_id)
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['interruptions'], 3)
        self.assertIsNone(self.store.claim())

    def test_completed_manifest_can_be_recovered_after_crash(self):
        job_id = self.enqueue()
        self.store.claim()
        self.publish(job_id)
        self.assertTrue(complete_output(self.settings, self.store.get(job_id)))

    def test_second_worker_is_rejected(self):
        with worker_lock(self.settings):
            with self.assertRaisesRegex(BoxError, 'Já existe'):
                with worker_lock(self.settings):
                    self.fail('Lock duplicado')

    def test_model_missing_or_corrupt_is_rejected(self):
        read_manifest(self.settings.models, verify=True)
        (self.settings.models / 'small' / 'model.bin').write_bytes(b'corrupt')
        with self.assertRaises(BoxError):
            read_manifest(self.settings.models, verify=True)

    def test_missing_worker_and_bad_arguments_fail_clearly(self):
        (self.settings.state / 'heartbeat.json').unlink()
        with self.assertRaisesRegex(BoxError, 'indisponível'):
            self.enqueue()
        with self.assertRaises(BoxError) as error:
            wait(self.settings, 'anything', 0)
        self.assertEqual(error.exception.exit_code, 3)

    def test_input_change_during_copy_is_rejected(self):
        original_stat = Path.stat
        calls = 0

        def changing_stat(path, *args, **kwargs):
            nonlocal calls
            if path == self.source:
                calls += 1
                if calls == 3:
                    self.source.write_bytes(b'a new recording still being written')
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, 'stat', changing_stat):
            with self.assertRaisesRegex(BoxError, 'mudou'):
                self.enqueue()
        self.assertEqual(list(self.settings.inputs.iterdir()), [])

    def test_cli_stdout_is_one_json_and_exit_codes_are_stable(self):
        env = {**os.environ, 'WHISPER_BOX_STATE': str(self.settings.state)}
        process = subprocess.run([sys.executable, '-m', 'whisper_box', 'status', '--job', 'missing'],
                                 capture_output=True, text=True, env=env)
        self.assertEqual(process.returncode, 3)
        self.assertEqual(len(process.stdout.splitlines()), 1)
        self.assertEqual(json.loads(process.stdout)['error']['code'], 'job_not_found')


if __name__ == '__main__':
    unittest.main()
