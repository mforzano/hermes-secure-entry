"""Explicit sign-in password fill for a single inspected top-level input."""

import logging
import re
from typing import ClassVar

from .native import validate_origin
from .signup import SavedPasswordFill, SavedPasswordTarget, validate_nodes

LOGIN_DIAGNOSTIC_VERSION = "0.5.20"
LOGIN_ARGS = frozenset(
    {"handle", "identifier", "origin", "parent", "frame", "loader_id", "password_node"}
)


class LoginTarget(SavedPasswordTarget):
    def __init__(self, capture, args, guard):
        self.loader_id = args["loader_id"]
        super().__init__(capture, args, guard)

    def check_document(self):
        root = self.call("Page.getFrameTree", {}, self.psid)["frameTree"]["frame"]
        if root["id"] != self.frame or root.get("loaderId") != self.loader_id:
            raise ValueError("document_changed")

    def world(self, frame, sid):
        # The shared target supports iframes/offsite roots for other operations;
        # login supports only the inspected top-level document at the vault origin.
        self.check_document()
        return super().world(frame, sid)

    def check(self):
        self.check_document()
        super().check()


class LoginFill(SavedPasswordFill):
    target_type = LoginTarget
    diagnostic: ClassVar[dict[str, str]] = {
        "login_diagnostic_version": LOGIN_DIAGNOSTIC_VERSION
    }

    def prepare(self, args):
        args = dict(args)
        if args.keys() != LOGIN_ARGS:
            raise ValueError("invalid_arguments")
        for key in ("parent", "frame", "loader_id"):
            if not isinstance(args[key], str) or not re.fullmatch(r"[0-9A-Fa-f]{32}", args[key]):
                raise ValueError("invalid_document_identity")
        args["frame_origin"] = args["origin"] = validate_origin(args["origin"])
        args["password_nodes"] = validate_nodes([args["password_node"]])
        return args

    def check_transport(self):
        # WebSocket frame tracing can otherwise record CDP arguments before
        # application-level redaction, including the password write.
        if logging.getLogger("websockets.client").isEnabledFor(logging.DEBUG):
            raise ValueError("unsafe_browser_logging")

    def consent(self, args, target):
        origin = args["origin"]
        return (
            f"Sign-in password fill for {args['identifier']} at {origin}; saved login {args['handle']}",
            (
                f"Sign-in destination and password document origin {origin}; exact page {target.parent}; "
                f"root frame {target.frame}; document loader {target.loader_id}; "
                f"selected password backendNodeId {args['password_node']}. "
                "Fill only this sign-in password field with the saved password, replacing any prefill. "
                "No identifier is typed and no form is submitted by this tool."
            ),
            "Confirm sign-in password fill?",
        )
