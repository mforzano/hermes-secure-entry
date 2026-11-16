"""Native payment-kind storage adapter, never a second vault or login payload."""
import re


class VaultCardSource:
    def __init__(self, service):
        self.service = service
        self.store = None

    def identifier(self, args, merchant):
        from agent.vault_store import get_vault_store
        handle = args.get('handle', '')
        if not isinstance(handle, str) or not re.fullmatch(r'vault_[0-9a-f]{12}', handle):
            raise ValueError('invalid_handle')
        # Capture the native profile store on this authenticated worker, not HTTP.
        self.store = self.service.store_factory() if self.service.store_factory else get_vault_store()
        self._metadata(handle, merchant)
        return handle

    def _metadata(self, handle, merchant):
        meta = self.store.get_meta(handle)
        from .native import is_reusable_card
        if meta is None or meta.kind != 'payment' or (not is_reusable_card(meta) and meta.origin != merchant):
            raise ValueError('card_origin_mismatch')

    def load(self, handle, merchant):
        self._metadata(handle, merchant)
        secret = self.store.resolve_secret(handle)
        try:
            return {'preserve_unsupplied_billing': True,
                    'number':secret['card_number'], 'cvc':secret['cvc'],
                    'exp_month':int(secret['exp_month']), 'exp_year':int(secret['exp_year']),
                    'billing_address':{'name':secret.get('cardholder_name', ''),
                                       'postal_code':secret.get('billing_postal_code', '')}}
        finally:
            secret.clear()
