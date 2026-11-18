"""Registered OTP through stock capture, approval, DM delivery and real HTTP/Chrome."""
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from native_transport import synthetic_bot_network, synthetic_gateway_run


class OtpTests(unittest.TestCase):
    code = '047281'

    def setUp(self):
        from gateway.config import GatewayConfig, PlatformConfig
        from gateway.outbound import send as sender
        from gateway.platforms.base import BasePlatformAdapter
        from gateway.session_context import clear_session_vars, set_session_vars
        from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager
        from hermes_constants import get_hermes_home, profile_name_for_home
        from test_payment_browser import PaymentBrowserTests
        from tools import approval
        from tools.registry import registry

        self.fixture = PaymentBrowserTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.page = self.fixture.page
        self.messages, self.prompts = [], []
        self.choice, self.action = 'once', 'submit'
        self.before_answer = self.after_delivery = lambda: None
        self.chat = '2468101214'
        tokens = set_session_vars(platform='discord', chat_type='dm', chat_id=self.chat,
            user_id='synthetic-owner', session_key='synthetic-otp-key', session_id='synthetic-otp-session',
            profile=profile_name_for_home(get_hermes_home()) or '', cron_session='')
        self.addCleanup(clear_session_vars, tokens)

        root = Path(__file__).resolve().parents[1]
        name = '_secure_entry_otp_test'
        spec = importlib.util.spec_from_file_location(name, root / '__init__.py', submodule_search_locations=[str(root)])
        plugin = importlib.util.module_from_spec(spec)
        sys.modules[name] = plugin
        self.addCleanup(lambda: [sys.modules.pop(k) for k in list(sys.modules) if k == name or k.startswith(name + '.')])
        spec.loader.exec_module(plugin)
        ctx = PluginContext(PluginManifest(name='synthetic-otp'), get_plugin_manager())
        # Keep native registry/dispatch, but dispose all records from this test.
        register = ctx.register_tool
        def track(**kw):
            registration = register(**kw)
            self.addCleanup(registration.dispose)
            if kw['name'] == 'secure_entry_otp_fill':
                self.service = kw['handler'].__self__
        self.enterContext(patch.object(ctx, 'register_tool', side_effect=track))
        self.enterContext(patch.object(ctx, 'register_hook'))
        self.enterContext(patch.object(ctx, 'register_middleware'))
        self.enterContext(patch.object(ctx, 'on_unload', side_effect=self.addCleanup))
        self.enterContext(patch.object(ctx, 'get_config', side_effect=lambda key, default=None: 0 if key == 'port' else default))
        plugin.register(ctx)
        self.ctx = ctx
        self.assertIsNotNone(registry.get_entry('secure_entry_otp_fill'), 'plugin did not register manual OTP')

        def notify(data):
            self.prompts.append(data)
            self.before_answer()
            approval.resolve_gateway_approval('synthetic-otp-key', self.choice, request_id=data['request_id'])
        approval.register_gateway_notify('synthetic-otp-key', notify)
        self.addCleanup(approval.unregister_gateway_notify, 'synthetic-otp-key')

        platform = sender._platform_enum('discord')[0]
        class Adapter(BasePlatformAdapter):
            async def connect(self, **kw): return True
            async def disconnect(self): pass
            async def send(self, **kw): raise AssertionError('expected standalone sender')
            async def get_chat_info(self, chat_id): return {'id': chat_id, 'type': 'dm'}
        cfg = PlatformConfig(enabled=True, token='SYNTHETIC-ONLY')
        adapter = Adapter(cfg, platform)
        gateway = ModuleType('gateway.run')
        gateway._gateway_runner_ref = lambda: SimpleNamespace(adapters={platform: adapter})
        self.enterContext(synthetic_gateway_run(gateway))
        self.enterContext(synthetic_bot_network('discord', self.deliver))
        self.enterContext(patch('gateway.config.load_gateway_config', return_value=GatewayConfig(platforms={platform: cfg})))
        self.enterContext(patch.object(sender, '_mirror_sent_message', return_value=False))

    async def deliver(self, chat_id, content):
        self.messages.append((chat_id, content))
        self.assertEqual(chat_id, self.chat)
        link = re.search(r'https://[^\s]+/r/[\w-]+', content).group()
        url = f'http://127.0.0.1:{self.service.server.httpd.server_port}' + urlsplit(link).path
        with urlopen(url, timeout=5) as page:
            csrf = re.search(r'name="csrf" value="([^"]+)"', page.read().decode()).group(1)
        with urlopen(Request(url, data=urlencode({'action': self.action, 'csrf': csrf, 'code': self.code}).encode()), timeout=5) as reply:
            self.assertNotIn(self.code, reply.read().decode())
        self.after_delivery()

    def install(self, markup):
        self.page.evaluate('html=>document.body.innerHTML=html', markup)
        self.page.evaluate("""()=>{window.submits=0;window.writes=0;
            document.body.addEventListener('submit',e=>{e.preventDefault();window.submits++});
            document.body.addEventListener('input',()=>window.writes++);}""")
        session = self.fixture.context.new_cdp_session(self.page)
        try:
            root = session.send('DOM.getDocument')['root']['nodeId']
            ids = session.send('DOM.querySelectorAll', {'nodeId': root, 'selector': '[data-otp]'})['nodeIds']
            nodes = [session.send('DOM.describeNode', {'nodeId': node})['node']['backendNodeId'] for node in ids]
            frame = session.send('Page.getFrameTree')['frameTree']['frame']['id']
        finally:
            session.detach()
        return dict(parent=self.fixture.parent, frame=frame, origin='https://merchant.test',
                    frame_origin='https://merchant.test', otp_nodes=nodes)

    def fill(self, args):
        result = json.loads(self.ctx.dispatch_tool('secure_entry_otp_fill', args, task_id='synthetic-payment'))
        self.assertNotIn(self.code, json.dumps(result) + str(self.messages) + str(self.prompts))
        return result

    def assert_fields(self, expected):
        self.assertTrue(self.page.evaluate("""expected=>{
            const fields=[...document.querySelectorAll('[data-otp]')];
            return fields.length===expected.length && fields.every((e,i)=>e.value===expected[i]) && window.submits===0 &&
                [...document.querySelectorAll('input:not([data-otp])')].every(e=>e.value==='leave');
        }""", expected))

    def test_registered_single_otp(self):
        args = self.install('<form><input data-otp autocomplete="one-time-code"><input name="promo" value="leave"></form>')
        result = self.fill(args)
        self.assertEqual(result.get('status'), 'filled', result)
        self.assertEqual(result.get('filled_fields'), 1)
        self.assertIs(result.get('submitted'), False)
        self.assert_fields([self.code])
        self.assertEqual((len(self.prompts), len(self.messages)), (1, 1))
        self.assertEqual(self.page.evaluate('window.writes'), 1)
        self.assertEqual(next(iter(self.service.broker.requests.values())).status, 'filled')

    @staticmethod
    def numbered(positions=range(1, 7)):
        return ''.join(f'<input data-otp aria-label="Enter code Enter digit {i} of 6">' for i in positions)

    def test_explicit_digit_count_and_complete_splits(self):
        for markup, expected in (
            ('<label for="challenge">Enter the 6-digit code</label><input data-otp id="challenge">', [self.code]),
            ('<section>' + self.numbered() + '</section>', list(self.code)),
            ('<form>' + '<input data-otp name="otp" maxlength="1">'*6 + '</form>', list(self.code)),
            ('<div><input data-otp autocomplete="one-time-code" maxlength="1">'
             + '<input data-otp inputmode="numeric" maxlength="1">'*5 + '</div>', list(self.code)),
        ):
            with self.subTest(markup=markup):
                self.prompts.clear()
                self.messages.clear()
                args = self.install(markup + '<input name="postal-code" value="leave">')
                args['otp_nodes'].reverse()  # site order, not tool argument order
                result = self.fill(args)
                self.assertEqual(result['status'], 'filled', result)
                self.assert_fields(expected)
                self.assertEqual((len(self.prompts), len(self.messages)), (1, 1))

    def test_bad_plans_refuse_before_consent_and_link(self):
        classic = '<input data-otp name="otp" maxlength="1">'
        for markup in (
            '<input data-otp aria-label="Verification code digit 6 of">',
            '<input data-otp aria-label="Enter the 6.5-digit code">',
            '<section>' + self.numbered([-1,2,3,4,5,6]) + '</section>',
            '<section>' + self.numbered([1,2,3,4,5,5]) + '</section>',
            '<section>' + self.numbered(range(1, 6)) + '</section>',
            '<form>' + classic + '<input name="billing" value="leave">' + classic + '</form>',
            '<form>' + classic + '</form><form>' + classic + '</form>',
            '<form>' + classic + '<input name="otp" maxlength="1" value="leave">' + classic + '</form>',
            '<form>' + classic + '<input data-otp name="promo-code" maxlength="1"></form>',
            '<input data-otp name="country-code">',
            '<input data-otp name="postal-code" autocomplete="one-time-code">',
        ):
            with self.subTest(markup=markup):
                args = self.install(markup)
                self.assertEqual(self.fill(args)['status'], 'refused')
                self.assert_fields(['']*len(args['otp_nodes']))
        self.assertEqual((len(self.prompts), len(self.messages)), (0, 0))

    def test_length_mismatch_ends_after_one_prompt_without_writes(self):
        self.code = '04728'
        for markup in (
            '<input data-otp aria-label="Enter the 6-digit code">',
            '<section>' + self.numbered() + '</section>',
            '<form>' + '<input data-otp name="otp" maxlength="1">'*6 + '</form>',
        ):
            with self.subTest(markup=markup):
                self.prompts.clear()
                self.messages.clear()
                args = self.install(markup)
                result = self.fill(args)
                self.assertEqual(result['status'], 'code_mismatch', result)
                self.assert_fields(['']*len(args['otp_nodes']))
                self.assertEqual((len(self.prompts), len(self.messages)), (1, 1))

    def test_private_cancel_and_target_changes(self):
        def replace():
            capture = self.fixture.capture
            capture.call('Runtime.evaluate', {'expression': "{const e=document.querySelector('[data-otp]');e.replaceWith(e.cloneNode())}"},
                         session_id=capture.page_session_id)

        for before, after, choice, action, links, status in (
            (None, None, 'deny', 'submit', 0, 'consent_declined'),
            (replace, None, 'once', 'submit', 0, 'refused'),
            (None, None, 'once', 'cancel', 1, 'cancelled'),
            (None, replace, 'once', 'submit', 1, 'refused'),
            (None, lambda: self.service.stopped(session_id='synthetic-otp-session'), 'once', 'submit', 1, 'cancelled'),
        ):
            with self.subTest(status=status, links=links):
                self.prompts.clear()
                self.messages.clear()
                self.choice, self.action = choice, action
                self.before_answer, self.after_delivery = before or (lambda: None), after or (lambda: None)
                args = self.install('<input data-otp autocomplete="one-time-code">')
                result = self.fill(args)
                self.assertEqual(result['status'], status, result)
                self.assert_fields([''])
                self.assertEqual((len(self.prompts), len(self.messages)), (1, links))

    def test_lost_write_reply_is_not_retried(self):
        from importlib import import_module
        cls = import_module('_secure_entry_otp_test.secure_entry.otp').OtpTarget
        original = cls.invoke
        def invoke(target, sid, obj, js, args=()):
            result = original(target, sid, obj, js, args)
            if 'this.write' in js:
                raise TimeoutError('synthetic lost reply')
            return result
        args = self.install('<input data-otp autocomplete="one-time-code">')
        with patch.object(cls, 'invoke', invoke):
            result = self.fill(args)
        self.assertEqual(result['status'], 'write_unknown', result)
        self.assert_fields([self.code])
        self.assertEqual(self.page.evaluate('window.writes'), 1)
        self.assertEqual((len(self.prompts), len(self.messages)), (1, 1))
        self.assertEqual(next(iter(self.service.broker.requests.values())).status, 'write_unknown')

    def test_takeover_and_handback_before_entry_refuses(self):
        from tools.bot_desktop import lease

        def takeover():
            lease.acquire('synthetic-otp-viewer')
            lease.release('synthetic-otp-viewer')

        self.before_answer = takeover
        args = self.install('<input data-otp autocomplete="one-time-code">')
        self.assertEqual(self.fill(args)['status'], 'refused')
        self.assert_fields([''])
        self.assertEqual((len(self.prompts), len(self.messages)), (1, 0))

    def test_framework_edit_after_write_before_readback_is_unknown(self):
        from importlib import import_module

        cls = import_module('_secure_entry_otp_test.secure_entry.otp').OtpTarget
        original = cls.invoke
        capture = self.fixture.capture

        def invoke(target, sid, obj, js, args=()):
            result = original(target, sid, obj, js, args)
            if 'this.write' in js:
                capture.call('Runtime.evaluate', {'expression': "document.querySelector('[data-otp]').value=''"},
                             session_id=capture.page_session_id)
            return result

        args = self.install('<input data-otp autocomplete="one-time-code">')
        with patch.object(cls, 'invoke', invoke):
            result = self.fill(args)
        self.assertEqual(result['status'], 'write_unknown', result)
        self.assert_fields([''])
        self.assertEqual(self.page.evaluate('window.writes'), 1)

    def test_wire_debug_refuses_before_prompt(self):
        import logging

        logger = logging.getLogger('websockets.client')
        args = self.install('<input data-otp autocomplete="one-time-code">')
        old = logger.level
        try:
            logger.setLevel(logging.DEBUG)
            self.assertEqual(self.fill(args)['status'], 'refused')
        finally:
            logger.setLevel(old)
        self.assert_fields([''])
        self.assertEqual((len(self.prompts), len(self.messages)), (0, 0))

    def test_ambiguous_delivery_never_retries_or_uses_received_input(self):
        from gateway.outbound import send as sender

        original = sender.send_message_tool
        def lost_reply(args):
            original(args)
            raise TimeoutError('synthetic lost send reply')

        args = self.install('<input data-otp autocomplete="one-time-code">')
        with patch.object(sender, 'send_message_tool', side_effect=lost_reply) as send:
            self.assertEqual(self.fill(args)['status'], 'cancelled')
        send.assert_called_once()
        self.assert_fields([''])
        self.assertEqual((len(self.prompts), len(self.messages)), (1, 1))

    def test_only_selected_cross_origin_document_receives_code(self):
        url = 'https://provider.test/otp'
        self.fixture.context.route(url, lambda r: r.fulfill(content_type='text/html',
            body='<input id="otp" autocomplete="one-time-code">'))
        self.page.evaluate("url=>document.body.innerHTML=`<input id='parent' autocomplete='one-time-code'><iframe src='${url}'></iframe>`", url)
        self.page.frame_locator('iframe').locator('#otp').wait_for()
        child = self.page.frame(url=url)
        self.assertIsNotNone(child)
        session = self.fixture.context.new_cdp_session(child)
        try:
            root = session.send('DOM.getDocument')['root']['nodeId']
            node = session.send('DOM.querySelector', {'nodeId':root, 'selector':'#otp'})['nodeId']
            backend = session.send('DOM.describeNode', {'nodeId':node})['node']['backendNodeId']
            frame = session.send('Page.getFrameTree')['frameTree']['frame']['id']
        finally:
            session.detach()
        args = dict(parent=self.fixture.parent, frame=frame, origin='https://merchant.test',
                    frame_origin='https://provider.test', otp_nodes=[backend])
        result = self.fill(args)
        self.assertEqual(result['status'], 'filled', result)
        self.assertTrue(child.evaluate('code=>document.querySelector("#otp").value===code', self.code))
        self.assertTrue(self.page.evaluate('document.querySelector("#parent").value===""'))
        self.assertEqual((len(self.prompts), len(self.messages)), (1, 1))
