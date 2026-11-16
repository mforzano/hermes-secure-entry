import importlib.util
import unittest
from pathlib import Path


class RegistrationTests(unittest.TestCase):
    def test_registered_handlers_refuse_omitted_mapping(self):
        import json
        from secure_entry.service import Service
        from hermes_constants import get_hermes_home
        service=Service('https://example.invalid',str(get_hermes_home()),port=0)
        self.addCleanup(service.close)
        for method in ('selected_card_fill','selected_payment_fill'):
            self.assertTrue(callable(getattr(service,method,None)), 'public mapped handler missing')
            result=json.loads(getattr(service,method)({}))
            self.assertEqual(result.get('refusal'),'field_mapping_required')

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
            'secure_entry_payment_fill', 'secure_entry_card_fill', 'secure_entry_card_remove', 'secure_entry_card_list',
            'secure_entry_signup_fill'})
        signup = ctx.tools['secure_entry_signup_fill']['schema']['parameters']
        self.assertEqual(set(signup['required']), {'handle','origin','identifier','parent','frame','frame_origin','password_nodes'})
        self.assertFalse(signup['additionalProperties'])
        self.assertEqual(signup['properties']['password_nodes']['items']['type'], 'integer')
        request_params = ctx.tools['secure_entry_request']['schema']['parameters']
        self.assertIn('add_reusable_card', request_params['properties']['operation']['enum'])
        self.assertNotIn('origin', request_params['required'])
        self.assertEqual(ctx.tools['secure_entry_card_remove']['schema']['parameters']['required'], ['handle'])
        self.assertIn('add_card', ctx.tools['secure_entry_request']['schema']['parameters']['properties']['operation']['enum'])
        for name in ('secure_entry_payment_fill','secure_entry_card_fill'):
            parameters=ctx.tools[name]['schema']['parameters']
            self.assertIn('field_mapping',parameters['required'])
            self.assertEqual(parameters['properties']['field_mapping']['properties']['cc-number']['type'],'integer')
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
