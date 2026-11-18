"""Network-only fakes for native one-shot bot senders; never contact a service."""
from contextlib import ExitStack, contextmanager
from importlib import import_module
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch


@contextmanager
def synthetic_gateway_run(module):
    # Replace only the launcher: restoring all of sys.modules would also
    # discard real modules imported by deferred plugin discovery.
    old = sys.modules.get('gateway.run')
    sys.modules['gateway.run'] = module
    try:
        yield
    finally:
        if old is None:
            sys.modules.pop('gateway.run', None)
        else:
            sys.modules['gateway.run'] = old


@contextmanager
def synthetic_bot_network(platform, deliver):
    with ExitStack() as stack:
        if platform == 'discord':
            class Response:
                status = 200
                content = None
                async def __aenter__(self): return self
                async def __aexit__(self, *args): pass
                async def json(self): return {'id': 'synthetic-message-id', 'type': 1}
            class Session:
                def __init__(self, *args, **kwargs): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *args): pass
                def get(self, url, **kwargs): return Response()
                def post(self, url, **kwargs):
                    class Sent(Response):
                        async def __aenter__(self):
                            chat_id = url.split('/channels/', 1)[1].split('/', 1)[0]
                            await deliver(chat_id=chat_id, content=kwargs['json']['content'])
                            return self
                    return Sent()
            stack.enter_context(patch('aiohttp.ClientSession', Session))
        elif platform == 'telegram':
            from gateway.outbound.send import prepare_send_message_platforms
            from gateway.platform_registry import platform_registry

            # Let the native loader resolve the bundled Telegram plugin. Patch
            # the registered module instance (not an independently imported copy).
            stack.enter_context(patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'SYNTHETIC-BOT-TOKEN'}))
            prepare_send_message_platforms()
            sender = platform_registry.get('telegram').standalone_sender_fn
            class Bot:
                async def send_message(self, **kwargs):
                    import re
                    text = re.sub(r'\\(.)', r'\1', kwargs['text'])
                    await deliver(chat_id=str(kwargs['chat_id']), content=text)
                    return SimpleNamespace(message_id='synthetic-message-id')
            stack.enter_context(patch.object(import_module(sender.__module__), '_telegram_bot', return_value=Bot()))
        yield
