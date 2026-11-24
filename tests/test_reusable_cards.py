"""Reusable opt-in uses only disposable native vaults and synthetic card data."""
import json
from unittest.mock import patch
from test_cards import CardTests

FIELDS = dict(card_number='4242424242424242', cardholder_name='SYNTHETIC CARDHOLDER',
              exp_month='12', exp_year='2035', cvc='987', billing_postal_code='10001')


import unittest


class ReusableTests(unittest.TestCase):
    setUp = CardTests.setUp

    def test_private_opt_in_single_originless_record(self):
        self.save_reusable()


def test_private_opt_in_single_originless_record(self):
    issued = json.loads(self.service.request({'operation':'add_reusable_card'}))
    self.assertEqual(issued['status'], 'pending', issued)
    request = self.service.broker.requests[issued['url'].rsplit('/', 1)[1]]
    html = self.service.broker.page(request.token)
    self.assertIn('name="reusable_consent"', html)
    self.assertIn('until explicit deletion', html)
    self.assertIn('CVC is encrypted and saved', html)
    fields = dict(FIELDS, csrf=request.csrf, action='submit')
    self.assertEqual(self.service.broker.submit(request.token, fields)['status'], 'invalid_input')
    self.assertEqual(self.store.list_items(), [])
    result = self.service.broker.submit(request.token, dict(fields, reusable_consent='yes'))
    self.assertEqual(result['status'], 'saved')
    self.service.broker.submit(request.token, dict(fields, reusable_consent='yes'))
    self.assertEqual(len(self.store.list_items()), 1)
    meta = self.store.get_meta(result['handle'])
    self.assertIsNone(meta.origin)
    self.assertEqual(meta.kind, 'payment')
    self.assertEqual(meta.label, 'Hermes reusable payment v1')
    return result['handle']

ReusableTests.save_reusable = test_private_opt_in_single_originless_record


def test_metadata_discovery_and_explicit_deletion(self):
    handle = self.save_reusable()
    legacy = self.store.add_item('payment', 'Legacy originless', FIELDS).id
    bound = self.store.add_item('payment', 'Bound', FIELDS, origin='https://merchant.test').id
    with patch.object(self.store, 'resolve_secret', side_effect=AssertionError('metadata only')):
        result = json.loads(self.service.list_cards({}))
        cards = {c['handle']: c for c in result['cards']}
        self.assertEqual(set(cards), {handle, bound})
        self.assertEqual(cards[handle]['scope'], 'reusable')
        self.assertIsNone(cards[handle]['origin'])
        self.assertEqual(cards[bound]['scope'], 'merchant_bound')
        self.assertNotIn(FIELDS['card_number'], json.dumps(result))
        self.assertEqual(json.loads(self.service.remove_card({'handle':legacy}))['status'], 'refused')
        self.assertEqual(json.loads(self.service.remove_card({'handle':bound}))['status'], 'refused')
        self.assertEqual(json.loads(self.service.remove_card({'handle':handle}))['status'], 'deleted')
        self.assertIsNone(self.store.get_meta(handle))
        self.assertEqual(json.loads(self.service.remove_card({'handle':handle}))['status'], 'absent')

ReusableTests.test_metadata_discovery_and_explicit_deletion = test_metadata_discovery_and_explicit_deletion


def test_same_card_two_merchants_top_level_and_iframe(self):
    from test_payment_mapping import MappingTests
    from tools import approval
    from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager
    handle = self.save_reusable()
    fixture = MappingTests()
    fixture.setUp()
    self.addCleanup(fixture.doCleanups)
    prompts = []
    issued = json.loads(self.service.request({'operation':'rename_reusable_card', 'handle':handle}))
    request = self.service.broker.requests[issued['url'].rsplit('/', 1)[1]]
    self.assertEqual(self.service.broker.submit(request.token, {'csrf':request.csrf,
        'action':'submit', 'nickname':'Travel Card'})['status'], 'renamed')
    decision = ['once']
    def notify(data):
        prompts.append(data)
        approval.resolve_gateway_approval('synthetic-key', decision[0], request_id=data['request_id'])
    approval.register_gateway_notify('synthetic-key', notify)
    self.addCleanup(approval.unregister_gateway_notify, 'synthetic-key')
    ctx = PluginContext(PluginManifest(name='synthetic-reusable'), get_plugin_manager())
    reg = ctx.register_tool(name='secure_entry_card_fill', toolset='secure_entry',
        schema={'name':'secure_entry_card_fill','parameters':{'type':'object'}},
        handler=self.service.selected_card_fill)
    self.addCleanup(reg.dispose)
    def fill(merchant, provider, frame, mapping):
        return json.loads(ctx.dispatch_tool('secure_entry_card_fill', dict(handle=handle,
            parent=fixture.parent, frame=frame, merchant_origin=merchant,
            frame_origin=provider, field_mapping=mapping), task_id='synthetic-payment'))
    mapping = fixture.mapping(fixture.html())
    result = fill('https://merchant.test', 'https://provider.test', fixture.frame, mapping)
    self.assertTrue(result.get('success'), result)
    self.assertEqual(result['filled_fields'], 5)
    self.assertTrue(fixture.page.frames[1].evaluate("document.querySelector('#pan').value==='4242424242424242'"))
    # A different exact HTTPS merchant, top-level. Same native record, fresh consent.
    fixture.context.route('https://second.test/**', lambda r:r.fulfill(content_type='text/html', body=fixture.html()))
    fixture.page.goto('https://second.test/pay')
    cdp = fixture.context.new_cdp_session(fixture.page)
    root = cdp.send('Page.getFrameTree')['frameTree']['frame']['id']
    cdp.detach()
    mapping = fixture.mapping(frame=fixture.page.main_frame)
    decision[0] = 'deny'
    with patch.object(self.store, 'resolve_secret', side_effect=AssertionError('consent first')):
        result = fill('https://second.test', 'https://second.test', root, mapping)
        self.assertFalse(result.get('success'), result)
    self.assertTrue(fixture.page.evaluate("document.querySelector('#pan').value==='old pan'"))
    decision[0] = 'once'
    result = fill('https://second.test', 'https://second.test', root, mapping)
    self.assertTrue(result.get('success'), result)
    self.assertEqual(result['filled_fields'], 5)
    self.assertTrue(fixture.page.evaluate("document.querySelector('#pan').value==='4242424242424242'"))
    self.assertEqual(len(prompts), 3)
    self.assertIn('https://merchant.test', str(prompts[0]))
    self.assertEqual(prompts[0]['command'],
        'Fill saved payment on merchant https://merchant.test; payment frame https://provider.test; reusable card nickname: "Travel Card"')
    self.assertNotIn(handle, str(prompts))
    self.assertIn('https://provider.test', str(prompts[0]))
    self.assertIn('https://second.test', str(prompts[2]))
    self.assertNotIn(FIELDS['card_number'], str(prompts) + json.dumps(result))
    self.assertEqual(len(self.store.list_items()), 1)
    self.assertIsNone(self.store.get_meta(handle).origin)
    self.assertEqual(json.loads(self.service.remove_card({'handle':handle}))['status'], 'deleted')
    with patch.object(self.store, 'resolve_secret', side_effect=AssertionError('deleted')):
        self.assertFalse(fill('https://second.test', 'https://second.test', root, mapping).get('success'))
    self.assertEqual(len(prompts), 3)

ReusableTests.test_same_card_two_merchants_top_level_and_iframe = test_same_card_two_merchants_top_level_and_iframe

