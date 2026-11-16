"""Reusable-card lifecycle and authority regressions in isolated native storage."""
import json
import re
import unittest
import urllib.parse
import urllib.request
from unittest.mock import patch
import test_reusable_cards
from secure_entry.cards import VaultCardSource
from gateway.session_context import set_session_vars, clear_session_vars


class ReusablePolicyTests(unittest.TestCase):
    setUp = test_reusable_cards.ReusableTests.setUp
    save_reusable = test_reusable_cards.ReusableTests.save_reusable

    def test_real_http_form_opt_in_encrypts_one_record(self):
        issued = json.loads(self.service.request({'operation':'add_reusable_card'}))
        token = issued['url'].rsplit('/', 1)[1]
        url = f'http://127.0.0.1:{self.service.server.port}/r/{token}'
        with urllib.request.urlopen(url) as response:
            html = response.read().decode()
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
        fields = dict(test_reusable_cards.FIELDS, csrf=csrf, action='submit', reusable_consent='yes')
        with urllib.request.urlopen(url, data=urllib.parse.urlencode(fields).encode()) as response:
            self.assertNotIn(fields['card_number'], response.read().decode())
        status = json.loads(self.service.status({'request_id':issued['request_id']}))
        self.assertEqual(status['status'], 'saved')
        meta = self.store.get_meta(status['handle'])
        self.assertIsNone(meta.origin)
        self.assertEqual(len(self.store.list_items()), 1)
        self.assertNotIn(fields['card_number'], json.dumps(status))
        self.assertNotIn(fields['card_number'].encode(), self.store._vault_path.read_bytes())

    def test_cancel_and_reset_prevent_late_reusable_save(self):
        for reset in (False, True):
            issued = json.loads(self.service.request({'operation':'add_reusable_card'}))
            request = self.service.broker.requests[issued['url'].rsplit('/', 1)[1]]
            if reset:
                self.service.reset(old_session_id='synthetic-session')
            else:
                self.assertEqual(json.loads(self.service.cancel({'request_id':issued['request_id']}))['status'], 'cancelled')
            result = self.service.broker.submit(request.token, dict(test_reusable_cards.FIELDS,
                csrf=request.csrf, action='submit', reusable_consent='yes'))
            self.assertEqual(result['status'], 'cancelled')
            self.assertEqual(self.store.list_items(), [])

    def test_legacy_originless_is_not_opt_in_and_binding_rechecked_before_load(self):
        fields = test_reusable_cards.FIELDS
        handle = self.save_reusable()
        legacy = self.store.add_item('payment', 'Legacy originless', fields).id
        source = VaultCardSource(self.service)
        with self.assertRaises(ValueError):
            source.identifier({'handle':legacy}, 'https://merchant.test')
        self.assertEqual(source.identifier({'handle':handle}, 'https://merchant.test'), handle)
        from dataclasses import replace
        meta = self.store.get_meta(handle)
        with patch.object(self.store, 'get_meta', return_value=replace(meta, label='Legacy originless')), \
             patch.object(self.store, 'resolve_secret', side_effect=AssertionError('must recheck first')):
            with self.assertRaises(ValueError):
                source.load(handle, 'https://second.test')

    def test_authenticated_discovery_and_delete_refuse_group_or_unload(self):
        handle = self.save_reusable()
        tokens = set_session_vars(platform='photon', chat_id='group', chat_type='group')
        try:
            self.assertEqual(json.loads(self.service.list_cards({}))['status'], 'unavailable')
            self.assertEqual(json.loads(self.service.remove_card({'handle':handle}))['status'], 'refused')
        finally:
            clear_session_vars(tokens)
        self.assertIsNotNone(self.store.get_meta(handle))
        self.service.close()
        self.assertEqual(json.loads(self.service.list_cards({}))['status'], 'unavailable')
        self.assertEqual(json.loads(self.service.remove_card({'handle':handle}))['status'], 'refused')

    def test_reusable_request_does_not_accept_origin_or_implicitly_convert_bound_card(self):
        result = json.loads(self.service.request({'operation':'add_reusable_card','origin':'https://merchant.test'}))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(self.store.list_items(), [])
        legacy = self.store.add_item('payment', 'Hermes reusable payment v1', test_reusable_cards.FIELDS,
                                     origin='https://merchant.test').id
        source = VaultCardSource(self.service)
        with self.assertRaises(ValueError):
            source.identifier({'handle':legacy}, 'https://second.test')
        self.assertEqual(self.store.get_meta(legacy).origin, 'https://merchant.test')
