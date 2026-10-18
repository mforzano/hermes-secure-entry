import importlib.util
import unittest
from pathlib import Path


class RegistrationTests(unittest.TestCase):
    def test_registration_uses_only_public_plugin_methods_and_no_listener(self):
        path = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('secure_entry_plugin_test', path / '__init__.py',
                                                     submodule_search_locations=[str(path)])
        plugin = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name] = plugin
        spec.loader.exec_module(plugin)
        class Context:
            def __init__(self): self.tools, self.hooks, self.cleanup, self.middleware = {}, {}, [], {}
            def get_config(self, key, default=None): return {'public_base_url':'https://example.ts.net:9443','port':8769}.get(key, default)
            def register_tool(self, **kw): self.tools[kw['name']] = kw
            def register_hook(self, name, callback): self.hooks[name] = callback
            def register_middleware(self, name, callback): self.middleware[name] = callback
            def dispatch_tool(self, *args, **kwargs): raise AssertionError('must not dispatch during registration')
            def on_unload(self, callback): self.cleanup.append(callback)
        ctx = Context()
        plugin.register(ctx)
        self.assertEqual(set(ctx.tools), {'secure_entry_request', 'secure_entry_status', 'secure_entry_cancel',
            'secure_entry_payment_fill', 'secure_entry_card_fill', 'secure_entry_card_remove'})
        self.assertIn('add_card', ctx.tools['secure_entry_request']['schema']['parameters']['properties']['operation']['enum'])
        for name in ('secure_entry_payment_fill','secure_entry_card_fill'):
            schema=ctx.tools[name]['schema']
            self.assertIn('root',schema['parameters']['properties']['frame']['description'])
            self.assertIn('top-level',schema['description'])
        self.assertIn('agent_loop_stopped', ctx.hooks)
        self.assertIn('tool_execution', ctx.middleware)
        for item in ctx.tools.values():
            properties = item['schema']['parameters']['properties']
            self.assertNotIn('password', properties)
            self.assertNotIn('code', properties)
            service = item['handler'].__self__
            self.assertIsNone(service.server)
        for cleanup in ctx.cleanup:
            cleanup()
