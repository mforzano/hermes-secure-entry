"""In-process native prompt bridge. No browser injector or approval overrides."""
import json
import threading
from .native import MissingSessionID, MissingSessionBinding, owner
from .server import Server


class Bridge:
    def __init__(self, service, dispatch, isolation):
        self.service, self.dispatch, self.isolation = service, dispatch, isolation
        self.timeout = 180

    def bound_owner(self, context):
        # Shared owner admission also fences metadata tools and add-login.
        bound = owner(self.service.home)
        if not context.get('session_id') or context['session_id'] != bound[-1]:
            raise ValueError('session correlation mismatch')
        if self.isolation != 'in_process':
            raise ValueError('in-process callbacks required')
        return bound

    def middleware(self, *, tool_name, args, next_call, **context):
        if tool_name not in ('browser_vault_enter_code', 'browser_vault_unlock', 'browser_vault_list'):
            return next_call(args)
        # Return a refusal, never raise into middleware's skip-and-continue path.
        try:
            from tools.interrupt import is_interrupted
            if is_interrupted():
                raise ValueError('interrupted')
            with self.service.lock:
                if self.service.closed:
                    return json.dumps({'success': False, 'status': 'unavailable', 'error_type': 'service_unloaded'})
                generation = self.service.generation
            bound = self.bound_owner(context)
            with self.service.lock:
                if self.service.closed or generation != self.service.generation:
                    raise ValueError('invalidated admission')
            if tool_name == 'browser_vault_enter_code' and args.get('handle'):
                return json.dumps({'success': False, 'status': 'unsupported_handle_binding'})
        except MissingSessionID:
            return json.dumps({'success': False, 'status': 'unavailable', 'error_type': 'missing_session_id'})
        except MissingSessionBinding:
            return json.dumps({'success': False, 'status': 'unavailable', 'error_type': 'missing_session_binding'})
        except Exception:
            return json.dumps({'success': False, 'status': 'unavailable', 'error_type': 'admission_unavailable'})
        from agent.vault_backends import unlock
        old_code = unlock.get_code_prompt_callback()
        old_unlock = unlock.get_unlock_prompt_callback()
        requests = []
        diagnostics = []  # Fixed local categories only; never exception or input text.
        active = threading.Event()
        active.set()
        deadline = self.service.broker.clock() + self.timeout
        def prompt(site, hint):
            return self.prompt('code', site, bound, generation, requests, active, deadline, diagnostics)
        def unlock_prompt(backend, display):
            return self.prompt('unlock', display or backend, bound, generation, requests, active, deadline, diagnostics)
        try:
            unlock.set_code_prompt_callback(prompt)
            unlock.set_unlock_prompt_callback(unlock_prompt)
            result = None
            try:
                raw = next_call(args)
                if tool_name == 'browser_vault_list':
                    return raw  # native metadata only; list does not collect input
                result = json.loads(raw) if isinstance(raw, str) else raw
                success = isinstance(result, dict) and result.get('success') is True
                status = ('filled' if tool_name == 'browser_vault_enter_code' else 'unlocked') if success else 'refused'
            except Exception:
                success, status = False, 'commit_unknown'
            with self.service.broker.lock:
                if not success and any(r.status == 'commit_unknown' for r in requests):
                    status = 'commit_unknown'
                elif not success and requests and requests[-1].status in ('cancelled', 'expired'):
                    status = requests[-1].status
            for request in requests:
                with self.service.broker.lock:
                    if request.status == 'commit_unknown':
                        final = 'unlocked' if request.kind == 'unlock' and success else status
                        self.service.broker.finish(request.token, final)
            # Never relay native exception/error strings: a browser boundary may
            # return input in its diagnostics. Authentication is not established.
            output = {'success': success, 'status': status, 'authenticated': False}
            if isinstance(result, dict) and result.get('error_type') in (
                    'no_code_field', 'code_declined', 'prompt_unavailable', 'origin_changed',
                    'human_has_control', 'supervisor_required', 'unlock_unavailable',
                    'unlock_cancelled', 'unlock_failed'):
                output['error_type'] = result['error_type']
            if diagnostics and not success and status != 'commit_unknown':
                output['error_type'] = diagnostics[-1]
            return json.dumps(output)
        finally:
            with self.service.lock:
                active.clear()
            unlock.set_code_prompt_callback(old_code)
            unlock.set_unlock_prompt_callback(old_unlock)
            for request in requests:
                with self.service.broker.lock:
                    if request.status in ('pending', 'received'):
                        self.service.broker.finish(request.token, 'cancelled')

    def prompt(self, kind, site, bound, generation, requests, active, deadline, diagnostics, *, current=None):
        from tools.interrupt import is_interrupted
        service, broker = self.service, self.service.broker
        box = []
        def receive(fields):
            from agent.redact import register_vault_redaction_value
            value = fields['password' if kind == 'unlock' else 'code']
            register_vault_redaction_value(value)
            box.append(value)
            return {'status': 'received'}
        try:
            with service.lock:
                if (is_interrupted() or not active.is_set() or broker.clock() >= deadline or service.closed
                        or generation != service.generation
                        or self.bound_owner({'session_id': bound[-1]}) != bound):
                    return None
                if current is not None:
                    current()
                if service.server is None:
                    try:
                        service.server = Server(broker, port=service.port).__enter__()
                    except OSError:
                        diagnostics.append('listener_binding_failed')
                        return None
                request = broker.issue(kind, site, bound, receive)
                request.deadline = min(request.deadline, deadline)
                requests.append(request)
                # Index lifecycle ownership and allow the existing metadata tools.
                import secrets
                service.ids = {rid: item for rid, item in service.ids.items() if item[0] in broker.requests}
                service.ids[secrets.token_hex(16)] = (request.token, bound)
            sent = self.dispatch('send_message', {'action': 'send', 'target': bound[1] + ':' + bound[3],
                'message': 'Private native ' + kind + ' entry (expires in 180 seconds): ' + broker.url(request)})
            sent = json.loads(sent) if isinstance(sent, str) else sent
            if not isinstance(sent, dict) or sent.get('success') is not True:
                broker.finish(request.token, 'cancelled')
                return None
            while True:
                with service.lock, broker.lock:
                    if current is not None:
                        current()
                    if is_interrupted() or not active.is_set() or service.closed or generation != service.generation:
                        if request.status in ('pending', 'received'):
                            broker.finish(request.token, 'cancelled')
                    state = broker.status(request.token)['status']
                    if state == 'received':
                        # Cancellation after handoff cannot promise no native write.
                        broker.finish(request.token, 'commit_unknown')
                        return box.pop() if box else None
                    if state != 'pending':
                        return None
                request.event.wait(0.1)
        except Exception:
            if 'request' in locals():
                with broker.lock:
                    if request.status in ('pending', 'received'):
                        broker.finish(request.token, 'cancelled')
            return None
        finally:
            box.clear()
