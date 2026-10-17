"""Retained native payment consumer: local Link or site-bound native vault card.

Only registered metadata-only handlers invoke this consumer; ``card_source`` is
an internal plugin adapter, never a model-selected callable or script.
Authenticated owner admission, native vault-payment consent, retained
CapturedCDP, native takeover fences and redaction compose one synchronous fill.
Link retains its protected private-file handoff and independent authorization.
Saved native cards retain their merchant binding and explicit cleanup handle.
Neither route submits, purchases or deletes automatically.
"""

import json
import re
import time
from pathlib import Path
from .native import owner, validate_origin
from .payment_file import PrivateCard, PrivateFileRefused
from .payment_browser import BindingRefused, Target, WriteRefused


PAYMENT_DIAGNOSTIC_VERSION = "0.5.9"


class RetrievalRefused(ValueError):
    """Fixed, non-secret diagnostics only; never retain process output/errors."""

    CATEGORIES = frozenset(
        {
            "command_invalid",
            "subprocess_exit",
            "subprocess_timeout",
            "subprocess_unavailable",
            "output_too_large",
            "output_json_invalid",
            "output_envelope_mismatch",
            "output_id_mismatch",
            "output_status_mismatch",
            "producer_failed",
        }
    )

    def __init__(self, category, exit_status=None):
        super().__init__("link_retrieval_refused")
        self.category = category if category in self.CATEGORIES else "producer_failed"
        self.exit_status = exit_status if type(exit_status) is int else None


def retrieve_card(command, request_id, output):
    """Trusted operator-configured CLI prefix; no shell, spend creation or approval.

    Link itself must have approved this exact request. Its full private artifact
    is never stdout, model args, logs or vault storage. The metadata stdout is
    parsed privately, validated and discarded, never forwarded on any failure.
    """
    import subprocess

    try:
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(p, str) and p for p in command)
            or not Path(command[0]).is_absolute()
            or Path(command[0]).suffix.lower() in (".bat", ".cmd")
        ):
            raise RetrievalRefused("command_invalid")
        result = subprocess.run(
            [
                *command,
                "spend-request",
                "retrieve",
                request_id,
                "--include",
                "card",
                "--output-file",
                str(output),
                "--format",
                "json",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=40,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RetrievalRefused("subprocess_exit", result.returncode)
        if len(result.stdout) > 65536:
            raise RetrievalRefused("output_too_large")
        try:
            metadata = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise RetrievalRefused("output_json_invalid") from None
        # Link CLI 0.27.4 streams retrieve results as a JSON array. Require
        # exactly one result; never select an approved row from ambiguous output.
        if isinstance(metadata, list):
            if len(metadata) != 1:
                raise RetrievalRefused("output_envelope_mismatch")
            metadata = metadata[0]
        if not isinstance(metadata, dict):
            raise RetrievalRefused("output_envelope_mismatch")
        if metadata.get("id") != request_id:
            raise RetrievalRefused("output_id_mismatch")
        if metadata.get("status") != "approved":
            raise RetrievalRefused("output_status_mismatch")
    except RetrievalRefused:
        raise
    except subprocess.TimeoutExpired:
        raise RetrievalRefused("subprocess_timeout") from None
    except OSError:
        raise RetrievalRefused("subprocess_unavailable") from None
    except Exception:
        raise RetrievalRefused("producer_failed") from None


class LocalPayment:
    def __init__(self, service, command, *, retrieve=None, card_source=None):
        self.card_source = card_source
        self.service, self.command, self.retrieve = (
            service,
            command,
            retrieve or retrieve_card,
        )

    def fill(self, args, **kwargs):
        target, card = None, None
        stage = "admission"
        try:
            from hermes_cli.plugin_isolation import isolation_mode
            from tools.browser_supervisor import SUPERVISOR_REGISTRY
            from tools.bot_desktop import lease
            from tools.interrupt import is_interrupted
            from tools.approval_prompt import request_elicitation_consent
            from tools.approval_human_wait import human_wait_seconds
            from .redaction import register_payment_redaction_values

            if (
                isolation_mode() != "in_process"
                or (not self.command and self.card_source is None)
                or self.retrieve is None
            ):
                raise ValueError("facility_unavailable")
            with self.service.lock:
                if self.service.closed:
                    raise ValueError("operation_cancelled")
                generation = self.service.generation
            bound = owner(self.service.home)
            merchant = validate_origin(args["merchant_origin"])
            provider = validate_origin(args["frame_origin"])
            rid = self.card_source.identifier(args, merchant) if self.card_source else args["spend_request_id"]
            if self.card_source is None and (not isinstance(rid, str) or not re.fullmatch(
                r"lsrq_[A-Za-z0-9_]{1,100}", rid
            )):
                raise ValueError("invalid_request")
            task = kwargs.get("task_id")
            if not isinstance(task, str) or not task:
                raise ValueError("missing_task")
            deadline = time.monotonic() + 180
            # Route metadata is not secret authority. Public native capture below
            # pins the task's existing socket; Target binds the exact documents.
            # Fence ALL routes conservatively, including unknown/named/cloud CDP,
            # rather than infer desktop provenance from a legacy session cache.
            admitted = lease.assert_agent_may_act(str(self.service.home))
            capture = None

            # Synchronous native lease/lifecycle checks on the supervisor loop
            # immediately before dispatch. No capture, owner lookup or CDP here.
            def guard():
                if (
                    self.service.closed
                    or self.service.generation != generation
                    or is_interrupted()
                ):
                    raise ValueError("operation_cancelled")
                if time.monotonic() >= deadline:
                    raise ValueError("operation_timeout")
                try:
                    epoch = lease.assert_agent_may_act(str(self.service.home)).epoch
                except Exception:
                    raise ValueError("takeover_refused") from None
                if epoch != admitted.epoch:
                    raise ValueError("takeover_refused")
                if capture is not None and not capture.is_valid():
                    raise ValueError("browser_capture_invalid")

            def current():
                guard()
                if owner(self.service.home) != bound:
                    raise ValueError("owner_changed")

            def operation():
                nonlocal target, card, stage, capture, deadline
                current()
                capture = SUPERVISOR_REGISTRY.capture(task)
                current()
                stage = "target_binding"
                target = Target(
                    capture, args["parent"], args["frame"], merchant, provider, guard
                )
                stage = "native_consent"
                wait_before = human_wait_seconds(bound[-2])
                consent_started = time.monotonic()
                # Genuine existing native surface; no approval callbacks installed
                # or forged. Photon/gateway notification belongs to the host.
                verdict = request_elicitation_consent(
                    f"Fill saved payment on merchant {merchant}; payment frame {provider}; handle {rid}" if self.card_source else
                    f"Fill Link payment on merchant {merchant}; payment frame {provider}; request {rid}",
                    "Enter the site-bound saved card into this exact authorized merchant/payment-frame pair. "
                    "This does not submit, reserve or purchase. Card remains saved; explicitly delete after verifying checkout outcome." if self.card_source else
                    "Enter the approved one-time Link card into this exact checkout document. "
                    "This does not submit or purchase. No card is saved in the vault.",
                    surface="vault-payment",
                    title="Confirm saved card fill?" if self.card_source else "Confirm local Link card fill?",
                )
                # Credit only host-recorded, bounded human waiting during this
                # actual native consent call, never arbitrary wall-clock stalls.
                deadline += min(
                    max(0, time.monotonic() - consent_started),
                    max(0, human_wait_seconds(bound[-2]) - wait_before),
                )
                if verdict != "accept":
                    return {"success": False, "status": "payment_declined"}
                stage = "postconsent_current"
                current()
                stage = "postconsent_target"
                target.check()
                if self.card_source:
                    stage = "vault_card_resolve"
                    card = self.card_source.load(rid, merchant)
                else:
                    stage = "private_inbox"
                    root = Path(self.service.home) / "cache"
                    root.mkdir(parents=True, exist_ok=True)
                    with PrivateCard(root) as inbox:
                        stage = "link_retrieval_producer"
                        self.retrieve(self.command, rid, inbox.path)
                        stage = "post_retrieval_current"
                        current()
                        stage = "post_retrieval_target_check"
                        target.check()
                        stage = "private_file"
                        card = inbox.consume(rid, merchant)
                # Both sources use `number`; the plugin helper uses `card_number`.
                # Never register billing metadata or standalone expiry fragments.
                register_payment_redaction_values({
                    "card_number": card["number"], "cvc": card.get("cvc"),
                    "exp_month": card["exp_month"], "exp_year": card["exp_year"],
                })
                current()
                stage = "write"
                return target.fill(card)

            result = operation()
            current()
            return json.dumps(
                {**result, "payment_diagnostic_version": PAYMENT_DIAGNOSTIC_VERSION}
            )
        except Exception as exc:
            diagnostic = {}
            if isinstance(exc, RetrievalRefused):
                diagnostic = {"refusal": exc.category}
                if exc.exit_status is not None:
                    diagnostic["subprocess_exit_status"] = exc.exit_status
            elif isinstance(exc, BindingRefused):
                diagnostic = {"refusal": exc.category}
            elif stage == "write":
                diagnostic = {"refusal": "write_failed"}
                if isinstance(exc, WriteRefused):
                    safe = WriteRefused({"reason": exc.category, "field": exc.field, "written": exc.written})
                    diagnostic["refusal"] = safe.category
                    if safe.field is not None:
                        diagnostic["field"] = safe.field
                    if safe.written is not None:
                        diagnostic["written_fields"] = safe.written
            elif stage == "private_file":
                diagnostic = {
                    "refusal": exc.category
                    if isinstance(exc, PrivateFileRefused)
                    and isinstance(exc.category, str)
                    and exc.category in PrivateFileRefused.CATEGORIES
                    else "private_file_failed"
                }
                if isinstance(exc, PrivateFileRefused):
                    if exc.object_type in {"directory", "file"}:
                        diagnostic["private_object"] = exc.object_type
                    if exc.owner_class in PrivateFileRefused.OWNER_CLASSES:
                        diagnostic["owner_class"] = exc.owner_class
            elif stage == "link_retrieval_producer":
                diagnostic = {"refusal": "producer_failed"}
            elif stage == "native_consent":
                diagnostic = {
                    "refusal": "consent_timeout"
                    if isinstance(exc, TimeoutError)
                    else "consent_failed"
                }
            elif stage in {
                "post_retrieval_current",
                "postconsent_current",
                "postconsent_target",
            }:
                reason = (
                    exc.args[0]
                    if type(exc) is ValueError and len(exc.args) == 1
                    else None
                )
                diagnostic = {
                    "refusal": reason
                    if isinstance(reason, str)
                    and reason
                    in {
                        "operation_cancelled",
                        "operation_timeout",
                        "takeover_refused",
                        "browser_capture_invalid",
                        "owner_changed",
                    }
                    else (
                        "target_check_failed"
                        if stage == "postconsent_target"
                        else "current_check_failed"
                    )
                }
            elif stage == "post_retrieval_target_check":
                diagnostic = {"refusal": "target_check_failed"}
            return json.dumps(
                {
                    "success": False,
                    "status": "write_unknown"
                    if target and target.started
                    else "refused",
                    "stage": stage,
                    "payment_diagnostic_version": PAYMENT_DIAGNOSTIC_VERSION,
                    **diagnostic,
                }
            )
        finally:
            if card is not None:
                card.clear()
            if target is not None:
                target.close()
