import contextlib
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
        with patch.dict(wrapper.os.environ, {'WHISPER_BOX_PAINEL_PORT': ''}):
            code, lines, calls = self.call(['start'], [completed(0), completed(0)])
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), {'status': 'ready',
                                                'painel_url': 'http://127.0.0.1:8765/'})
        self.assertIn('--wait', calls[0][0])
        self.assertEqual(calls[0][0][-1], 'worker')
        self.assertEqual(calls[1][0][-1], 'painel')
        code, lines, calls = self.call(['stop'], [completed(0)])
        self.assertEqual((code, lines), (0, ['{"status":"stopped"}']))
        self.assertEqual(calls[0][0][-3:], ['stop', 'worker', 'painel'])
        code, lines, _ = self.call(['stop'], [completed(1)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(lines[-1])['error']['code'], 'docker_error')

    def test_start_honors_panel_port_from_environment(self):
        with patch.dict(wrapper.os.environ, {'WHISPER_BOX_PAINEL_PORT': '9000'}):
            code, lines, _ = self.call(['start'], [completed(0), completed(0)])
        self.assertEqual(json.loads(lines[0])['painel_url'], 'http://127.0.0.1:9000/')

    def test_panel_failure_does_not_break_start(self):
        code, lines, _ = self.call(['start'], [completed(0), completed(1)])
        body = json.loads(lines[0])
        self.assertEqual((code, len(lines), body['status']), (0, 1, 'ready'))
        self.assertIn('painel_error', body)
        self.assertNotIn('painel_url', body)

    def test_worker_failure_skips_panel(self):
        code, lines, calls = self.call(['start'], [completed(1)])
        self.assertEqual((code, len(calls)), (1, 1))
        self.assertEqual(json.loads(lines[-1])['error']['code'], 'docker_error')

    def test_prepare_skips_model_when_build_fails(self):
        code, lines, calls = self.call(['prepare'], [completed(1)])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(lines[-1])['error']['code'], 'docker_error')

    def test_prepare_success_prints_exactly_one_json(self):
        body = b'{"status": "ready", "model": "small", "revision": "r", "reused": true}'
        code, lines, calls = self.call(['prepare'], [completed(0), completed(0, body)])
        self.assertEqual((code, len(lines)), (0, 1))
        self.assertEqual(json.loads(lines[0])['status'], 'ready')
        build, prepare = calls[0][0], calls[1][0]
        self.assertEqual(build[-3:-1], ['--build-arg', 'SOURCE_DIGEST=' + wrapper.source_digest()])
        self.assertEqual(prepare[-1], 'prepare')
        self.assertEqual(calls[1][1]['stdout'], subprocess.PIPE)

    def test_prepare_container_failure_prints_exactly_one_json(self):
        engine_error = b'{"error": {"code": "model_not_ready", "message": "Modelo invalido."}}'
        for output in (engine_error, b'', b'Traceback boom'):
            with self.subTest(output=output):
                code, lines, _ = self.call(['prepare'], [completed(0), completed(1, output)])
                self.assertEqual((code, len(lines)), (1, 1))
                expected = 'model_not_ready' if output == engine_error else 'docker_error'
                self.assertEqual(json.loads(lines[0])['error']['code'], expected)

    def test_status_commands_report_timeout_and_interrupt_with_job_id(self):
        job = 'b' * 32
        for failure, code_name in ((subprocess.TimeoutExpired(['docker'], 1), 'docker_timeout'),
                                   (KeyboardInterrupt(), 'interrupted')):
            out = io.StringIO()
            calls = []

            def fake_run(arguments, **kwargs):
                calls.append(arguments)
                if arguments[:2] == ['docker', 'rm']:
                    return completed(0)
                raise failure

            with patch.object(wrapper.subprocess, 'run', side_effect=fake_run):
                code = wrapper.main(['status', '--job', job], out)
            body = json.loads(out.getvalue())
            self.assertEqual((code, body['job_id'], body['error']['code']), (1, job, code_name))
            self.assertEqual(calls[-1][:3], ['docker', 'rm', '-f'])

    def test_wait_timeout_follows_requested_wait(self):
        _, _, calls = self.call(['wait', '--job', 'a' * 32, '--timeout', '45'],
                                [completed(0, b'{"status": "succeeded"}')])
        self.assertEqual(calls[0][1]['timeout'], 105)


class BrowserTest(unittest.TestCase):
    def find(self, platform, existing=(), env=None, which=None):
        existing = set(existing)
        return wrapper.find_browser(env or {}, platform, exists=lambda p: p in existing,
                                    which=lambda name: (which or {}).get(name))

    def test_windows_prefers_edge_and_searches_all_bases(self):
        env = {'ProgramFiles': r'C:\Program Files', 'ProgramFiles(x86)': r'C:\Program Files (x86)',
               'LOCALAPPDATA': r'C:\Users\u\AppData\Local'}
        edge = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
        chrome = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
        local_chrome = r'C:\Users\u\AppData\Local\Google\Chrome\Application\chrome.exe'
        self.assertEqual(self.find('windows', [edge, chrome], env), edge)
        self.assertEqual(self.find('windows', [chrome], env), chrome)
        self.assertEqual(self.find('windows', [local_chrome], env), local_chrome)
        self.assertIsNone(self.find('windows', [], env))

    def test_windows_env_copy_with_uppercase_keys(self):
        # dict(os.environ) no Windows tem chaves em maiúsculas.
        env = {'PROGRAMFILES': r'C:\Program Files', 'PROGRAMFILES(X86)': r'C:\Program Files (x86)'}
        edge = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
        self.assertEqual(self.find('windows', [edge], env), edge)

    def test_macos_prefers_chrome(self):
        chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        edge = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
        self.assertEqual(self.find('macos', [edge, chrome]), chrome)
        self.assertEqual(self.find('macos', [edge]), edge)
        self.assertIsNone(self.find('macos'))

    def test_linux_uses_path_lookup_in_order(self):
        found = {'chromium': '/usr/bin/chromium', 'google-chrome': '/usr/bin/google-chrome'}
        self.assertEqual(self.find('linux', which=found), '/usr/bin/google-chrome')
        self.assertIsNone(self.find('linux'))

    def test_explicit_browser_overrides_search(self):
        env = {'WHISPER_BOX_NAVEGADOR': '/opt/meu/navegador'}
        self.assertEqual(self.find('linux', ['/opt/meu/navegador'], env, {'chromium': '/x'}), '/opt/meu/navegador')
        self.assertIsNone(self.find('linux', [], env, {'chromium': '/x'}))

    def test_browser_arguments(self):
        root = Path('/repo')
        arguments = wrapper.browser_arguments('/b/edge', 'http://127.0.0.1:8765/?ajudante=8766&token=t', root)
        self.assertEqual(arguments, [
            '/b/edge', '--app=http://127.0.0.1:8765/?ajudante=8766&token=t',
            '--user-data-dir=' + str(root / '.navegador'), '--window-size=380,640',
            '--no-first-run', '--no-default-browser-check'])


class PanelCommandTest(CallMixin, unittest.TestCase):
    def test_browser_not_found_returns_url_and_code_1(self):
        with patch.object(wrapper, 'find_browser', return_value=None), \
                patch.dict(wrapper.os.environ, {'WHISPER_BOX_PAINEL_PORT': ''}):
            code, lines, calls = self.call(['painel'], [completed(0), completed(0)])
        self.assertEqual((code, len(lines)), (1, 1))
        error = json.loads(lines[0])['error']
        self.assertEqual(error['code'], 'browser_not_found')
        self.assertIn('http://127.0.0.1:8765/', error['message'])
        self.assertEqual((calls[0][0][-1], calls[1][0][-1]), ('worker', 'painel'))

    def test_worker_failure_stops_before_browser(self):
        with patch.object(wrapper, 'find_browser') as find:
            code, lines, calls = self.call(['painel'], [completed(1)])
        self.assertEqual((code, len(calls)), (1, 1))
        self.assertEqual(json.loads(lines[0])['error']['code'], 'docker_error')
        find.assert_not_called()

    def test_opens_app_window_prints_one_json_without_token_and_exits_with_browser(self):
        launched = []
        real_start_helper = wrapper.start_helper

        class FakeProcess:
            polls = 0

            def poll(self):
                FakeProcess.polls += 1
                return None if FakeProcess.polls < 3 else 0

            def terminate(self):
                raise AssertionError('o navegador ja tinha terminado')

        def fake_popen(arguments, **kwargs):
            launched.append(arguments)
            return FakeProcess()

        with patch.object(wrapper, 'find_browser', return_value='/b/edge'), \
                patch.object(wrapper, 'BROWSER_SETTLE_SECONDS', 0.0), \
                patch.object(wrapper, 'start_helper', wraps=lambda token, panel_port: real_start_helper(
                    token, panel_port, base_port=0)) as helper, \
                patch.object(wrapper.subprocess, 'Popen', side_effect=fake_popen), \
                patch.dict(wrapper.os.environ, {'WHISPER_BOX_PAINEL_PORT': ''}):
            code, lines, _ = self.call(['painel'], [completed(0), completed(0)])
        self.assertEqual(code, 0)
        body = json.loads(lines[0])
        self.assertEqual(len(lines), 1)
        self.assertEqual((body['status'], body['painel_url']), ('open', 'http://127.0.0.1:8765/'))
        self.assertNotIn('token', lines[0])
        arguments = launched[0]
        self.assertEqual(arguments[0], '/b/edge')
        self.assertRegex(arguments[1], r'^--app=http://127\.0\.0\.1:8765/\?ajudante=%d&token=[\w-]{32}$'
                         % body['ajudante_port'])
        self.assertIn('--window-size=380,640', arguments)
        self.assertIn('--user-data-dir=' + str(wrapper.ROOT / '.navegador'), arguments)
        helper.assert_called_once()


class HelperTest(unittest.TestCase):
    TOKEN = 'token-de-teste'
    PANEL_PORT = 8765

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.job = 'a' * 32
        (self.root / 'saida' / self.job).mkdir(parents=True)
        (self.root / 'saida' / ('b' * 32)).write_text('arquivo, nao pasta')
        self.opened = []
        self.server, self.port = wrapper.start_helper(
            self.TOKEN, self.PANEL_PORT, self.root, opener=self.opened.append, base_port=0)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def request(self, method='POST', path='/abrir-pasta', body=None, headers=None):
        import http.client
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        if headers is None:
            headers = {'X-Whisper-Box-Token': self.TOKEN, 'Content-Type': 'application/json'}
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response.read()
        connection.close()
        return response

    def post(self, job_id=None, **kwargs):
        return self.request(body={'job_id': job_id or self.job}, **kwargs)

    def test_valid_request_opens_folder(self):
        response = self.post(headers={'X-Whisper-Box-Token': self.TOKEN,
                                      'Origin': 'http://127.0.0.1:%d' % self.PANEL_PORT})
        self.assertEqual(response.status, 204)
        self.assertEqual(response.getheader('Access-Control-Allow-Origin'),
                         'http://127.0.0.1:%d' % self.PANEL_PORT)
        self.assertEqual(self.opened, [self.root / 'saida' / self.job])

    def test_invalid_or_missing_token_is_403(self):
        for headers in ({'X-Whisper-Box-Token': 'errado'}, {}):
            self.assertEqual(self.post(headers=headers).status, 403)
        self.assertEqual(self.opened, [])

    def test_invalid_host_is_421(self):
        headers = {'X-Whisper-Box-Token': self.TOKEN, 'Host': 'evil.example:%d' % self.port}
        self.assertEqual(self.post(headers=headers).status, 421)
        self.assertEqual(self.opened, [])

    def test_foreign_origin_is_rejected_without_cors_header(self):
        response = self.post(headers={'X-Whisper-Box-Token': self.TOKEN, 'Origin': 'http://evil.example'})
        self.assertEqual(response.status, 403)
        self.assertIsNone(response.getheader('Access-Control-Allow-Origin'))
        self.assertEqual(self.opened, [])

    def test_invalid_job_ids_are_400_and_never_open(self):
        for job_id in ('../' + 'a' * 29, 'A' * 32, 'a' * 31, 'a' * 32 + '/..', 5, None):
            self.assertEqual(self.request(body={'job_id': job_id}).status, 400)
        self.assertEqual(self.request(body=b'nao e json').status, 400)
        self.assertEqual(self.request(body=b'').status, 400)
        self.assertEqual(self.opened, [])

    def test_missing_folder_or_plain_file_is_404(self):
        self.assertEqual(self.post('c' * 32).status, 404)
        self.assertEqual(self.post('b' * 32).status, 404)
        self.assertEqual(self.opened, [])

    def test_preflight_allows_panel_origin_only(self):
        for origin in ('http://127.0.0.1:%d' % self.PANEL_PORT, 'http://localhost:%d' % self.PANEL_PORT):
            response = self.request('OPTIONS', headers={'Origin': origin,
                                                        'Access-Control-Request-Method': 'POST'})
            self.assertEqual(response.status, 204)
            self.assertEqual(response.getheader('Access-Control-Allow-Origin'), origin)
            allowed = response.getheader('Access-Control-Allow-Headers').lower()
            self.assertIn('content-type', allowed)
            self.assertIn('x-whisper-box-token', allowed)
        response = self.request('OPTIONS', headers={'Origin': 'http://evil.example'})
        self.assertEqual(response.status, 403)
        self.assertIsNone(response.getheader('Access-Control-Allow-Origin'))

    def test_no_other_routes(self):
        self.assertEqual(self.request('GET', '/', headers={}).status, 404)
        self.assertEqual(self.request('GET', '/abrir-pasta', headers={}).status, 404)
        self.assertEqual(self.request('POST', '/outra', body={}).status, 404)

    def test_opener_failure_is_500(self):
        def failing(path):
            raise OSError('sem gerenciador')

        server, port = wrapper.start_helper(self.TOKEN, self.PANEL_PORT, self.root, opener=failing, base_port=0)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        import http.client
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        connection.request('POST', '/abrir-pasta', body=json.dumps({'job_id': self.job}).encode(),
                           headers={'X-Whisper-Box-Token': self.TOKEN})
        self.assertEqual(connection.getresponse().status, 500)

    def test_busy_port_falls_through_to_next(self):
        import socket
        blocker = socket.socket()
        blocker.bind(('127.0.0.1', 0))
        blocker.listen(1)
        self.addCleanup(blocker.close)
        busy = blocker.getsockname()[1]
        server, port = wrapper.start_helper(self.TOKEN, self.PANEL_PORT, self.root, base_port=busy)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.assertGreater(port, busy)


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_model(self, size=5, manifest=None):
        (self.root / 'modelos' / 'small').mkdir(parents=True)
        (self.root / 'modelos' / 'small' / 'model.bin').write_bytes(b'x' * 5)
        if manifest is None:
            manifest = json.dumps({'revision': 'rev', 'files': {'model.bin': {'size': size, 'sha256': 'h'}}})
        (self.root / 'modelos' / 'manifest.json').write_text(manifest)

    def diagnose(self, docker='/usr/bin/docker', responses=(), model=True, **model_options):
        if model:
            self.write_model(**model_options)
        responses = list(responses)
        out = io.StringIO()

        def fake_run(*arguments, **kwargs):
            item = responses.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        with patch.object(wrapper, 'ROOT', self.root), \
                patch.object(wrapper.shutil, 'which', return_value=docker), \
                patch.object(wrapper.subprocess, 'run', side_effect=fake_run):
            code = wrapper.main(['doctor'], out)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        return code, json.loads(lines[0])

    def ready_responses(self, label=b''):
        return [completed(0, b'2.29.0'), completed(0, b'linux'), completed(0, label)]

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
        code, body = self.diagnose(responses=self.ready_responses())
        self.assertEqual(code, 0)
        self.assertTrue(body['ready'])
        self.assertEqual(body['next_step']['code'], 'ask_for_recording')

    def test_invalid_manifest_or_wrong_model_size_asks_for_prepare_and_preserving_models(self):
        for options in ({'manifest': 'nao e json'}, {'manifest': '{}'},
                        {'manifest': json.dumps({'revision': 'r', 'files': {}})}, {'size': 4}):
            with self.subTest(options=options):
                self.setUp()
                code, body = self.diagnose(responses=self.ready_responses(), **options)
                self.assertEqual(code, 1)
                self.assertEqual(body['next_step']['code'], 'prepare')
                self.assertIn('modelos/', body['next_step']['action'])
                self.assertFalse(body['checks']['model']['ok'])
                self.tearDown()

    def test_missing_model_file_asks_for_prepare(self):
        self.write_model()
        (self.root / 'modelos' / 'small' / 'model.bin').unlink()
        self.assertIsNotNone(wrapper.model_problem(self.root))

    def test_stale_image_label_asks_for_rebuild_without_approval(self):
        code, body = self.diagnose(responses=self.ready_responses(b'0' * 64))
        self.assertEqual(code, 1)
        self.assertFalse(body['ready'])
        step = body['next_step']
        self.assertEqual(step['code'], 'rebuild')
        self.assertFalse(step['requires_user_approval'])
        self.assertIn('docker compose build', step['action'])

    def test_matching_label_or_unlabelled_image_is_ready(self):
        (self.root / 'whisper-box.py').write_text('x')
        digest = wrapper.source_digest(self.root)
        for label in (digest.encode(), b'', b'<no value>'):
            with self.subTest(label=label):
                self.setUp()
                (self.root / 'whisper-box.py').write_text('x')
                code, body = self.diagnose(responses=self.ready_responses(label))
                self.assertEqual((code, body['next_step']['code']), (0, 'ask_for_recording'))
                self.tearDown()

    def test_source_digest_changes_with_sources(self):
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'a.py').write_text('1')
        first = wrapper.source_digest(self.root)
        (self.root / 'src' / 'a.py').write_text('2')
        self.assertNotEqual(first, wrapper.source_digest(self.root))

    def test_permission_error_is_a_clean_failure_with_json(self):
        with patch.object(wrapper.subprocess, 'run', side_effect=PermissionError('negado')):
            self.assertEqual(wrapper.probe(['docker', 'info']), (None, 'sem permissao'))
        code, body = self.diagnose(responses=[completed(0, b'2.29.0'), PermissionError('negado')])
        self.assertEqual(code, 1)
        self.assertEqual(body['next_step']['code'], 'start_docker')
        self.assertIn('permissao', body['checks']['docker_engine']['detail'])
        self.assertIn('grupo docker', wrapper.DOCKER_START['linux'])


JOB = 'a' * 32
FILES = ('text', 'srt', 'segments', 'metadata')


class TranscribeTest(CallMixin, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'reunião.wav'
        self.source.write_bytes(b'media')
        sleeper = patch.object(wrapper.time, 'sleep')
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def tearDown(self):
        self.temp.cleanup()

    def done(self, create=True):
        files = {}
        for key in wrapper.ARTIFACTS:
            files[key] = str(self.root / (key + '.out'))
            if create:
                Path(files[key]).write_text('fixture')
        return completed(0, json.dumps({'job_id': JOB, 'status': 'succeeded', 'files': files,
                                        'output_relative': 'saida/' + JOB}).encode())

    def commands(self, calls):
        names = []
        for arguments, _ in calls:
            if arguments[:2] == ['docker', 'rm']:
                names.append('rm')
                continue
            for name in ('up', 'submit', 'wait', 'result'):
                if name in arguments:
                    names.append(name)
                    break
        return names

    submitted = completed(0, ('{"job_id": "%s", "status": "queued", "reused": false}' % JOB).encode())
    running = completed(2, ('{"job_id": "%s", "status": "running", "timed_out": true}' % JOB).encode())
    empty = completed(0, b'')

    def test_full_flow_renews_wait_without_resubmitting_or_calling_result(self):
        code, lines, calls = self.call(['transcribe', '--input', str(self.source)],
                                       [completed(0), self.submitted, self.running, self.done()])
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        body = json.loads(lines[0])
        self.assertEqual(body['status'], 'succeeded')
        self.assertEqual(sorted(body['files']), sorted(FILES))
        self.assertEqual(self.commands(calls), ['up', 'submit', 'wait', 'wait'])
        self.assertIn('pt', calls[1][0])

    def test_resume_by_job_does_not_submit(self):
        code, _, calls = self.call(['transcribe', '--job', JOB], [completed(0), self.done()])
        self.assertEqual(code, 0)
        self.assertEqual(self.commands(calls), ['up', 'wait'])

    def test_budget_exhausted_returns_code_2_with_job_id(self):
        with patch.object(wrapper.time, 'monotonic', side_effect=[0, 0, 5]):
            code, lines, _ = self.call(['transcribe', '--job', JOB, '--timeout-seconds', '1'],
                                       [completed(0), self.running])
        body = json.loads(lines[0])
        self.assertEqual(code, 2)
        self.assertEqual((body['job_id'], body['status']), (JOB, 'running'))
        self.assertTrue(body['wait_budget_exhausted'])

    def test_failures_stop_the_flow_and_carry_job_id(self):
        code, lines, calls = self.call(['transcribe', '--job', JOB], [completed(1)])
        self.assertEqual((code, len(calls)), (1, 1))
        self.assertEqual(json.loads(lines[0])['error']['code'], 'docker_error')
        failed = completed(1, ('{"job_id": "%s", "status": "failed", "error": {"code": "invalid_media"}}'
                               % JOB).encode())
        code, lines, calls = self.call(['transcribe', '--input', str(self.source)],
                                       [completed(0), self.submitted, failed])
        self.assertEqual(code, 1)
        self.assertEqual(self.commands(calls), ['up', 'submit', 'wait'])
        code, lines, _ = self.call(['transcribe', '--job', JOB], [completed(0), self.done(create=False)])
        self.assertEqual(code, 1)
        body = json.loads(lines[0])
        self.assertEqual((body['job_id'], body['error']['code']), (JOB, 'output_unreachable'))

    def test_transient_docker_failure_is_retried_silently(self):
        code, lines, calls = self.call(['transcribe', '--input', str(self.source)],
                                       [completed(0), self.submitted, self.empty, self.done()])
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])['status'], 'succeeded')
        self.assertEqual(self.commands(calls), ['up', 'submit', 'wait', 'wait'])
        self.sleep.assert_called_once_with(2)

    def test_persistent_docker_failure_reports_job_id_after_two_retries(self):
        code, lines, calls = self.call(['transcribe', '--input', str(self.source)],
                                       [completed(0), self.submitted, self.empty, self.empty, self.empty])
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1)
        body = json.loads(lines[0])
        self.assertEqual((body['job_id'], body['error']['code']), (JOB, 'docker_error'))
        self.assertEqual(self.commands(calls), ['up', 'submit', 'wait', 'wait', 'wait'])
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [2, 5])

    def test_non_json_response_becomes_structured_error_with_job_id(self):
        garbage = completed(0, b'Traceback (most recent call last): boom')
        code, lines, _ = self.call(['transcribe', '--job', JOB], [completed(0), garbage, garbage, garbage])
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1)
        body = json.loads(lines[0])
        self.assertEqual((body['job_id'], body['error']['code']), (JOB, 'docker_error'))
        code, lines, _ = self.call(['result', '--job', JOB], [completed(0, b'<html>')])
        self.assertEqual((code, json.loads(lines[0])['error']['code']), (1, 'docker_error'))

    def test_exception_from_subprocess_is_retried_then_reported_with_job_id(self):
        broken = OSError('docker sumiu')

        def fake_run(arguments, **kwargs):
            if 'up' in arguments:
                return completed(0)
            raise broken

        out = io.StringIO()
        with patch.object(wrapper.subprocess, 'run', side_effect=fake_run):
            code = wrapper.main(['transcribe', '--job', JOB], out)
        body = json.loads(out.getvalue())
        self.assertEqual((code, body['job_id'], body['error']['code']), (1, JOB, 'docker_error'))
        self.assertEqual(self.sleep.call_count, 2)

    def test_definitive_engine_errors_are_not_retried(self):
        missing = completed(3, b'{"error": {"code": "job_not_found", "message": "Trabalho inexistente."}}')
        code, lines, calls = self.call(['transcribe', '--job', JOB], [completed(0), missing])
        self.assertEqual(code, 3)
        body = json.loads(lines[0])
        self.assertEqual((body['job_id'], body['error']['code']), (JOB, 'job_not_found'))
        self.assertEqual(self.commands(calls), ['up', 'wait'])
        self.sleep.assert_not_called()

    def test_invalid_arguments_do_not_touch_docker_or_stderr(self):
        for argv in (['transcribe'], ['transcribe', '--input', 'a', '--job', 'b'],
                     ['transcribe', '--job', JOB, '--language', 'en'],
                     ['transcribe', '--job', JOB, '--timeout-seconds', '0'],
                     ['transcribe', '--input', ''], ['transcribe', '--job', ''],
                     ['transcribe', '--job', 'abc'], ['transcribe', '--job', JOB.upper()]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()) as err:
                code, lines, calls = self.call(argv)
                self.assertEqual(code, 3)
                self.assertEqual(len(lines), 1)
                self.assertEqual(json.loads(lines[0])['error']['code'], 'invalid_arguments')
                self.assertEqual(calls, [])
                self.assertEqual(err.getvalue(), '')
        code, lines, calls = self.call(['transcribe', '--input', str(self.root / 'nao-existe.mp4')])
        self.assertEqual((code, calls), (3, []))
        self.assertEqual(json.loads(lines[0])['error']['code'], 'input_not_found')

    def test_unsupported_input_paths_are_rejected_before_docker(self):
        code, lines, calls = self.call(['transcribe', '--input', '/tmp/reuniao:1.mp4'])
        self.assertEqual((code, calls), (3, []))
        self.assertEqual(json.loads(lines[0])['error']['code'], 'unsupported_path')

    def test_unexpected_exception_becomes_operational_error_without_traceback(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(wrapper, 'transcribe', side_effect=TypeError('segredo /caminho')), \
                patch.object(wrapper.sys, 'argv', ['whisper-box.py', 'transcribe', '--job', JOB]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wrapper.entrypoint()
        lines = out.getvalue().splitlines()
        self.assertEqual((code, len(lines)), (1, 1))
        self.assertEqual(json.loads(lines[0])['error']['code'], 'operational_error')
        self.assertNotIn('Traceback', out.getvalue() + err.getvalue())
        self.assertIn('TypeError', err.getvalue())
        self.assertNotIn('segredo', out.getvalue() + err.getvalue())

    def interrupting(self, failure):
        calls = []

        def fake_run(arguments, **kwargs):
            calls.append(arguments)
            if 'wait' in arguments:
                raise failure
            if 'submit' in arguments:
                return self.submitted
            return completed(0)

        out = io.StringIO()
        with patch.object(wrapper.subprocess, 'run', side_effect=fake_run):
            code = wrapper.main(['transcribe', '--input', str(self.source)], out)
        return code, json.loads(out.getvalue()), calls

    def assert_container_removed(self, calls):
        wait_call = next(c for c in calls if 'wait' in c)
        name = wait_call[wait_call.index('--name') + 1]
        self.assertTrue(name.startswith('whisper-box-cli-'))
        self.assertEqual(calls[-1], ['docker', 'rm', '-f', name])

    def test_ctrl_c_during_wait_reports_interrupted_and_removes_container(self):
        code, body, calls = self.interrupting(KeyboardInterrupt())
        self.assertEqual((code, body['job_id'], body['error']['code']), (1, JOB, 'interrupted'))
        self.assert_container_removed(calls)

    def test_hung_subprocess_times_out_and_removes_container(self):
        code, body, calls = self.interrupting(subprocess.TimeoutExpired(['docker'], 90))
        self.assertEqual((code, body['job_id'], body['error']['code']), (1, JOB, 'docker_timeout'))
        self.assert_container_removed(calls)
        self.sleep.assert_not_called()

    def test_container_calls_carry_timeouts(self):
        _, _, calls = self.call(['transcribe', '--input', str(self.source)],
                                [completed(0), self.submitted, self.done()])
        timeouts = [kwargs.get('timeout') for _, kwargs in calls]
        self.assertEqual(timeouts, [wrapper.START_TIMEOUT, wrapper.SUBMIT_TIMEOUT, 30 + 60])


class PathTest(CallMixin, unittest.TestCase):
    def test_posix_path_with_colon_is_unsupported_and_windows_drive_is_fine(self):
        self.assertEqual(wrapper.path_problem('/home/u/reuniao:1.mp4', 'linux')[0], 'unsupported_path')
        self.assertEqual(wrapper.path_problem('/Volumes/a:b/x.mp4', 'macos')[0], 'unsupported_path')
        self.assertIsNone(wrapper.path_problem('/home/u/reuniao.mp4', 'linux'))
        self.assertIsNone(wrapper.path_problem(r'C:\Reunioes\call.mp4', 'windows'))
        self.assertEqual(wrapper.path_problem(r'C:\Reunioes\call:stream.mp4', 'windows')[0], 'unsupported_path')

    def test_unc_paths_are_rejected_on_windows_only(self):
        for text in (r'\\servidor\compartilhamento\x.mp4', '//servidor/compartilhamento/x.mp4'):
            self.assertEqual(wrapper.path_problem(text, 'windows')[0], 'unsupported_path')
        self.assertIsNone(wrapper.path_problem(r'\\?\C:\Reunioes\x.mp4', 'windows'))
        self.assertIsNone(wrapper.path_problem('//tmp/x.mp4', 'linux'))
        with patch.object(wrapper, 'platform_name', return_value='windows'):
            code, lines, calls = self.call(['submit', '--input', r'\\servidor\compartilhamento\x.mp4'])
        self.assertEqual((code, calls), (3, []))
        self.assertEqual(json.loads(lines[0])['error']['code'], 'unsupported_path')

    def test_submit_command_rejects_colon_path_before_docker(self):
        code, lines, calls = self.call(['submit', '--input', '/tmp/a:b.mp4'])
        self.assertEqual((code, calls), (3, []))
        self.assertEqual(json.loads(lines[0])['error']['code'], 'unsupported_path')

    def test_supported_path_uses_short_mount_with_container_name(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'a.wav'
            source.write_bytes(b'x')
            arguments, failure = wrapper.submit_arguments(['--input', str(source)], 'whisper-box-cli-1234abcd')
        self.assertIsNone(failure)
        self.assertEqual(arguments[arguments.index('--name') + 1], 'whisper-box-cli-1234abcd')
        self.assertTrue(arguments[arguments.index('--volume') + 1].endswith(':/source/recording.wav:ro'))


class LifecycleArgumentsTest(unittest.TestCase):
    def test_start_and_painel_arguments(self):
        self.assertEqual(wrapper.start_arguments(),
                         ['up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '90', 'worker'])
        self.assertEqual(wrapper.painel_arguments(),
                         ['up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '30', 'painel'])

    def test_painel_url_honors_environment(self):
        self.assertEqual(wrapper.painel_url({}), 'http://127.0.0.1:8765/')
        self.assertEqual(wrapper.painel_url({'WHISPER_BOX_PAINEL_PORT': '9100'}), 'http://127.0.0.1:9100/')

    def test_job_arguments_without_name_keep_previous_shape(self):
        self.assertEqual(wrapper.job_arguments('status', ['--job', 'x']),
                         ['--profile', 'tools', 'run', '--rm', '--no-deps', '-T', 'cli', 'status', '--job', 'x'])


class ListCommandTest(CallMixin, unittest.TestCase):
    def test_list_passes_filters_and_host_utc_offset(self):
        with patch.object(wrapper, 'local_offset_minutes', return_value=-180):
            code, lines, calls = self.call(['list', '--limit', '5', '--since', '2026-11-19'],
                                           [completed(0, b'{"jobs": []}')])
        self.assertEqual((code, lines), (0, ['{"jobs": []}']))
        arguments = calls[0][0]
        self.assertEqual(arguments[arguments.index('list'):],
                         ['list', '--limit', '5', '--since', '2026-11-19', '--utc-offset-minutes', '-180'])

    def test_list_errors_keep_exit_code_and_single_json(self):
        body = b'{"error": {"code": "invalid_arguments", "message": "limite"}}'
        code, lines, _ = self.call(['list', '--limit', '0'], [completed(3, body)])
        self.assertEqual((code, len(lines)), (3, 1))

    def test_local_offset_comes_from_the_host_clock(self):
        from types import SimpleNamespace
        with patch.object(wrapper.time, 'localtime', return_value=SimpleNamespace(tm_gmtoff=-10800)):
            self.assertEqual(wrapper.local_offset_minutes(), -180)
        with patch.object(wrapper.time, 'localtime', return_value=SimpleNamespace(tm_gmtoff=19800)):
            self.assertEqual(wrapper.local_offset_minutes(), 330)
        with patch.object(wrapper.time, 'localtime', return_value=SimpleNamespace()):
            self.assertEqual(wrapper.local_offset_minutes(), 0)


if __name__ == '__main__':
    unittest.main()
