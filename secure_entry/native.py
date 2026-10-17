"""Narrow native API adapter. Never resolves existing passwords or bypasses approval context."""
from pathlib import Path
from urllib.parse import urlsplit


class MissingSessionID(ValueError):
    pass


class MissingSessionBinding(ValueError):
    pass


def validate_origin(origin):
    from agent.vault_store import normalize_origin
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or normalize_origin(origin) != origin):
        raise ValueError('An exact HTTPS origin without path is required')
    return origin


def owner(expected_home):
    from hermes_constants import get_hermes_home
    from gateway.session_context import get_session_env
    from tools.approval_context import (_is_cron_approval_context, _is_single_query_approval_context,
                                        _is_unattended_platform_approval_context)
    from agent.delegation_context import is_delegated_child_context
    if (_is_cron_approval_context() or _is_single_query_approval_context()
            or _is_unattended_platform_approval_context() or is_delegated_child_context()):
        raise ValueError('Secure entry requires the originating human DM conversation')
    home = str(Path(get_hermes_home()).resolve())
    values = tuple(get_session_env('HERMES_SESSION_' + key, '') for key in
                   ('PLATFORM', 'CHAT_TYPE', 'CHAT_ID', 'USER_ID', 'KEY', 'ID'))
    if (home != str(Path(expected_home).resolve()) or values[0] not in ('photon', 'discord', 'telegram')
            or values[1] != 'dm'):
        raise ValueError('Secure entry requires a bound supported DM and matching profile')
    if not values[-1]:
        raise MissingSessionID('Missing session ID binding')
    if not all(values[2:]):
        raise MissingSessionBinding('Missing session binding')
    # Native getters retain a legacy process-env fallback. Admission requires
    # authenticated task-local values, for metadata tools as well as callbacks.
    import contextvars
    local = {var.name: value for var, value in contextvars.copy_context().items()}
    for key, value in zip(('PLATFORM', 'CHAT_TYPE', 'CHAT_ID', 'USER_ID', 'KEY', 'ID'), values):
        if local.get('HERMES_SESSION_' + key) != value:
            raise MissingSessionBinding('Missing task-local identity')
    from hermes_constants import profile_name_for_home
    if local.get('HERMES_SESSION_PROFILE', '') not in ('', profile_name_for_home(expected_home)):
        raise ValueError('Profile mismatch')
    return (home, *values)


def dispatch_message(ctx, name, args):
    """Use native delivery, including snapshots without a registered send tool.

    The native CLI also calls send_message_tool directly. Select BEFORE sending,
    never retry another route after an ambiguous delivery error.
    """
    if name != 'send_message':
        raise ValueError('only native message delivery is supported')
    from tools.registry import registry
    if registry.get_entry(name) is not None:
        return ctx.dispatch_tool(name, args)
    from tools.send_message_tool import send_message_tool
    return send_message_tool(args)


def add_login(store, origin, fields):
    from agent.redact import register_vault_redaction_value
    validate_origin(origin)
    register_vault_redaction_value(fields['password'])
    identifier = fields['identifier'].strip()
    id_type = 'email' if '@' in identifier else 'phone' if identifier.lstrip('+').isdigit() else 'username'
    # Once native add begins, exceptions do not prove that no write occurred.
    result = {'status':'commit_unknown', 'identifier':identifier}
    try:
        meta = store.add_item('login', urlsplit(origin).netloc,
                              {'identifier': identifier, 'identifier_type': id_type, 'password': fields['password']}, origin=origin)
        result['handle'] = meta.id
        # Read back only metadata. Never resolve a secret to verify a write.
        saved = store.get_meta(meta.id)
        if saved and saved.origin == origin and saved.identifier == identifier:
            result['status'] = 'saved'
    except Exception:
        pass  # No secret-bearing exception text; never advise a blind retry.
    return result


def add_card(store, origin, fields):
    """Public native payment API only; its established schema persists CVC."""
    import re
    from agent.redact import register_payment_redaction_values
    validate_origin(origin)
    if (not re.fullmatch(r'[0-9]{12,19}', fields['card_number'])
            or not re.fullmatch(r'[0-9]{3,4}', fields['cvc'])
            or not re.fullmatch(r'(0?[1-9]|1[0-2])', fields['exp_month'])
            or not re.fullmatch(r'20[0-9]{2}', fields['exp_year'])):
        return {'status': 'invalid_input'}
    # Canonical secret fields only: expiry fragments and billing are not secrets.
    register_payment_redaction_values({
        'card_number': fields['card_number'], 'cvc': fields['cvc'],
        'exp_month': fields['exp_month'], 'exp_year': fields['exp_year'],
    })
    result = {'status': 'commit_unknown'}
    try:
        meta = store.add_item('payment', urlsplit(origin).netloc, fields, origin=origin)
        result['handle'] = meta.id
        saved = store.get_meta(meta.id)
        if saved and saved.kind == 'payment' and saved.origin == origin:
            result['status'] = 'saved'
    except Exception:
        pass
    return result
