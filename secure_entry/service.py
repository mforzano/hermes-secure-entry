"""Native vault ADD service and scoped native code/unlock prompt middleware."""
import json
import secrets
import threading
from contextvars import ContextVar
from .broker import Broker
from .server import Server
from .native import MissingSessionID, MissingSessionBinding, add_login, add_card, owner, validate_origin

BLOCKERS = {
    'update_login': 'Native VaultStore exposes add/remove, but no public atomic same-record update API. Existing records are not deleted.',
    'sign_in_once': 'Native save-login prompt always persists before fill; no supported transient native password-entry API exists.',
    'save_and_sign_in': 'Native save-login callback has origin/label only and fill can reselect a same-origin tab. No exact target/frame/generation binding contract.',
}


class Service:
    def __init__(self, public_base_url, home, port=8769, store_factory=None):
        self.broker = Broker(public_base_url)
        self.home, self.port, self.store_factory = home, port, store_factory
        self.server = None
        self.ids = {}
        self.lock = threading.RLock()
        self.generation = 0
        self.closed = False
        self.otp_turn = ContextVar('secure_entry_otp_turn', default='')
        self.otp_attempts = set()

    def claim_otp_prompt(self, bound, generation, scope):
        """Spend the shared attempt at consent or native prompt handoff, not inspection."""
        key = (bound, *scope)
        with self.lock:
            if self.closed or generation != self.generation:
                raise ValueError('operation_invalidated')
            if key in self.otp_attempts:
                return False
            self.otp_attempts.add(key)
            return True

    def configure_bridge(self, dispatch, isolation):
        from .bridge import Bridge
        self.bridge = Bridge(self, dispatch, isolation)

    def selected_payment_fill(self, args, **kwargs):
        if not isinstance(args, dict) or 'field_mapping' not in args:
            return json.dumps({'success':False,'status':'refused','refusal':'field_mapping_required'})
        return self.payment_fill(args, **kwargs)

    def selected_card_fill(self, args, **kwargs):
        if not isinstance(args, dict) or 'field_mapping' not in args:
            return json.dumps({'success':False,'status':'refused','refusal':'field_mapping_required'})
        return self.card_fill(args, **kwargs)

    def signup_fill(self, args, **kwargs):
        from .signup import SignupFill
        return SignupFill(self).fill(args, **kwargs)

    def otp_fill(self, args, **kwargs):
        from .otp import fill
        return fill(self, args, kwargs.get('task_id'))

    def payment_fill(self, args, **kwargs):
        return self.payment.fill(args, **kwargs)

    def card_fill(self, args, **kwargs):
        from .cards import VaultCardSource
        from .payment import LocalPayment
        return LocalPayment(self, [], card_source=VaultCardSource(self)).fill(args, **kwargs)

    def middleware(self, *, tool_name, args, next_call, **context):
        if tool_name == 'secure_entry_otp_fill':
            # Standard registry handlers don't receive turn_id on 0.23.2.
            token = self.otp_turn.set(context.get('turn_id') or '')
            try:
                return next_call(args)
            finally:
                self.otp_turn.reset(token)
        # Hermes 0.22.1 consolidates the native tools into browser_vault actions.
        # Normalize only the bridge's existing scopes; fill/save/unknown actions
        # keep their native path and never acquire our prompt callbacks.
        if tool_name == 'browser_vault' and args.get('action') in ('enter_code', 'unlock', 'list'):
            tool_name = 'browser_vault_' + args['action']
        if tool_name not in ('browser_vault_enter_code', 'browser_vault_unlock', 'browser_vault_list'):
            return next_call(args)
        if not hasattr(self, 'bridge'):
            return json.dumps({'success':False, 'status':'unavailable', 'error_type':'bridge_unavailable'})
        # Hermes skips middleware which raises before next_call. Never turn an
        # admission/compatibility failure into implicit permission to continue.
        try:
            return self.bridge.middleware(tool_name=tool_name, args=args, next_call=next_call, **context)
        except Exception:
            return json.dumps({'success':False, 'status':'unavailable', 'error_type':'bridge_unavailable'})

    def request(self, args, **kwargs):
        try:
            # Fence even owner/store acquisition, which can block before indexing.
            with self.lock:
                if self.closed:
                    return json.dumps({'status':'unavailable', 'error_type':'service_unloaded'})
                generation = self.generation
            bound = owner(self.home)
            operation = args.get('operation', 'add_login')
            if operation == 'verification_code':
                return json.dumps({'status':'native_tool_required', 'tool':'browser_vault', 'action':'enter_code',
                    'instruction':'Call the native tool without a handle. Only its inspected site can arm a private form. Never type a code in chat. Links are sent directly to this originating DM and may appear in history.'})
            if operation in BLOCKERS:
                return json.dumps({'status':'unsupported_native_contract', 'operation':operation, 'reason':BLOCKERS[operation]})
            if operation not in ('add_login', 'add_card', 'add_reusable_card'):
                return json.dumps({'status':'invalid_operation'})
            reusable = operation == 'add_reusable_card'
            if reusable and args.get('origin') not in (None, ''):
                raise ValueError('reusable_has_no_origin')
            origin = 'Reusable across websites' if reusable else validate_origin(args.get('origin', ''))
            from agent.vault_store import get_vault_store
            # Resolve the profile-scoped native object HERE, not on an unrelated HTTP thread.
            store = self.store_factory() if self.store_factory else get_vault_store()
            with self.lock:
                if self.closed or generation != self.generation:
                    return json.dumps({'status':'cancelled'})
                if self.server is None:
                    try:
                        self.server = Server(self.broker, port=self.port).__enter__()
                    except OSError:
                        return json.dumps({'status':'unavailable', 'error_type':'listener_binding_failed'})
                apply = (lambda fields: add_card(store, None, fields, reusable=True)) if reusable else (
                    lambda fields: (add_card if operation == 'add_card' else add_login)(store, origin, fields))
                kind = 'reusable_card' if reusable else 'card' if operation == 'add_card' else 'login'
                request = self.broker.issue(kind, origin, bound, apply)
                with self.broker.lock:
                    self.ids = {rid: item for rid, item in self.ids.items() if item[0] in self.broker.requests}
                request_id = secrets.token_hex(16)
                self.ids[request_id] = (request.token, bound)
            return json.dumps({'status':'pending', 'request_id':request_id, 'url':self.broker.url(request),
                               'origin':origin, 'operation':operation, 'expires_in_seconds':600,
                               'instruction':'Send this one-use link only in this originating conversation. The page saves a new native vault item; it does not sign in.'})
        except MissingSessionID:
            return json.dumps({'status':'unavailable', 'error_type':'missing_session_id'})
        except MissingSessionBinding:
            return json.dumps({'status':'unavailable', 'error_type':'missing_session_binding'})
        except Exception:
            return json.dumps({'status':'unavailable', 'error_type':'service_unavailable'})

    def status(self, args, **kwargs):
        try:
            bound = owner(self.home)
            with self.lock:
                token, expected = self.ids.get(args.get('request_id', ''), ('', None))
            return json.dumps(self.broker.status(token) if expected == bound else {'status':'unavailable'})
        except Exception:
            return json.dumps({'status':'unavailable'})

    def list_cards(self, args, **kwargs):
        """Authenticated metadata discovery; never resolve card payloads."""
        try:
            from .native import is_reusable_card
            from agent.vault_store import get_vault_store
            with self.lock:
                if self.closed:
                    raise ValueError('closed')
                generation = self.generation
            bound = owner(self.home)
            store = self.store_factory() if self.store_factory else get_vault_store()
            cards = []
            for meta in store.list_items():
                reusable = is_reusable_card(meta)
                if not reusable:
                    if meta.kind != 'payment' or not meta.origin:
                        continue
                    try:
                        validate_origin(meta.origin)
                    except Exception:
                        continue
                cards.append({'handle':meta.id, 'scope':'reusable' if reusable else 'merchant_bound',
                              'origin':meta.origin})
            with self.lock:
                if self.closed or generation != self.generation or owner(self.home) != bound:
                    raise ValueError('cancelled')
                return json.dumps({'status':'available', 'cards':cards})
        except Exception:
            return json.dumps({'status':'unavailable'})

    def remove_card(self, args, **kwargs):
        """Explicit cleanup only; read back absence before claiming deletion."""
        started = False
        handle = args.get('handle', '')
        try:
            with self.lock:
                if self.closed:
                    raise ValueError('closed')
                generation = self.generation
            bound = owner(self.home)
            from .native import is_reusable_card
            origin = args.get('merchant_origin')
            if origin is not None:
                origin = validate_origin(origin)
            import re
            if not isinstance(handle, str) or not re.fullmatch(r'vault_[0-9a-f]{12}', handle):
                raise ValueError('invalid_handle')
            from agent.vault_store import get_vault_store
            store = self.store_factory() if self.store_factory else get_vault_store()
            with self.lock:
                if self.closed or generation != self.generation or owner(self.home) != bound:
                    raise ValueError('cancelled')
                meta = store.get_meta(handle)
                if meta is None:
                    return json.dumps({'status':'absent', 'handle':handle})
                if not is_reusable_card(meta) and (meta.kind != 'payment' or not origin or meta.origin != origin):
                    return json.dumps({'status':'refused'})
                started = True
                store.remove_item(handle)
                if store.get_meta(handle) is not None:
                    raise ValueError('still_present')
                return json.dumps({'status':'deleted', 'handle':handle})
        except Exception:
            return json.dumps({'status':'deletion_unknown' if started else 'refused'})

    def cancel(self, args, **kwargs):
        try:
            bound = owner(self.home)
            with self.lock:
                token, expected = self.ids.get(args.get('request_id', ''), ('', None))
            if expected != bound:
                return json.dumps({'status':'unavailable'})
            with self.broker.lock:
                if self.broker.status(token)['status'] in ('pending', 'received'):
                    self.broker.finish(token, 'cancelled')
            return json.dumps(self.broker.status(token))
        except Exception:
            return json.dumps({'status':'unavailable'})

    def ended(self, turn_id='', completed=False, failed=False, interrupted=False, **kwargs):
        if turn_id and kwargs.get('session_id') and kwargs.get('task_id'):
            with self.lock:
                self.otp_attempts = {key for key in self.otp_attempts if
                    (key[0][-1], key[1], key[2]) != (kwargs['session_id'], kwargs['task_id'], turn_id)}
        # Hermes currently also emits on_session_end after EACH normal message.
        # These links must survive delivery of that message to the user.
        if turn_id and completed and not failed and not interrupted:
            return
        self.stopped(**kwargs)

    def reset(self, old_session_id='', session_id='', **kwargs):
        # /new reports session_id=NEW; invalidate the OLD owner, not the new one.
        self.stopped(session_id=old_session_id or session_id, **kwargs)

    def stopped(self, session_key='', session_id='', **kwargs):
        # The core emits these hooks, not model arguments or arbitrary inbound text.
        with self.lock:
            # Conservatively refuse all in-flight admissions on a lifecycle event;
            # indexed requests remain scoped to the specified owner. No tombstone leak.
            self.generation += 1
            owners = {bound for _, bound in self.ids.values()
                      if (session_key and bound[-2] == session_key) or (session_id and bound[-1] == session_id)}
            for bound in owners:
                self.broker.cancel_owner(bound)

    def close(self):
        with self.lock:
            self.closed = True
            self.otp_attempts.clear()
            self.generation += 1
            if self.server:
                self.server.close()
                self.server = None
            else:
                self.broker.close()
