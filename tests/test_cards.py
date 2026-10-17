"""Disposable real native vault; all inputs are synthetic, never user data."""
import json
import re
import tempfile
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from agent.vault_store import VaultStore
from gateway.session_context import set_session_vars, clear_session_vars
from hermes_constants import get_hermes_home
from secure_entry.service import Service


class CardTests(unittest.TestCase):
    def setUp(self):
        self.tokens = set_session_vars(platform='photon', chat_id='synthetic-chat', chat_type='dm',
            user_id='synthetic-user', session_key='synthetic-key', session_id='synthetic-session')
        self.addCleanup(clear_session_vars, self.tokens)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = VaultStore(Path(self.tmp.name))
        self.service = Service('https://example.ts.net:9443', str(get_hermes_home()), port=0,
            store_factory=lambda: self.store)
        self.addCleanup(self.service.close)

    def save_card(self):
        issued = json.loads(self.service.request({'operation':'add_card', 'origin':'https://merchant.test'}))
        self.assertEqual(issued['status'], 'pending')
        token = issued['url'].rsplit('/', 1)[1]
        url = 'http://127.0.0.1:' + str(self.service.server.port) + '/r/' + token
        with urllib.request.urlopen(url) as response:
            html = response.read().decode()
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn('CVC is encrypted and saved', html)
        self.assertIn('https://merchant.test', html)
        csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
        fields = {'csrf':csrf, 'action':'submit', 'card_number':'4242424242424242',
            'cardholder_name':'SYNTHETIC CARDHOLDER', 'exp_month':'12', 'exp_year':'2035',
            'cvc':'987', 'billing_postal_code':'10001'}
        with urllib.request.urlopen(url, data=urllib.parse.urlencode(fields).encode()) as response:
            saved_html = response.read().decode()
        status = json.loads(self.service.status({'request_id':issued['request_id']}))
        self.assertEqual(status['status'], 'saved')
        for secret in ('4242424242424242', '987', 'SYNTHETIC CARDHOLDER'):
            self.assertNotIn(secret, saved_html + json.dumps(status))
            if len(secret) >= 8:  # short CVC strings can occur by chance in Fernet base64
                self.assertNotIn(secret.encode(), (Path(self.tmp.name) / 'vault.json.enc').read_bytes())
        # Preview GET and duplicate POST never create another record.
        with urllib.request.urlopen(url, data=urllib.parse.urlencode(fields).encode()):
            pass
        self.assertEqual(len(self.store.list_items()), 1)
        return status['handle']

    def test_saved_native_card_dynamic_disabled_billing_through_registered_facility(self):
        self.test_saved_native_card_fills_retained_iframe_with_genuine_native_consent_then_cleanup(dynamic_billing=True)

    def test_saved_native_card_fills_retained_iframe_with_genuine_native_consent_then_cleanup(self, dynamic_billing=False):
        from test_payment_browser import PaymentBrowserTests
        from tools import approval
        handle = self.save_card()
        fixture = PaymentBrowserTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.page.frames[1].evaluate("""() => {
            const f=document.querySelector('form');
            for (const a of ['cc-name','billing postal-code']) {
                const i=document.createElement('input'); i.autocomplete=a; f.append(i);
            }
        }""")
        if dynamic_billing:
            fixture.page.frames[1].evaluate('''()=>{
                const zip=document.querySelector('[autocomplete="billing postal-code"]');
                zip.disabled=true;zip.required=true;
                document.querySelector('form').insertAdjacentHTML('afterbegin','<button type="submit" hidden>Pay</button>');
                document.querySelector('[autocomplete="cc-csc"]').onchange=()=>zip.disabled=false;
            }''')
        prompts = []
        def notify(data):
            prompts.append(data)
            approval.resolve_gateway_approval('synthetic-key', 'once', request_id=data['request_id'])
        approval.register_gateway_notify('synthetic-key', notify)
        self.addCleanup(approval.unregister_gateway_notify, 'synthetic-key')
        self.assertTrue(hasattr(self.service, 'card_fill'), 'missing retained native vault-card fill')
        from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager
        ctx = PluginContext(PluginManifest(name='synthetic-card-integration'), get_plugin_manager())
        registration = ctx.register_tool(name='secure_entry_card_fill', toolset='secure_entry',
            schema={'name':'secure_entry_card_fill', 'parameters':{'type':'object'}},
            handler=self.service.card_fill)
        self.assertIsNotNone(registration)
        self.addCleanup(registration.dispose)
        # Actual native registered dispatch, no secret args or fake browser writer.
        result = json.loads(ctx.dispatch_tool('secure_entry_card_fill', {'handle':handle, 'parent':fixture.parent,
            'frame':fixture.frame, 'merchant_origin':'https://merchant.test',
            'frame_origin':'https://provider.test'}, task_id='synthetic-payment'))
        self.assertTrue(result['success'], result)
        self.assertEqual(result['filled_fields'], 6)
        self.assertEqual(len(prompts), 1)
        self.assertIn('https://merchant.test', str(prompts))
        self.assertIn('https://provider.test', str(prompts))
        self.assertNotIn('4242424242424242', json.dumps(result) + str(prompts))
        self.assertEqual(fixture.page.frames[1].locator('[autocomplete=cc-number]').input_value(), '4242424242424242')
        self.assertEqual(fixture.page.frames[1].locator('[autocomplete=cc-csc]').input_value(), '987')
        self.assertEqual(fixture.page.frames[1].locator('[autocomplete=cc-name]').input_value(), 'SYNTHETIC CARDHOLDER')
        self.assertEqual(fixture.page.frames[1].locator('[autocomplete="billing postal-code"]').input_value(), '10001')
        self.assertIsNotNone(self.store.get_meta(handle), 'fill must not auto-delete before checkout verification')
        deleted = json.loads(self.service.remove_card({'handle':handle, 'merchant_origin':'https://merchant.test'}))
        self.assertEqual(deleted['status'], 'deleted')
        self.assertIsNone(self.store.get_meta(handle))

    def test_saved_card_preserves_prefilled_billing_absent_from_native_contract(self):
        from test_payment_browser import PaymentBrowserTests
        from tools import approval
        handle = self.save_card()
        fixture = PaymentBrowserTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        frame = fixture.page.frames[1]
        frame.evaluate('''() => {document.body.innerHTML=`<div>
          <input autocomplete="cc-number" required>
          <input autocomplete="cc-exp" required placeholder="MM/YY">
          <input autocomplete="cc-name" value="SYNTHETIC CARDHOLDER" required>
          <select autocomplete="billing country" required><option value="USA">United States</option></select>
          <input autocomplete="billing address-line1" value="1 Test St" required>
          <input autocomplete="billing address-line2">
          <input autocomplete="billing address-level2" value="Test City" required>
          <select autocomplete="billing address-level1" required><option value="NewYork">New York</option></select>
          <input autocomplete="billing postal-code" value="10001" required>
          <input autocomplete="billing tel" value="2125550100" required></div>`;}''')
        before = frame.locator('input,select').evaluate_all('(es)=>es.map(e=>e.value)')
        prompts = []
        def notify(data):
            prompts.append(data)
            approval.resolve_gateway_approval('synthetic-key', 'once', request_id=data['request_id'])
        approval.register_gateway_notify('synthetic-key', notify)
        self.addCleanup(approval.unregister_gateway_notify, 'synthetic-key')
        result = json.loads(self.service.card_fill({'handle':handle, 'parent':fixture.parent,
            'frame':fixture.frame, 'merchant_origin':'https://merchant.test',
            'frame_origin':'https://provider.test'}, task_id='synthetic-payment'))
        self.assertTrue(result['success'], result)
        self.assertEqual(result['filled_fields'], 2)
        from agent.redact import redact_registered_vault_values
        self.assertEqual(redact_registered_vault_values('True'), 'True', 'policy metadata is not a secret')
        self.assertEqual(len(prompts), 1)
        after = frame.locator('input,select').evaluate_all('(es)=>es.map(e=>e.value)')
        self.assertEqual(after[2:], before[2:])
        self.assertEqual(after[:2], ['4242424242424242', '12/35'])
        self.assertTrue(frame.locator('input,select').evaluate_all('(es)=>es.every(e=>e.checkValidity())'))
        self.assertIsNotNone(self.store.get_meta(handle))

    def test_core_native_fill_cannot_reach_cross_origin_widget(self):
        from test_payment_browser import PaymentBrowserTests
        from tools import approval, browser_vault_tool
        from types import SimpleNamespace
        from unittest.mock import patch
        handle = self.save_card()
        fixture = PaymentBrowserTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.page.evaluate('''() => {
          for(const name of ['cardnumber','depDate']) {
            const e=document.createElement('input');e.type='hidden';e.name=name;document.body.append(e);
          }
        }''')
        prompts = []
        def notify(data):
            prompts.append(data)
            approval.resolve_gateway_approval('synthetic-key', 'once', request_id=data['request_id'])
        approval.register_gateway_notify('synthetic-key', notify)
        self.addCleanup(approval.unregister_gateway_notify, 'synthetic-key')
        # Replace backend discovery only, never native consent, inspection,
        # supervisor evaluation, tab selection, or classifier/fill planning.
        backend = SimpleNamespace(needs_unlock=False, get_meta=self.store.get_meta,
            resolve_secret=self.store.resolve_secret, name='synthetic-native')
        with patch('agent.vault_backends.backend_for_handle', return_value=backend), \
             patch.object(backend, 'resolve_secret', side_effect=AssertionError('must not resolve')):
            result = json.loads(browser_vault_tool.browser_vault_fill(handle, task_id='synthetic-payment'))
        self.assertEqual(len(prompts), 1)
        self.assertFalse(result['success'], result)
        self.assertEqual(result['error'], 'No payment form fields were found on the current page.')
        self.assertEqual(fixture.page.frames[1].locator('[autocomplete=cc-number]').input_value(), '')

    def test_saved_card_refusal_fences_keep_secret_unresolved_and_browser_empty(self):
        from test_payment_browser import PaymentBrowserTests
        from tools import approval
        from unittest.mock import patch
        handle = self.save_card()
        fixture = PaymentBrowserTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        args = {'handle':handle, 'parent':fixture.parent, 'frame':fixture.frame,
                'merchant_origin':'https://merchant.test', 'frame_origin':'https://provider.test'}
        decision = ['deny']
        prompts = []
        def notify(data):
            prompts.append(data)
            if decision[0] == 'reset':
                self.service.reset(old_session_id='synthetic-session')
            approval.resolve_gateway_approval('synthetic-key', 'once' if decision[0] == 'reset' else 'deny',
                request_id=data['request_id'])
        approval.register_gateway_notify('synthetic-key', notify)
        self.addCleanup(approval.unregister_gateway_notify, 'synthetic-key')
        with patch.object(self.store, 'resolve_secret', side_effect=AssertionError('must not resolve')):
            for overrides, task in [({}, 'synthetic-payment'),
                    ({'merchant_origin':'https://other.test'}, 'synthetic-payment'),
                    ({'frame_origin':'https://other.test'}, 'synthetic-payment'),
                    ({'handle':'invalid'}, 'synthetic-payment'), ({}, 'missing-synthetic-task')]:
                result = json.loads(self.service.card_fill({**args, **overrides}, task_id=task))
                self.assertFalse(result['success'], result)
                self.assertEqual(fixture.page.frames[1].locator('[autocomplete=cc-number]').input_value(), '')
            self.assertEqual(len(prompts), 1, 'wrong origin/handle/capture must refuse before consent')
            decision[0] = 'reset'
            result = json.loads(self.service.card_fill(args, task_id='synthetic-payment'))
            self.assertEqual(result['status'], 'refused')
            self.assertEqual(result['stage'], 'postconsent_current')
        self.assertIsNotNone(self.store.get_meta(handle))

    def test_card_form_csrf_reset_and_invalid_input_never_save(self):
        issued = json.loads(self.service.request({'operation':'add_card', 'origin':'https://merchant.test'}))
        request = self.service.broker.requests[issued['url'].rsplit('/', 1)[1]]
        fields = {'csrf':'wrong', 'action':'submit', 'card_number':'4242424242424242',
            'cardholder_name':'SYNTHETIC', 'exp_month':'12', 'exp_year':'2035', 'cvc':'987',
            'billing_postal_code':'10001'}
        self.assertEqual(self.service.broker.submit(request.token, fields)['status'], 'csrf_rejected')
        self.assertEqual(self.store.list_items(), [])
        self.service.reset(old_session_id='synthetic-session')
        fields['csrf'] = request.csrf
        self.assertEqual(self.service.broker.submit(request.token, fields)['status'], 'cancelled')
        self.assertEqual(self.store.list_items(), [])
        issued = json.loads(self.service.request({'operation':'add_card', 'origin':'https://merchant.test'}))
        request = self.service.broker.requests[issued['url'].rsplit('/', 1)[1]]
        fields.update(csrf=request.csrf, exp_month='13')
        self.assertEqual(self.service.broker.submit(request.token, fields)['status'], 'invalid_input')
        self.assertEqual(self.store.list_items(), [])

    def test_cleanup_unknown_after_native_commit_does_not_claim_deleted(self):
        from unittest.mock import patch
        handle = self.save_card()
        remove = self.store.remove_item
        def uncertain(value):
            remove(value)
            raise RuntimeError('synthetic secret-bearing failure')
        with patch.object(self.store, 'remove_item', side_effect=uncertain):
            result = json.loads(self.service.remove_card({'handle':handle, 'merchant_origin':'https://merchant.test'}))
        self.assertEqual(result, {'status':'deletion_unknown'})
        self.assertIsNone(self.store.get_meta(handle))
        self.assertEqual(json.loads(self.service.remove_card({'handle':handle,
            'merchant_origin':'https://merchant.test'}))['status'], 'absent')

    def test_cleanup_rejects_nonpayment_and_unbound_sessions(self):
        handle = self.store.add_item('login', 'synthetic', {'identifier':'synthetic',
            'identifier_type':'username', 'password':'SYNTHETIC PASSWORD'}, origin='https://merchant.test').id
        self.assertEqual(json.loads(self.service.remove_card({'handle':handle,
            'merchant_origin':'https://merchant.test'}))['status'], 'refused')
        self.assertIsNotNone(self.store.get_meta(handle))
        tokens = set_session_vars(platform='photon', chat_type='group', chat_id='synthetic-group')
        try:
            result = json.loads(self.service.request({'operation':'add_card', 'origin':'https://merchant.test'}))
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(json.loads(self.service.remove_card({'handle':handle,
                'merchant_origin':'https://merchant.test'}))['status'], 'refused')
        finally:
            clear_session_vars(tokens)

    def test_cleanup_rejects_malformed_handle_without_echo(self):
        result = json.loads(self.service.remove_card({'handle':'not-a-vault-handle',
            'merchant_origin':'https://merchant.test'}))
        self.assertEqual(result['status'], 'refused')
        self.assertNotIn('not-a-vault-handle', json.dumps(result))

    def test_explicit_cleanup_verifies_absence_and_refuses_wrong_origin(self):
        handle = self.save_card()
        self.assertTrue(callable(getattr(self.service, 'remove_card', None)), 'missing metadata-only cleanup tool')
        refused = json.loads(self.service.remove_card({'handle':handle, 'merchant_origin':'https://other.test'}))
        self.assertEqual(refused['status'], 'refused')
        self.assertIsNotNone(self.store.get_meta(handle))
        result = json.loads(self.service.remove_card({'handle':handle, 'merchant_origin':'https://merchant.test'}))
        self.assertEqual(result['status'], 'deleted')
        self.assertEqual(result['handle'], handle)
        self.assertIsNone(VaultStore(Path(self.tmp.name)).get_meta(handle))
        self.assertEqual(self.store.list_items(), [])
        self.assertEqual(json.loads(self.service.remove_card({'handle':handle,
            'merchant_origin':'https://merchant.test'}))['status'], 'absent')

    def test_private_http_add_encrypts_native_payment_and_lists_metadata_only(self):
        handle = self.save_card()
        meta = self.store.get_meta(handle)
        self.assertEqual(meta.kind, 'payment')
        self.assertEqual(meta.origin, 'https://merchant.test')
        self.assertNotIn('4242424242424242', json.dumps(meta.to_dict()))
        # Native supported contract persists CVC; never imitate a missing CVC.
        self.assertEqual(self.store.resolve_secret(handle)['cvc'], '987')
        self.assertEqual(VaultStore(Path(self.tmp.name)).get_meta(handle), meta)


if __name__ == '__main__':
    unittest.main()
