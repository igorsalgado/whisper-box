import dataclasses
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from whisper_box import painel
from whisper_box.config import BoxError, Settings
from whisper_box.jobs import ARTIFACTS
from whisper_box.model import REQUIRED, sha256_file
from whisper_box.painel import PainelServer
from whisper_box.store import Store

PORT = 8765
HOST = f'127.0.0.1:{PORT}'
SAFE = {'Host': HOST, 'X-Whisper-Box': '1'}


class PainelTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(root / 'state', root / 'input', root / 'output', root / 'models')
        self.settings.initialize()
        (self.settings.models / 'small').mkdir(parents=True)
        files = {}
        for name in REQUIRED:
            path = self.settings.models / 'small' / name
            path.write_bytes(b'fixture')
            files[name] = {'size': path.stat().st_size, 'sha256': sha256_file(path)}
        (self.settings.models / 'manifest.json').write_text(json.dumps({
            'repo': 'Systran/faster-whisper-small', 'revision': 'fixture-revision', 'files': files}))
        self.heartbeat(True)
        self.static = root / 'static'
        self.static.mkdir()
        (self.static / 'index.html').write_text('<h1>painel</h1>', encoding='utf-8')
        (self.static / 'app.js').write_text('1', encoding='utf-8')
        (root / 'segredo.txt').write_text('fora', encoding='utf-8')
        self.start_server()

    def start_server(self, submit=None):
        self.server = PainelServer(('127.0.0.1', 0), self.settings, self.static, PORT, submit)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05})
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def heartbeat(self, alive):
        path = self.settings.state / 'heartbeat.json'
        if alive:
            path.write_text(json.dumps({'timestamp': time.time()}))
        else:
            path.unlink(missing_ok=True)

    def call(self, method, path, body=None, headers=None, raw=False):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = dict(SAFE if headers is None else headers)
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        if raw:
            return response, data
        return response.status, (json.loads(data) if data else None)

    def create(self):
        status, body = self.call('POST', '/api/gravacoes', {'mime': 'audio/webm;codecs=opus'})
        self.assertEqual(status, 201)
        return body['id']

    def put(self, recording_id, seq, data=b'abc', headers=None):
        return self.call('PUT', f'/api/gravacoes/{recording_id}/pedacos/{seq}', data, headers)

    def staging(self):
        return self.settings.inputs / '.gravacoes'

    def publish(self, job_id):
        job = Store(self.settings.state).get(job_id)
        destination = self.settings.outputs / job_id
        destination.mkdir()
        for name in ARTIFACTS.values():
            (destination / name).write_text('conteúdo ' + name, encoding='utf-8')
        (destination / 'manifest.json').write_text(json.dumps({
            'fingerprint': job['fingerprint'],
            'sha256': {name: sha256_file(destination / name) for name in ARTIFACTS.values()}}))

    # -- segurança -------------------------------------------------------
    def test_invalid_host_is_rejected_with_421(self):
        for host in ('evil.example:8765', '127.0.0.1:9999', 'localhost'):
            status, body = self.call('GET', '/api/saude', headers={'Host': host})
            self.assertEqual(status, 421)
            self.assertEqual(body['error']['code'], 'host_invalido')
        self.assertEqual(self.call('GET', '/api/saude', headers={'Host': f'localhost:{PORT}'})[0], 200)

    def test_mutations_require_header_and_same_origin(self):
        status, _ = self.call('POST', '/api/gravacoes', {'mime': 'audio/webm'}, headers={'Host': HOST})
        self.assertEqual(status, 403)
        status, _ = self.call('POST', '/api/gravacoes', {'mime': 'audio/webm'},
                              headers={**SAFE, 'Origin': 'http://evil.example'})
        self.assertEqual(status, 403)
        status, _ = self.call('POST', '/api/gravacoes', {'mime': 'audio/webm'},
                              headers={**SAFE, 'Origin': f'http://localhost:{PORT}'})
        self.assertEqual(status, 201)
        self.assertEqual(len(list(self.staging().glob('*.part'))), 1)

    # -- gravação --------------------------------------------------------
    def test_health_reflects_worker_and_model(self):
        self.assertEqual(self.call('GET', '/api/saude')[1], {'painel': 'ok', 'worker': True, 'modelo': True})
        self.heartbeat(False)
        self.assertEqual(self.call('GET', '/api/saude')[1], {'painel': 'ok', 'worker': False, 'modelo': True})

    def test_chunks_in_sequence_idempotent_resend_and_order_check(self):
        recording_id = self.create()
        part = self.staging() / (recording_id + '.part')
        self.assertEqual(self.put(recording_id, 0, b'aaa')[0], 204)
        self.assertEqual(self.put(recording_id, 1, b'bbb')[0], 204)
        self.assertEqual(self.put(recording_id, 1, b'bbb')[0], 204)  # reenvio do último
        self.assertEqual(part.read_bytes(), b'aaabbb')
        status, body = self.put(recording_id, 5, b'zzz')
        self.assertEqual(status, 409)
        self.assertEqual(body['error']['code'], 'sequencia_invalida')
        self.assertEqual(body['esperado'], 2)
        self.assertEqual(self.put(recording_id, 2, b'ccc')[0], 204)
        self.assertEqual(part.read_bytes(), b'aaabbbccc')
        self.assertEqual(self.put('0' * 32, 0)[0], 404)

    def test_state_survives_server_restart(self):
        recording_id = self.create()
        self.put(recording_id, 0, b'aaa')
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.start_server()
        self.assertEqual(self.put(recording_id, 1, b'bbb')[0], 204)
        self.assertEqual((self.staging() / (recording_id + '.part')).read_bytes(), b'aaabbb')

    def test_size_limits_return_413(self):
        recording_id = self.create()
        with patch.object(painel, 'CHUNK_LIMIT', 4):
            self.assertEqual(self.put(recording_id, 0, b'12345')[0], 413)
        self.assertEqual(self.put(recording_id, 0, b'123')[0], 204)
        with patch.object(painel, 'RECORDING_LIMIT', 5):
            status, body = self.put(recording_id, 1, b'456')
        self.assertEqual((status, body['error']['code']), (413, 'gravacao_grande_demais'))
        self.assertEqual((self.staging() / (recording_id + '.part')).read_bytes(), b'123')

    def test_invalid_mime_and_empty_chunk(self):
        self.assertEqual(self.call('POST', '/api/gravacoes', {'mime': 'text/html'})[0], 415)
        recording_id = self.create()
        self.assertEqual(self.put(recording_id, 0, b'')[0], 400)

    def test_cancel_deletes_staging(self):
        recording_id = self.create()
        self.put(recording_id, 0)
        self.assertEqual(self.call('DELETE', f'/api/gravacoes/{recording_id}')[0], 204)
        self.assertEqual(list(self.staging().iterdir()), [])
        self.assertEqual(self.call('DELETE', f'/api/gravacoes/{recording_id}')[0], 404)

    # -- transcrição -----------------------------------------------------
    def test_transcribe_submits_readable_name_and_removes_staging(self):
        calls = []

        def fake_submit(settings, source, language):
            calls.append((source.name, language, source.read_bytes()))
            return {'job_id': 'a' * 32, 'status': 'queued', 'reused': False}

        self.server.gravacoes.submit = fake_submit
        recording_id = self.create()
        self.put(recording_id, 0, b'aaa')
        self.put(recording_id, 1, b'bbb')
        status, body = self.call('POST', f'/api/gravacoes/{recording_id}/transcrever', {'language': 'en'})
        self.assertEqual(status, 202)
        self.assertEqual(body, {'job_id': 'a' * 32, 'status': 'queued', 'reused': False})
        name, language, data = calls[0]
        self.assertRegex(name, r'^gravacao-\d{4}-\d{2}-\d{2}_\d{4}\.webm$')
        self.assertEqual((language, data), ('en', b'aaabbb'))
        self.assertEqual(list(self.staging().iterdir()), [])

    def test_real_submit_flow_with_simulated_heartbeat(self):
        recording_id = self.create()
        self.put(recording_id, 0, b'audio ')
        self.put(recording_id, 1, b'fixture')
        status, body = self.call('POST', f'/api/gravacoes/{recording_id}/transcrever', {})
        self.assertEqual((status, body['status'], body['reused']), (202, 'queued', False))
        job = Store(self.settings.state).get(body['job_id'])
        self.assertTrue(job['source_name'].startswith('gravacao-') and job['source_name'].endswith('.webm'))
        self.assertEqual(Path(job['input_path']).read_bytes(), b'audio fixture')
        self.assertEqual(json.loads(job['config'])['language'], 'auto')
        self.assertEqual(list(self.staging().iterdir()), [])
        # mesma gravação novamente: reaproveita o trabalho existente
        again = self.create()
        self.put(again, 0, b'audio fixture')
        status, body2 = self.call('POST', f'/api/gravacoes/{again}/transcrever')
        self.assertEqual((status, body2['job_id'], body2['reused']), (202, body['job_id'], True))
        self.assertEqual(list(self.staging().iterdir()), [])

    def test_submit_error_keeps_staging_and_allows_retry(self):
        recording_id = self.create()
        self.put(recording_id, 0, b'audio fixture')
        self.heartbeat(False)
        status, body = self.call('POST', f'/api/gravacoes/{recording_id}/transcrever', {})
        self.assertEqual((status, body['error']['code']), (503, 'worker_unavailable'))
        self.assertEqual(self.put(recording_id, 1, b'x')[0], 409)  # já fechada
        self.assertEqual([p.name for p in self.staging().iterdir() if p.is_dir()], [recording_id])
        self.heartbeat(True)
        status, body = self.call('POST', f'/api/gravacoes/{recording_id}/transcrever', {})
        self.assertEqual((status, body['status']), (202, 'queued'))
        self.assertEqual(list(self.staging().iterdir()), [])

    def test_transcribe_validates_language_and_empty_recording(self):
        recording_id = self.create()
        status, body = self.call('POST', f'/api/gravacoes/{recording_id}/transcrever', {})
        self.assertEqual((status, body['error']['code']), (400, 'gravacao_vazia'))
        self.put(recording_id, 0)
        status, body = self.call('POST', f'/api/gravacoes/{recording_id}/transcrever', {'language': 'fr'})
        self.assertEqual((status, body['error']['code']), (400, 'invalid_language'))

    # -- consulta e downloads -----------------------------------------------
    def enqueue_job(self, content=b'audio fixture'):
        source = Path(self.temp.name) / 'gravacao.wav'
        source.write_bytes(content)
        from whisper_box.jobs import submit
        return submit(self.settings, source, 'pt')['job_id']

    def test_list_most_recent_first_and_no_host_paths(self):
        first = self.enqueue_job(b'um')
        time.sleep(0.01)
        second = self.enqueue_job(b'dois')
        Store(self.settings.state).claim()
        Store(self.settings.state).finish(first, BoxError('no_audio', 'Sem áudio'))
        status, body = self.call('GET', '/api/transcricoes')
        self.assertEqual(status, 200)
        items = body['transcricoes']
        self.assertEqual([i['job_id'] for i in items], [second, first])
        self.assertEqual(items[1]['error']['code'], 'no_audio')
        self.assertEqual(set(items[0]) - {'error'}, {'job_id', 'status', 'progress_seconds', 'created_at',
                                                   'started_at', 'finished_at', 'source_name'})
        self.assertNotIn(self.temp.name, json.dumps(body))
        self.assertNotIn('pasta', items[0])  # só em trabalhos concluídos

    def test_folder_path_for_succeeded_jobs_follows_host_root(self):
        job_id = self.enqueue_job()
        self.publish(job_id)
        Store(self.settings.state).claim()
        Store(self.settings.state).finish(job_id)
        self.assertIsNone(self.call('GET', '/api/transcricoes')[1]['transcricoes'][0]['pasta'])
        windows = 'C:\\Users\\Igor\\whisper-box'
        for root, expected in ((windows, windows + '\\saida\\' + job_id),
                               ('/home/igor/whisper-box', '/home/igor/whisper-box/saida/' + job_id)):
            self.server.settings = dataclasses.replace(self.settings, host_root=root)
            item = self.call('GET', '/api/transcricoes')[1]['transcricoes'][0]
            self.assertEqual(item['pasta'], expected)

    def test_download_only_when_verified(self):
        job_id = self.enqueue_job()
        base = f'/api/transcricoes/{job_id}'
        self.assertNotIn('downloads', self.call('GET', base)[1])
        self.assertEqual(self.call('GET', base + '/arquivos/text')[0], 409)
        self.publish(job_id)
        Store(self.settings.state).claim()
        Store(self.settings.state).finish(job_id)
        status, body = self.call('GET', base)
        self.assertEqual(body['downloads'], {'text': base + '/arquivos/text', 'srt': base + '/arquivos/srt'})
        self.assertNotIn(self.temp.name, json.dumps(body))
        response, data = self.call('GET', base + '/arquivos/text', raw=True)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Content-Type'), 'text/plain; charset=utf-8')
        self.assertIn('attachment', response.getheader('Content-Disposition'))
        self.assertEqual(data.decode('utf-8'), 'conteúdo transcricao.txt')
        response, _ = self.call('GET', base + '/arquivos/srt', raw=True)
        self.assertEqual(response.getheader('Content-Type'), 'application/x-subrip')
        (self.settings.outputs / job_id / 'transcricao.txt').write_text('alterado')
        self.assertEqual(self.call('GET', base + '/arquivos/text')[0], 409)
        self.assertNotIn('downloads', self.call('GET', base)[1])
        self.assertEqual(self.call('GET', '/api/transcricoes/' + '0' * 32)[0], 404)

    # -- estáticos -------------------------------------------------------
    def test_static_files_and_mime_types(self):
        response, data = self.call('GET', '/', raw=True)
        self.assertEqual((response.status, data), (200, b'<h1>painel</h1>'))
        self.assertTrue(response.getheader('Content-Type').startswith('text/html'))
        response, _ = self.call('GET', '/app.js', raw=True)
        self.assertTrue(response.getheader('Content-Type').startswith('text/javascript'))
        self.assertEqual(self.call('GET', '/nao-existe.css')[0], 404)

    def test_path_traversal_is_blocked(self):
        for path in ('/../segredo.txt', '/%2e%2e/segredo.txt', '/..%2fsegredo.txt',
                     '/static/../../segredo.txt', '/%2e%2e%2fsegredo.txt', '/..\\segredo.txt',
                     '/.gravacoes', '/%00'):
            response, data = self.call('GET', path, raw=True)
            self.assertIn(response.status, (400, 404), path)
            self.assertNotIn(b'fora', data, path)

    def test_unknown_routes_and_methods(self):
        self.assertEqual(self.call('GET', '/api/nada')[0], 404)
        self.assertEqual(self.call('GET', '/api/gravacoes')[0], 405)
        self.assertEqual(self.call('POST', '/index.html')[0], 405)


if __name__ == '__main__':
    unittest.main()
