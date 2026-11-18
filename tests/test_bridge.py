"""Synthetic HTTP -> real registered native handler; never connects to a browser."""
import contextvars
import json
import re
import threading
import unittest
import urllib.parse
import urllib.request
from unittest.mock import patch
from gateway.session_context import set_session_vars, clear_session_vars
from hermes_constants import get_hermes_home, profile_name_for_home
from agent.vault_backends import unlock
from tools import browser_vault_tool  # native registry registration, as at runtime
from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager
from hermes_cli.middleware import run_tool_execution_middleware
from secure_entry.service import Service


class BridgeTests(unittest.TestCase):
    platform = 'photon'
    user_id = 'synthetic-owner'
    chat_id = 'any;-;+15555550123'

    def setUp(self):
        self.tokens = set_session_vars(platform=self.platform, chat_type='dm', chat_id=self.chat_id,
            user_id=self.user_id, session_key='synthetic-key', session_id='synthetic-session',
            profile=profile_name_for_home(get_hermes_home()) or '', cron_session='')
        self.service = Service('https://example.invalid', str(get_hermes_home()), port=0)
        self.ctx = PluginContext(PluginManifest(name='synthetic-bridge'), get_plugin_manager())
        self.sent = []
        self.delivered = threading.Event()
        def send(name, args):
            self.assertEqual(name, 'send_message')
            self.assertEqual(args['target'], self.platform + ':' + self.chat_id)
            self.sent.append(args)
            self.delivered.set()
            return json.dumps({'success': True})
        self.service.configure_bridge(send, isolation='in_process')
        self.lease = self.ctx.register_middleware('tool_execution', self.service.middleware)

    def tearDown(self):
        self.lease.dispose()
        self.service.close()
        clear_session_vars(self.tokens)

    def call(self, fn, args=None, **context):
        return run_tool_execution_middleware('browser_vault', {'action': 'enter_code', **(args or {})},
            lambda a: fn(a), session_id=context.pop('session_id', 'synthetic-session'), **context)

    def worker(self, fn):
        results = []
        errors = []
        ctx = contextvars.copy_context()
        def run():
            try: results.append(ctx.run(fn))
            except BaseException as exc: errors.append(exc)
            finally:
                # Native sync-to-async delivery caches one loop per worker.
                # These synthetic workers are short-lived; release their loop.
                import sys
                native_tools = sys.modules.get('model_tools')
                local = getattr(native_tools, '_worker_thread_local', None)
                loop = getattr(local, 'loop', None)
                if loop is not None and not loop.is_running() and not loop.is_closed():
                    loop.close()
        t = threading.Thread(target=run)
        t.start()
        self.addCleanup(lambda: t.join(5))
        return t, results, errors

    def post(self, value, field='code', action='submit'):
        self.assertTrue(self.delivered.wait(8))
        url = self.sent[-1]['message'].split()[-1]
        token = url.rsplit('/', 1)[1]
        local = f'http://127.0.0.1:{self.service.server.port}/r/{token}'
        with urllib.request.urlopen(local) as r: page = r.read().decode()
        csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        data = urllib.parse.urlencode({'csrf': csrf, 'action': action, field: value}).encode()
        with urllib.request.urlopen(local, data) as r: reply = r.read().decode()
        self.assertNotIn(value, reply)
        return token, page

    def test_http_code_reaches_registered_native_handler_redacted_without_submit(self):
        from tools import browser_vault_tool as native
        from agent.redact import redact_registered_vault_values
        synthetic = '753159'
        controls = [{'index': 0, 'type': 'text', 'name': 'otp', 'label': 'Authentication code', 'autocomplete': 'one-time-code'}]
        def inspect(task, expr):
            return {'success': True, 'result': json.dumps(controls) if 'querySelectorAll' in expr else 'https://synthetic.example/two-factor'}
        writes = []
        def write(task, expr):
            self.assertIn('https://synthetic.example', expr)
            self.assertIn('data-hermes-vault-slot', expr)
            self.assertIn('origin_changed', expr)
            self.assertIn(synthetic, expr)
            self.assertNotIn(synthetic, redact_registered_vault_values(synthetic))
            self.assertNotIn('.submit(', expr)
            writes.append(task)
            return {'success': True, 'result': json.dumps({'filled': 1})}
        self.assertFalse(self.service.broker.requests)  # no collector before native inspection
        from types import SimpleNamespace
        from tools.browser_supervisor import SUPERVISOR_REGISTRY
        def evaluate(expr):
            result = write('synthetic-session', expr) if synthetic in expr else inspect('synthetic-session', expr)
            return {'ok': result['success'], 'result': result['result']}
        supervisor = SimpleNamespace(focus_page=lambda *a, **k: {'ok': True, 'url': 'https://synthetic.example/two-factor'},
                                     evaluate_runtime=evaluate)
        with patch.object(SUPERVISOR_REGISTRY, 'get', return_value=supervisor):
            t, results, errors = self.worker(lambda: self.call(lambda a: self.ctx.dispatch_tool('browser_vault', a, task_id='synthetic-session')))
            token, page = self.post(synthetic)
            t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(errors, [])
        self.assertIn('synthetic.example', page)
        self.assertEqual(writes, ['synthetic-session'])
        self.assertEqual(json.loads(results[0])['status'], 'filled')
        self.assertFalse(json.loads(results[0])['authenticated'])
        self.assertEqual(self.service.broker.status(token)['status'], 'filled')
        self.assertNotIn(synthetic, json.dumps(self.sent) + str(results))
        self.assertIsNone(unlock.get_code_prompt_callback())
        self.assertIsNone(unlock.get_unlock_prompt_callback())

    def test_captured_callback_cannot_collect_after_execution_scope_ends(self):
        captured = []
        def capture(args):
            captured.append(unlock.get_code_prompt_callback())
            return json.dumps({'success': False})
        self.call(capture)
        self.service.bridge.timeout = 0.01
        self.assertIsNone(captured[0]('synthetic.example', ''))
        self.assertFalse(self.sent)
        self.assertFalse(self.service.broker.requests)

    def test_mismatched_profile_is_refused_before_native_execution(self):
        set_session_vars(platform=self.platform, chat_type='dm', chat_id=self.chat_id, user_id=self.user_id,
            session_key='synthetic-key', session_id='synthetic-session', profile='other-profile', cron_session='')
        called = []
        result = self.call(lambda a: called.append(a))
        self.assertFalse(called)
        self.assertEqual(json.loads(result)['status'], 'unavailable')

    def test_failure_after_secret_handoff_has_unknown_not_refused_outcome(self):
        def consumer(args):
            value = unlock.get_code_prompt_callback()('synthetic.example', '')
            return json.dumps({'success': False, 'error': 'native diagnostics: ' + value})
        t, results, errors = self.worker(lambda: self.call(consumer))
        token, page = self.post('SYNTHETIC-UNKNOWN-CODE')
        t.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(json.loads(results[0])['status'], 'commit_unknown')
        self.assertEqual(self.service.broker.status(token)['status'], 'commit_unknown')
        self.assertNotIn('SYNTHETIC-UNKNOWN-CODE', str(results))

    def test_native_no_code_field_never_arms_collector_and_keeps_typed_refusal(self):
        from types import SimpleNamespace
        from tools.browser_supervisor import SUPERVISOR_REGISTRY
        def evaluate(expr):
            return {'ok': True, 'result': '[]' if 'querySelectorAll' in expr else 'https://synthetic.example/passkey'}
        supervisor = SimpleNamespace(focus_page=lambda *a, **k: {'ok': True}, evaluate_runtime=evaluate)
        with patch.object(SUPERVISOR_REGISTRY, 'get', return_value=supervisor):
            result = json.loads(self.call(lambda a: self.ctx.dispatch_tool('browser_vault', a, task_id='synthetic-session')))
        self.assertEqual(result['error_type'], 'no_code_field')
        self.assertFalse(self.sent)
        self.assertIsNone(self.service.server)

    def test_authentic_context_rejections_never_call_native_or_send(self):
        from agent.delegation_context import delegated_child_context
        from gateway.session_context import reset_session_vars
        called = []
        def denied(**kw):
            result = self.call(lambda a: called.append(a), **kw)
            self.assertEqual(json.loads(result)['status'], 'unavailable')
        denied(session_id='different-session')
        with delegated_child_context(): denied()
        for changes in ({'cron_session':'1'}, {'chat_type':'group'}, {'platform':'api_server'}, {'user_id':''}, {'session_id':''}):
            values = dict(platform=self.platform, chat_type='dm', chat_id=self.chat_id, user_id=self.user_id,
                session_key='synthetic-key', session_id='synthetic-session', profile=profile_name_for_home(get_hermes_home()) or '', cron_session='')
            values.update(changes)
            contextvars.copy_context().run(lambda: (set_session_vars(**values), denied()))
        import os
        env = {'HERMES_SESSION_'+key: value for key, value in dict(PLATFORM=self.platform, CHAT_TYPE='dm',
            CHAT_ID=self.chat_id, USER_ID=self.user_id, KEY='synthetic-key', ID='synthetic-session').items()}
        with patch.dict(os.environ, env):
            contextvars.copy_context().run(lambda: (reset_session_vars(), denied()))
        self.service.bridge.isolation = 'host'
        denied()
        self.assertFalse(called)
        self.assertFalse(self.sent)
        self.assertIsNone(self.service.server)

    def test_handle_is_rejected_before_selected_runtime_can_resolve_wrong_origin(self):
        called = []
        result = self.call(lambda a: called.append(a), args={'handle':'vault_synthetic'})
        self.assertEqual(json.loads(result)['status'], 'unsupported_handle_binding')
        self.assertFalse(called)
        self.assertFalse(self.sent)

    def test_original_callbacks_restored_on_success_and_native_error(self):
        old_code = lambda *a: None
        old_unlock = lambda *a: None
        unlock.set_code_prompt_callback(old_code)
        unlock.set_unlock_prompt_callback(old_unlock)
        try:
            for fails in (False, True):
                def consumer(args):
                    self.assertIsNot(unlock.get_code_prompt_callback(), old_code)
                    self.assertTrue(unlock.can_prompt_here())
                    if fails: raise RuntimeError('SYNTHETIC-SECRET-ERROR')
                    return json.dumps({'success': False})
                result = self.call(consumer)
                self.assertNotIn('SYNTHETIC-SECRET-ERROR', result)
                self.assertIs(unlock.get_code_prompt_callback(), old_code)
                self.assertIs(unlock.get_unlock_prompt_callback(), old_unlock)
        finally:
            unlock.set_code_prompt_callback(None)
            unlock.set_unlock_prompt_callback(None)

    def test_thread_context_handoff_and_cleanup(self):
        from concurrent.futures import ThreadPoolExecutor
        from tools.thread_context import propagate_context_to_thread
        with ThreadPoolExecutor(1) as pool:
            def consumer(args):
                return pool.submit(propagate_context_to_thread(lambda: json.dumps({
                    'success': unlock.can_prompt_here() and unlock.get_code_prompt_callback() is not None}))).result(5)
            self.assertTrue(json.loads(self.call(consumer))['success'])
            self.assertEqual(pool.submit(lambda: (unlock.get_code_prompt_callback(), unlock.get_unlock_prompt_callback())).result(5), (None, None))

    def test_cancel_expire_reset_and_unload_release_waiter_and_reject_late_post(self):
        # Each lifecycle case starts on a different synthetic turn.
        for action in ('form', 'expire', 'reset', 'unload'):
            with self.subTest(action=action):
                self.sent.clear()
                self.delivered.clear()
                self.service.broker.requests.clear()
                def consumer(args):
                    code = unlock.get_code_prompt_callback()('synthetic.example', '')
                    self.assertIsNone(code)
                    return json.dumps({'success': False})
                t, results, errors = self.worker(lambda: self.call(consumer, turn_id=action))
                self.assertTrue(self.delivered.wait(5))
                token = self.sent[-1]['message'].split()[-1].rsplit('/', 1)[1]
                request = self.service.broker.requests[token]
                if action == 'form':
                    self.post('UNUSED-SYNTHETIC', action='cancel')
                elif action == 'expire':
                    with self.service.broker.lock: request.deadline = 0
                elif action == 'reset': self.service.reset(old_session_id='synthetic-session')
                else: self.service.close()
                t.join(5)
                self.assertFalse(t.is_alive())
                self.assertEqual(errors, [])
                expected = 'expired' if action == 'expire' else 'cancelled'
                self.assertEqual(self.service.broker.status(token)['status'], expected)
                self.assertEqual(json.loads(results[0])['status'], expected)
                late = self.service.broker.submit(token, {'csrf':request.csrf, 'action':'submit', 'code':'LATE-SYNTHETIC'})
                self.assertEqual(late['status'], expected)

    def test_send_failure_revokes_form_without_accepting_input(self):
        self.service.bridge.dispatch = lambda *a: json.dumps({'success': False, 'error':'SYNTHETIC-ERROR'})
        def consumer(args):
            self.assertIsNone(unlock.get_code_prompt_callback()('synthetic.example', ''))
            return json.dumps({'success':False})
        result = self.call(consumer)
        self.assertEqual(json.loads(result)['status'], 'cancelled')
        self.assertTrue(all(r.status == 'cancelled' for r in self.service.broker.requests.values()))
        self.assertNotIn('SYNTHETIC-ERROR', result)

    def test_list_reports_native_unlock_action_with_genuine_callback_scope(self):
        from types import SimpleNamespace
        backend = SimpleNamespace(name='bitwarden', display_name='Bitwarden', needs_unlock=True, is_unlocked=lambda: False)
        with patch('agent.vault_backends.enabled_backends', return_value=[backend]):
            raw = run_tool_execution_middleware('browser_vault', {'action':'list'},
                lambda a: self.ctx.dispatch_tool('browser_vault', a), session_id='synthetic-session')
        self.assertEqual(json.loads(raw)['locked'][0]['unlock'], 'browser_vault action=unlock')
        self.assertFalse(self.sent)
        self.assertIsNone(unlock.get_unlock_prompt_callback())

    def test_unrelated_tool_exception_not_swallowed_by_prompt_middleware(self):
        def boom(args): raise ValueError('synthetic unrelated failure')
        with self.assertRaisesRegex(ValueError, 'synthetic unrelated'):
            run_tool_execution_middleware('synthetic_unrelated', {}, boom)

    def test_received_input_is_not_handed_off_after_deadline_during_delivery(self):
        entered, resume = threading.Event(), threading.Event()
        original_send = self.service.bridge.dispatch
        def delayed_send(name, args):
            result = original_send(name, args)
            entered.set()
            resume.wait(5)
            return result
        self.service.bridge.dispatch = delayed_send
        consumed = []
        def consumer(args):
            consumed.append(unlock.get_code_prompt_callback()('synthetic.example', ''))
            return json.dumps({'success': False})
        t, results, errors = self.worker(lambda: self.call(consumer))
        self.assertTrue(entered.wait(5))
        try:
            token, _ = self.post('SYNTHETIC-LATE-DELIVERY')
            with self.service.broker.lock:
                self.assertEqual(self.service.broker.requests[token].status, 'received')
                self.service.broker.requests[token].deadline = 0
        finally:
            resume.set()
        t.join(5)
        self.assertEqual(consumed, [None])
        self.assertEqual(self.service.broker.status(token)['status'], 'expired')

    def test_callback_handoff_rechecks_task_local_owner_not_process_env(self):
        import os
        env = {'HERMES_SESSION_'+key: value for key, value in dict(PLATFORM=self.platform, CHAT_TYPE='dm',
            CHAT_ID=self.chat_id, USER_ID=self.user_id, KEY='synthetic-key', ID='synthetic-session').items()}
        self.service.bridge.timeout = 0.01
        def consumer(args):
            prompt = unlock.get_code_prompt_callback()
            self.assertIsNone(contextvars.Context().run(prompt, 'synthetic.example', ''))
            return json.dumps({'success':False})
        with patch.dict(os.environ, env): self.call(consumer)
        self.assertFalse(self.sent)
        self.assertFalse(self.service.broker.requests)

    def test_native_secret_write_keeps_supervisor_only_and_takeover_guards(self):
        from types import SimpleNamespace
        from tools import browser_vault_tool as native
        from tools.bot_desktop import lease
        with patch.object(native, '_ensure_supervisor', return_value=None):
            result = native._eval_js_secret('synthetic-session', 'SYNTHETIC-NOT-A-COMMAND')
        self.assertEqual(result['error_type'], 'supervisor_required')
        writes = []
        supervisor = SimpleNamespace(evaluate_runtime=lambda e: writes.append(e))
        with patch.object(native, '_ensure_supervisor', return_value=supervisor), patch.object(native, '_bot_desktop_browser_session', return_value=True), patch.object(lease, 'assert_agent_may_act', side_effect=lease.HumanHasControl('synthetic takeover')):
            result = native._eval_js_secret('synthetic-session', 'SYNTHETIC-NOT-A-COMMAND')
        self.assertEqual(result['error_type'], 'human_has_control')
        self.assertEqual(writes, [])

    def test_cancel_after_callback_handoff_does_not_claim_prevented_native_action(self):
        handed, finish = threading.Event(), threading.Event()
        def consumer(args):
            self.assertEqual(unlock.get_code_prompt_callback()('synthetic.example', ''), 'SYNTHETIC-COMMIT-CODE')
            handed.set()
            finish.wait(5)
            return json.dumps({'success':True})
        t, results, errors = self.worker(lambda: self.call(consumer))
        try:
            token, _ = self.post('SYNTHETIC-COMMIT-CODE')
            self.assertTrue(handed.wait(5))
            rid = next(rid for rid, item in self.service.ids.items() if item[0] == token)
            result = json.loads(self.service.cancel({'request_id':rid}))
            self.assertEqual(result['status'], 'commit_unknown')
            self.service.stopped(session_id='synthetic-session')
            self.assertEqual(self.service.broker.status(token)['status'], 'commit_unknown')
        finally:
            finish.set()
        t.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(self.service.broker.status(token)['status'], 'filled')
        self.assertEqual(json.loads(results[0])['status'], 'filled')

    def test_native_send_delivers_synthetic_link_on_gateway_loop_while_worker_waits(self):
        import asyncio
        from types import SimpleNamespace
        from gateway.outbound import send as sender
        loop = asyncio.new_event_loop()
        ready = threading.Event()
        def run_loop():
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()
        thread = threading.Thread(target=run_loop)
        thread.start()
        self.assertTrue(ready.wait(5))
        async def send(**kwargs):
            if self.platform == 'photon':
                self.assertIs(asyncio.get_running_loop(), loop)
            self.assertEqual(kwargs['chat_id'], self.chat_id)
            self.sent.append({'message':kwargs['content']})
            self.delivered.set()
            return SimpleNamespace(success=True, message_id='synthetic-message-id')
        from gateway.config import GatewayConfig, PlatformConfig
        from gateway.platforms.base import BasePlatformAdapter, SendResult
        platform = sender._platform_enum(self.platform)[0]
        class SyntheticNativeAdapter(BasePlatformAdapter):
            async def connect(self, **kwargs): return True
            async def disconnect(self): pass
            async def get_chat_info(self, chat_id): return {'id': chat_id, 'type': 'dm'}
            async def send(self, **kwargs):
                result = await send(**kwargs)
                return SendResult(success=result.success, message_id=result.message_id)
        adapter = SyntheticNativeAdapter(PlatformConfig(enabled=True, token='SYNTHETIC-BOT-TOKEN'), platform)
        runner = SimpleNamespace(_gateway_loop=loop)
        config = GatewayConfig(platforms={platform: adapter.config})
        # The new relay egress guard imports the live gateway reference. Provide
        # an actual synthetic native adapter there; never import gateway.run's
        # launcher, which may relaunch this test process into the selected env.
        from types import ModuleType
        gateway_run = ModuleType('gateway.run')
        runner.adapters = {platform: adapter}
        gateway_run._gateway_runner_ref = lambda: runner
        dispatched = []
        def dispatch(name, args):
            from secure_entry.native import dispatch_message
            result = dispatch_message(self.ctx, name, args)
            dispatched.append(result)
            return result
        self.service.bridge.dispatch = dispatch
        def consumer(args):
            self.assertEqual(unlock.get_code_prompt_callback()('synthetic.example', ''), 'SYNTHETIC-TRANSPORT-CODE')
            return json.dumps({'success':True})
        from native_transport import synthetic_bot_network, synthetic_gateway_run
        try:
            with synthetic_gateway_run(gateway_run), synthetic_bot_network(self.platform, adapter.send), patch('gateway.config.load_gateway_config', return_value=config), patch.object(sender, '_mirror_sent_message', return_value=False):
                t, results, errors = self.worker(lambda: self.call(consumer))
                self.assertTrue(self.delivered.wait(8), str(dispatched) + str(results) + str(errors))
                self.assertTrue(t.is_alive())
                self.post('SYNTHETIC-TRANSPORT-CODE')
                t.join(5)
                self.assertEqual(errors, [])
                self.assertEqual(json.loads(results[0])['status'], 'filled')
        finally:
            self.service.close()
            loop.call_soon_threadsafe(loop.stop)
            thread.join(5)
            loop.close()

    def test_registered_delivery_error_is_not_retried_through_native_function(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from secure_entry.native import dispatch_message
        ctx = SimpleNamespace(dispatch_tool=Mock(return_value=json.dumps({'success':False})))
        with patch('tools.registry.registry.get_entry', return_value=object()), patch('gateway.outbound.send.send_message_tool') as direct:
            result = dispatch_message(ctx, 'send_message', {'action':'send', 'target':self.platform + ':' + self.chat_id, 'message':'synthetic only'})
            self.assertFalse(json.loads(result)['success'])
            ctx.dispatch_tool.assert_called_once()
            direct.assert_not_called()
        with self.assertRaises(ValueError): dispatch_message(ctx, 'other_tool', {})

    def test_callback_install_failure_is_fail_closed_not_middleware_skip(self):
        called = []
        with patch.object(unlock, 'set_code_prompt_callback', side_effect=RuntimeError('synthetic unsupported API')):
            result = self.call(lambda a: called.append(a))
        self.assertFalse(called)
        self.assertEqual(json.loads(result)['status'], 'unavailable')
        self.assertIsNone(unlock.get_code_prompt_callback())
        self.assertIsNone(unlock.get_unlock_prompt_callback())

    def test_lifecycle_during_owner_acquisition_fences_native_admission(self):
        entered, resume = threading.Event(), threading.Event()
        original = self.service.bridge.bound_owner
        called = []
        def paused(context):
            result = original(context)
            entered.set()
            resume.wait(5)
            return result
        with patch.object(self.service.bridge, 'bound_owner', side_effect=paused):
            t, results, errors = self.worker(lambda: self.call(lambda a: called.append(a)))
            self.assertTrue(entered.wait(5))
            self.service.stopped(session_id='synthetic-session')
            resume.set()
            t.join(5)
        self.assertEqual(errors, [])
        self.assertFalse(called)
        self.assertEqual(json.loads(results[0])['status'], 'unavailable')
        self.assertFalse(self.service.broker.requests)

    def test_owner_cancel_clears_received_input_before_native_handoff(self):
        resume = threading.Event()
        original = self.service.bridge.dispatch
        def delayed(name, args):
            result = original(name, args)
            resume.wait(5)
            return result
        self.service.bridge.dispatch = delayed
        consumed = []
        def consumer(args):
            consumed.append(unlock.get_code_prompt_callback()('synthetic.example', ''))
            return json.dumps({'success':False})
        t, results, errors = self.worker(lambda: self.call(consumer))
        try:
            token, _ = self.post('SYNTHETIC-CANCEL-BUFFER')
            rid = next(rid for rid, item in self.service.ids.items() if item[0] == token)
            result = json.loads(self.service.cancel({'request_id':rid}))
            self.assertEqual(result['status'], 'cancelled')
        finally:
            resume.set()
        t.join(5)
        self.assertEqual(consumed, [None])
        self.assertEqual(self.service.broker.status(token)['status'], 'cancelled')

    def test_native_interrupt_signal_releases_callback_without_waiting_for_lifecycle_hook(self):
        from tools.interrupt import set_interrupt
        consumed = []
        def consumer(args):
            consumed.append(unlock.get_code_prompt_callback()('synthetic.example', ''))
            return json.dumps({'success':False})
        t, results, errors = self.worker(lambda: self.call(consumer))
        try:
            self.assertTrue(self.delivered.wait(5))
            set_interrupt(True, thread_id=t.ident, reason='stop_command')
            t.join(2)
            self.assertFalse(t.is_alive())
            self.assertEqual(consumed, [None])
            self.assertEqual(json.loads(results[0])['status'], 'cancelled')
        finally:
            self.service.close()
            t.join(5)
            set_interrupt(False, thread_id=t.ident)

    def test_genuine_unlock_form_returns_masked_input_only_to_native_callback(self):
        from agent.redact import redact_registered_vault_values
        synthetic = 'SYNTHETIC-MASTER-INPUT'
        from types import SimpleNamespace
        unlocked = []
        def native_unlock(value):
            self.assertEqual(value, synthetic)
            self.assertNotIn(synthetic, redact_registered_vault_values(synthetic))
            unlocked.append(True)
        backend = SimpleNamespace(name='bitwarden', display_name='Bitwarden', needs_unlock=True,
                                  is_unlocked=lambda: False, unlock=native_unlock)
        with patch('agent.vault_backends.enabled_backends', return_value=[backend]):
            t, results, errors = self.worker(lambda: run_tool_execution_middleware('browser_vault', {'action':'unlock', 'backend':'bitwarden'},
                lambda a: self.ctx.dispatch_tool('browser_vault', a), session_id='synthetic-session'))
            token, page = self.post(synthetic, field='password')
            t.join(5)
        self.assertEqual(unlocked, [True])
        self.assertEqual(errors, [])
        self.assertIn('type="password"', page)
        self.assertIn('Bitwarden', page)
        self.assertNotIn('Website password', page)
        self.assertEqual(json.loads(results[0])['status'], 'unlocked')
        self.assertEqual(self.service.broker.status(token)['status'], 'unlocked')

    def check_relay_egress_decline_revokes_link_without_transport_send(self):
        from types import ModuleType, SimpleNamespace
        from gateway.config import GatewayConfig, Platform, PlatformConfig
        from secure_entry.native import dispatch_message
        platform = Platform(self.platform)
        gateway_run = ModuleType('gateway.run')
        relay = SimpleNamespace(fronts_platform=lambda p: p == platform)
        runner = SimpleNamespace(adapters={Platform.RELAY:relay})
        gateway_run._gateway_runner_ref = lambda: runner
        config = GatewayConfig(platforms={platform:PlatformConfig(enabled=True, token='SYNTHETIC-TOKEN')})
        self.service.bridge.dispatch = lambda name, args: dispatch_message(self.ctx, name, args)
        def consumer(args):
            self.assertIsNone(unlock.get_code_prompt_callback()('synthetic.example', ''))
            return json.dumps({'success':False})
        from gateway.outbound import send as sender
        from native_transport import synthetic_gateway_run
        with synthetic_gateway_run(gateway_run), patch('gateway.config.load_gateway_config', return_value=config), patch.object(sender, '_send_to_platform') as transport:
            result = json.loads(self.call(consumer))
            transport.assert_not_called()
        self.assertEqual(result['status'], 'cancelled')
        self.assertFalse(self.sent)
        self.assertTrue(self.service.broker.requests)
        self.assertTrue(all(r.status == 'cancelled' for r in self.service.broker.requests.values()))

    def test_model_destination_cannot_redirect_bound_prompt(self):
        def consumer(args):
            self.assertEqual(unlock.get_code_prompt_callback()('synthetic.example', ''), 'SYNTHETIC-BOUND-CODE')
            return json.dumps({'success': True})
        t, results, errors = self.worker(lambda: self.call(consumer, args={
            'target':'telegram:999999999', 'destination':'discord:999999999', 'username':'untrusted-name'}))
        token, _ = self.post('SYNTHETIC-BOUND-CODE')
        t.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(self.sent[0]['target'], self.platform + ':' + self.chat_id)
        self.assertEqual(json.loads(results[0])['status'], 'filled')

    def test_callback_cannot_handoff_from_another_supported_platform(self):
        def consumer(args):
            prompt = unlock.get_code_prompt_callback()
            def wrong_platform():
                set_session_vars(platform='telegram' if self.platform != 'telegram' else 'discord',
                    chat_type='dm', chat_id=self.chat_id, user_id=self.user_id,
                    session_key='synthetic-key', session_id='synthetic-session',
                    profile=profile_name_for_home(get_hermes_home()) or '', cron_session='')
                self.assertIsNone(prompt('synthetic.example', ''))
            contextvars.copy_context().run(wrong_platform)
            return json.dumps({'success':False})
        self.call(consumer)
        self.assertFalse(self.sent)
        self.assertFalse(self.service.broker.requests)

