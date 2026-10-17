"""Payment registrations must not poison unrelated links (synthetic data only)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.redact import redact_registered_vault_values
from agent.vault_store import VaultStore
from secure_entry.native import add_card


class PaymentRedactionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        environment = patch.dict(os.environ, HERMES_HOME=str(self.home))
        environment.start()
        self.addCleanup(environment.stop)
        self.fields = {
            "card_number": "4242424242424242",
            "cvc": "987",
            "exp_month": "1",
            "exp_year": "2035",
            "cardholder_name": "SYNTHETIC CARDHOLDER",
            "billing_postal_code": "10001",
        }

    def assert_payment_redaction(self):
        unrelated = (
            "https://entry.invalid:9443/r/a1b2035c10001dUS2 "
            "month=1 year=2035 SYNTHETIC CARDHOLDER US 10001 True"
        )
        self.assertEqual(redact_registered_vault_values(unrelated), unrelated)
        for secret in (
            "4242424242424242", "4242 4242 4242 4242", "4242-4242-4242-4242",
            "987", "1/35", "01/35", "01/2035", "01 / 35", "0135",
        ):
            with self.subTest(secret_format=secret):
                self.assertEqual(
                    redact_registered_vault_values("before=" + secret + ";after"),
                    "before=«redacted-vault-secret»;after",
                )

    def test_saved_card_fill_registers_secrets_before_write(self):
        self.check_fill_registration("saved")

    def test_link_fill_registers_secrets_before_write(self):
        self.check_fill_registration("link")

    def check_fill_registration(self, source):
        import json
        from types import SimpleNamespace
        from gateway.session_context import set_session_vars, clear_session_vars
        from hermes_constants import profile_name_for_home
        from secure_entry.cards import VaultCardSource
        from secure_entry.payment import LocalPayment
        from secure_entry.service import Service

        tokens = set_session_vars(
            platform="photon", chat_type="dm", chat_id="synthetic-chat",
            user_id="synthetic-owner", session_key="synthetic-key",
            session_id="synthetic-session", profile=profile_name_for_home(self.home) or "",
            cron_session="",
        )
        self.addCleanup(clear_session_vars, tokens)
        store = VaultStore(self.home / "vault")
        # Seed storage directly so add_card's registrations cannot hide a fill bug.
        meta = store.add_item("payment", "synthetic", dict(self.fields), origin="https://merchant.test")
        service = Service("https://example.invalid", str(self.home), port=0, store_factory=lambda: store)
        self.addCleanup(service.close)
        args = {
            "handle": meta.id, "spend_request_id": "lsrq_synthetic",
            "parent": "synthetic-parent", "frame": "synthetic-frame",
            "merchant_origin": "https://merchant.test", "frame_origin": "https://provider.test",
        }

        def fill(card):
            self.assert_payment_redaction()
            return {"success": True, "filled_fields": 4}

        target = SimpleNamespace(started=False, check=lambda: None, close=lambda: None, fill=fill)
        with (
            patch("tools.browser_supervisor.SUPERVISOR_REGISTRY.capture",
                  return_value=SimpleNamespace(is_valid=lambda: True)),
            patch("tools.approval_prompt.request_elicitation_consent", return_value="accept"),
            patch("secure_entry.payment.Target", return_value=target),
            patch("secure_entry.payment.PrivateCard") as inbox,
        ):
            inbox.return_value.__enter__.return_value.consume.return_value = {
                "number": self.fields["card_number"], "cvc": self.fields["cvc"],
                "exp_month": 1, "exp_year": 2035,
                "billing_address": {"name": self.fields["cardholder_name"],
                                    "postal_code": "10001", "country": "US"},
            }
            facility = LocalPayment(
                service, ["synthetic-cli"], retrieve=lambda *a: None,
                card_source=VaultCardSource(service) if source == "saved" else None,
            )
            result = json.loads(facility.fill(args, task_id="synthetic-payment"))
            self.assert_payment_redaction()
            self.assertTrue(result["success"], result)

    def test_add_card_registers_secrets_before_native_storage_without_url_fragments(self):
        test = self

        class CheckingStore(VaultStore):
            def add_item(self, *args, **kwargs):
                test.assert_payment_redaction()
                return super().add_item(*args, **kwargs)

        result = add_card(CheckingStore(self.home / "vault"), "https://merchant.test", self.fields)
        self.assert_payment_redaction()
        self.assertEqual(result["status"], "saved")
