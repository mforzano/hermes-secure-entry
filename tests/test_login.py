"""Explicit sign-in on isolated Chrome, native vault and native approval."""

import importlib.util
import json
import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_signup


class LoginTests(unittest.TestCase):
    def setUp(self):
        fixture = self.fixture = test_signup.SignupTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.install(
            '<form action="/u/login"><input name="username" value="synthetic@example.test">'
            '<input id="password" type="password" autocomplete="new-password">'
            '<button>Sign in</button></form><input id="other" type="password">'
        )
        fixture.document.evaluate("""() => {
            window.events = [];
            const p = document.querySelector('#password');
            for (const name of ['input', 'change']) p.addEventListener(name, () => events.push(name));
            document.addEventListener('submit', e => { e.preventDefault(); events.push('submit'); });
        }""")
        self.args = self.inspected_args()

    def inspected_args(self):
        args = self.fixture.args
        session = self.fixture.fixture.context.new_cdp_session(self.fixture.fixture.page)
        try:
            root = session.send('Page.getFrameTree')['frameTree']['frame']
        finally:
            session.detach()
        return {key: args[key] for key in ('handle', 'origin', 'identifier', 'parent', 'frame')} | {
            'loader_id': root['loaderId'], 'password_node': args['password_nodes'][0],
        }

    def fill(self, **overrides):
        from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager

        # Use the plugin entry point's real schema and service handler; keep only
        # the constructor on the disposable fixture vault/home.
        path = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            'synthetic_login_plugin', path / '__init__.py', submodule_search_locations=[str(path)]
        )
        plugin = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = plugin
        spec.loader.exec_module(plugin)
        ctx = PluginContext(PluginManifest(name='synthetic-login'), get_plugin_manager())
        registrations = []

        native_register = ctx.register_tool
        # Register the actual login definition without replacing the test's
        # other tools or middleware for unrelated routes.
        def selected_register(**kw):
            if kw['name'] == 'secure_entry_login_fill':
                registrations.append(native_register(**kw))

        try:
            with (
                patch.object(plugin, 'Service', return_value=self.fixture.service),
                patch.object(ctx, 'register_tool', side_effect=selected_register),
                patch.object(ctx, 'register_middleware'),
                patch.object(ctx, 'register_hook'),
                patch.object(ctx, 'on_unload'),
            ):
                plugin.register(ctx)
            self.assertEqual(len(registrations), 1, 'explicit login tool is not registered')
            result = json.loads(ctx.dispatch_tool(
                'secure_entry_login_fill', self.args | overrides, task_id='synthetic-payment'
            ))
        finally:
            for registration in registrations:
                registration.dispose()
        self.assertNotIn(self.fixture.secret, json.dumps(result) + str(self.fixture.prompts))
        return result

    def test_new_password_autocomplete_on_sign_in_is_filled_without_submission(self):
        from agent.vault_login_classifier import LoginControl, classify_login_control

        descriptor = self.fixture.document.evaluate("""() => {
            const p = document.querySelector('#password');
            return {type: p.type, autocomplete: p.getAttribute('autocomplete'), name: p.id, label: 'Password'};
        }""")
        self.assertIsNone(classify_login_control(LoginControl.from_dict(descriptor)))
        result = self.fill()
        self.assertTrue(result.get('success'), result)
        self.assertEqual((result['status'], result['filled_fields'], result['submitted']), ('filled', 1, False))
        self.assertTrue(self.fixture.document.evaluate("""want => {
            const p = document.querySelector('#password');
            return p.value === want && p.getAttribute('autocomplete') === 'new-password' &&
                !document.querySelector('#other').value &&
                document.querySelector('[name=username]').value === 'synthetic@example.test' &&
                events.join(',') === 'input,change';
        }""", self.fixture.secret))
        [prompt] = self.fixture.prompts
        text = str(prompt)
        self.assertIn('sign-in', text.lower())
        self.assertNotIn('registration', text.lower())
        self.assertIs(prompt['allow_session'], False)
        self.assertIs(prompt['allow_permanent'], False)
        for value in self.args.values():
            self.assertIn(str(value), text)

    def test_denial_prevents_decryption_even_with_native_yolo(self):
        from tools import approval

        approval.enable_session_yolo('synthetic-signup-key')
        self.addCleanup(approval.disable_session_yolo, 'synthetic-signup-key')
        self.fixture.choice = 'deny'
        with patch.object(self.fixture.store, 'resolve_secret') as resolve:
            self.assertEqual(self.fill()['status'], 'consent_declined')
            resolve.assert_not_called()
        self.assertEqual(len(self.fixture.prompts), 1)
        self.assertTrue(self.fixture.document.evaluate("!document.querySelector('#password').value"))

    def test_mismatched_metadata_or_document_never_prompts_or_decrypts(self):
        for overrides in (
            {'origin': 'https://other.test'}, {'origin': 'http://merchant.test'},
            {'identifier': 'another@example.test'}, {'loader_id': '0' * 32},
            {'parent': '0' * 32}, {'frame': '0' * 32}, {'password_node': True},
        ):
            with self.subTest(overrides=overrides), patch.object(self.fixture.store, 'resolve_secret') as resolve:
                self.assertEqual(self.fill(**overrides)['status'], 'refused')
                resolve.assert_not_called()
        self.assertEqual(self.fixture.prompts, [])

    def test_wire_debug_enabled_during_consent_refuses_before_decryption(self):
        logger = logging.getLogger('websockets.client')
        self.addCleanup(logger.setLevel, logger.level)
        self.fixture.before_answer = lambda: logger.setLevel(logging.DEBUG)
        with patch.object(self.fixture.store, 'resolve_secret') as resolve:
            self.assertEqual(self.fill()['status'], 'refused')
            resolve.assert_not_called()

    def test_same_url_reload_cannot_retarget_stale_inspection(self):
        stale = self.args['loader_id']
        self.fixture.fixture.page.reload()
        self.fixture.install('<input type="password" autocomplete="new-password">')
        self.args = self.inspected_args()
        self.assertNotEqual(self.args['loader_id'], stale)
        with patch.object(self.fixture.store, 'resolve_secret') as resolve:
            self.assertEqual(self.fill(loader_id=stale)['status'], 'refused')
            resolve.assert_not_called()
        self.assertEqual(self.fixture.prompts, [])

    def test_wrong_actual_origin_rejected_even_with_valid_vault_metadata(self):
        fixture = self.fixture
        fixture.fixture.page.goto('https://provider.test/other')
        fixture.install('<input id="password" type="password" autocomplete="new-password">')
        self.args = self.inspected_args()
        with patch.object(fixture.store, 'resolve_secret') as resolve:
            self.assertEqual(self.fill()['status'], 'refused')
            resolve.assert_not_called()
        self.assertEqual(fixture.prompts, [])

    def test_same_origin_iframe_is_not_a_top_level_document(self):
        self.fixture.install('<input type="password">', topology='same')
        self.args = self.inspected_args()
        with patch.object(self.fixture.store, 'resolve_secret') as resolve:
            self.assertEqual(self.fill()['status'], 'refused')
            resolve.assert_not_called()
        self.assertEqual(self.fixture.prompts, [])

    def test_node_replacement_during_consent_refuses_before_decryption(self):
        fixture = self.fixture
        fixture.before_answer = lambda: fixture.document.evaluate("""() => {
            const p = document.querySelector('#password'); p.replaceWith(p.cloneNode(true));
        }""")
        with patch.object(fixture.store, 'resolve_secret') as resolve:
            self.assertEqual(self.fill()['status'], 'refused')
            resolve.assert_not_called()
        self.assertEqual(len(fixture.prompts), 1)

    def test_framework_rewrite_is_not_a_verified_fill(self):
        self.fixture.document.evaluate("() => { document.querySelector('#password').onchange=e=>{e.target.value=''}; }")
        result = self.fill()
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'write_unknown')
