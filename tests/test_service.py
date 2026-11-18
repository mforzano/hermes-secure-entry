import json
import tempfile
import unittest
from pathlib import Path
from gateway.session_context import set_session_vars, clear_session_vars
from hermes_constants import get_hermes_home
from agent.vault_store import VaultStore


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tokens = set_session_vars(platform='photon', chat_id='synthetic-chat', chat_type='dm',
                                      user_id='synthetic-user', session_key='synthetic-key', session_id='synthetic-session')

    def tearDown(self):
        clear_session_vars(self.tokens)

    def test_real_native_add_then_owner_scoped_status(self):
        from secure_entry.service import Service
        with tempfile.TemporaryDirectory() as folder:
            store = VaultStore(Path(folder))
            service = Service('https://example.ts.net:9443', str(get_hermes_home()), port=0, store_factory=lambda:store)
            try:
                result = json.loads(service.request({'operation':'add_login','origin':'https://example.invalid'}))
                self.assertEqual(result['status'], 'pending')
                r = service.broker.requests[result['url'].rsplit('/', 1)[1]]
                import urllib.request, urllib.parse, re
                local = 'http://127.0.0.1:' + str(service.server.port) + '/r/' + r.token
                with urllib.request.urlopen(local) as response:
                    html = response.read().decode()
                csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
                data = urllib.parse.urlencode({'csrf':csrf,'identifier':'synthetic-user','password':'SYNTHETIC-PASSWORD','action':'submit'}).encode()
                with urllib.request.urlopen(local, data=data) as response:
                    result_page = response.read().decode()
                self.assertIn('Saved in the native encrypted vault', result_page)
                self.assertNotIn('SYNTHETIC-PASSWORD', result_page)
                status = json.loads(service.status({'request_id':result['request_id']}))
                self.assertEqual(status['status'], 'saved')
                self.assertNotIn('SYNTHETIC-PASSWORD', json.dumps(status))
                tokens = set_session_vars(platform='photon', chat_id='other-chat', chat_type='dm',
                                          user_id='other-user', session_key='other-key', session_id='other-session')
                try:
                    self.assertEqual(json.loads(service.status({'request_id':result['request_id']}))['status'], 'unavailable')
                finally: clear_session_vars(tokens)
            finally: service.close()

    def test_unsupported_browser_flows_never_create_collector(self):
        from secure_entry.service import Service
        service = Service('https://example.ts.net:9443', str(get_hermes_home()), port=0)
        try:
            for operation in ['update_login', 'sign_in_once', 'save_and_sign_in']:
                result = json.loads(service.request({'operation':operation, 'origin':'https://example.invalid'}))
                self.assertEqual(result['status'], 'unsupported_native_contract')
                self.assertNotIn('url', result)
            self.assertIsNone(service.server)
        finally: service.close()

    def test_code_request_redirects_to_native_inspection_without_collecting(self):
        from secure_entry.service import Service
        service = Service('https://example.ts.net:9443', str(get_hermes_home()), port=0)
        try:
            result = json.loads(service.request({'operation':'verification_code', 'origin':'https://example.invalid'}))
            self.assertEqual(result['status'], 'native_tool_required')
            self.assertEqual(result['tool'], 'browser_vault')
            self.assertEqual(result['action'], 'enter_code')
            self.assertNotIn('url', result)
            self.assertIsNone(service.server)
        finally: service.close()

    def test_normal_turn_end_preserves_link_but_reset_cancels_old_session(self):
        from secure_entry.service import Service
        service = Service('https://example.ts.net:9443', str(get_hermes_home()), port=0)
        try:
            result = json.loads(service.request({'operation':'add_login','origin':'https://example.invalid'}))
            service.ended(session_id='synthetic-session', turn_id='synthetic-turn', completed=True, failed=False, interrupted=False)
            self.assertEqual(json.loads(service.status({'request_id':result['request_id']}))['status'], 'pending')
            service.reset(session_id='new-session', old_session_id='synthetic-session', new_session_id='new-session')
            self.assertEqual(json.loads(service.status({'request_id':result['request_id']}))['status'], 'cancelled')
        finally: service.close()

    def test_actual_idle_stop_does_not_revoke_delivered_link(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock, patch
        from gateway.slash_commands import GatewaySlashCommandsMixin
        from secure_entry.service import Service
        service = Service('https://example.ts.net:9443', str(get_hermes_home()), port=0)
        try:
            result = json.loads(service.request({'origin':'https://example.invalid'}))
            service.ended(session_id='synthetic-session', turn_id='turn', completed=True)
            runner = SimpleNamespace(
                async_session_store=SimpleNamespace(get_or_create_session=AsyncMock(return_value=SimpleNamespace(
                    session_key='synthetic-key', session_id='synthetic-session'))),
                _running_agents={}, _same_chat_runs=Mock(return_value=[]),
                _sibling_thread_run_keys=Mock(return_value=[]), _chat_scoped_run_keys=Mock(return_value=[]),
                _interrupt_and_clear_session=AsyncMock(), _hm_stop_owner_turn=AsyncMock(), adapters={})
            from gateway.platforms.event import MessageEvent
            event = MessageEvent(text='/stop', source=SimpleNamespace(platform='photon', chat_id='synthetic-chat'))
            # Isolate the host launcher import, not stop dispatch logic. Importing
            # gateway.run would relaunch the test runner into the live PM runtime.
            from types import ModuleType
            from native_transport import synthetic_gateway_run
            constants = ModuleType('gateway.run')
            constants._AGENT_PENDING_SENTINEL = object()
            constants._INTERRUPT_REASON_STOP = 'stop_command'
            with synthetic_gateway_run(constants), patch('tools.async_delegation.interrupt_for_session', return_value=0):
                asyncio.run(GatewaySlashCommandsMixin._handle_stop_command(runner, event))
            runner._interrupt_and_clear_session.assert_not_awaited()
            self.assertEqual(json.loads(service.status({'request_id':result['request_id']}))['status'], 'pending')
            for filename in ('README.md', 'SECURITY.md'):
                text = (Path(__file__).resolve().parents[1] / filename).read_text(encoding='utf-8')
                self.assertIn('Idle `/stop` does not reliably revoke', text)
            self.assertEqual(json.loads(service.cancel({'request_id':result['request_id']}))['status'], 'cancelled')
        finally: service.close()

    def test_metadata_index_is_bounded_with_broker_tombstones(self):
        from secure_entry.service import Service
        service = Service('https://example.ts.net:9443', str(get_hermes_home()), port=0)
        service.broker.capacity = 2
        try:
            for _ in range(4):
                result = json.loads(service.request({'operation':'add_login','origin':'https://example.invalid'}))
                service.cancel({'request_id':result['request_id']})
            self.assertLessEqual(len(service.ids), 2)
        finally: service.close()

    def test_inflight_admission_is_fenced_by_stop_reset_and_unload(self):
        import contextvars
        import threading
        from secure_entry.service import Service
        for invalidation in ('stop', 'reset', 'close'):
            with self.subTest(invalidation=invalidation), tempfile.TemporaryDirectory() as folder:
                entered, resume = threading.Event(), threading.Event()
                store = VaultStore(Path(folder))
                def factory():
                    entered.set()
                    if not resume.wait(5): raise RuntimeError('test timeout')
                    return store
                service = Service('https://example.ts.net:9443', str(get_hermes_home()), port=0, store_factory=factory)
                results = []
                context = contextvars.copy_context()
                worker = threading.Thread(target=lambda: context.run(lambda: results.append(json.loads(service.request({'origin':'https://example.invalid'})))))
                worker.start()
                try:
                    self.assertTrue(entered.wait(5))
                    if invalidation == 'stop': service.stopped(session_key='synthetic-key')
                    elif invalidation == 'reset': service.reset(old_session_id='synthetic-session')
                    else: service.close()
                    resume.set()
                    worker.join(5)
                    self.assertFalse(worker.is_alive())
                    self.assertNotEqual(results[0]['status'], 'pending')
                    self.assertNotIn('url', results[0])
                    self.assertFalse(service.broker.requests)
                    self.assertIsNone(service.server)
                    self.assertEqual(store.list_items(), [])
                    if invalidation == 'close':
                        self.assertNotEqual(json.loads(service.request({'origin':'https://example.invalid'}))['status'], 'pending')
                finally:
                    resume.set()
                    worker.join(5)
                    service.close()

    def test_cancel_owner_on_stop_before_a_user_submits(self):
        from secure_entry.service import Service
        service = Service('https://example.ts.net:9443', str(get_hermes_home()), port=0)
        try:
            result = json.loads(service.request({'operation':'add_login','origin':'https://example.invalid'}))
            service.stopped(session_key='synthetic-key')
            self.assertEqual(json.loads(service.status({'request_id':result['request_id']}))['status'], 'cancelled')
        finally: service.close()
