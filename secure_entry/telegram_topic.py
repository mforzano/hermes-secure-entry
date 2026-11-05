"""Fail-closed Telegram topic admission and non-mirroring private native delivery.

Private Hermes APIs are intentionally confined here. No patching, session-context
rewriting, tool dispatch, fallback destination, or delivery retry is permitted.
"""
import re


def validate_topic(bound):
    """Correlate task-local identity with the gateway's authenticated live source."""
    if (bound.platform != 'telegram' or bound.chat_type != 'group'
            or not re.fullmatch(r'-[1-9][0-9]*', bound.chat_id)
            or not re.fullmatch(r'[1-9][0-9]*', bound.user_id)
            or bound.user_id in ('1087968824', '136817688')  # anonymous admin / channel actor
            or not re.fullmatch(r'[1-9][0-9]*', bound.thread_id)
            or not re.fullmatch(r'[1-9][0-9]*', bound.message_id)
            or not isinstance(bound.task_id, str) or not bound.task_id):
        raise ValueError('Missing interactive topic identity')
    from gateway.run import _gateway_runner_ref
    runner = _gateway_runner_ref()
    source = runner._get_cached_session_source(bound.session_key)
    if (source is None or source.is_bot or source.profile_route_rejected
            or source.platform.value != bound.platform or source.chat_type != bound.chat_type
            or source.chat_id != bound.chat_id or source.user_id != bound.user_id
            or source.thread_id != bound.thread_id or source.message_id != bound.message_id
            or (source.profile or '') != bound.profile
            or runner._session_key_for_source(source) != bound.session_key
            or runner._is_user_authorized_for_source(source) is not True):
        raise ValueError('Topic source no longer authenticated')


def deliver_private(bound, message):
    """Send once to the authenticated sender's numeric DM, never a model target.

    send_message_tool mirrors capabilities into model history; its Telegram
    formatting sender can retry. Use its SAME profile config/egress policy and
    native Bot factory, but the native single-attempt text primitive instead.
    The gateway source is checked again before acquiring the transport snapshot.
    All errors are fixed-category and no capability-bearing exception is logged.
    """
    try:
        from .native import owner
        if owner(bound.home, allow_telegram_topic=True, task_id=bound.task_id) != bound:
            return {'success': False}
        from gateway.config import load_gateway_config
        from tools.send_message_tool import _resolve_platform_config, _authorize_relay_target
        from tools.send_message_senders import _telegram_bot, _send_telegram_message_with_retry
        from tools.interrupt import is_interrupted
        from model_tools import _run_async
        _, config, _, error = _resolve_platform_config('telegram', load_gateway_config())
        if error or config is None or not config.enabled or not config.token or is_interrupted():
            return {'success': False}
        # The guard and send MUST use this one credential snapshot.
        if _authorize_relay_target('telegram', bound.user_id, None, native_token=config.token):
            return {'success': False}
        from agent.redact import register_vault_redaction_value
        register_vault_redaction_value(message.split()[-1])
        async def send():
            try:
                result = await _send_telegram_message_with_retry(
                    _telegram_bot(config.token), attempts=1, chat_id=int(bound.user_id),
                    text=message, parse_mode=None, disable_web_page_preview=True)
                return bool(getattr(result, 'message_id', None))
            except Exception:
                return False  # no exception text can cross the sync/async boundary
        return {'success': _run_async(send()) is True}
    except Exception:
        return {'success': False}
