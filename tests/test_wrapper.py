import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

WRAPPER = Path(__file__).resolve().parents[1] / 'whisper-box.py'
spec = importlib.util.spec_from_file_location('whisper_box_wrapper', WRAPPER)
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


def completed(code=0, stdout=b''):
    return subprocess.CompletedProcess([], code, stdout=stdout)


class CallMixin:
    def call(self, argv, responses=None):
        out = io.StringIO()
        calls = []

        def fake_run(arguments, **kwargs):
            calls.append((arguments, kwargs))
            return responses.pop(0) if responses else completed()

        with patch.object(wrapper.subprocess, 'run', side_effect=fake_run):
            code = wrapper.main(argv, out)
        lines = [line for line in out.getvalue().splitlines() if line]
        return code, lines, calls


class WrapperTest(CallMixin, unittest.TestCase):
    def test_invalid_arguments_return_code_3_and_one_json(self):
        for argv in ([], ['desconhecido'], ['submit'], ['submit', '--input']):
            code, lines, calls = self.call(argv)
            self.assertEqual(code, 3)
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])['error']['code'], 'invalid_arguments')
            self.assertEqual(calls, [])

    def test_missing_input_is_rejected_before_docker(self):
        code, lines, calls = self.call(['submit', '--input', '/nao/existe.mp4'])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(lines[0])['error']['code'], 'input_not_found')
        self.assertEqual(calls, [])

    def test_submit_mounts_only_the_recording_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'reunião com espaços.MP4'
            source.write_bytes(b'media')
            body = b'{"job_id": "abc", "status": "queued", "reused": false}\n'
            code, lines, calls = self.call(['submit', '--input', str(source), '--language', 'en'],
                                           [completed(0, body)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(lines[0])['job_id'], 'abc')
        arguments, kwargs = calls[0]
        mount = arguments[arguments.index('--volume') + 1]
        self.assertEqual(mount, str(source.resolve()) + ':/source/recording.MP4:ro')
        self.assertEqual(arguments[-5:], ['submit', '--input', '/source/recording.MP4', '--language', 'en'])
        self.assertEqual(kwargs['env']['WHISPER_BOX_HOST_ROOT'], str(wrapper.ROOT))
        self.assertEqual(kwargs['stdout'], subprocess.PIPE)

    def test_job_commands_preserve_container_exit_code(self):
        body = '{"job_id": "abc", "status": "running", "timed_out": true}\n'.encode()
        code, lines, calls = self.call(['wait', '--job', 'abc', '--timeout', '30'], [completed(2, body)])
        self.assertEqual(code, 2)
        self.assertTrue(json.loads(lines[0])['timed_out'])
        self.assertEqual(calls[0][0][-6:], ['cli', 'wait', '--job', 'abc', '--timeout', '30'])

    def test_utf8_json_is_preserved(self):
        body = json.dumps({'error': {'code': 'invalid_media', 'message': 'Mídia inválida'}},
                          ensure_ascii=False).encode('utf-8')
        code, lines, _ = self.call(['result', '--job', 'abc'], [completed(1, body)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(lines[0])['error']['message'], 'Mídia inválida')

    def test_empty_container_response_becomes_docker_error(self):
        code, lines, _ = self.call(['status', '--job', 'abc'], [completed(0, b'')])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(lines[0])['error']['code'], 'docker_error')

    def test_lifecycle_commands_report_status_or_docker_error(self):
        code, lines, calls = self.call(['start'], [completed(0)])
        self.assertEqual((code, lines), (0, ['{"status":"ready"}']))
        self.assertIn('--wait', calls[0][0])
        code, lines, _ = self.call(['stop'], [completed(1)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(lines[-1])['error']['code'], 'docker_error')

    def test_prepare_skips_model_when_build_fails(self):
        code, lines, calls = self.call(['prepare'], [completed(1)])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(lines[-1])['error']['code'], 'docker_error')


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def diagnose(self, docker='/usr/bin/docker', responses=(), model=True):
        if model:
            (self.root / 'modelos').mkdir()
            (self.root / 'modelos' / 'manifest.json').write_text('{}')
        responses = list(responses)
        out = io.StringIO()
        with patch.object(wrapper, 'ROOT', self.root), \
                patch.object(wrapper.shutil, 'which', return_value=docker), \
                patch.object(wrapper.subprocess, 'run', side_effect=lambda *a, **k: responses.pop(0)):
            code = wrapper.main(['doctor'], out)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        return code, json.loads(lines[0])

    def test_missing_docker_asks_approval_to_install(self):
        code, body = self.diagnose(docker=None)
        self.assertEqual(code, 1)
        self.assertFalse(body['ready'])
        self.assertEqual(body['next_step']['code'], 'install_docker')
        self.assertTrue(body['next_step']['requires_user_approval'])
        self.assertIn(body['platform'], ('windows', 'linux', 'macos'))

    def test_stopped_engine_asks_to_start_docker(self):
        code, body = self.diagnose(responses=[completed(0, b'2.29.0'), completed(1, b'')])
        self.assertEqual(code, 1)
        self.assertEqual(body['next_step']['code'], 'start_docker')

    def test_missing_image_or_model_asks_for_prepare(self):
        code, body = self.diagnose(responses=[completed(0, b'2.29.0'), completed(0, b'linux'), completed(1)],
                                   model=False)
        self.assertEqual(code, 1)
        self.assertEqual(body['next_step']['code'], 'prepare')
        self.assertFalse(body['checks']['image']['ok'])
        self.assertFalse(body['checks']['model']['ok'])

    def test_ready_host_asks_for_recording(self):
        code, body = self.diagnose(responses=[completed(0, b'2.29.0'), completed(0, b'linux'), completed(0)])
        self.assertEqual(code, 0)
        self.assertTrue(body['ready'])
        self.assertEqual(body['next_step']['code'], 'ask_for_recording')


class TranscribeTest(CallMixin, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'reunião.wav'
        self.source.write_bytes(b'media')

    def tearDown(self):
        self.temp.cleanup()

    def result(self, create=True):
        files = {}
        for key in wrapper.ARTIFACTS:
            files[key] = str(self.root / (key + '.out'))
            if create:
                Path(files[key]).write_text('fixture')
        return completed(0, json.dumps({'job_id': 'abc', 'status': 'succeeded', 'files': files}).encode())

    def commands(self, calls):
        names = []
        for arguments, _ in calls:
            for name in ('up', 'submit', 'wait', 'result'):
                if name in arguments:
                    names.append(name)
                    break
        return names

    def test_full_flow_renews_wait_without_resubmitting(self):
        submitted = completed(0, b'{"job_id": "abc", "status": "queued", "reused": false}')
        running = completed(2, b'{"job_id": "abc", "status": "running", "timed_out": true}')
        done = completed(0, b'{"job_id": "abc", "status": "succeeded"}')
        pending = completed(4, b'{"job_id": "abc", "status": "running"}')
        code, lines, calls = self.call(['transcribe', '--input', str(self.source)],
                                       [completed(0), submitted, running, done, pending, done, self.result()])
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])['status'], 'succeeded')
        self.assertEqual(self.commands(calls), ['up', 'submit', 'wait', 'wait', 'result', 'wait', 'result'])
        self.assertIn('pt', calls[1][0])

    def test_resume_by_job_does_not_submit(self):
        code, _, calls = self.call(['transcribe', '--job', 'abc'],
                                   [completed(0), completed(0, b'{"status": "succeeded"}'), self.result()])
        self.assertEqual(code, 0)
        self.assertEqual(self.commands(calls), ['up', 'wait', 'result'])

    def test_budget_exhausted_returns_code_2_with_job_id(self):
        running = completed(2, b'{"job_id": "abc", "status": "running", "timed_out": true}')
        with patch.object(wrapper.time, 'monotonic', side_effect=[0, 0, 5]):
            code, lines, _ = self.call(['transcribe', '--job', 'abc', '--timeout-seconds', '1'],
                                       [completed(0), running])
        body = json.loads(lines[0])
        self.assertEqual(code, 2)
        self.assertEqual((body['job_id'], body['status']), ('abc', 'running'))
        self.assertTrue(body['wait_budget_exhausted'])

    def test_failures_stop_the_flow(self):
        code, lines, calls = self.call(['transcribe', '--job', 'abc'], [completed(1)])
        self.assertEqual((code, len(calls)), (1, 1))
        self.assertEqual(json.loads(lines[0])['error']['code'], 'docker_error')
        failed = completed(1, b'{"job_id": "abc", "status": "failed", "error": {"code": "invalid_media"}}')
        code, lines, calls = self.call(['transcribe', '--input', str(self.source)],
                                       [completed(0), completed(0, b'{"job_id": "abc"}'), failed])
        self.assertEqual(code, 1)
        self.assertEqual(self.commands(calls), ['up', 'submit', 'wait'])
        code, lines, _ = self.call(['transcribe', '--job', 'abc'],
                                   [completed(0), completed(0, b'{}'), self.result(create=False)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(lines[0])['error']['code'], 'output_unreachable')

    def test_invalid_arguments_do_not_touch_docker(self):
        for argv in (['transcribe'], ['transcribe', '--input', 'a', '--job', 'b'],
                     ['transcribe', '--job', 'x', '--language', 'en'],
                     ['transcribe', '--job', 'x', '--timeout-seconds', '0']):
            code, lines, calls = self.call(argv)
            self.assertEqual(code, 3)
            self.assertEqual(json.loads(lines[0])['error']['code'], 'invalid_arguments')
            self.assertEqual(calls, [])
        code, lines, calls = self.call(['transcribe', '--input', str(self.root / 'nao-existe.mp4')])
        self.assertEqual((code, calls), (3, []))
        self.assertEqual(json.loads(lines[0])['error']['code'], 'input_not_found')


if __name__ == '__main__':
    unittest.main()
