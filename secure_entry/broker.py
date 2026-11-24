"""Memory-only, one-use requests. No network creation endpoint or secret status API."""
from dataclasses import dataclass, field
from html import escape
import secrets
import threading
import time
from urllib.parse import urlsplit
from .card_nicknames import clean_nickname, MAX_NICKNAME

CARD_LIMITS = {'card_number':19, 'cardholder_name':160, 'exp_month':2,
               'exp_year':4, 'cvc':4, 'billing_postal_code':32}


@dataclass(repr=False)
class Request:
    token: str = field(repr=False)
    csrf: str = field(repr=False)
    kind: str
    origin: str
    owner: tuple
    deadline: float
    apply: object = field(repr=False)
    nickname: str | None = None
    status: str = 'pending'
    result: dict = field(default_factory=dict)
    event: threading.Event = field(default_factory=threading.Event, repr=False)


class Broker:
    def __init__(self, public_base_url, ttl=600, clock=time.monotonic, capacity=64):
        parsed = urlsplit(public_base_url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise ValueError('public_base_url must be a trusted HTTPS origin')
        self.base = public_base_url.rstrip('/')
        self.ttl, self.clock, self.capacity = ttl, clock, capacity
        self.lock = threading.RLock()
        self.requests = {}

    def issue(self, kind, origin, owner, apply, *, nickname=None):
        if kind not in ('login', 'card', 'reusable_card', 'card_nickname', 'code', 'unlock') or not origin or not owner:
            raise ValueError('invalid request metadata')
        with self.lock:
            for token in list(self.requests):
                self._lookup(token)
            while len(self.requests) >= self.capacity:
                completed = next((token for token, r in self.requests.items() if r.status not in ('pending', 'received')), None)
                if completed is None:
                    raise ValueError('request capacity reached')
                del self.requests[completed]
            request = Request(secrets.token_urlsafe(32), secrets.token_urlsafe(32), kind, origin,
                              owner, self.clock() + self.ttl, apply, nickname=nickname)
            self.requests[request.token] = request
            return request

    def url(self, request):
        return self.base + '/r/' + request.token

    def _lookup(self, token):
        request = self.requests.get(token)
        if request and request.status in ('pending', 'received') and self.clock() >= request.deadline:
            request.status = 'expired'
            request.apply = None
            request.event.set()
        return request

    def status(self, token):
        with self.lock:
            request = self._lookup(token)
            return {'status': request.status, **request.result} if request else {'status': 'unavailable'}

    def finish(self, token, status, result=None):
        with self.lock:
            request = self._lookup(token)
            if request:
                request.status = status
                request.result = result or {}
                request.apply = None
                request.event.set()

    def submit(self, token, fields):
        with self.lock:
            request = self._lookup(token)
            if request is None:
                return {'status': 'unavailable'}
            if request.status != 'pending':
                return self.status(token)
            if not secrets.compare_digest(str(fields.get('csrf', '')), request.csrf):
                return {'status': 'csrf_rejected'}
            if fields.get('action') == 'cancel':
                self.finish(token, 'cancelled')
                return self.status(token)
            required = (('identifier', 'password') if request.kind == 'login' else
                        tuple(CARD_LIMITS) if request.kind in ('card', 'reusable_card') else
                        ('password',) if request.kind == 'unlock' else
                        () if request.kind == 'card_nickname' else ('code',))
            limits = {'identifier':320, 'password':4096, 'code':256, **CARD_LIMITS}
            if (fields.get('action') != 'submit'
                    or any(not isinstance(fields.get(k), str) or not fields[k] or len(fields[k]) > limits[k] for k in required)):
                return {'status': 'invalid_input'}
            if request.kind == 'reusable_card' and fields.get('reusable_consent') != 'yes':
                return {'status': 'invalid_input'}
            payload = {k: fields[k] for k in required}
            if request.kind == 'card_nickname' or (request.kind == 'reusable_card' and fields.get('nickname', '') != ''):
                try:
                    payload['nickname'] = clean_nickname(fields.get('nickname'))
                except ValueError:
                    return {'status': 'invalid_input'}
            request.status = 'received'
            apply, request.apply = request.apply, None
            # Serialize cancellation with the native commit. A cancellation cannot be
            # acknowledged and then be followed by a late credential write.
            # Actions must be short native commits, never human-length waits.
            try:
                result = apply(payload)
            except Exception:
                result = {'status': 'failed'}  # Never stringify a secret-bearing exception.
            if request.status == 'received':
                request.status = result.get('status', 'failed')
                request.result = {k: result[k] for k in ('handle', 'identifier', 'nickname_status') if k in result}
            request.event.set()
            return self.status(token)

    def cancel_owner(self, owner):
        with self.lock:
            for request in self.requests.values():
                if request.owner == owner and request.status in ('pending', 'received'):
                    self.finish(request.token, 'cancelled')

    def close(self):
        with self.lock:
            for request in self.requests.values():
                if request.status in ('pending', 'received'):
                    self.finish(request.token, 'cancelled')

    def page(self, token):
        with self.lock:
            request = self._lookup(token)
            status = request.status if request else 'unavailable'
            content = '<p role="status">' + escape(status) + '</p>'
            if request and status == 'pending':
                content += '<p>Site: <strong>' + escape(request.origin) + '</strong></p>'
                content += '<p>This link works once and expires shortly. Native prompts expire in at most three minutes; login saves in ten minutes. Never enter a passkey here.</p>'
                content += '<form method="post"><input type="hidden" name="csrf" value="' + request.csrf + '">'
                if request.kind == 'login':
                    content += ('<p>Save a website login in the native encrypted Hermes vault. This does not sign you in.</p>'
                                '<label for="identifier">Username, email, or phone</label>'
                                '<input id="identifier" name="identifier" autocomplete="username" required maxlength="320">'
                                '<label for="password">Website password</label>'
                                '<input id="password" name="password" type="password" autocomplete="current-password" required maxlength="4096">')
                elif request.kind in ('card', 'reusable_card'):
                    if request.kind == 'reusable_card':
                        content += ('<p>Save one reusable card across websites until explicit deletion. '
                                    'Each fill still requires native consent for the exact merchant/payment document.</p>'
                                    '<label><input type="checkbox" name="reusable_consent" value="yes" required>'
                                    'I explicitly opt in to reusable storage until explicit deletion.</label>')
                        content += nickname_input(required=False)
                    else:
                        content += '<p>This card is bound only to this merchant. Request explicit deletion after verifying checkout outcome.</p>'
                    content += ('<p>Save a payment card in the native encrypted vault. '
                                'CVC is encrypted and saved under the native payment contract. '
                                'This does not fill, submit, reserve, or pay.</p>')
                    labels = {'card_number':'Card number', 'cardholder_name':'Cardholder name',
                              'exp_month':'Expiry month (1-12)', 'exp_year':'Expiry year (YYYY)',
                              'cvc':'CVC (saved encrypted)', 'billing_postal_code':'Billing postal code'}
                    for name, limit in CARD_LIMITS.items():
                        content += (f'<label for="{name}">{labels[name]}</label>'
                                    f'<input id="{name}" name="{name}" type="password" autocomplete="off" required maxlength="{limit}">')
                elif request.kind == 'unlock':
                    content += ('<p>Unlock the named password manager for the waiting native tool. '
                                'This is your manager master password, not a website password. It is not saved by this plugin.</p>'
                                '<label for="password">Password manager master password</label>'
                                '<input id="password" name="password" type="password" autocomplete="off" required maxlength="4096">')
                elif request.kind == 'card_nickname':
                    current = ('Current nickname: “' + escape(request.nickname) + '”.' if request.nickname else
                               'The selected reusable card has no nickname.')
                    content += '<p>' + current + ' Continue only if this is the card you intended to label.</p>'
                    content += nickname_input(required=True)
                else:
                    content += ('<p>Enter the SMS, email, authenticator, or other login verification code. '
                                'It will be sent only to the waiting native browser tool. This does not confirm sign-in.</p>'
                                '<label for="code">Verification code</label>'
                                '<input id="code" name="code" type="password" autocomplete="one-time-code" required maxlength="256">')
                content += ('<button type="submit" name="action" value="submit">Continue securely</button>'
                            '<button type="submit" name="action" value="cancel" formnovalidate>Cancel</button></form>')
            elif status == 'received':
                content += '<p>Received privately. Waiting for the native tool. Refresh to check; do not submit again.</p>'
            elif status in ('applied', 'filled'):
                content += '<p>The native tool filled the code field. Authentication has not been verified.</p>'
            elif status == 'unlocked':
                content += '<p>The native password manager reports unlocked. No website authentication has been verified.</p>'
            elif status == 'commit_unknown' and request.kind != 'login':
                content += '<p>Input handed to the native tool; outcome not yet verified. Inspect the browser or manager before retrying. Cancellation cannot undo a native action already begun.</p>'
            elif status == 'write_unknown':
                content += '<p>The code may have reached the website. The write could not be verified. Do not submit another code; check the website state first.</p>'
            elif status == 'code_mismatch':
                content += '<p>The entered code did not match the selected field format or length. No code was sent to the website.</p>'
            elif status == 'commit_unknown':
                content += ('<p>The save may have completed, but could not be verified. '
                            'Inspect the native vault before retrying to avoid duplicate items. '
                            'Do not submit again or request another link until checked.</p>')
            elif status == 'saved':
                content += '<p>Saved in the native encrypted vault. No browser fields were filled.</p>'
                if request.result.get('nickname_status') == 'unverified':
                    content += '<p>The nickname could not be verified. Check the saved-card list; do not save the card again.</p>'
            elif status == 'nickname_unavailable':
                content += '<p>The nickname store was unavailable. No card was saved.</p>'
            elif status == 'renamed':
                content += '<p>Nickname saved. The native card record was not changed.</p>'
            elif status == 'nickname_taken':
                content += '<p>Another reusable card already uses that nickname. Request a new link and choose a different name.</p>'
            elif status in ('card_unavailable', 'nickname_changed'):
                content += '<p>The selected card is no longer available or its nickname changed. Check the saved-card list before requesting a new link.</p>'
            else:
                content += '<p>No further entry is accepted. Request a new link if needed.</p>'
            return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width, initial-scale=1">'
                    '<title>Hermes secure entry</title></head><body><main><h1>Hermes secure entry</h1>'
                    + content + '</main></body></html>')


def nickname_input(*, required):
    return ('<label for="nickname">Card nickname' + ('' if required else ' (optional)') + '</label>'
            '<p>Use only English letters and single spaces, for example Travel Card. '
            'Do not enter card details, passwords, or other private information here. '
            'The nickname is visible in the saved-card list and fill approval.</p>'
            f'<input id="nickname" name="nickname" autocomplete="off" maxlength="{MAX_NICKNAME}"'
            + (' required' if required else '') + '>')
