import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_pipeline import write_silence
from whisper_box.config import BoxError, Settings, effective_config
from whisper_box.jobs import ARTIFACTS, submit
from whisper_box.model import REQUIRED, sha256_file
from whisper_box.painel import Gravacoes
from whisper_box.pipeline import transcribe
from whisper_box.retention import (apply_input_retention, clean_partial, parse_policy, purge,
                                   retention_start, sweep_inputs)
from whisper_box.store import Store

DAY = 86400


class Model:
    def transcribe(self, audio, **_kwargs):
        return iter([SimpleNamespace(start=0.1, end=0.5, text='x', avg_logprob=-0.1,
                                      no_speech_prob=0.0)]), \
            SimpleNamespace(language='pt', duration_after_vad=len(audio) / 16000)


class RetentionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root / 'state', self.root / 'input', self.root / 'output',
                                 self.root / 'models')
        self.settings.initialize()
        (self.settings.models / 'small').mkdir(parents=True)
        files = {}
        for name in REQUIRED:
            path = self.settings.models / 'small' / name
            path.write_bytes(b'fixture')
            files[name] = {'size': path.stat().st_size, 'sha256': sha256_file(path)}
        (self.settings.models / 'manifest.json').write_text(json.dumps({
            'repo': 'Systran/faster-whisper-small', 'revision': 'rev', 'files': files}))
        (self.settings.state / 'heartbeat.json').write_text(json.dumps({'timestamp': time.time()}))
        self.store = Store(self.settings.state)
        self.counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def source(self):
        self.counter += 1
        path = self.root / f'origem{self.counter}.wav'
        path.write_bytes(b'audio-%d' % self.counter)
        return path

    def enqueue(self):
        return submit(self.settings, self.source(), 'pt')['job_id']

    def publish(self, job_id):
        job = self.store.get(job_id)
        destination = self.settings.outputs / job_id
        destination.mkdir()
        for name in ARTIFACTS.values():
            (destination / name).write_text('fixture')
        (destination / 'manifest.json').write_text(json.dumps({
            'fingerprint': job['fingerprint'],
            'sha256': {n: sha256_file(destination / n) for n in ARTIFACTS.values()}}))

    def set_finished(self, job_id, finished_at):
        with self.store.connection() as db:
            db.execute('UPDATE jobs SET finished_at=? WHERE id=?', (finished_at, job_id))

    def succeed(self, finished_at=None):
        job_id = self.enqueue()
        self.store.claim()
        self.publish(job_id)
        self.store.finish(job_id)
        if finished_at is not None:
            self.set_finished(job_id, finished_at)
        return job_id

    def fail(self, finished_at=None):
        job_id = self.enqueue()
        self.store.claim()
        self.store.finish(job_id, BoxError('invalid_media', 'ruim'))
        if finished_at is not None:
            self.set_finished(job_id, finished_at)
        return job_id

    def entry(self, job_id):
        return self.settings.inputs / job_id

    def replace_entry_with_symlink(self, job_id, target):
        shutil.rmtree(self.entry(job_id))
        try:
            os.symlink(target, self.entry(job_id), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlink indisponível')

    # -- política -----------------------------------------------------------
    def test_parse_policy(self):
        self.assertEqual(parse_policy(None), ('delete', None))
        self.assertEqual(parse_policy('keep'), ('keep', None))
        self.assertEqual(parse_policy(' 7d '), ('days', 7))
        for bad in ('0d', 'abc', '-1d', '7'):
            with self.assertRaises(BoxError):
                parse_policy(bad)

    # -- .partial -----------------------------------------------------------
    def job_for_pipeline(self, source, attempts=1):
        config = effective_config('rev')
        return {'id': 'a' * 32, 'fingerprint': 'f', 'input_hash': 'h', 'input_path': str(source),
                'attempts': attempts, 'interruptions': 0, 'config': json.dumps(config)}

    def test_failed_attempt_leaves_no_partial(self):
        source = self.root / 'ruim.wav'
        source.write_bytes(b'not audio')
        with self.assertRaises(BoxError):
            transcribe(self.settings, self.job_for_pipeline(source), Model(), lambda _: None)
        self.assertEqual(list((self.settings.outputs / '.partial').iterdir()), [])

    def test_system_exit_leaves_no_partial(self):
        source = self.root / 'ok.wav'
        write_silence(source, 2)

        class Boom:
            def transcribe(self, *_a, **_k):
                raise SystemExit(0)
        with self.assertRaises(SystemExit):
            transcribe(self.settings, self.job_for_pipeline(source), Boom(), lambda _: None)
        self.assertEqual(list((self.settings.outputs / '.partial').iterdir()), [])

    def test_success_removes_empty_job_partial_and_publishes(self):
        source = self.root / 'ok.wav'
        write_silence(source, 2)
        job = self.job_for_pipeline(source)
        transcribe(self.settings, job, Model(), lambda _: None)
        self.assertEqual(list((self.settings.outputs / '.partial').iterdir()), [])
        self.assertTrue((self.settings.outputs / job['id'] / 'manifest.json').is_file())

    def test_clean_partial_removes_orphans_but_not_final_outputs(self):
        orphan = self.settings.outputs / '.partial' / 'x' / 'y'
        orphan.mkdir(parents=True)
        (orphan / 'f.txt').write_text('abc')
        job_id = self.succeed()
        result = clean_partial(self.settings)
        self.assertEqual(result, {'items': 1, 'bytes': 3})
        self.assertEqual(list((self.settings.outputs / '.partial').iterdir()), [])
        self.assertTrue((self.settings.outputs / job_id / 'manifest.json').is_file())

    # -- retenção da entrada --------------------------------------------------
    def test_delete_policy_removes_input_after_verified_success_and_dedup_still_reuses(self):
        source = self.source()
        job_id = submit(self.settings, source, 'pt')['job_id']
        self.store.claim()
        self.publish(job_id)
        self.store.finish(job_id)
        freed = apply_input_retention(self.settings, self.store, self.store.get(job_id),
                                      ('delete', None))
        self.assertGreater(freed, 0)
        self.assertFalse(self.entry(job_id).exists())
        again = submit(self.settings, source, 'pt')
        self.assertEqual((again['job_id'], again['reused']), (job_id, True))
        leftovers = [p.name for p in self.settings.inputs.iterdir() if p.name != '.gravacoes']
        self.assertEqual(leftovers, [])
        self.assertTrue(source.is_file())  # original intocado

    def test_keep_policy_keeps_input(self):
        job_id = self.succeed()
        self.assertIsNone(apply_input_retention(self.settings, self.store, self.store.get(job_id),
                                                ('keep', None)))
        self.assertTrue(self.entry(job_id).is_dir())

    def test_unverified_success_keeps_input(self):
        job_id = self.enqueue()
        self.store.claim()
        self.store.finish(job_id)  # sucesso sem saída publicada
        self.assertIsNone(apply_input_retention(self.settings, self.store, self.store.get(job_id),
                                                ('delete', None)))
        self.assertTrue(self.entry(job_id).is_dir())

    def test_failed_queued_running_never_removed(self):
        failed = self.fail()
        queued = self.enqueue()
        running = self.enqueue()
        with self.store.connection() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (running,))
        for job_id in (failed, queued, running):
            self.assertIsNone(apply_input_retention(self.settings, self.store,
                                                    self.store.get(job_id), ('delete', None)))
        sweep_inputs(self.settings, self.store, ('delete', None))
        for job_id in (failed, queued, running):
            self.assertTrue(self.entry(job_id).is_dir())

    def test_days_policy_respects_age(self):
        now = time.time()
        old = self.succeed(finished_at=now - 8 * DAY)
        recent = self.succeed(finished_at=now - 1 * DAY)
        result = sweep_inputs(self.settings, self.store, ('days', 7), now=now)
        self.assertEqual(result['removed'], 1)
        self.assertFalse(self.entry(old).exists())
        self.assertTrue(self.entry(recent).is_dir())

    def test_sweep_skips_history_before_activation_and_unknown_dirs(self):
        now = time.time()
        legacy = self.succeed(finished_at=now - 10)
        fresh = self.succeed(finished_at=now + 5)
        unknown = self.settings.inputs / ('b' * 32)  # submit em andamento: sem job
        unknown.mkdir()
        (self.settings.inputs / '.gravacoes' / 'x').mkdir(parents=True)
        sweep_inputs(self.settings, self.store, ('delete', None), since=now)
        self.assertTrue(self.entry(legacy).is_dir())
        self.assertFalse(self.entry(fresh).exists())
        self.assertTrue(unknown.is_dir())
        self.assertTrue((self.settings.inputs / '.gravacoes' / 'x').is_dir())

    def test_retention_marker_is_written_once(self):
        self.assertEqual(retention_start(self.settings, now=100.0), 100.0)
        self.assertEqual(retention_start(self.settings, now=999.0), 100.0)

    def test_retention_ignores_symlinked_input(self):
        job_id = self.succeed()
        target = self.root / 'alvo'
        target.mkdir()
        (target / 'keep.txt').write_text('x')
        self.replace_entry_with_symlink(job_id, target)
        apply_input_retention(self.settings, self.store, self.store.get(job_id), ('delete', None))
        self.assertTrue((target / 'keep.txt').is_file())

    # -- purge ----------------------------------------------------------------
    def test_purge_job_dry_run_changes_nothing(self):
        job_id = self.succeed()
        other = self.succeed()
        (self.settings.outputs / '.partial' / job_id).mkdir(parents=True)
        response, code = purge(self.settings, job_id=job_id)
        self.assertEqual(code, 0)
        self.assertTrue(response['dry_run'])
        self.assertEqual(response['would_purge'][0]['job_id'], job_id)
        self.assertGreater(response['would_purge'][0]['input_bytes'], 0)
        self.assertGreater(response['freed_bytes'], 0)
        self.assertTrue(self.entry(job_id).is_dir())
        self.assertTrue((self.settings.outputs / job_id).is_dir())
        self.assertEqual(self.store.get(job_id)['id'], job_id)
        self.assertEqual(self.store.get(other)['id'], other)

    def test_purge_job_yes_removes_only_that_job(self):
        job_id = self.succeed()
        other = self.succeed()
        (self.settings.outputs / '.partial' / job_id).mkdir(parents=True)
        response, code = purge(self.settings, job_id=job_id, yes=True)
        self.assertEqual(code, 0)
        self.assertFalse(response['dry_run'])
        self.assertEqual([i['job_id'] for i in response['purged']], [job_id])
        for path in (self.entry(job_id), self.settings.outputs / job_id,
                     self.settings.outputs / '.partial' / job_id):
            self.assertFalse(path.exists())
        with self.assertRaises(BoxError) as ctx:
            self.store.get(job_id)
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ('job_not_found', 3))
        self.assertTrue(self.entry(other).is_dir())
        self.assertTrue((self.settings.outputs / other).is_dir())
        self.store.get(other)

    def test_purge_refuses_active_malformed_unknown_and_bad_combinations(self):
        queued = self.enqueue()
        with self.assertRaises(BoxError) as ctx:
            purge(self.settings, job_id=queued, yes=True)
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ('job_active', 3))
        self.assertTrue(self.entry(queued).is_dir())
        self.store.claim()
        with self.assertRaises(BoxError) as ctx:
            purge(self.settings, job_id=queued, yes=True)
        self.assertEqual(ctx.exception.code, 'job_active')
        for bad in ('../x', 'A' * 32, 'abc', '..\\..'):
            with self.assertRaises(BoxError) as ctx:
                purge(self.settings, job_id=bad, yes=True)
            self.assertEqual(ctx.exception.exit_code, 3)
        with self.assertRaises(BoxError) as ctx:
            purge(self.settings, job_id='c' * 32)
        self.assertEqual(ctx.exception.code, 'job_not_found')
        for kwargs in ({}, {'job_id': queued, 'older_than': 1}, {'older_than': -1},
                       {'older_than': 1, 'status': 'queued'}):
            with self.assertRaises(BoxError) as ctx:
                purge(self.settings, **kwargs)
            self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ('invalid_arguments', 3))

    def test_purge_does_not_follow_symlinks_outside(self):
        job_id = self.succeed()
        outside = self.root / 'fora'
        outside.mkdir()
        (outside / 'a.txt').write_text('x')
        self.replace_entry_with_symlink(job_id, outside)
        purge(self.settings, job_id=job_id, yes=True)
        self.assertTrue((outside / 'a.txt').is_file())

    def test_purge_older_than_with_status_lists_only_matching(self):
        now = time.time()
        old_failed = self.fail(finished_at=now - 40 * DAY)
        self.fail(finished_at=now - 5 * DAY)
        self.succeed(finished_at=now - 40 * DAY)
        queued = self.enqueue()
        response, code = purge(self.settings, older_than=30, status='failed', now=now)
        self.assertEqual(code, 0)
        self.assertEqual([i['job_id'] for i in response['would_purge']], [old_failed])
        response, _ = purge(self.settings, older_than=30, now=now)
        self.assertEqual(len(response['would_purge']), 2)
        self.assertNotIn(queued, [i['job_id'] for i in response['would_purge']])
        self.assertTrue(self.entry(old_failed).is_dir())

    def test_purge_inputs_only_keeps_output_and_record(self):
        job_id = self.succeed()
        response, _ = purge(self.settings, job_id=job_id, yes=True, inputs_only=True)
        self.assertEqual(response['purged'][0]['output_bytes'], 0)
        self.assertFalse(self.entry(job_id).exists())
        self.assertTrue((self.settings.outputs / job_id / 'manifest.json').is_file())
        self.assertEqual(self.store.get(job_id)['status'], 'succeeded')


class StagingCleanupTest(unittest.TestCase):
    def test_cleanup_removes_only_old_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root / 's', root / 'i', root / 'o', root / 'm')
            settings.initialize()
            gravacoes = Gravacoes(settings)
            old, recent, closed = 'a' * 32, 'b' * 32, 'c' * 32
            staging = settings.inputs / '.gravacoes'
            job_dir = settings.inputs / ('d' * 32)
            job_dir.mkdir()
            (job_dir / 'source.wav').write_bytes(b'x')
            for rid in (old, recent):
                (staging / (rid + '.part')).write_bytes(b'12345')
                (staging / (rid + '.meta')).write_text('{}')
            (staging / closed).mkdir()
            (staging / closed / 'gravacao.webm').write_bytes(b'abc')
            (staging / 'estranho.txt').write_text('nao tocar')
            ancient = time.time() - 10 * DAY
            for path in [staging / (old + '.part'), staging / (old + '.meta'),
                         staging / closed / 'gravacao.webm', staging / closed]:
                os.utime(path, (ancient, ancient))
            result = gravacoes.cleanup(7)
            self.assertEqual(result['removed'], 2)
            self.assertFalse((staging / (old + '.part')).exists())
            self.assertFalse((staging / (old + '.meta')).exists())
            self.assertFalse((staging / closed).exists())
            self.assertTrue((staging / (recent + '.part')).exists())
            self.assertTrue((staging / 'estranho.txt').exists())
            self.assertTrue((job_dir / 'source.wav').exists())  # entrada/<job_id> nunca é tocada


if __name__ == '__main__':
    unittest.main()
