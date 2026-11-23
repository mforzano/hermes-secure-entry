"""Compatibility gate plus real native registry schema (no credentials)."""
import inspect
from pathlib import Path
import unittest
import hermes_yaml as yaml
from packaging.specifiers import SpecifierSet
from agent.vault_backends import unlock
from hermes_cli.plugins_manifest import version_satisfies
from tools import browser_vault_tool  # register the actual native handler
from tools.registry import registry


class HermesCompatibilityTests(unittest.TestCase):
    def test_manifest_preserves_baseline_and_caps_the_verified_patch_series(self):
        manifest = yaml.safe_load((Path(__file__).parents[1] / 'plugin.yaml').read_text(encoding='utf-8'))
        spec = manifest['requires_hermes']
        supported = SpecifierSet(spec)
        upper, = [clause.version for clause in supported if clause.operator in ('==', '<=')]
        major, minor, patch = map(int, upper.split('.'))
        self.assertEqual((major, minor), (0, 23))
        self.assertGreaterEqual(patch, 2)
        for admitted in sorted({'0.23.2', upper}):
            with self.subTest(admitted=admitted):
                self.assertIn(admitted, supported)
                self.assertTrue(version_satisfies(spec, admitted))
        for other_release in ('0.22.5', '0.22.6', '0.23.0', '0.23.1', f'0.23.{patch + 1}', '0.24.0'):
            with self.subTest(other_release=other_release):
                self.assertNotIn(other_release, supported)
                self.assertFalse(version_satisfies(spec, other_release))

    def test_actual_registered_native_schema_retains_intercepted_actions(self):
        entry = registry.get_entry('browser_vault')
        self.assertIsNotNone(entry)
        schema = entry.schema
        if 'function' in schema:
            schema = schema['function']
        actions = schema['parameters']['properties']['action']['enum']
        for action in ('list', 'unlock', 'enter_code', 'fill', 'save_login'):
            self.assertIn(action, actions)
        for name in ('set_code_prompt_callback', 'set_unlock_prompt_callback'):
            self.assertEqual(len(inspect.signature(getattr(unlock, name)).parameters), 1)
        for name in ('get_code_prompt_callback', 'get_unlock_prompt_callback'):
            self.assertEqual(len(inspect.signature(getattr(unlock, name)).parameters), 0)
