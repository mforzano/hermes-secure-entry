"""Field-aware payment registration using the existing native exact-value registry.

No registry mutation, core patches, or live-registry recovery is performed here.
"""
import re

from agent.redact import register_vault_redaction_value


def register_payment_redaction_values(payment: dict) -> None:
    """Register canonical payment fields, not public metadata fragments.

    Accepts ``card_number``, ``cvc``, ``exp_month`` and ``exp_year`` (strings or
    integers). Other fields, including cardholder/billing/country, are ignored.
    PAN and CVC retain exact-substring protection, even when short. Expiry is
    registered as a complete date only: standalone month/year are public values,
    not passwords, and registering them globally corrupts unrelated URLs/text.
    Call BEFORE filling/storing a card; never additionally register all values.
    Uses the same profile-scoped, bounded, memory-only registry as vault secrets.
    Also covers compact/space/hyphen-grouped PANs and common slash, hyphen,
    spaced and compact MMYY/MMYYYY expiry forms. This is not general PII masking:
    separate month/year controls and billing metadata may remain visible. Exact
    credential/full-date collisions still redact unrelated text intentionally.
    """
    for field in ("card_number", "cvc"):
        value = payment.get(field)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            register_vault_redaction_value(str(value))
    pan = payment.get("card_number")
    if isinstance(pan, (str, int)) and not isinstance(pan, bool):
        digits = re.sub(r"[\s-]", "", str(pan))
        if re.fullmatch(r"[0-9]{12,19}", digits):
            register_vault_redaction_value(digits)
            groups = [digits[i:i + 4] for i in range(0, len(digits), 4)]
            groupings = [groups]
            if len(digits) == 15:
                groupings.append([digits[:4], digits[4:10], digits[10:]])
            for parts in groupings:
                for separator in (" ", "-"):
                    register_vault_redaction_value(separator.join(parts))
    month, year = payment.get("exp_month"), payment.get("exp_year")
    if not all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in (month, year)):
        return
    month, year = str(month).strip(), str(year).strip()
    if not (re.fullmatch(r"[0-9]{1,2}", month) and 1 <= int(month) <= 12
            and re.fullmatch(r"(?:[0-9]{2}|[0-9]{4})", year)):
        return
    for mm in {str(int(month)), month.zfill(2)}:
        for yy in {year, year[-2:]}:
            for separator in ("/", "-", " / ", " - "):
                register_vault_redaction_value(f"{mm}{separator}{yy}")
            register_vault_redaction_value(f"{mm.zfill(2)}{yy}")


