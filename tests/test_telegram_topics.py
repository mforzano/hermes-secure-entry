"""Synthetic Telegram transport + real Hermes authorization, middleware and HTTP.

Only external I/O/config and the browser supervisor are substituted. No owner,
private delivery, egress guard, native handler, or callback is mocked.
"""
import contextvars
import dataclasses
import io
import json
import logging
import os
import re
import sys
import threading
import unittest
import urllib.parse
import urllib.request
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gateway.run import GatewayRunner
from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.session import SessionSource, build_session_key
from gateway.session_context import set_session_vars, reset_session_vars
from hermes_constants import get_hermes_home, profile_name_for_home
from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager
from hermes_cli.middleware import run_tool_execution_middleware
from agent.vault_backends import unlock
from tools import browser_vault_tool
from secure_entry.service import Service


class TopicTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(reset_session_vars)
        self.profile = profile_name_for_home(get_hermes_home()) or ''
        self.source = SessionSource(platform=Platform.TELEGRAM, chat_type='group',
            chat_id='-1001234500001', thread_id='17', user_id='123450001',
            message_id='301', profile=self.profile)
        self.key = build_session_key(self.source, profile=self.profile)
        self.values = dict(platform='telegram', chat_type='group', chat_id=self.source.chat_id,
            thread_id=self.source.thread_id, user_id=self.source.user_id, message_id=self.source.message_id,
            session_key=self.key, session_id='synthetic-topic-session', profile=self.profile, cron_session='')
        set_session_vars(**self.values)
        self.service = Service('https://example.invalid', str(get_hermes_home()), port=0)
        self.addCleanup(self.service.close)
        self.dispatch = Mock(side_effect=AssertionError('Topic capability reached model-tool dispatch'))
        self.service.configure_bridge(self.dispatch, 'in_process')
        self.addCleanup(self.dispatch.assert_not_called)
        self.ctx = PluginContext(PluginManifest(name='synthetic-topic-bridge'), get_plugin_manager())
        self.lease = self.ctx.register_middleware('tool_execution', self.service.middleware)
        self.addCleanup(self.lease.dispose)
        self.sent = []
        self.delivered = threading.Event()
        self.delivery_error = None
        self.delivery_message_id = 'synthetic-message'
        case = self
        class Adapter(BasePlatformAdapter):
            async def connect(self, **kwargs): return True
            async def disconnect(self): pass
            async def get_chat_info(self, chat_id): return {'id': chat_id, 'type': 'dm'}
            async def send(self, **kwargs):
                case.sent.append(kwargs)
                case.delivered.set()
                if case.delivery_error:
                    raise case.delivery_error
                return SendResult(success=True, message_id=case.delivery_message_id)
        self.config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token='SYNTHETIC-TOKEN')})
        self.adapter = Adapter(self.config.platforms[Platform.TELEGRAM], Platform.TELEGRAM)
        # Use the pinned gateway's actual cache, key derivation and profile-aware
        # authorization seams. Bypass only construction/startup of a live gateway.
        self.runner = object.__new__(GatewayRunner)
        self.runner.config = self.config
        self.runner.adapters = {Platform.TELEGRAM: self.adapter}
        self.runner._cache_session_source(self.key, self.source)
        self.stack.enter_context(patch('gateway.run._gateway_runner_ref', return_value=self.runner))
        self.stack.enter_context(patch.dict(os.environ, {'TELEGRAM_ALLOWED_USERS': self.source.user_id,
            'TELEGRAM_GROUP_ALLOWED_USERS': '', 'TELEGRAM_GROUP_ALLOWED_CHATS': '',
            'GATEWAY_ALLOWED_USERS': '', 'GATEWAY_ALLOW_ALL_USERS': '', 'TELEGRAM_ALLOW_ALL_USERS': ''}))
        self.stack.enter_context(patch('gateway.config.load_gateway_config', return_value=self.config))
        class Bot:
            async def send_message(inner, **kwargs):
                result = await case.adapter.send(chat_id=str(kwargs['chat_id']), content=kwargs['text'],
                    metadata={k: v for k, v in kwargs.items() if k not in ('chat_id', 'text')})
                return SimpleNamespace(message_id=result.message_id)
        self.stack.enter_context(patch('tools.send_message_senders._telegram_bot', return_value=Bot()))
        # A tripwire, not a suppressed mirror: a capability must never reach this API.
        self.mirror = self.stack.enter_context(patch('gateway.mirror.mirror_to_session',
            side_effect=AssertionError('private capability reached transcript mirror')))
        self.native_mirror = self.stack.enter_context(patch('tools.send_message_tool._mirror_sent_message',
            side_effect=AssertionError('private capability entered native mirror')))
        # Assert even on cancellation cases, where a throwing tripwire alone
        # could be swallowed by the fail-closed delivery boundary.
        self.addCleanup(self.mirror.assert_not_called)
        self.addCleanup(self.native_mirror.assert_not_called)
        self.log = io.StringIO()
        handler = logging.StreamHandler(self.log)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)

    def call(self, action='enter_code', fn=None, **context):
        args = {'action': action}
        if action == 'unlock': args['backend'] = 'bitwarden'
        return run_tool_execution_middleware('browser_vault', args,
            fn or (lambda a: self.ctx.dispatch_tool('browser_vault', a, task_id='synthetic-browser-task')),
            session_id=context.pop('session_id', 'synthetic-topic-session'),
            task_id=context.pop('task_id', 'synthetic-browser-task'), **context)

    def worker(self, fn):
        results, errors = [], []
        ctx = contextvars.copy_context()
        def run():
            try: results.append(ctx.run(fn))
            except BaseException as exc: errors.append(exc)
            finally:
                local = getattr(sys.modules.get('model_tools'), '_worker_thread_local', None)
                loop = getattr(local, 'loop', None)
                if loop is not None and not loop.is_running() and not loop.is_closed(): loop.close()
        thread = threading.Thread(target=run)
        thread.start()
        self.addCleanup(lambda: thread.join(5))
        return thread, results, errors

    def post(self, index=0, value='824761', field='code', action='submit'):
        self.assertTrue(self.delivered.wait(3))
        token = self.sent[index]['content'].split()[-1].rsplit('/', 1)[-1]
        url = f'http://127.0.0.1:{self.service.server.port}/r/{token}'
        with urllib.request.urlopen(url) as response: page = response.read().decode()
        csrf = re.search(r'name="csrf" value="([^"]+)"', page)
        data = urllib.parse.urlencode({'csrf': csrf.group(1), 'action': action, field: value}).encode()
        with urllib.request.urlopen(url, data) as response: result = response.read().decode()
        self.assertNotIn(value, result)
        return token, url, data

    def test_native_http_code_stays_in_topic_task_but_link_only_in_requester_dm(self):
        from tools.browser_supervisor import SUPERVISOR_REGISTRY
        synthetic = '824761'
        writes, tasks = [], []
        controls = [{'index': 0, 'type': 'text', 'name': 'otp', 'label': 'Code', 'autocomplete': 'one-time-code'}]
        def evaluate(expr):
            if synthetic in expr:
                writes.append(expr)
                return {'ok': True, 'result': json.dumps({'filled': 1})}
            return {'ok': True, 'result': json.dumps(controls) if 'querySelectorAll' in expr else 'https://synthetic.example/otp'}
        supervisor = SimpleNamespace(focus_page=lambda *a, **k: {'ok': True}, evaluate_runtime=evaluate)
        def get(task):
            tasks.append(task)
            return supervisor
        with patch.object(SUPERVISOR_REGISTRY, 'get', side_effect=get):
            thread, results, errors = self.worker(self.call)
            token, url, data = self.post()
            thread.join(5)
        self.assertEqual(errors, [])
        self.assertFalse(thread.is_alive())
        self.assertEqual(json.loads(results[0])['status'], 'filled')
        self.assertEqual(len(writes), 1)
        self.assertTrue(tasks)
        self.assertEqual(set(tasks), {'synthetic-browser-task'})
        self.assertEqual(self.sent[0]['chat_id'], self.source.user_id)
        self.assertNotIn('message_thread_id', self.sent[0]['metadata'])
        self.assertTrue(self.sent[0]['metadata']['disable_web_page_preview'])
        request = self.service.broker.requests[token]
        self.assertIn(self.source.thread_id, request.owner)
        self.assertIn('synthetic-browser-task', request.owner)
        with urllib.request.urlopen(url, data) as response:
            self.assertNotIn(synthetic, response.read().decode())
        self.assertEqual(len(writes), 1)
        self.mirror.assert_not_called()
        self.assertNotIn(token, str(results) + self.log.getvalue())
        self.assertNotIn(synthetic, str(results) + str(self.sent) + self.log.getvalue())
        self.assertIsNone(unlock.get_code_prompt_callback())

    def test_topic_list_and_unlock_admitted_but_standalone_writes_refused(self):
        called = []
        result = self.call(action='list', fn=lambda a: (called.append(a), json.dumps({'items': []}))[1])
        self.assertEqual(json.loads(result), {'items': []})
        self.assertEqual(len(called), 1)
        backend = SimpleNamespace(name='bitwarden', display_name='Bitwarden', needs_unlock=True,
            is_unlocked=lambda: False, unlock=lambda value: called.append(value))
        with patch('agent.vault_backends.enabled_backends', return_value=[backend]):
            t, results, errors = self.worker(lambda: self.call('unlock'))
            self.post(value='SYNTHETIC-MASTER', field='password')
            t.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(json.loads(results[0])['status'], 'unlocked')
        for operation in ('add_login', 'add_card'):
            self.assertNotIn('url', json.loads(self.service.request({'operation': operation, 'origin': 'https://example.invalid'})))
        self.assertEqual(json.loads(self.service.remove_card({'handle': 'vault_000000000000', 'merchant_origin': 'https://example.invalid'}))['status'], 'refused')

    def test_topic_admission_fails_closed_for_untrusted_or_mismatched_bindings(self):
        from agent.delegation_context import delegated_child_context
        def denied(**context):
            called = []
            result = json.loads(self.call(fn=lambda a: called.append(a), **context))
            self.assertFalse(called)
            self.assertEqual(result['status'], 'unavailable')
        changes = [{'thread_id': ''}, {'thread_id': '18'}, {'user_id': ''}, {'user_id': '-100123'},
            {'user_id': '1087968824'}, {'user_id': '136817688'}, {'chat_type': 'channel'},
            {'chat_id': '123450001'}, {'session_key': 'mismatch'}, {'profile': 'other'},
            {'message_id': ''}, {'message_id': '302'}, {'cron_session': '1'}]
        for change in changes:
            with self.subTest(change=change):
                contextvars.copy_context().run(lambda: (set_session_vars(**{**self.values, **change}), denied()))
        denied(session_id='other')
        denied(task_id='')
        with delegated_child_context(): denied()
        self.runner._cache_session_source(self.key, dataclasses.replace(self.source, is_bot=True))
        denied()
        self.runner._session_sources.clear()
        denied()
        self.assertFalse(self.sent)
        self.assertIsNone(self.service.server)

    def test_changed_source_before_handoff_revokes_without_native_write(self):
        # The valid HTTP bearer is not sufficient when the initiating source or
        # its authorization changed during the wait, including the same sender's
        # next message. Exercise the real owner/auth check at the handoff fence.
        changes = ({'message_id': '302'}, {'profile': 'other'}, {'thread_id': '18'},
            {'user_id': '123450002'}, {'chat_id': '-1001234500002'},
            {'profile_route_rejected': True}, {'is_bot': True}, None, 'authorization')
        for change in changes:
            with self.subTest(change=change), patch.dict(os.environ, {}):
                self.runner._cache_session_source(self.key, self.source)
                self.delivered.clear()
                index = len(self.sent)
                consumed = []
                def consumer(args):
                    consumed.append(unlock.get_code_prompt_callback()('synthetic.example', ''))
                    return json.dumps({'success': consumed[-1] is not None})
                t, results, errors = self.worker(lambda: self.call(fn=consumer))
                self.assertTrue(self.delivered.wait(3))
                if change is None:
                    self.runner._session_sources.clear()
                elif change == 'authorization':
                    os.environ['TELEGRAM_ALLOWED_USERS'] = '123459999'
                else:
                    self.runner._cache_session_source(self.key, dataclasses.replace(self.source, **change))
                token, _, _ = self.post(index=index)
                t.join(5)
                self.assertFalse(t.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(consumed, [None])
                self.assertEqual(json.loads(results[0])['status'], 'cancelled')
                self.assertEqual(self.service.broker.status(token)['status'], 'cancelled')
                self.assertNotIn(token, str(results) + self.log.getvalue())
                self.assertEqual(self.service.bridge.topic_scopes, {})

    def test_source_replacement_before_prompt_never_issues_or_sends(self):
        consumed = []
        def consumer(args):
            self.runner._cache_session_source(self.key, dataclasses.replace(self.source, message_id='302'))
            consumed.append(unlock.get_code_prompt_callback()('synthetic.example', ''))
            return json.dumps({'success': consumed[-1] is not None})
        result = self.call(fn=consumer)
        self.assertEqual(consumed, [None])
        self.assertFalse(json.loads(result)['success'])
        self.assertFalse(self.service.broker.requests)
        self.assertIsNone(self.service.server)
        self.assertFalse(self.sent)

    def test_source_replacement_after_issue_never_reaches_transport(self):
        issue = self.service.broker.issue
        def replace_source(*args, **kwargs):
            request = issue(*args, **kwargs)
            self.runner._cache_session_source(self.key, dataclasses.replace(self.source, message_id='302'))
            return request
        consumed = []
        def consumer(args):
            consumed.append(unlock.get_code_prompt_callback()('synthetic.example', ''))
            return json.dumps({'success': consumed[-1] is not None})
        # Inject a deterministic race at the real issue/delivery boundary; do
        # not replace the owner validator, transport policy or broker behavior.
        with patch.object(self.service.broker, 'issue', side_effect=replace_source):
            result = self.call(fn=consumer)
        self.assertEqual(consumed, [None])
        self.assertEqual(json.loads(result)['status'], 'cancelled')
        self.assertEqual(len(self.service.broker.requests), 1)
        self.assertEqual(next(iter(self.service.broker.requests.values())).status, 'cancelled')
        self.assertFalse(self.sent)
        self.mirror.assert_not_called()

    def test_stop_during_transport_revokes_even_if_delivery_later_succeeds(self):
        entered, release = threading.Event(), threading.Event()
        send = self.adapter.send
        async def blocked_send(**kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('synthetic transport barrier')
            return await send(**kwargs)
        consumed = []
        def consumer(args):
            consumed.append(unlock.get_code_prompt_callback()('synthetic.example', ''))
            return json.dumps({'success': consumed[-1] is not None})
        with patch.object(self.adapter, 'send', side_effect=blocked_send):
            t, results, errors = self.worker(lambda: self.call(fn=consumer))
            try:
                self.assertTrue(entered.wait(3))
                self.service.stopped(session_key=self.key)
            finally:
                release.set()
            t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(consumed, [None])
        self.assertEqual(json.loads(results[0])['status'], 'cancelled')
        self.assertEqual(len(self.sent), 1)
        token = self.sent[0]['content'].split()[-1].rsplit('/', 1)[-1]
        request = self.service.broker.requests[token]
        self.assertEqual(self.service.broker.submit(token, {'csrf': request.csrf,
            'action': 'submit', 'code': 'SYNTHETIC-LATE'})['status'], 'cancelled')
        self.assertEqual(self.service.bridge.topic_scopes, {})
        self.mirror.assert_not_called()

    def test_equivalent_cache_copy_and_normal_turn_end_do_not_cancel_waiter(self):
        consumed = []
        def consumer(args):
            consumed.append(unlock.get_code_prompt_callback()('synthetic.example', ''))
            return json.dumps({'success': consumed[-1] is not None})
        t, results, errors = self.worker(lambda: self.call(fn=consumer))
        self.assertTrue(self.delivered.wait(3))
        # The native gateway caches dataclass copies, not source object identity.
        self.runner._cache_session_source(self.key, self.source)
        self.service.ended(turn_id='synthetic-turn', completed=True,
            session_key=self.key, session_id=self.values['session_id'])
        self.post(value='SYNTHETIC-UNCHANGED')
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(consumed, ['SYNTHETIC-UNCHANGED'])
        self.assertEqual(json.loads(results[0])['status'], 'filled')
        self.assertEqual(self.service.bridge.topic_scopes, {})

    def test_same_sender_reset_only_cancels_old_topic_while_other_callback_starts(self):
        # Topic 2 is admitted, but has not issued a request when topic 1 resets.
        # Indexing only issued requests (or using a global generation at prompt)
        # would either miss the targeted callback or cancel the unrelated topic.
        source2 = dataclasses.replace(self.source, thread_id='18', message_id='302')
        key2 = build_session_key(source2, profile=self.profile)
        self.runner._cache_session_source(key2, source2)
        values2 = {**self.values, 'thread_id': '18', 'message_id': '302',
            'session_key': key2, 'session_id': 'synthetic-topic-session-2'}
        entered, release = threading.Event(), threading.Event()
        consumed = [[], []]
        def consumer(index):
            def run(args):
                if index == 1:
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError('synthetic callback barrier')
                consumed[index].append(unlock.get_code_prompt_callback()('synthetic.example', ''))
                return json.dumps({'success': consumed[index][-1] is not None})
            return run
        t1, result1, error1 = self.worker(lambda: self.call(fn=consumer(0)))
        self.assertTrue(self.delivered.wait(3))
        self.delivered.clear()
        def second():
            set_session_vars(**values2)
            return self.call(fn=consumer(1), session_id=values2['session_id'], task_id='synthetic-task-2')
        t2, result2, error2 = self.worker(second)
        try:
            self.assertTrue(entered.wait(3))
            self.service.reset(old_session_id=self.values['session_id'], session_id='synthetic-new-session')
        finally:
            release.set()
        self.post(index=1, value='SYNTHETIC-SECOND')
        t1.join(5)
        t2.join(5)
        self.assertFalse(t1.is_alive() or t2.is_alive())
        self.assertEqual(error1 + error2, [])
        self.assertEqual(consumed, [[None], ['SYNTHETIC-SECOND']])
        self.assertEqual(json.loads(result1[0])['status'], 'cancelled')
        self.assertEqual(json.loads(result2[0])['status'], 'filled')
        self.assertEqual([sent['chat_id'] for sent in self.sent], [self.source.user_id] * 2)
        self.assertEqual(self.service.bridge.topic_scopes, {})
        self.mirror.assert_not_called()

    def test_unauthorized_sender_never_enters_native(self):
        with patch.dict(os.environ, {'TELEGRAM_ALLOWED_USERS': '123459999'}):
            called = []
            result = self.call(fn=lambda a: called.append(a))
        self.assertFalse(called)
        self.assertEqual(json.loads(result)['status'], 'unavailable')

    def test_failed_or_ambiguous_dm_cancels_once_without_fallback_or_logging(self):
        from telegram.error import Forbidden, NetworkError, RetryAfter, TimedOut
        # Unlike a timeout, 429 and 5xx are retried by the native helper unless
        # the topic path explicitly requests one attempt. No ACK is ambiguous.
        outcomes = (TimeoutError('SYNTHETIC-SECRET-ERROR'),
            TimedOut('SYNTHETIC-SECRET-ERROR'), Forbidden('SYNTHETIC-SECRET-ERROR'),
            NetworkError('503 SYNTHETIC-SECRET-ERROR'), RetryAfter(0), None)
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__):
                self.delivery_error = outcome
                self.delivery_message_id = None if outcome is None else 'synthetic-message'
                index = len(self.sent)
                consumed = []
                def consumer(args):
                    consumed.append(unlock.get_code_prompt_callback()('synthetic.example', ''))
                    return json.dumps({'success': consumed[-1] is not None})
                result = self.call(fn=consumer)
                self.assertEqual(consumed, [None])
                self.assertEqual(len(self.sent), index + 1)
                self.assertEqual(self.sent[index]['chat_id'], self.source.user_id)
                self.assertEqual(json.loads(result)['status'], 'cancelled')
                token = self.sent[index]['content'].split()[-1].rsplit('/', 1)[-1]
                request = self.service.broker.requests[token]
                self.assertEqual(request.status, 'cancelled')
                self.assertEqual(self.service.broker.submit(token, {'csrf': request.csrf,
                    'action': 'submit', 'code': 'SYNTHETIC-LATE'})['status'], 'cancelled')
                self.assertNotIn('SYNTHETIC-SECRET-ERROR', result + self.log.getvalue())
                self.assertNotIn(token, result + self.log.getvalue())
                self.mirror.assert_not_called()

    def test_lifecycle_expiry_cancel_session_end_and_unload(self):
        # Each branch gets a fresh request and uses the existing native callback.
        for ending in ('expiry', 'web_cancel', 'session_end', 'unload'):
            with self.subTest(ending=ending):
                self.delivered.clear()
                index = len(self.sent)
                consumed = []
                def consumer(args):
                    consumed.append(unlock.get_code_prompt_callback()('synthetic.example', ''))
                    return json.dumps({'success': consumed[-1] is not None})
                t, results, errors = self.worker(lambda: self.call(fn=consumer))
                self.assertTrue(self.delivered.wait(3))
                token = self.sent[index]['content'].split()[-1].rsplit('/', 1)[-1]
                if ending == 'web_cancel':
                    self.post(index=index, action='cancel')
                elif ending == 'expiry':
                    with self.service.broker.lock:
                        self.service.broker.requests[token].deadline = 0
                elif ending == 'session_end':
                    self.service.stopped(session_key=self.key)
                else:
                    self.service.close()
                t.join(5)
                self.assertFalse(t.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(consumed, [None])
                self.assertEqual(json.loads(results[0])['status'], 'expired' if ending == 'expiry' else 'cancelled')
                self.assertEqual(self.service.broker.submit(token, {'csrf': self.service.broker.requests[token].csrf,
                    'action': 'submit', 'code': 'SYNTHETIC-LATE'})['status'],
                    'expired' if ending == 'expiry' else 'cancelled')

    def test_simultaneous_topics_users_and_sessions_do_not_cross(self):
        source2 = dataclasses.replace(self.source, user_id='123450002', thread_id='18', message_id='302')
        key2 = build_session_key(source2, profile=self.profile)
        self.runner._cache_session_source(key2, source2)
        values2 = {**self.values, 'user_id': source2.user_id, 'thread_id': source2.thread_id,
            'message_id': source2.message_id, 'session_key': key2, 'session_id': 'synthetic-topic-session-2'}
        consumed = [[], []]
        def consumer(index):
            def run(args):
                consumed[index].append(unlock.get_code_prompt_callback()('synthetic.example', ''))
                return json.dumps({'success': consumed[index][-1] is not None})
            return run
        with patch.dict(os.environ, {'TELEGRAM_ALLOWED_USERS': self.source.user_id + ',' + source2.user_id}):
            t1, result1, error1 = self.worker(lambda: self.call(fn=consumer(0)))
            self.assertTrue(self.delivered.wait(3))
            self.delivered.clear()
            def second():
                set_session_vars(**values2)
                return self.call(fn=consumer(1), session_id=values2['session_id'], task_id='synthetic-task-2')
            t2, result2, error2 = self.worker(second)
            self.assertTrue(self.delivered.wait(3))
            token2 = self.sent[1]['content'].split()[-1].rsplit('/', 1)[-1]
            request2 = self.service.broker.requests[token2]
            request1 = self.service.broker.requests[self.sent[0]['content'].split()[-1].rsplit('/', 1)[-1]]
            self.assertNotEqual(request1.owner, request2.owner)
            self.assertEqual(self.sent[1]['chat_id'], source2.user_id)
            # Browser CSRF from topic 1 cannot submit to topic 2.
            self.assertEqual(self.service.broker.submit(token2, {'csrf': request1.csrf,
                'action': 'submit', 'code': 'SYNTHETIC-WRONG'})['status'], 'csrf_rejected')
            self.service.stopped(session_key=self.key)
            self.assertEqual(request2.status, 'pending')
            self.post(index=1, value='SYNTHETIC-SECOND')
            t1.join(5)
            t2.join(5)
        self.assertEqual(error1 + error2, [])
        self.assertEqual(consumed, [[None], ['SYNTHETIC-SECOND']])
        self.assertEqual(json.loads(result1[0])['status'], 'cancelled')
        self.assertEqual(json.loads(result2[0])['status'], 'filled')

    def test_model_destination_cannot_redirect_private_link(self):
        def native(args):
            self.assertEqual(unlock.get_code_prompt_callback()('synthetic.example', ''), 'SYNTHETIC-BOUND')
            return json.dumps({'success': True})
        t, results, errors = self.worker(lambda: run_tool_execution_middleware('browser_vault',
            {'action': 'enter_code', 'target': 'telegram:123459999', 'destination': '-1001234599999'},
            native, session_id=self.values['session_id'], task_id='synthetic-browser-task'))
        self.post(value='SYNTHETIC-BOUND')
        t.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(self.sent[0]['chat_id'], self.source.user_id)
        self.assertEqual(json.loads(results[0])['status'], 'filled')

    def test_native_relay_egress_denial_sends_nothing(self):
        self.runner.adapters = {Platform.RELAY: SimpleNamespace(fronts_platform=lambda p: p == Platform.TELEGRAM)}
        result = self.call(fn=lambda a: json.dumps({'success': unlock.get_code_prompt_callback()('synthetic.example', '') is not None}))
        self.assertEqual(json.loads(result)['status'], 'cancelled')
        self.assertFalse(self.sent)
        self.assertTrue(self.service.broker.requests)
