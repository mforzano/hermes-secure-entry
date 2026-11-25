"""POSIX private-inbox refusals: mode, owner, links, types, swaps (synthetic only).

These are the Linux and macOS equivalents of the Windows DACL, token-owner and
handle tests. Owner changes need root, so ownership is simulated by changing
the uid the consumer compares against; the stat results are real.
"""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secure_entry import payment, payment_file
from test_payment_file import CARD, write_as_link

POSIX = os.name != "nt"
# Captured before any patch so the swap test can call the real validator.
ORIGINAL_PAYLOAD = payment_file._payload
SKIP_REASON = "POSIX mode/owner semantics; Windows DACL tests are in test_payment_file_owner.py"


@unittest.skipIf(not POSIX, SKIP_REASON)
class PosixPrivateFileTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)

    def _inbox(self):
        inbox = payment_file.PrivateCard(self.root.name)
        inbox.__enter__()
        self.addCleanup(self._close, inbox)
        return inbox

    def _close(self, inbox):
        # Idempotent cleanup that tolerates tests that left odd entries behind.
        for path in (inbox.path, inbox.directory):
            try:
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.chmod(0o700)
                    path.rmdir()
            except OSError:
                pass

    def _write_card(self, inbox, data=CARD):
        write_as_link(inbox.path, json.dumps(data))

    def _consume_refused(self, inbox, category):
        with self.assertRaises(ValueError) as caught:
            inbox.consume("lsrq_synthetic", "https://merchant.invalid")
        self.assertEqual(str(caught.exception), "private_file_refused")
        self.assertEqual(getattr(caught.exception, "category", None), category)
        return caught.exception

    def test_private_directory_is_owner_only_from_creation(self):
        inbox = self._inbox()
        self.assertEqual(stat.S_IMODE(os.stat(inbox.directory).st_mode), 0o700)

    def test_valid_owner_only_file_consumed_once_and_deleted(self):
        inbox = self._inbox()
        self._write_card(inbox)
        self.assertEqual(
            inbox.consume("lsrq_synthetic", "https://merchant.invalid"),
            CARD["card"],
        )
        self.assertFalse(inbox.path.exists())
        self._consume_refused(inbox, "file_open")

    def test_group_or_world_readable_file_rejected_and_deleted(self):
        for mode in (0o644, 0o640, 0o604, 0o666):
            with self.subTest(mode=oct(mode)):
                inbox = self._inbox()
                self._write_card(inbox)
                inbox.path.chmod(mode)
                exc = self._consume_refused(inbox, "posix_acl")
                self.assertEqual(getattr(exc, "object_type", None), "file")
                self.assertFalse(inbox.path.exists())

    def test_group_or_world_accessible_directory_refused(self):
        for mode in (0o750, 0o755, 0o707):
            with self.subTest(mode=oct(mode)):
                inbox = self._inbox()
                self._write_card(inbox)
                inbox.directory.chmod(mode)
                try:
                    exc = self._consume_refused(inbox, "posix_acl")
                    self.assertEqual(getattr(exc, "object_type", None), "directory")
                    # Refused before the file is opened, so it is left for cleanup.
                    self.assertTrue(inbox.path.exists())
                finally:
                    inbox.directory.chmod(0o700)

    def test_foreign_directory_owner_refused(self):
        inbox = self._inbox()
        self._write_card(inbox)
        with patch.object(payment_file, "_current_uid", return_value=os.geteuid() + 1):
            exc = self._consume_refused(inbox, "owner")
        self.assertEqual(getattr(exc, "owner_class", None), "other")
        self.assertEqual(getattr(exc, "object_type", None), "directory")

    def test_foreign_file_owner_refused_and_deleted(self):
        inbox = self._inbox()
        self._write_card(inbox)
        real = os.geteuid()
        # First call checks the directory (owner matches), second the file.
        with patch.object(payment_file, "_current_uid", side_effect=[real, real + 1]):
            exc = self._consume_refused(inbox, "owner")
        self.assertEqual(getattr(exc, "owner_class", None), "other")
        self.assertEqual(getattr(exc, "object_type", None), "file")
        self.assertFalse(inbox.path.exists())

    def test_symlinked_card_refused_and_target_untouched(self):
        inbox = self._inbox()
        target = Path(self.root.name) / "outside-card.json"
        write_as_link(target, json.dumps(CARD))
        inbox.path.symlink_to(target)
        self._consume_refused(inbox, "file_open")
        self.assertTrue(target.exists())

    def test_symlinked_inbox_directory_refused(self):
        target_dir = Path(self.root.name) / "outside"
        target_dir.mkdir()
        write_as_link(target_dir / "card.json", json.dumps(CARD))
        inbox = payment_file.PrivateCard(self.root.name)
        inbox.__enter__()
        inbox.directory.rmdir()
        inbox.directory.symlink_to(target_dir, target_is_directory=True)
        try:
            self._consume_refused(inbox, "directory_open")
            self.assertTrue((target_dir / "card.json").exists())
        finally:
            # Remove only the symlink; never go through it in cleanup.
            inbox.directory.unlink()

    def test_fifo_refused_without_blocking_and_removed(self):
        inbox = self._inbox()
        os.mkfifo(inbox.path, 0o600)
        exc = self._consume_refused(inbox, "filetype")
        self.assertEqual(getattr(exc, "object_type", None), "file")
        self.assertFalse(inbox.path.exists())

    def test_hardlinked_card_refused_and_removed(self):
        inbox = self._inbox()
        self._write_card(inbox)
        os.link(inbox.path, Path(self.root.name) / "other-link.json")
        self._consume_refused(inbox, "linkcount")
        self.assertFalse(inbox.path.exists())

    def test_oversized_valid_json_refused_as_size(self):
        inbox = self._inbox()
        padded = json.dumps(CARD) + " " * (16385 - len(json.dumps(CARD)))
        write_as_link(inbox.path, padded)
        self._consume_refused(inbox, "size")
        self.assertFalse(inbox.path.exists())

    def test_swapped_name_is_not_deleted_and_refused(self):
        inbox = self._inbox()
        self._write_card(inbox)

        def swap_then_return(raw, request_id, merchant_origin):
            # Simulates a same-user replacement between open and unlink.
            inbox.path.unlink()
            write_as_link(inbox.path, json.dumps(CARD))
            return ORIGINAL_PAYLOAD(raw, request_id, merchant_origin)

        with patch.object(payment_file, "_payload", side_effect=swap_then_return):
            self._consume_refused(inbox, "file_info")
        self.assertTrue(inbox.path.exists())

    def test_child_process_gets_owner_only_umask(self):
        self.assertEqual(payment._child_umask(), {"umask": 0o077})


@unittest.skipIf(POSIX, "Windows child-process handling has no umask; DACL inheritance applies")
class WindowsChildUmaskTests(unittest.TestCase):
    def test_windows_passes_no_umask(self):
        self.assertEqual(payment._child_umask(), {})


if __name__ == "__main__":
    unittest.main()
