"""Only synthetic credentials; Windows kernel ACL and handle tests."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secure_entry import payment_file

CARD = {
    "spend_request_id": "lsrq_synthetic",
    "merchant_url": "https://merchant.invalid",
    "card": {
        "number": "4242424242424242",
        "cvc": "123",
        "exp_month": 12,
        "exp_year": 2030,
    },
}


def write_as_link(path, text):
    """Create the file the way Link does: exclusive, owner-only (0600) on POSIX.

    Windows keeps the inherited protected DACL on the inbox, so a plain write
    is what that platform's tests have always used.
    """
    if os.name == "nt":
        Path(path).write_text(text, encoding="utf-8")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


class PaymentFileTests(unittest.TestCase):
    def test_refusal_categories_are_fixed_and_malformed_shapes_are_secret_free(self):
        cases = [
            ([], "object"),
            ({**CARD, "spend_request_id": "SYNTHETIC_PRIVATE"}, "request_match"),
            ({**CARD, "merchant_url": ["SYNTHETIC_PRIVATE"]}, "merchant_origin"),
            ({**CARD, "card": None}, "card_type"),
        ]
        for fields, category in (
            ({"number": 4242424242424242}, "card_number_type"),
            ({"number": "SYNTHETIC_PRIVATE"}, "card_number_format"),
            ({"cvc": []}, "cvc_type_format"),
            ({"exp_month": True}, "expiry_type_range"),
            ({"exp_year": 1}, "expiry_type_range"),
            ({"billing_address": []}, "billing_type"),
            ({"billing_address": {"line2": None}}, "billing_field_type"),
            ({"billing_address": {"line1": "x" * 257}}, "billing_field_format"),
        ):
            cases.append(({**CARD, "card": {**CARD["card"], **fields}}, category))
        for data, category in cases:
            with self.subTest(category=category), tempfile.TemporaryDirectory() as root:
                with payment_file.PrivateCard(root) as inbox:
                    write_as_link(inbox.path, json.dumps(data))
                    with self.assertRaises(ValueError) as caught:
                        inbox.consume("lsrq_synthetic", "https://merchant.invalid")
                    self.assertEqual(str(caught.exception), "private_file_refused")
                    self.assertEqual(getattr(caught.exception, "category", None), category)
                    self.assertNotIn("SYNTHETIC_PRIVATE", repr(caught.exception))
                    self.assertFalse(inbox.path.exists())
        with tempfile.TemporaryDirectory() as root, payment_file.PrivateCard(root) as inbox:
            write_as_link(inbox.path, json.dumps(CARD))
            check = "_check_acl" if os.name == "nt" else "_check_posix_acl"
            with patch.object(payment_file, check, side_effect=OSError("SYNTHETIC_PRIVATE")):
                with self.assertRaises(ValueError) as caught:
                    inbox.consume("lsrq_synthetic", "https://merchant.invalid")
            self.assertEqual(getattr(caught.exception, "category", None), payment_file.ACL_CATEGORY)
            self.assertNotIn("SYNTHETIC_PRIVATE", repr(caught.exception))

    def test_issued_billing_and_optional_cvc_preserved(self):
        data = json.loads(json.dumps(CARD))
        del data["card"]["cvc"]
        data["card"]["billing_address"] = dict(
            name="Synthetic Person", line1="1 Test St", country="US"
        )
        with (
            tempfile.TemporaryDirectory() as root,
            payment_file.PrivateCard(root) as inbox,
        ):
            write_as_link(inbox.path, json.dumps(data))
            self.assertEqual(
                inbox.consume("lsrq_synthetic", "https://merchant.invalid"),
                data["card"],
            )

    @unittest.skipUnless(
        os.name == "nt",
        "Windows DACL edit; the POSIX equivalent is test_posix_group_or_world_mode_rejected_and_file_deleted",
    )
    def test_world_readable_acl_rejected_and_file_deleted(self):
        import win32security as sec

        with tempfile.TemporaryDirectory() as root:
            with payment_file.PrivateCard(root) as inbox:
                write_as_link(inbox.path, json.dumps(CARD))
                sd = sec.GetFileSecurity(str(inbox.path), sec.DACL_SECURITY_INFORMATION)
                acl = sd.GetSecurityDescriptorDacl()
                acl.AddAccessAllowedAce(
                    sec.ACL_REVISION, 0x120089, sec.ConvertStringSidToSid("S-1-1-0")
                )
                sd.SetSecurityDescriptorDacl(True, acl, False)
                sec.SetFileSecurity(str(inbox.path), sec.DACL_SECURITY_INFORMATION, sd)
                with self.assertRaisesRegex(ValueError, "^private_file_refused$"):
                    inbox.consume("lsrq_synthetic", "https://merchant.invalid")
                self.assertFalse(inbox.path.exists())

    def test_hardlink_refused(self):
        with tempfile.TemporaryDirectory() as root:
            with payment_file.PrivateCard(root) as inbox:
                write_as_link(inbox.path, json.dumps(CARD))
                os.link(inbox.path, Path(root) / "other-link.json")
                with self.assertRaisesRegex(ValueError, "^private_file_refused$"):
                    inbox.consume("lsrq_synthetic", "https://merchant.invalid")
                self.assertFalse(inbox.path.exists())

    def test_wrong_merchant_id_malformed_and_oversized_are_secret_free(self):
        for raw, rid, origin in (
            (json.dumps(CARD), "lsrq_other", "https://merchant.invalid"),
            (json.dumps(CARD), "lsrq_synthetic", "https://other.invalid"),
            ("secret-invalid-json", "lsrq_synthetic", "https://merchant.invalid"),
            ("x" * 16385, "lsrq_synthetic", "https://merchant.invalid"),
        ):
            with (
                self.subTest(rid=rid, origin=origin),
                tempfile.TemporaryDirectory() as root,
            ):
                with payment_file.PrivateCard(root) as inbox:
                    write_as_link(inbox.path, raw)
                    with self.assertRaisesRegex(ValueError, "^private_file_refused$"):
                        inbox.consume(rid, origin)
                    self.assertFalse(inbox.path.exists())

    def test_private_directory_and_one_use_handle_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            with payment_file.PrivateCard(root) as inbox:
                p = inbox.path
                write_as_link(p, json.dumps(CARD))
                self.assertEqual(
                    inbox.consume("lsrq_synthetic", "https://merchant.invalid")[
                        "number"
                    ],
                    CARD["card"]["number"],
                )
                self.assertFalse(p.exists())
                with self.assertRaises(ValueError):
                    inbox.consume("lsrq_synthetic", "https://merchant.invalid")
            self.assertFalse(p.parent.exists())


if __name__ == "__main__":
    unittest.main()
