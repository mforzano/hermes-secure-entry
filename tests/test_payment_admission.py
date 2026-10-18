"""Native payment owner/lifecycle admission; synthetic identities, no browser."""

import contextvars
import json
import unittest
from unittest.mock import patch
from gateway.session_context import set_session_vars, clear_session_vars
from hermes_constants import get_hermes_home, profile_name_for_home
from secure_entry.service import Service
from secure_entry.payment import LocalPayment
from secure_entry.native import owner
from tools import browser_tool


class PaymentAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tokens = set_session_vars(
            platform="photon",
            chat_type="dm",
            chat_id="synthetic-chat",
            user_id="synthetic-owner",
            session_key="synthetic-key",
            session_id="synthetic-session",
            profile=profile_name_for_home(get_hermes_home()) or "",
            cron_session="",
        )
        self.addCleanup(clear_session_vars, self.tokens)
        self.service = Service(
            "https://example.invalid", str(get_hermes_home()), port=0
        )
        self.addCleanup(self.service.close)
        self.facility = LocalPayment(
            self.service,
            ["synthetic-cli"],
            retrieve=lambda *a: self.fail("must not retrieve"),
        )
        self.args = {
            "parent": "synthetic-target",
            "frame": "synthetic-frame",
            "merchant_origin": "https://merchant.test",
            "frame_origin": "https://provider.test",
            "spend_request_id": "lsrq_synthetic",
        }
        self.key = browser_tool._last_session_key("synthetic-payment")

    def test_retrieval_failure_stage_and_version_are_fixed_and_secret_free(self):
        from types import SimpleNamespace
        from secure_entry.payment import RetrievalRefused

        for failure, expected_stage, expected_reason in (
            ("private", "private_file", "billing_field_type"),
            ("private_owner", "private_file", "owner"),
            ("unknown_private", "private_file", "private_file_failed"),
            ("producer", "link_retrieval_producer", "subprocess_exit"),
            ("unknown_producer", "link_retrieval_producer", "producer_failed"),
            ("current", "post_retrieval_current", "operation_cancelled"),
            ("owner", "post_retrieval_current", "owner_changed"),
            ("target", "post_retrieval_target_check", "target_check_failed"),
        ):
            with self.subTest(failure=failure):
                retrieved = False
                original_owner = owner(self.service.home)

                def retrieve(*args):
                    nonlocal retrieved
                    retrieved = True
                    if failure == "producer":
                        raise RetrievalRefused("subprocess_exit", 7)
                    if failure == "unknown_producer":
                        raise ValueError("SYNTHETIC_PRIVATE")
                    if failure == "current":
                        self.service.closed = True

                def check():
                    if retrieved and failure == "target":
                        raise ValueError("SYNTHETIC_PRIVATE")

                def bound_owner(home):
                    return None if retrieved and failure == "owner" else original_owner

                target = SimpleNamespace(started=False, check=check, close=lambda: None)
                self.facility.retrieve = retrieve
                with (
                    patch("secure_entry.payment.owner", side_effect=bound_owner),
                    patch(
                        "tools.browser_supervisor.SUPERVISOR_REGISTRY.capture",
                        return_value=SimpleNamespace(is_valid=lambda: True),
                    ),
                    patch(
                        "tools.approval_prompt.request_elicitation_consent",
                        return_value="accept",
                    ),
                    patch("secure_entry.payment.Target", return_value=target),
                    patch("secure_entry.payment.PrivateCard") as inbox,
                ):
                    from secure_entry.payment_file import PrivateFileRefused
                    if failure == "private_owner":
                        refusal = PrivateFileRefused("owner", owner_class="other")
                        refusal.object_type = "file"
                        inbox.return_value.__enter__.return_value.consume.side_effect = refusal
                    if failure in {"private", "unknown_private"}:
                        inbox.return_value.__enter__.return_value.consume.side_effect = (
                            PrivateFileRefused("billing_field_type")
                            if failure == "private"
                            else RuntimeError("SYNTHETIC_PRIVATE")
                        )
                    raw = self.facility.fill(self.args, task_id="synthetic-payment")
                self.service.closed = False
                result = json.loads(raw)
                self.assertEqual(result.get("stage"), expected_stage)
                self.assertEqual(result.get("refusal"), expected_reason)
                if failure == "private_owner":
                    self.assertEqual(result.get("private_object"), "file")
                    self.assertEqual(result.get("owner_class"), "other")
                self.assertEqual(result.get("payment_diagnostic_version"), "0.5.12")
                self.assertEqual(
                    result.get("subprocess_exit_status"),
                    7 if failure == "producer" else None,
                )
                self.assertNotIn("SYNTHETIC_PRIVATE", raw)
                if failure in {"private", "unknown_private", "private_owner"}:
                    inbox.return_value.__enter__.return_value.consume.assert_called_once()
                else:
                    inbox.return_value.__enter__.return_value.consume.assert_not_called()

    def test_consent_diagnostics_and_native_wait_accounting(self):
        from types import SimpleNamespace

        for failure, stage, reason in (
            ("exception", "native_consent", "consent_failed"),
            ("timeout", "native_consent", "consent_timeout"),
            ("closed", "postconsent_current", "operation_cancelled"),
            ("deadline", "postconsent_current", "operation_timeout"),
            ("target", "postconsent_target", "target_check_failed"),
            ("human_wait", "postconsent_target", "target_check_failed"),
        ):
            with self.subTest(failure=failure):
                clock = [0.0]
                waited = [0.0]

                def consent(*a, **kw):
                    if failure == "exception":
                        raise RuntimeError("SYNTHETIC_PRIVATE")
                    if failure == "timeout":
                        raise TimeoutError("SYNTHETIC_PRIVATE")
                    if failure == "closed":
                        self.service.closed = True
                    if failure in ("deadline", "human_wait"):
                        clock[0] = 200.0
                    if failure == "human_wait":
                        waited[0] = 200.0
                    return "accept"

                target = SimpleNamespace(
                    started=False,
                    close=lambda: None,
                    check=lambda: (_ for _ in ()).throw(
                        ValueError("SYNTHETIC_PRIVATE")
                    ),
                )
                with (
                    patch(
                        "secure_entry.payment.time.monotonic",
                        side_effect=lambda: clock[0],
                    ),
                    patch(
                        "tools.approval_human_wait.human_wait_seconds",
                        side_effect=lambda *a: waited[0],
                    ),
                    patch(
                        "tools.approval_prompt.request_elicitation_consent",
                        side_effect=consent,
                    ),
                    patch(
                        "tools.browser_supervisor.SUPERVISOR_REGISTRY.capture",
                        return_value=SimpleNamespace(is_valid=lambda: True),
                    ),
                    patch("secure_entry.payment.Target", return_value=target),
                    patch("secure_entry.payment.PrivateCard") as inbox,
                ):
                    raw = self.facility.fill(self.args, task_id="synthetic-payment")
                self.service.closed = False
                result = json.loads(raw)
                self.assertEqual(result.get("stage"), stage)
                self.assertEqual(result.get("refusal"), reason)
                self.assertNotIn("SYNTHETIC_PRIVATE", raw)
                inbox.assert_not_called()

    def test_existing_public_capture_needs_no_legacy_local_metadata(self):
        from types import SimpleNamespace

        with (
            patch.dict(browser_tool._active_sessions, {}, clear=True),
            patch(
                "tools.browser_supervisor.SUPERVISOR_REGISTRY.capture",
                return_value=SimpleNamespace(is_valid=lambda: True),
            ) as capture,
            patch(
                "secure_entry.payment.Target",
                side_effect=ValueError("stop before consent"),
            ) as target,
        ):
            result = json.loads(
                self.facility.fill(self.args, task_id="synthetic-payment")
            )
        capture.assert_called_once_with("synthetic-payment")
        target.assert_called_once()
        self.assertFalse(result["success"])

    def test_lifecycle_during_owner_acquisition_prevents_capture(self):
        def acquire(home):
            bound = owner(home)
            self.service.stopped(session_id="synthetic-session")
            return bound

        with (
            patch("secure_entry.payment.owner", side_effect=acquire),
            patch.dict(
                browser_tool._active_sessions, {self.key: {"features": {"local": True}}}
            ),
            patch("tools.browser_supervisor.SUPERVISOR_REGISTRY.capture") as capture,
        ):
            result = json.loads(
                self.facility.fill(self.args, task_id="synthetic-payment")
            )
        capture.assert_not_called()
        self.assertFalse(result["success"])

    def test_active_native_takeover_prevents_capture_without_metadata(self):
        from tools.bot_desktop import lease

        lease.acquire("synthetic-viewer")
        self.addCleanup(lease.release, "synthetic-viewer")
        with patch("tools.browser_supervisor.SUPERVISOR_REGISTRY.capture") as capture:
            result = json.loads(
                self.facility.fill(self.args, task_id="synthetic-payment")
            )
        capture.assert_not_called()
        self.assertFalse(result["success"])

    def test_native_takeover_during_capture_prevents_target(self):
        from tools.bot_desktop import lease
        from types import SimpleNamespace

        self.addCleanup(lease.release, "synthetic-viewer")

        def acquire(task):
            lease.acquire("synthetic-viewer")
            return SimpleNamespace(is_valid=lambda: True)

        with (
            patch(
                "tools.browser_supervisor.SUPERVISOR_REGISTRY.capture",
                side_effect=acquire,
            ),
            patch("secure_entry.payment.Target") as target,
        ):
            result = json.loads(
                self.facility.fill(self.args, task_id="synthetic-payment")
            )
        target.assert_not_called()
        self.assertFalse(result["success"])

    def test_takeover_then_handback_during_capture_still_invalidates_operation(self):
        from tools.bot_desktop import lease
        from types import SimpleNamespace

        self.addCleanup(lease.release, "synthetic-viewer")

        def acquire(task):
            lease.acquire("synthetic-viewer")
            lease.release("synthetic-viewer")
            return SimpleNamespace(is_valid=lambda: True)

        with (
            patch(
                "tools.browser_supervisor.SUPERVISOR_REGISTRY.capture",
                side_effect=acquire,
            ),
            patch("secure_entry.payment.Target") as target,
        ):
            result = json.loads(
                self.facility.fill(self.args, task_id="synthetic-payment")
            )
        target.assert_not_called()
        self.assertFalse(result["success"])

    def test_invalidated_capture_refuses_before_target(self):
        from types import SimpleNamespace

        with (
            patch(
                "tools.browser_supervisor.SUPERVISOR_REGISTRY.capture",
                return_value=SimpleNamespace(is_valid=lambda: False),
            ),
            patch("secure_entry.payment.Target") as target,
        ):
            result = json.loads(
                self.facility.fill(self.args, task_id="synthetic-payment")
            )
        target.assert_not_called()
        self.assertFalse(result["success"])

    def test_concurrent_stop_while_capture_pending_refuses_before_target(self):
        import threading
        from types import SimpleNamespace

        entered, resume = threading.Event(), threading.Event()
        results = []
        context = contextvars.copy_context()

        def acquire(task):
            entered.set()
            if not resume.wait(5):
                raise TimeoutError("test capture barrier")
            return SimpleNamespace(is_valid=lambda: True)

        with (
            patch(
                "tools.browser_supervisor.SUPERVISOR_REGISTRY.capture",
                side_effect=acquire,
            ),
            patch("secure_entry.payment.Target") as target,
        ):
            worker = threading.Thread(
                target=lambda: results.append(
                    context.run(
                        self.facility.fill, self.args, task_id="synthetic-payment"
                    )
                )
            )
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                self.service.stopped(session_id="synthetic-session")
            finally:
                resume.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
        target.assert_not_called()
        self.assertFalse(json.loads(results[0])["success"])

    def test_absent_capture_never_resolves_endpoint_or_starts_browser(self):
        from tools.browser_supervisor_capture import CapturedCDPInvalid

        with (
            patch(
                "tools.browser_supervisor.SUPERVISOR_REGISTRY.capture",
                side_effect=CapturedCDPInvalid("no synthetic route"),
            ),
            patch("tools.browser_supervisor.SUPERVISOR_REGISTRY.get_or_start") as start,
            patch("tools.browser_use_cli._resolve_backend_cdp") as resolve,
            patch("secure_entry.payment.Target") as target,
        ):
            result = json.loads(
                self.facility.fill(self.args, task_id="synthetic-payment")
            )
        start.assert_not_called()
        resolve.assert_not_called()
        target.assert_not_called()
        self.assertFalse(result["success"])

    def test_missing_task_local_identity_rejected_before_capture(self):
        with patch("tools.browser_supervisor.SUPERVISOR_REGISTRY.capture") as capture:
            result = contextvars.Context().run(
                self.facility.fill, self.args, task_id="synthetic-payment"
            )
        capture.assert_not_called()
        self.assertFalse(json.loads(result)["success"])


if __name__ == "__main__":
    unittest.main()
