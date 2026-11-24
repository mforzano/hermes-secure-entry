"""Nickname changes are private, metadata-only, and scoped to a native card."""
import json
import re
import tempfile
import unittest
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from urllib.error import HTTPError
from unittest.mock import patch

from hermes_constants import get_hermes_home
from secure_entry.service import Service
import test_reusable_cards


class NicknameTests(unittest.TestCase):
    save_reusable = test_reusable_cards.ReusableTests.save_reusable

    def setUp(self):
        test_reusable_cards.ReusableTests.setUp(self)
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.service.nickname_home = Path(state.name)

    def open_form(self, operation, **args):
        issued = json.loads(self.service.request(dict(args, operation=operation)))
        self.assertEqual(issued['status'], 'pending', issued)
        token = issued['url'].rsplit('/', 1)[1]
        url = f'http://127.0.0.1:{self.service.server.port}/r/{token}'
        with urllib.request.urlopen(url) as response:
            page = response.read().decode()
        csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        return issued, url, dict(csrf=csrf, action='submit'), page

    def post(self, url, fields):
        with urllib.request.urlopen(url, urllib.parse.urlencode(fields).encode()) as response:
            return response.read().decode()

    def status(self, issued):
        return json.loads(self.service.status({'request_id':issued['request_id']}))

    def test_optional_nickname_at_save_via_real_http(self):
        issued, url, fields, page = self.open_form('add_reusable_card')
        self.assertIn('Card nickname (optional)', page)
        self.post(url, dict(fields, **test_reusable_cards.FIELDS, reusable_consent='yes', nickname='Daily Card'))
        saved = self.status(issued)
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(json.loads(self.service.list_cards({}))['cards'], [
            {'handle':saved['handle'], 'scope':'reusable', 'origin':None, 'nickname':'Daily Card'}])

        issued, url, fields, _ = self.open_form('add_reusable_card')
        self.post(url, dict(fields, **test_reusable_cards.FIELDS, reusable_consent='yes', nickname='daily CARD'))
        self.assertEqual(self.status(issued), {'status':'nickname_taken'})
        self.assertEqual(len(self.store.list_items()), 1)

    def test_private_form_does_not_echo_invalid_input(self):
        handle = self.save_reusable()
        issued, url, fields, _ = self.open_form('rename_reusable_card', handle=handle)
        for text in ('4242 4242 4242 4242', '987', '12/35', 'Approved\nMerchant example',
                     '<script>Call</script>', 'Home\u202e Card', '"Approved"', 'Approve Once; Origin'):
            with self.subTest(text=text):
                with self.assertRaises(HTTPError) as error:
                    self.post(url, dict(fields, nickname=text))
                with error.exception as response:
                    self.assertEqual(response.code, 403)
                    self.assertNotIn(text, response.read().decode())
                self.assertEqual(self.status(issued), {'status':'pending'})
        self.assertEqual(json.loads(self.service.list_cards({}))['cards'][0]['nickname'], None)

    def test_stale_form_cannot_overwrite_new_nickname_or_rename_deleted_card(self):
        handle = self.save_reusable()
        first = self.open_form('rename_reusable_card', handle=handle)
        second = self.open_form('rename_reusable_card', handle=handle)
        self.post(first[1], dict(first[2], nickname='First'))
        self.post(second[1], dict(second[2], nickname='Second'))
        self.assertEqual(self.status(second[0]), {'status':'nickname_changed'})
        issued, url, fields, page = self.open_form('rename_reusable_card', handle=handle)
        self.assertIn('First', page)
        self.assertEqual(json.loads(self.service.remove_card({'handle':handle}))['status'], 'deleted')
        self.post(url, dict(fields, nickname='Third'))
        self.assertEqual(self.status(issued), {'status':'card_unavailable'})
        self.assertEqual(json.loads(self.service.list_cards({}))['cards'], [])
        from secure_entry.card_nicknames import CardNicknames
        self.assertEqual(CardNicknames(self.service.nickname_home).snapshot(), {})

    def test_rename_refuses_other_kinds_and_keeps_list_read_only(self):
        from secure_entry.card_nicknames import CardNicknames
        from secure_entry.native import add_card
        bound = add_card(self.store, 'https://merchant.test', test_reusable_cards.FIELDS)['handle']
        legacy = self.store.add_item('payment', 'Legacy', test_reusable_cards.FIELDS).id
        for handle in (bound, legacy, 'vault_000000000000'):
            self.assertEqual(json.loads(self.service.request({'operation':'rename_reusable_card',
                'handle':handle}))['status'], 'unavailable')
        self.assertIsNone(self.service.server)
        self.assertEqual(json.loads(self.service.list_cards({}))['status'], 'available')
        self.assertFalse(CardNicknames(self.service.nickname_home).path.exists())

    def test_two_concurrent_writers_cannot_assign_duplicate_nicknames(self):
        from secure_entry.card_nicknames import CardNicknames
        from secure_entry.native import add_card
        first = self.save_reusable()
        second = add_card(self.store, None, test_reusable_cards.FIELDS, reusable=True)['handle']
        start = Barrier(2)

        def rename(handle, name):
            start.wait(timeout=5)
            return CardNicknames(self.service.nickname_home).rename(self.store, handle, None, name)

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(rename, first, 'Travel Card')
            b = pool.submit(rename, second, 'TRAVEL CARD')
            self.assertCountEqual([a.result(), b.result()], ['renamed', 'nickname_taken'])
        labels = [card['nickname'] for card in json.loads(self.service.list_cards({}))['cards']]
        self.assertCountEqual([name.lower() if name else None for name in labels], ['travel card', None])

    def test_label_existing_card_without_reentering_or_rewriting_vault(self):
        handle = self.save_reusable()
        before = self.store._vault_path.read_bytes()
        with patch.object(self.store, 'resolve_secret', side_effect=AssertionError('metadata only')):
            issued, url, fields, page = self.open_form('rename_reusable_card', handle=handle)
            self.assertNotIn(handle, page)
            self.assertNotIn('name="card_number"', page)
            self.assertIn('name="nickname"', page)
            self.post(url, dict(fields, nickname='Travel Card'))
            self.assertEqual(json.loads(self.service.status({'request_id':issued['request_id']}))['status'], 'renamed')
            fresh = Service('https://example.ts.net:9443', str(get_hermes_home()), store_factory=lambda: self.store)
            fresh.nickname_home = self.service.nickname_home
            self.addCleanup(fresh.close)
            self.assertEqual(json.loads(fresh.list_cards({}))['cards'], [
                {'handle':handle, 'scope':'reusable', 'origin':None, 'nickname':'Travel Card'}])
        self.assertEqual(self.store._vault_path.read_bytes(), before)
        self.assertEqual(self.store.get_meta(handle).label, 'Hermes reusable payment v1')
