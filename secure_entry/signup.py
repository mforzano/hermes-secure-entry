"""Retained password writer and explicit registration-password adapter.

Version-pinned server-side native VaultStore/approval APIs, NOT a public SDK
password provider. Secrets exist only in this native handler and captured CDP.
"""

import json
import re
import time
from typing import ClassVar

from .native import owner, validate_origin
from .payment_browser import Target

SIGNUP_DIAGNOSTIC_VERSION = "0.5.17"

# Fixed native-only code. No caller script, selectors, attribute rewriting or
# broad form inventory. Resolve actual inspected nodes ONCE, before consent.
PASSWORDS = r"""function(...fields) {
 const doc=document, href=location.href, origin=location.origin;
 const usable=e=>e instanceof HTMLInputElement && e.ownerDocument===doc &&
   e.isConnected && e.type==='password' && !e.matches(':disabled') && !e.readOnly &&
   e.getClientRects().length>0 && getComputedStyle(e).visibility==='visible' &&
   !e.closest('[inert]');
 if(!fields.length || new Set(fields).size!==fields.length || !fields.every(usable))throw Error('targets');
 const semantic=['type','name','form','autocomplete'];
 const attributes=fields.map(e=>semantic.map(a=>e.getAttribute(a)));
 let changed=false, used=false, writing=null;
 const relevant=records=>records.some((r,k)=>{
   if(r.type==='childList')return [...r.removedNodes].some(n=>fields.some(e=>n===e || n.contains(e)));
   if(!fields.includes(r.target))return false;
   if(semantic.includes(r.attributeName)) {
     const next=records.slice(k+1).find(n=>n.target===r.target && n.attributeName===r.attributeName);
     return r.oldValue!==(next?next.oldValue:r.target.getAttribute(r.attributeName));
   }
   if(r.attributeName==='value' && writing && r.target===writing.node){
     const next=records.slice(k+1).find(n=>n.target===r.target && n.attributeName==='value');
     return (next?next.oldValue:r.target.getAttribute('value'))!==writing.value;
   }
   return false;
 });
 const observer=new MutationObserver(rs=>{if(relevant(rs))changed=true;});
 observer.observe(doc,{subtree:true,childList:true,attributes:true,attributeOldValue:true});
 const valid=()=>{if(relevant(observer.takeRecords()))changed=true;
   return !changed && document===doc && location.href===href && location.origin===origin &&
     fields.every((e,i)=>usable(e) && semantic.every((a,j)=>e.getAttribute(a)===attributes[i][j]));};
 const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
 return {origin,valid,
   write(password){
     let written=0;
     const fail=()=>({valid:false,written});
     if(used || typeof password!=='string' || !password || !valid())return fail();
     used=true;
     for(const e of fields){
       if(!valid())return fail();
       writing={node:e,value:password};
       try {
         setter.call(e,password);written++;
         e.dispatchEvent(new Event('input',{bubbles:true}));
         if(!valid() || e.value!==password)return fail();
         e.dispatchEvent(new Event('change',{bubbles:true}));
         if(!valid() || e.value!==password)return fail();
       } finally {writing=null;}
     }
     return {valid:valid() && fields.every(e=>e.value===password && e.checkValidity()),written};
   },close(){changed=true;observer.disconnect();}};
}"""


def validate_nodes(nodes):
    if (
        not isinstance(nodes, list)
        or not nodes
        or any(type(n) is not int or n < 1 for n in nodes)
        or len(set(nodes)) != len(nodes)
    ):
        raise ValueError("invalid_targets")
    return list(nodes)


class RetainedInputTarget(Target):
    def __init__(self, capture, args, guard):
        self.nodes = validate_nodes(args[self.field_key])
        # Non-None mapping selects the existing mapped parent/frame policy only.
        super().__init__(
            capture,
            args["parent"],
            args["frame"],
            args["origin"],
            args["frame_origin"],
            guard,
            field_mapping={},
        )

    def bind_fields(self, context, sid):
        nodes = []
        try:
            for backend in self.nodes:
                node = self.call(
                    "DOM.resolveNode",
                    {
                        "backendNodeId": backend,
                        "executionContextId": context,
                        "objectGroup": self.group,
                    },
                    sid,
                )["object"]["objectId"]
                nodes.append(node)
            return self.remote(
                "Runtime.callFunctionOn",
                {
                    "executionContextId": context,
                    "functionDeclaration": self.binding,
                    "arguments": [{"objectId": n} for n in nodes],
                },
                sid,
            )
        finally:
            for node in nodes:
                try:
                    self.call(
                        "Runtime.releaseObject", {"objectId": node}, sid, cleanup=True
                    )
                except Exception:  # noqa: BLE001, S110 -- private cleanup; never log CDP errors
                    pass


class SavedPasswordTarget(RetainedInputTarget):
    field_key = "password_nodes"
    binding = PASSWORDS

    def fill_password(self, password):
        self.check()
        self.started = True  # dispatch may write even if CDP's reply is lost
        result = self.invoke(
            self.csid, self.cg, "function(p){return this.write(p);}", (password,)
        )
        self.check()
        if (
            not isinstance(result, dict)
            or result.get("valid") is not True
            or type(result.get("written")) is not int
            or result["written"] != len(self.nodes)
        ):
            raise ValueError("write_unverified")
        return {
            "success": True,
            "status": "filled",
            "filled_fields": len(self.nodes),
            "submitted": False,
        }


class SavedPasswordFill:
    def __init__(self, service):
        self.service = service

    def prepare(self, args):
        args = dict(args)
        args["password_nodes"] = validate_nodes(args["password_nodes"])
        args["origin"] = validate_origin(args["origin"])
        args["frame_origin"] = validate_origin(args["frame_origin"])
        return args

    def check_transport(self):
        pass

    def fill(self, args, **kwargs):
        target, secret = None, None
        stage = "admission"
        try:
            from agent.redact import register_vault_redaction_value
            from agent.vault_store import get_vault_store
            from hermes_cli.plugin_isolation import isolation_mode
            from tools.approval_human_wait import human_wait_seconds
            from tools.approval_prompt import request_elicitation_consent
            from tools.bot_desktop import lease
            from tools.browser_supervisor import SUPERVISOR_REGISTRY
            from tools.interrupt import is_interrupted

            if isolation_mode() != "in_process":
                raise ValueError("facility_unavailable")
            self.check_transport()
            with self.service.lock:
                if self.service.closed:
                    raise ValueError("operation_cancelled")
                generation = self.service.generation
            bound = owner(self.service.home)
            args = self.prepare(args)
            origin = args["origin"]
            handle, identifier = args["handle"], args["identifier"]
            if not isinstance(handle, str) or not re.fullmatch(
                r"vault_[0-9a-f]{12}", handle
            ):
                raise ValueError("invalid_handle")
            if (
                not isinstance(identifier, str)
                or not identifier
                or len(identifier) > 1024
                or any(ord(c) < 32 or ord(c) == 127 for c in identifier)
            ):
                raise ValueError("invalid_identifier")
            task = kwargs.get("task_id")
            if not isinstance(task, str) or not task:
                raise ValueError("missing_task")
            deadline = time.monotonic() + 180
            admitted = lease.assert_agent_may_act(str(self.service.home))
            capture = None

            def guard():
                self.check_transport()
                if (
                    self.service.closed
                    or self.service.generation != generation
                    or is_interrupted()
                ):
                    raise ValueError("operation_cancelled")
                if time.monotonic() >= deadline:
                    raise ValueError("operation_timeout")
                if (
                    lease.assert_agent_may_act(str(self.service.home)).epoch
                    != admitted.epoch
                ):
                    raise ValueError("takeover_refused")
                if capture is not None and not capture.is_valid():
                    raise ValueError("browser_capture_invalid")

            def current():
                guard()
                if owner(self.service.home) != bound:
                    raise ValueError("owner_changed")

            current()
            store = (
                self.service.store_factory()
                if self.service.store_factory
                else get_vault_store()
            )

            def metadata():
                meta = store.get_meta(handle)
                if (
                    meta is None
                    or meta.id != handle
                    or meta.kind != "login"
                    or meta.origin != origin
                    or meta.identifier != identifier
                ):
                    raise ValueError("account_mismatch")

            metadata()
            current()
            capture = SUPERVISOR_REGISTRY.capture(task)
            current()
            stage = "target_binding"
            target = self.target_type(capture, args, guard)
            stage = "native_consent"
            wait_before = human_wait_seconds(bound[-2])
            started = time.monotonic()
            message, description, title = self.consent(args, target)
            verdict = request_elicitation_consent(message, description, surface="vault-login", title=title)
            deadline += min(
                max(0, time.monotonic() - started),
                max(0, human_wait_seconds(bound[-2]) - wait_before),
            )
            if verdict != "accept":
                return json.dumps(
                    {
                        "success": False,
                        "status": "consent_declined",
                        **self.diagnostic,
                    }
                )
            stage = "postconsent_current"
            current()
            stage = "postconsent_target"
            target.check()
            stage = "vault_metadata"
            metadata()
            current()
            stage = "vault_resolve"
            self.check_transport()
            secret = store.resolve_secret(handle)
            password = secret.get("password")
            if not isinstance(password, str) or not password:
                raise ValueError("source_unavailable")
            register_vault_redaction_value(password)
            current()
            metadata()
            target.check()
            stage = "write"
            result = target.fill_password(password)
            current()
            return json.dumps({**result, **self.diagnostic})
        except Exception:  # noqa: BLE001 -- value-free native exception boundary
            # Neither raw native errors nor CDP exceptionDetails cross this boundary.
            return json.dumps(
                {
                    "success": False,
                    "status": "write_unknown"
                    if target is not None and target.started
                    else "refused",
                    "stage": stage,
                    "reinspection_required": stage
                    in {"target_binding", "postconsent_target", "write"},
                    **self.diagnostic,
                }
            )
        finally:
            if secret is not None:
                secret.clear()
            if target is not None:
                target.close()


class SignupTarget(SavedPasswordTarget):
    pass


class SignupFill(SavedPasswordFill):
    target_type = SignupTarget
    diagnostic: ClassVar[dict[str, str]] = {
        "signup_diagnostic_version": SIGNUP_DIAGNOSTIC_VERSION
    }

    def consent(self, args, target):
        origin = args["origin"]
        return (
            f"Registration password fill for {args['identifier']} at {origin}; saved login {args['handle']}",
            f"Registration destination {origin}; password document {args['frame_origin']}; "
            f"exact page {target.parent}; frame {target.frame}; selected password backendNodeIds "
            + ", ".join(str(n) for n in args["password_nodes"])
            + ". "
            "Fill ONLY these selected actual password fields with the saved password, including confirmation if selected. "
            "Selected prefills may be replaced. No identifier is typed, no form is submitted and no account is created by this tool. "
            + (
                "No live registration-origin parent is retained for this offsite top-level document. "
                if getattr(target, "offsite_root", False)
                else ""
            ),
            "Confirm registration password fill?",
        )
