"""Targeted local regression: synthetic storage, no model calls or QQ startup."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from persona.server import Runtime, Handler
from persona.common import VERSION


class ConnectionAndRoles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Runtime(self.temp.name, Path(__file__).resolve().parents[1], preview=True, headless=True)
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http.app = self.app
        self.app.port = self.http.server_port
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.headers = {'Cookie': f'persona_session_{self.app.port}={self.app.token}',
                        'X-CSRF-Token': self.app.token, 'X-App-Client-Version': VERSION}

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.app.close()
        self.temp.cleanup()

    def request(self, path, body=None):
        headers = {**self.headers, 'Content-Type': 'application/json'}
        req = urllib.request.Request(f'http://127.0.0.1:{self.app.port}{path}', headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)

    def test_state_reads_do_not_wait_for_conversation_lock(self):
        with self.app.engine.lock:
            self.assertEqual(self.request('/api/state')['profile']['id'], self.app.engine.profile()['id'])
            self.assertIsInstance(self.request('/api/ui3/overview'), dict)

    def test_job_observation_does_not_wait_for_business_read_lock(self):
        self.app.jobs['synthetic'] = {'id': 'synthetic', 'status': 'running', 'phase': 'synthetic'}
        try:
            with self.app.job_lock:
                self.assertEqual(self.request('/api/jobs/synthetic')['status'], 'running')
        finally:
            self.app.jobs.clear()

    def test_recycle_restore_preserves_original_role_and_restart(self):
        first = self.app.subjects.catalog['active']
        first_name = self.app.engine.profile()['name']
        with self.app.store.lock, self.app.store.db:
            self.app.store.setmeta('synthetic_preserved', {'memory': 'kept'})
        self.request('/api/persona/new', {'name': 'Synthetic second', 'seed': 'synthetic'})
        second = self.app.subjects.catalog['active']
        body = {'id': first, 'expected_active': second, 'confirm_name': first_name}
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/persona/delete', {**body, 'confirm_name': 'wrong'})
        self.assertTrue(self.request('/api/persona/delete', body)['archived'])
        self.assertEqual(self.app.contexts[first][0].meta('synthetic_preserved'), {'memory': 'kept'})
        state = self.request('/api/state')['personas']
        self.assertNotIn(first, [r['id'] for r in state['items']])
        self.assertIn(first, [r['id'] for r in state['trash']])
        with self.assertRaises(urllib.error.HTTPError): self.request('/api/persona/activate', {'id': first})
        with self.assertRaises(urllib.error.HTTPError): self.request('/api/persona/delete', {'id': second, 'expected_active': second, 'confirm_name': 'Synthetic second'})
        self.app.close()
        self.app = Runtime(self.temp.name, Path(__file__).resolve().parents[1], preview=True, headless=True)
        self.http.app = self.app
        self.app.port = self.http.server_port
        self.headers.update(Cookie=f'persona_session_{self.app.port}={self.app.token}', **{'X-CSRF-Token': self.app.token})
        self.assertNotIn(first, self.app.contexts)
        self.request('/api/persona/restore', {'id': first, 'expected_active': second})
        self.request('/api/persona/activate', {'id': first})
        self.assertEqual(self.app.store.meta('synthetic_preserved'), {'memory': 'kept'})

    def test_existing_package_round_trip_without_overwrite(self):
        first = self.app.subjects.catalog['active']
        pack = self.request('/api/persona/export?scope=continuity&persona_id=' + first)
        self.assertEqual(pack['profile']['id'], first)
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/persona/import', pack)
        with tempfile.TemporaryDirectory() as folder:
            other = Runtime(folder, Path(__file__).resolve().parents[1], preview=True, headless=True)
            try:
                other.create_persona({'package': pack})
                self.assertEqual(other.subjects.catalog['active'], first)
            finally: other.close()
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/persona/export?persona_id=wrong')


if __name__ == '__main__': unittest.main()
