import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from whisper_box.config import BoxError, Settings, effective_config
from whisper_box.jobs import ARTIFACTS, complete_output, list_jobs, output_state, status, submit, wait
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

    def test_posix_host_root_produces_posix_paths(self):
        job_id = self.enqueue()
        self.publish(job_id)
        self.store.finish(job_id)
        settings = Settings(self.settings.state, self.settings.inputs, self.settings.outputs,
                            self.settings.models, '/home/usuario/whisper-box')
        response = status(settings, job_id, include_files=True)
        self.assertEqual(response['files']['text'],
                         f'/home/usuario/whisper-box/saida/{job_id}/transcricao.txt')

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

    # -- I5: error só em failed ---------------------------------------------
    def test_requeued_job_after_recover_exposes_no_error_but_failed_job_does(self):
        job_id = self.enqueue()
        self.store.claim()
        self.store.recover(job_id)
        self.assertEqual(self.store.get(job_id)['status'], 'queued')
        self.assertNotIn('error', status(self.settings, job_id))
        self.store.claim()
        self.assertIsNone(self.store.get(job_id)['error_code'])
        self.assertEqual(self.store.get(job_id)['interruptions'], 1)
        for _ in range(2):
            self.store.recover(job_id)
            self.store.claim()
        self.store.recover(job_id)
        response = status(self.settings, job_id)
        self.assertEqual((response['status'], response['error']['code']), ('failed', 'interrupted_limit'))

    # -- I6: reprocessar quando a saída foi perdida --------------------------
    def succeed(self, job_id):
        self.store.claim()
        self.publish(job_id)
        self.store.finish(job_id)

    def test_intact_succeeded_job_is_still_reused(self):
        job_id = self.enqueue()
        self.succeed(job_id)
        again = submit(self.settings, self.source, 'pt')
        self.assertEqual((again['job_id'], again['reused']), (job_id, True))

    def test_lost_output_invalidates_old_job_and_creates_a_new_one(self):
        job_id = self.enqueue()
        self.succeed(job_id)
        shutil.rmtree(self.settings.outputs / job_id)
        again = submit(self.settings, self.source, 'pt')
        self.assertFalse(again['reused'])
        self.assertNotEqual(again['job_id'], job_id)
        self.assertEqual(again['status'], 'queued')
        old = self.store.get(job_id)
        self.assertEqual((old['status'], old['error_code']), ('failed', 'output_lost'))
        self.assertEqual(status(self.settings, job_id)['error']['code'], 'output_lost')
        _, code = wait(self.settings, job_id, 1)
        self.assertEqual(code, 1)
        self.store.claim()
        self.publish(again['job_id'])
        self.store.finish(again['job_id'])
        self.assertIn('files', status(self.settings, again['job_id'], include_files=True))
        self.assertEqual(submit(self.settings, self.source, 'pt')['job_id'], again['job_id'])

    def test_altered_output_is_also_reprocessed(self):
        job_id = self.enqueue()
        self.succeed(job_id)
        (self.settings.outputs / job_id / 'transcricao.txt').write_text('altered')
        self.assertFalse(submit(self.settings, self.source, 'pt')['reused'])

    def test_transient_io_error_does_not_invalidate(self):
        job_id = self.enqueue()
        self.succeed(job_id)
        with patch('whisper_box.jobs.sha256_file', side_effect=PermissionError('busy')):
            self.assertEqual(output_state(self.settings, self.store.get(job_id)), 'unknown')
            again = submit(self.settings, self.source, 'pt')
        self.assertEqual((again['job_id'], again['reused']), (job_id, True))
        self.assertEqual(self.store.get(job_id)['status'], 'succeeded')

    def test_queued_and_running_jobs_are_never_invalidated(self):
        job_id = self.enqueue()
        self.assertEqual(submit(self.settings, self.source, 'pt')['job_id'], job_id)
        self.store.claim()
        again = submit(self.settings, self.source, 'pt')
        self.assertEqual((again['job_id'], again['reused'], again['status']), (job_id, True, 'running'))

    # -- comando list -------------------------------------------------------
    def make_job(self, content, created_at, status_name='queued', language='pt'):
        self.source.write_bytes(content)
        job_id = submit(self.settings, self.source, language)['job_id']
        with self.store.connection() as db:
            db.execute("UPDATE jobs SET created_at=? WHERE id=?", (created_at, job_id))
        if status_name == 'running':
            self.force_running(job_id, created_at)
        elif status_name == 'failed':
            self.force_running(job_id, created_at)
            self.store.finish(job_id, BoxError('no_audio', 'Sem áudio'))
        elif status_name == 'succeeded':
            self.force_running(job_id, created_at)
            self.publish(job_id)
            metadata = self.settings.outputs / job_id / 'metadados.json'
            metadata.write_text(json.dumps({'duration_seconds': 12.5, 'texto': 'segredo da reunião'}))
            self.refresh_manifest(job_id)
            self.store.finish(job_id)
        return job_id

    def force_running(self, job_id, created_at):
        with self.store.connection() as db:
            db.execute("UPDATE jobs SET status='running', attempts=1, started_at=? WHERE id=?",
                       (created_at + 1, job_id))

    def refresh_manifest(self, job_id):
        directory = self.settings.outputs / job_id
        manifest = json.loads((directory / 'manifest.json').read_text())
        manifest['sha256'] = {name: sha256_file(directory / name) for name in ARTIFACTS.values()}
        (directory / 'manifest.json').write_text(json.dumps(manifest))

    def test_list_schema_order_and_privacy(self):
        queued = self.make_job(b'q', 1000.0)
        succeeded = self.make_job(b's', 2000.0, 'succeeded', 'auto')
        failed = self.make_job(b'f', 3000.0, 'failed')
        running = self.make_job(b'r', 4000.0, 'running')
        response = list_jobs(self.settings)
        self.assertEqual([j['job_id'] for j in response['jobs']], [running, failed, succeeded, queued])
        by_id = {j['job_id']: j for j in response['jobs']}
        item = by_id[succeeded]
        self.assertEqual((item['status'], item['language'], item['duration_seconds']), ('succeeded', 'auto', 12.5))
        self.assertEqual(item['output_relative'], 'saida/' + succeeded)
        self.assertEqual(sorted(item['files']), ['metadata', 'segments', 'srt', 'text'])
        self.assertEqual(item['source_name'], self.source.name)
        self.assertNotIn('error', item)
        self.assertEqual(by_id[failed]['error']['code'], 'no_audio')
        for other in (queued, running, failed):
            self.assertNotIn('files', by_id[other])
            self.assertIsNone(by_id[other]['duration_seconds'])
        self.assertNotIn('error', by_id[running])
        self.assertIsNone(by_id[queued]['started_at'])
        self.assertTrue(item['created_at'].endswith('+00:00'))
        self.assertNotIn('segredo', json.dumps(response, ensure_ascii=False))
        self.assertNotIn('texto', json.dumps(response))

    def test_list_filters_by_status_limit_and_empty_result(self):
        self.make_job(b'a', 1000.0)
        failed = self.make_job(b'b', 2000.0, 'failed')
        self.make_job(b'c', 3000.0)
        self.assertEqual([j['job_id'] for j in list_jobs(self.settings, status='failed')['jobs']], [failed])
        self.assertEqual(len(list_jobs(self.settings, limit=2)['jobs']), 2)
        self.assertEqual(list_jobs(self.settings, status='succeeded'), {'jobs': []})
        for bad in (0, 201):
            with self.assertRaises(BoxError) as error:
                list_jobs(self.settings, limit=bad)
            self.assertEqual((error.exception.code, error.exception.exit_code), ('invalid_arguments', 3))

    def test_list_dates_are_inclusive_and_use_the_host_offset(self):
        from datetime import date, datetime, timezone
        # 23:30 de 19/11 em UTC-3 equivale a 02:30 de 20/11 em UTC.
        late = datetime(2026, 11, 20, 2, 30, tzinfo=timezone.utc).timestamp()
        job = self.make_job(b'late', late)
        on_19 = list_jobs(self.settings, since=date(2026, 11, 19), until=date(2026, 11, 19), utc_offset_minutes=-180)
        self.assertEqual([j['job_id'] for j in on_19['jobs']], [job])
        self.assertEqual(on_19['jobs'][0]['created_at'], '2026-11-19T23:30:00-03:00')
        self.assertEqual(list_jobs(self.settings, since=date(2026, 11, 20), utc_offset_minutes=-180), {'jobs': []})
        self.assertEqual(list_jobs(self.settings, since=date(2026, 11, 20))['jobs'][0]['job_id'], job)
        self.assertEqual(list_jobs(self.settings, until=date(2026, 11, 19)), {'jobs': []})

    def test_list_omits_files_for_invalid_output_without_failing(self):
        job = self.make_job(b'x', 1000.0, 'succeeded')
        (self.settings.outputs / job / 'transcricao.txt').write_text('altered')
        item = list_jobs(self.settings)['jobs'][0]
        self.assertEqual(item['status'], 'succeeded')
        self.assertNotIn('files', item)
        self.assertIsNone(item['duration_seconds'])

    def test_list_cli_contract(self):
        self.make_job(b'x', 1000.0)
        env = {**os.environ, 'WHISPER_BOX_STATE': str(self.settings.state)}

        def run(*arguments):
            process = subprocess.run([sys.executable, '-m', 'whisper_box', 'list', *arguments],
                                     capture_output=True, text=True, env=env)
            self.assertEqual(len(process.stdout.splitlines()), 1)
            return process.returncode, json.loads(process.stdout)

        code, body = run('--utc-offset-minutes', '-180', '--since', '1969-12-30')
        self.assertEqual((code, len(body['jobs'])), (0, 1))
        self.assertTrue(body['jobs'][0]['created_at'].endswith('-03:00'))
        self.assertEqual(run('--status', 'failed'), (0, {'jobs': []}))
        for bad in (['--status', 'nada'], ['--since', '2026-13-40'], ['--since', '19/11/2026'],
                    ['--limit', '0'], ['--limit', '201'], ['--limit', 'x'], ['--utc-offset-minutes', '900']):
            code, body = run(*bad)
            self.assertEqual((code, body['error']['code']), (3, 'invalid_arguments'), bad)

    def test_cli_stdout_is_one_json_and_exit_codes_are_stable(self):
        env = {**os.environ, 'WHISPER_BOX_STATE': str(self.settings.state)}
        process = subprocess.run([sys.executable, '-m', 'whisper_box', 'status', '--job', 'missing'],
                                 capture_output=True, text=True, env=env)
        self.assertEqual(process.returncode, 3)
        self.assertEqual(len(process.stdout.splitlines()), 1)
        self.assertEqual(json.loads(process.stdout)['error']['code'], 'job_not_found')


if __name__ == '__main__':
    unittest.main()
