import unittest
from unittest.mock import Mock

from automation import UPSTREAM, plan, publication_blocker, publish
from test_policy import BASE

BASE_SHA = 'a' * 40


def releases(endpoint, **kwargs):
    tag = endpoint.rsplit('/', 1)[-1]
    if tag == 'latest':
        tag = 'v0.23.3'
    if '/releases/' in endpoint:
        return {'tag_name': tag, 'draft': False, 'prerelease': False}
    if '/git/ref/tags/' in endpoint:
        return {'object': {'type': 'commit', 'sha': {'v0.23.2': 'b', 'v0.23.3': 'c'}[tag] * 40}}
    raise AssertionError(endpoint)


class AutomationTests(unittest.TestCase):
    def test_plan_resolves_exact_official_commits(self):
        approved, payload = plan(releases, BASE_SHA, BASE)
        self.assertEqual(approved['hosts'], [dict(tag='v0.23.2', sha='b' * 40), dict(tag='v0.23.3', sha='c' * 40)])
        self.assertNotEqual(payload, BASE)

    def test_already_supported_skips_tag_resolution(self):
        api = Mock(return_value=dict(tag_name='v0.23.2', draft=False, prerelease=False))
        self.assertIsNone(plan(api, BASE_SHA, BASE))
        api.assert_called_once_with(f'{UPSTREAM}/releases/latest')

    def test_open_bot_pr_or_closed_exact_candidate_blocks_duplicate(self):
        branch = 'automation/hermes-stable-v0.23.3'
        old = 'automation/hermes-stable-v0.23.2'
        self.assertIsNotNone(publication_blocker(branch, {old}, set(), set()))
        self.assertIsNotNone(publication_blocker(branch, set(), {branch}, set()))
        self.assertIsNone(publication_blocker(branch, set(), {old}, set()))

    def test_orphan_branch_is_not_overwritten(self):
        branch = 'automation/hermes-stable-v0.23.3'
        with self.assertRaises(ValueError):
            publication_blocker(branch, set(), set(), {branch})

    def test_unverified_or_stale_plan_performs_no_writes(self):
        api = Mock(side_effect=releases)
        approved, _ = plan(api, BASE_SHA, BASE)
        api.reset_mock()
        for evidence, result in ((approved, 'skipped'), ({**approved, 'base': 'f' * 40}, 'success')):
            with self.subTest(result=result), self.assertRaises(ValueError):
                publish(api, BASE_SHA, BASE, evidence, result, 'https://github.com/mforzano/hermes-secure-entry/actions/runs/1')
        self.assertTrue(all(not call.kwargs for call in api.mock_calls))

    def test_bad_tag_object_is_not_verification_evidence(self):
        def api(endpoint):
            if '/git/ref/' in endpoint:
                return {'object': {'type': 'tree', 'sha': 'b' * 40}}
            return releases(endpoint)
        with self.assertRaises(ValueError):
            plan(api, BASE_SHA, BASE)
