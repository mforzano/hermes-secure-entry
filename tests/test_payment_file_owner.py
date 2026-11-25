"""Synthetic Windows kernel ownership; no credentials, browser or network.

Windows-only: token owner and DACL semantics have no POSIX counterpart. The
POSIX owner and mode refusals are covered by test_payment_file_posix.py.
"""

import json
import os
import tempfile
import unittest
from contextlib import contextmanager

if os.name != "nt":
    raise unittest.SkipTest(
        "Windows token-owner and DACL tests; POSIX owner/mode tests are in test_payment_file_posix.py"
    )

import win32api as api
import win32con as con
import win32file as file
import win32security as sec

from secure_entry import payment_file
from test_payment_file import CARD
from secure_entry.payment_file import _handle as handle_scope


@contextmanager
def default_group_owner():
    """An actual effective thread token with a non-user assignable owner."""
    with handle_scope(
        sec.OpenProcessToken(
            api.GetCurrentProcess(), con.TOKEN_QUERY | con.TOKEN_DUPLICATE
        )
    ) as process:
        user = sec.GetTokenInformation(process, sec.TokenUser)[0]
        groups = [
            sid
            for sid, flags in sec.GetTokenInformation(process, sec.TokenGroups)
            if flags & con.SE_GROUP_OWNER and sid != user
        ]
        if not groups:
            raise unittest.SkipTest("requires an owner-capable token group")
        with handle_scope(
            sec.DuplicateTokenEx(
                process,
                sec.SecurityImpersonation,
                con.MAXIMUM_ALLOWED,
                sec.TokenImpersonation,
                None,
            )
        ) as token:
            sec.SetTokenInformation(token, sec.TokenOwner, groups[0])
            sec.SetThreadToken(None, token)
            try:
                yield user, groups[0]
            finally:
                sec.RevertToSelf()


class PaymentFileOwnerTests(unittest.TestCase):
    def test_effective_default_owner_normalized_before_read(self):
        with (
            tempfile.TemporaryDirectory() as root,
            default_group_owner() as (user, owner),
        ):
            with payment_file.PrivateCard(root) as inbox:
                inbox.path.write_text(json.dumps(CARD))
                sd = sec.GetFileSecurity(
                    str(inbox.path), sec.OWNER_SECURITY_INFORMATION
                )
                self.assertEqual(sd.GetSecurityDescriptorOwner(), owner)
                with handle_scope(
                    file.CreateFile(
                        str(inbox.path),
                        con.READ_CONTROL | con.WRITE_OWNER,
                        0,
                        None,
                        con.OPEN_EXISTING,
                        0,
                        None,
                    )
                ) as handle:
                    payment_file._check_acl(handle)
                    sd = sec.GetSecurityInfo(
                        handle, sec.SE_FILE_OBJECT, sec.OWNER_SECURITY_INFORMATION
                    )
                    self.assertEqual(sd.GetSecurityDescriptorOwner(), user)
                inbox.path.unlink()
                inbox.path.write_text(json.dumps(CARD))
                self.assertEqual(
                    inbox.consume("lsrq_synthetic", "https://merchant.invalid"),
                    CARD["card"],
                )

    def test_directory_default_owner_normalized(self):
        with (
            tempfile.TemporaryDirectory() as root,
            default_group_owner() as (user, owner),
        ):
            with payment_file.PrivateCard(root) as inbox:
                with handle_scope(
                    file.CreateFile(
                        str(inbox.directory),
                        con.WRITE_OWNER,
                        0,
                        None,
                        con.OPEN_EXISTING,
                        con.FILE_FLAG_BACKUP_SEMANTICS,
                        None,
                    )
                ) as handle:
                    sec.SetSecurityInfo(
                        handle,
                        sec.SE_FILE_OBJECT,
                        sec.OWNER_SECURITY_INFORMATION,
                        owner,
                        None,
                        None,
                        None,
                    )
                inbox.path.write_text(json.dumps(CARD))
                self.assertEqual(
                    inbox.consume("lsrq_synthetic", "https://merchant.invalid"),
                    CARD["card"],
                )
                sd = sec.GetFileSecurity(
                    str(inbox.directory), sec.OWNER_SECURITY_INFORMATION
                )
                self.assertEqual(sd.GetSecurityDescriptorOwner(), user)

    def test_foreign_owner_rejected_with_private_dacl(self):
        with (
            tempfile.TemporaryDirectory() as root,
            payment_file.PrivateCard(root) as inbox,
        ):
            inbox.path.write_text(json.dumps(CARD))
            with handle_scope(
                sec.OpenProcessToken(api.GetCurrentProcess(), con.TOKEN_QUERY)
            ) as token:
                current_owner = sec.GetTokenInformation(token, sec.TokenOwner)
                groups = [
                    sid
                    for sid, flags in sec.GetTokenInformation(token, sec.TokenGroups)
                    if flags & con.SE_GROUP_OWNER and sid != current_owner
                ]
            if not groups:
                self.skipTest("requires a non-default assignable owner group")
            foreign = groups[0]
            expected = (
                "administrators"
                if sec.ConvertSidToStringSid(foreign) == "S-1-5-32-544"
                else "other"
            )
            # A valid assignable group is still foreign when not TokenOwner.
            # No restore/take-ownership privilege needs to be enabled.
            with handle_scope(
                file.CreateFile(
                    str(inbox.path),
                    con.READ_CONTROL | con.WRITE_OWNER,
                    0,
                    None,
                    con.OPEN_EXISTING,
                    0,
                    None,
                )
            ) as handle:
                sec.SetSecurityInfo(
                    handle,
                    sec.SE_FILE_OBJECT,
                    sec.OWNER_SECURITY_INFORMATION,
                    foreign,
                    None,
                    None,
                    None,
                )
                with self.assertRaises(payment_file.PrivateFileRefused) as caught:
                    payment_file._check_acl(handle)
                self.assertEqual(caught.exception.category, "owner")
            with self.assertRaises(payment_file.PrivateFileRefused) as caught:
                inbox.consume("lsrq_synthetic", "https://merchant.invalid")
            self.assertEqual(caught.exception.object_type, "file")
            self.assertEqual(caught.exception.owner_class, expected)

    def test_default_owner_does_not_bypass_foreign_dacl(self):
        with tempfile.TemporaryDirectory() as root, default_group_owner() as (_, owner):
            with payment_file.PrivateCard(root) as inbox:
                inbox.path.write_text(json.dumps(CARD))
                acl = sec.GetFileSecurity(
                    str(inbox.path), sec.DACL_SECURITY_INFORMATION
                ).GetSecurityDescriptorDacl()
                acl.AddAccessAllowedAce(
                    sec.ACL_REVISION,
                    con.GENERIC_READ,
                    sec.ConvertStringSidToSid("S-1-1-0"),
                )
                with handle_scope(
                    file.CreateFile(
                        str(inbox.path),
                        con.READ_CONTROL | con.WRITE_DAC | con.WRITE_OWNER,
                        0,
                        None,
                        con.OPEN_EXISTING,
                        0,
                        None,
                    )
                ) as handle:
                    sec.SetSecurityInfo(
                        handle,
                        sec.SE_FILE_OBJECT,
                        sec.DACL_SECURITY_INFORMATION,
                        None,
                        None,
                        acl,
                        None,
                    )
                    with self.assertRaises(payment_file.PrivateFileRefused):
                        payment_file._check_acl(handle)
                    sd = sec.GetSecurityInfo(
                        handle, sec.SE_FILE_OBJECT, sec.OWNER_SECURITY_INFORMATION
                    )
                    self.assertEqual(sd.GetSecurityDescriptorOwner(), owner)


if __name__ == "__main__":
    unittest.main()
