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


class WrapperTest(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
