import unittest

from policy import proposal, stable_tag

BASE = b'name: secure-entry\nversion: 0.5.19\nrequires_hermes: "==0.23.2"\nprovides_tools: []\n'


class PolicyTests(unittest.TestCase):
    def test_adjacent_patch_changes_only_gate(self):
        manifest, versions = proposal(BASE, 'v0.23.3')
        self.assertEqual(manifest, BASE.replace(b'==0.23.2', b'>=0.23.2,<=0.23.3'))
        self.assertEqual(versions, ['0.23.2', '0.23.3'])

    def test_extension_rechecks_all_previously_admitted_patches(self):
        manifest, _ = proposal(BASE, 'v0.23.3')
        _, versions = proposal(manifest, 'v0.23.4')
        self.assertEqual(versions, ['0.23.2', '0.23.3', '0.23.4'])

    def test_already_supported_is_noop(self):
        self.assertIsNone(proposal(BASE, 'v0.23.2'))
        manifest, _ = proposal(BASE, 'v0.23.3')
        self.assertIsNone(proposal(manifest, 'v0.23.2'))

    def test_no_gaps_minor_changes_downgrades_or_prereleases(self):
        for tag in ('v0.23.4', 'v0.24.0', 'v1.23.3', 'v0.23.1', 'v0.23.3rc1', 'v0.23.03', 'unknown', 'v0.23.3\n'):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                proposal(BASE, tag)

    def test_noncanonical_or_duplicate_manifest_gate_is_refused(self):
        for data in (BASE.replace(b'==0.23.2', b'>=0.23.2'), BASE + b'requires_hermes: "==0.23.2"\n',
                     BASE.replace(b'version:', b'"requires_hermes": "==0.23.6"\nversion:'),
                     BASE.replace(b'==0.23.2', b'>=0.22.0,<=0.23.2')):
            with self.subTest(data=data), self.assertRaises(ValueError):
                proposal(data, 'v0.23.3')

    def test_matrix_budget_does_not_silently_drop_supported_hosts(self):
        with self.assertRaises(ValueError):
            proposal(BASE.replace(b'==0.23.2', b'>=0.23.2,<=0.23.9'), 'v0.23.10')

    def test_release_metadata_must_be_explicit_and_match_requested_tag(self):
        release = dict(tag_name='v0.23.3', draft=False, prerelease=False)
        self.assertEqual(stable_tag(release, 'v0.23.3'), 'v0.23.3')
        for change in (dict(draft=True), dict(prerelease=True), dict(draft=None), dict(tag_name='v0.23.4')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                stable_tag(release | change, 'v0.23.3')

    def test_crlf_and_other_manifest_bytes_are_preserved(self):
        data = BASE.replace(b'\n', b'\r\n')
        actual, _ = proposal(data, 'v0.23.3')
        self.assertEqual(actual, data.replace(b'==0.23.2', b'>=0.23.2,<=0.23.3'))
