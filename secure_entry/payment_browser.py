"""Registered payment facility's exact-document browser transport.

Only native CapturedCDP handles; never endpoint discovery, page searching, main
world injection, model JavaScript/selectors, or submission. Deliberately strict:
one direct iframe, one form or cohesive container, standard autocomplete.
PAN/expiry/CVC must be empty; matching issued public billing stays private.
Parent pre/post checks are not an atomic cross-document no-disclosure fence.
Inspired by the reviewed secure-env-ingress design; no source copied (upstream
has no declared license). Remote object IDs retain document/node identity in an
isolated world; navigation destroys them rather than retargeting a new document.
"""

import secrets

# Generated fixed code runs only inside the registered native payment facility.
# All authority is closure-private in a fresh isolated world, never DOM stamps.
PARENT = r"""function(expected) {
 const doc=document, href=location.href, node=this;
 const lineage=[];
 for(let e=node;e;e=e.parentNode)lineage.push(e);
 if(node.tagName!=='IFRAME' || lineage[lineage.length-1]!==doc)throw Error('unsupported');
 // Retain exact ancestry. Observe records, not just final state, so removal or
 // security-attribute mutation followed by restoration remains a refusal.
 const relevant=records=>records.some(r=>r.type==='attributes'
   ? lineage.includes(r.target) && r.attributeName!=='title' && !r.attributeName.startsWith('aria-')
   : Array.from(r.removedNodes).some(n=>lineage.includes(n)));
 let changed=false;
 const observer=new MutationObserver(records=>{if(relevant(records))changed=true;});
 observer.observe(doc,{subtree:true,childList:true,attributes:true});
 return {valid(){if(relevant(observer.takeRecords()))changed=true;
   return !changed && document===doc && location.href===href && location.origin===expected &&
     node.isConnected && lineage.every((e,i)=>e.ownerDocument===doc || e===doc) &&
     lineage.every((e,i)=>e.parentNode===(lineage[i+1] || null));},
   close(){changed=true;observer.disconnect();}};
}"""
CHILD = r"""(() => {
 const doc=document, href=location.href, origin=location.origin;
 const forms=Array.from(doc.forms);
 if(forms.length>1)throw Error('unsupported');
 const form=forms[0] || null;
 // Action, grouping and derived-output controls are not data-entry targets.
 // Apply the same inventory filter globally so unsupported data inputs outside
 // the form still refuse. Unknown form-associated control types stay rejected.
 const dataControl=e=>!['BUTTON','FIELDSET','OUTPUT'].includes(e.tagName) &&
   !(e.tagName==='INPUT' && ['submit','reset','button','image'].includes(e.type));
 const documentFields=Array.from(doc.querySelectorAll('input,select,textarea')).filter(dataControl);
 const fields=form ? Array.from(form.elements).filter(dataControl) : documentFields;
 // A null form owner alone is not a group. Retain the smallest common
 // non-document container; sibling widgets joined only by body/html refuse.
 let container=form || (fields[0] && fields[0].parentElement);
 if(!form){
   if(fields.some(e=>e.form!==null))throw Error('unsupported');
   while(container && !fields.every(e=>container.contains(e)))container=container.parentElement;
   if(!container || container===doc.body || container===doc.documentElement)throw Error('unsupported');
 }
 const parents=fields.map(e=>e.parentNode);
 const allowed=['cc-number','cc-exp','cc-exp-month','cc-exp-year','cc-csc','cc-name',
   'billing country','billing address-line1','billing address-line2','billing address-level2',
   'billing address-level1','billing postal-code','billing tel'];
 // Canonicalize only the standard unsectioned postal token for billing lookup.
 // Retain the original descriptors for authority checks; never edit page attributes.
 const autocomplete=fields.map(e=>e.autocomplete);
 const tokens=autocomplete.map(t=>t==='postal-code'?'billing postal-code':t);
 if(documentFields.length!==fields.length ||
   fields.some((e,i)=>!['INPUT','SELECT'].includes(e.tagName) || !allowed.includes(tokens[i]) ||
     (e.tagName==='SELECT' && !['billing country','billing address-level1'].includes(e.autocomplete))) ||
   new Set(tokens).size!==tokens.length || !tokens.includes('cc-number') ||
   (tokens.includes('cc-exp') ? tokens.includes('cc-exp-month') || tokens.includes('cc-exp-year') :
     !tokens.includes('cc-exp-month') || !tokens.includes('cc-exp-year')))throw Error('unsupported');
 const credential=i=>tokens[i].startsWith('cc-') && tokens[i]!=='cc-name';
 const visible=e=>!['hidden','password','checkbox','radio','file','submit','button'].includes(e.type) &&
   e.getClientRects().length && getComputedStyle(e).visibility==='visible';
 const disabled=fields.map(e=>e.matches(':disabled'));
 const readonly=fields.map(e=>!!e.readOnly);
 // Billing availability is not credential authority. Retain even unavailable
 // billing nodes; never admit unavailable or prefilled PAN/expiry/CVC.
 if(fields.some((e,i)=>!visible(e) || (credential(i) && (disabled[i] || readonly[i] || e.value))))throw Error('unsupported');
 const initial=fields.map(e=>e.value);
 const initiallyDisabled=disabled.slice(), settled=new Set();
 let changed=false, used=false;
 // Retain every control/group ancestor, not unrelated presentation subtrees.
 // Mutation records make removal/reparent and security changes sticky even if
 // restored synchronously before the next check. Class is widget presentation;
 // actual visibility/usability is still checked before and after each event.
 const lineages=fields.map(e=>{const a=[];for(;e;e=e.parentNode)a.push(e);return a;});
 const retained=new Set(lineages.flat());
 const selects=fields.filter(e=>e.tagName==='SELECT');
 const semanticNode=n=>n.nodeType===1 && (n.matches('input,select,textarea,form,base') || n.querySelector('input,select,textarea,form,base'));
 // Only the currently dispatched self-write may reflect into its INPUT value
 // attribute. Keep exact semantic PAN/expiry invariants, including every queued
 // intermediate attribute value (oldValue reconstructs synchronous restoration).
 let reflection=null;
 const mayTransition=i=>reflection!==null && initiallyDisabled[i] && !credential(i) && !settled.has(i);
 const billingStateRecord=r=>{
   if(!reflection || r.attributeName!=='disabled')return false;
   const legend=r.target.tagName==='FIELDSET' ? Array.from(r.target.children).find(e=>e.tagName==='LEGEND') : null;
   const affected=fields.map((e,i)=>e===r.target ||
     (r.target.tagName==='FIELDSET' && r.target.contains(e) && !(legend && legend.contains(e))) ? i : -1).filter(i=>i>=0);
   return affected.length>0 && affected.every(mayTransition);
 };
 const reflects=(v,i,want)=>v===want || (tokens[i]==='cc-number' &&
   /^[0-9]+(?:[ -][0-9]+)*$/.test(v) && v.replace(/[ -]/g,'')===want) ||
   (tokens[i]==='cc-exp' && /^[0-9]{2} *\/ *[0-9]{2}$/.test(v) && v.replace(/ /g,'')===want);
 const securityRecords=records=>records.some((r,k)=>{
   // An excluded action INPUT must not turn into an unretained data control,
   // even if its type is restored before the next check.
   if(r.type==='attributes' && r.attributeName==='type' && r.target.tagName==='INPUT')return true;
   if(r.type==='attributes' && r.attributeName==='value' && reflection &&
     r.target===fields[reflection.i] && r.target.tagName==='INPUT'){
     const next=records.slice(k+1).find(n=>n.type==='attributes' && n.target===r.target && n.attributeName==='value');
     const value=next ? next.oldValue : r.target.getAttribute('value');
     return value===null || !reflects(value,reflection.i,reflection.value) ||
       !reflects(r.target.value,reflection.i,reflection.value);
   }
   if(r.type==='attributes' && billingStateRecord(r))return false;
   if(r.type==='attributes')return (retained.has(r.target) ||
     selects.some(e=>e.contains(r.target)) || r.target.tagName==='BASE') &&
     !['class','aria-invalid','aria-describedby','aria-errormessage'].includes(r.attributeName);
   if(r.type==='characterData')return selects.some(e=>e.contains(r.target));
   return Array.from(r.removedNodes).some(n=>retained.has(n) || semanticNode(n)) ||
     Array.from(r.addedNodes).some(semanticNode) || selects.some(e=>e.contains(r.target));
 });
 const observer=new MutationObserver(records=>{if(securityRecords(records))changed=true;});
 observer.observe(doc,{subtree:true,childList:true,attributes:true,attributeOldValue:true,characterData:true});
 const valid=()=>{if(securityRecords(observer.takeRecords()))changed=true;
   fields.forEach((e,i)=>{
     const state=e.matches(':disabled');
     if(state!==disabled[i]){if(!mayTransition(i))changed=true;else disabled[i]=state;}
     if(!!e.readOnly!==readonly[i])changed=true;
   });
   return !changed && document===doc && location.href===href && location.origin===origin &&
     container.isConnected && container.ownerDocument===doc && fields.every((e,i)=>e.isConnected && e.form===form && container.contains(e) && e.parentNode===parents[i] && e.ownerDocument===doc && visible(e) && e.autocomplete===autocomplete[i]);};
 const setters={INPUT:Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set,
   SELECT:Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set};
 return {valid, origin,
   write(card){const values=tokens.map(t=>card[t]);
     // Phone is contact metadata, not Link's billing identity: preserve a prefilled
     // value privately. Never use guest profile fields in place of issued billing.
     // Saved native cards do not contain full billing addresses. Preserve only
     // unsupplied billing controls, including blank optional line2, in this mode.
     // Supplied identity (name/postal) still must match; Link keeps issued billing.
     values.forEach((v,i)=>{if(v===undefined && tokens[i].startsWith('billing ') &&
       card.preserve_unsupplied_billing===true && fields[i].checkValidity() &&
       (!fields[i].required || initial[i].trim()!==''))values[i]=initial[i];});
     values.forEach((v,i)=>{if(tokens[i]==='billing tel' && v===undefined)values[i]=initial[i] || undefined;});
     let written=0;
     const refuse=(reason,i)=>({written,valid:false,reason,...(i>=0?{field:tokens[i]}:{})});
     if(used)return refuse('already_used');
     if(!valid())return refuse('invalidated');
     const unavailable=i=>fields[i].matches(':disabled') || !!fields[i].readOnly;
     const skippable=i=>!credential(i) && unavailable(i) && !fields[i].required;
     const skipped=[];
     let index=values.findIndex((v,i)=>typeof v!=='string' && !skippable(i));
     if(index>=0)return refuse('source_missing',index);
     index=fields.findIndex((e,i)=>e.value!==initial[i]);
     if(index>=0)return refuse('field_changed',index);
     index=fields.findIndex((e,i)=>initial[i] && initial[i]!==values[i]);
     if(index>=0)return refuse('initial_mismatch',index);
     index=fields.findIndex((e,i)=>e.tagName==='SELECT' && !unavailable(i) &&
       Array.from(e.options).filter(o=>o.value===values[i] && !o.disabled && !o.parentElement.disabled).length!==1);
     if(index>=0)return refuse('select_mismatch',index);
     used=true;
     const expected=initial.slice();
     // Dependencies may enable billing on expiry/CVC, not only on PAN. Process
     // credential events first, then settle billing against its current state.
     const order=fields.map((e,i)=>i).sort((a,b)=>Number(credential(b))-Number(credential(a)));
     while(order.length){
       const next=order.findIndex(i=>!unavailable(i));
       const i=order.splice(next<0?0:next,1)[0];
       if(!valid())return refuse('invalidated');
       index=fields.findIndex((e,j)=>e.value!==expected[j]);
       if(index>=0)return refuse('field_changed',index);
       if(unavailable(i)){
         if(!fields[i].matches(':disabled') && fields[i].value===values[i] &&
           (!fields[i].required || fields[i].value.trim()!=='')){settled.add(i);continue;}
         if(!skippable(i))return refuse('billing_unavailable',i);
         skipped.push(tokens[i]);continue;
       }
       if(typeof values[i]!=='string')return refuse('source_missing',i);
       if(card.preserve_unsupplied_billing===true && tokens[i].startsWith('billing ') &&
         card[tokens[i]]===undefined && !fields[i].checkValidity())return refuse('source_missing',i);
       if(fields[i].tagName==='SELECT' && Array.from(fields[i].options).filter(o=>
         o.value===values[i] && !o.disabled && !o.parentElement.disabled).length!==1)return refuse('select_mismatch',i);
       settled.add(i);
       if(fields[i].value===values[i])continue;
       reflection={i,value:values[i]};
       try {
         setters[fields[i].tagName].call(fields[i],values[i]);written++;
         expected[i]=values[i];
         fields[i].dispatchEvent(new Event('input',{bubbles:true}));
         if(!valid())return refuse('invalidated');
         fields[i].dispatchEvent(new Event('change',{bubbles:true}));
         if(!valid())return refuse('invalidated');
         const actual=fields[i].value;
         if(tokens[i]==='cc-number' && /^[0-9]+(?:[ -][0-9]+)*$/.test(actual) && actual.replace(/[ -]/g,'')===values[i])expected[i]=actual;
         else if(tokens[i]==='cc-exp' && /^[0-9]{2} *\/ *[0-9]{2}$/.test(actual) && actual.replace(/ /g,'')===values[i])expected[i]=actual;
         else if(actual!==values[i])return refuse(actual===initial[i]?'unchanged':tokens[i]==='cc-exp'?'expiry_format':'write_mismatch',i);
       } finally {reflection=null;}
     }
     if(!valid())return refuse('invalidated');
     index=fields.findIndex((e,i)=>e.value!==expected[i]);
     if(index>=0)return refuse('field_changed',index);
     return {written,valid:true,skipped};},
   close(){changed=true;observer.disconnect();}};
})()"""


class WriteRefused(ValueError):
    """Fixed writer diagnostics, sanitized again at the public result boundary."""

    CATEGORIES = frozenset({
        "initial_mismatch", "source_missing", "field_changed", "invalidated",
        "select_mismatch", "unchanged", "expiry_format", "write_mismatch", "already_used",
        "billing_unavailable",
    })
    TOKENS = frozenset({
        "cc-number", "cc-exp", "cc-exp-month", "cc-exp-year", "cc-csc", "cc-name",
        "billing country", "billing address-line1", "billing address-line2",
        "billing address-level2", "billing address-level1", "billing postal-code", "billing tel",
    })

    def __init__(self, result):
        self.category = result.get("reason") if isinstance(result.get("reason"), str) and result["reason"] in self.CATEGORIES else "write_failed"
        self.field = result.get("field") if isinstance(result.get("field"), str) and result["field"] in self.TOKENS else None
        count = result.get("written")
        self.written = count if type(count) is int and 0 <= count <= len(self.TOKENS) else None
        super().__init__("write_unknown")


class BindingRefused(ValueError):
    """Only fixed public categories; never forward CDP exceptions or DOM data."""

    def __init__(self, category):
        self.category = category
        super().__init__("target_refused")


class Target:
    def __init__(self, capture, parent, frame, merchant, provider, guard):
        self.capture, self.guard = capture, guard
        self.parent, self.frame = parent, frame
        self.merchant, self.provider = merchant, provider
        self.psid = capture.page_session_id
        self.csid = self.psid
        self.objects = []
        self.group = "secure-entry-payment-" + secrets.token_hex(16)
        self.attached = False
        self.parent_attached = False
        self.closed = False
        self.started = False
        category = "selected_parent"
        try:
            info = self.call("Target.getTargetInfo", {"targetId": parent})["targetInfo"]
            if info["targetId"] != parent or info["type"] != "page":
                raise ValueError("target_refused")
            default = self.call("Target.getTargetInfo", {}, self.psid)["targetInfo"]
            if default["targetId"] != parent:
                # Attach only this explicit page on the captured socket. No page
                # enumeration, endpoint lookup, focus change or new browser.
                self.psid = self.attach_frame(parent)
                self.parent_attached = True
                self.csid = self.psid
            selected = self.call("Target.getTargetInfo", {}, self.psid)["targetInfo"]
            if selected["targetId"] != parent or selected["type"] != "page":
                raise ValueError("target_refused")
            category = "frame_lineage"
            tree = self.call("Page.getFrameTree", {}, self.psid)["frameTree"]
            root = tree["frame"]["id"]
            owner = self.call("DOM.getFrameOwner", {"frameId": frame}, self.psid)[
                "backendNodeId"
            ]
            # getFrameOwner in this page proves lineage; direct parent check is
            # enforced in the isolated world by resolving the actual owner node.
            context = self.world(root, self.psid)
            node = self.call(
                "DOM.resolveNode",
                {"backendNodeId": owner, "executionContextId": context},
                self.psid,
            )["object"]["objectId"]
            try:
                self.pg = self.remote(
                    "Runtime.callFunctionOn",
                    {
                        "objectId": node,
                        "functionDeclaration": PARENT,
                        "arguments": [{"value": merchant}],
                    },
                    self.psid,
                )
            finally:
                self.call("Runtime.releaseObject", {"objectId": node}, self.psid)
            try:
                context = self.world(frame, self.csid)
            except Exception:
                self.csid = self.attach_frame(frame)
                self.attached = True
                context = self.world(frame, self.csid)
            category = "form_layout"
            self.cg = self.remote(
                "Runtime.evaluate",
                {"expression": CHILD, "contextId": context},
                self.csid,
            )
            category = "frame_lineage"
            if (
                self.invoke(self.csid, self.cg, "function(){return this.origin;}")
                != provider
            ):
                raise ValueError("target_refused")
            self.check()
        except Exception:
            self.close()
            raise BindingRefused(category) from None
        except BaseException:
            self.close()
            raise

    def attach_frame(self, frame, timeout=5):
        # A finite CDP timeout can discard a successful attachment's late ID.
        # Keep the original socket's reply in a consumer-owned worker; after
        # abandonment that worker owns detach, never any replacement socket.
        import threading
        from contextvars import copy_context

        done, lock = threading.Event(), threading.Lock()
        state = {"abandoned": False, "sid": None, "failed": False}

        def detach(sid):
            try:
                self.capture.call(
                    "Target.detachFromTarget", {"sessionId": sid}, timeout=None
                )
            except Exception:
                pass

        def before_send():
            self.guard()
            if self.closed or state["abandoned"]:
                raise ValueError("target_refused")

        def worker():
            sid = None
            try:
                sid = self.capture.call(
                    "Target.attachToTarget",
                    {"targetId": frame, "flatten": True},
                    timeout=None,
                    before_send=before_send,
                )["result"]["sessionId"]
                with lock:
                    if not state["abandoned"]:
                        state["sid"] = sid
                        sid = None
            except Exception:
                with lock:
                    state["failed"] = True
            finally:
                done.set()
                if sid:
                    detach(sid)

        context = copy_context()
        threading.Thread(
            target=lambda: context.run(worker),
            daemon=True,
            name="secure-entry-payment-attach",
        ).start()
        if not done.wait(timeout):
            with lock:
                state["abandoned"] = True
                sid, state["sid"] = state["sid"], None
            if sid:
                threading.Thread(target=lambda: detach(sid), daemon=True).start()
            raise TimeoutError("frame_attachment_timeout")
        with lock:
            if state["failed"] or not state["sid"]:
                raise ValueError("target_refused")
            return state["sid"]

    def call(self, method, params, sid=None, *, cleanup=False):
        def before_send():
            if not cleanup:
                self.guard()
                if self.closed:
                    raise ValueError("target_refused")

        return self.capture.call(
            method, params, session_id=sid, before_send=before_send
        )["result"]

    def world(self, frame, sid):
        return self.call(
            "Page.createIsolatedWorld",
            {
                "frameId": frame,
                "worldName": "secure-entry-payment-" + secrets.token_hex(16),
            },
            sid,
        )["executionContextId"]

    def remote(self, method, params, sid):
        response = self.call(method, {**params, "objectGroup": self.group}, sid)
        if response.get("exceptionDetails") or not response.get("result", {}).get(
            "objectId"
        ):
            raise ValueError("target_refused")
        obj = response["result"]["objectId"]
        self.objects.append((sid, obj))
        return obj

    def invoke(self, sid, obj, function, args=()):
        response = self.call(
            "Runtime.callFunctionOn",
            {
                "objectId": obj,
                "functionDeclaration": function,
                "arguments": [{"value": v} for v in args],
                "returnByValue": True,
            },
            sid,
        )
        if response.get("exceptionDetails"):
            raise ValueError("target_refused")
        return response.get("result", {}).get("value")

    def check(self):
        self.guard()
        if self.closed or not self.capture.is_valid():
            raise ValueError("target_refused")
        for sid, obj in ((self.psid, self.pg), (self.csid, self.cg)):
            if self.invoke(sid, obj, "function(){return this.valid();}") is not True:
                raise ValueError("target_refused")

    def fill(self, card):
        self.check()
        billing = card.get("billing_address", {})
        billing_values = {
            token: billing[key]
            for token, key in {
                "cc-name": "name",
                "billing country": "country",
                "billing address-line1": "line1",
                "billing address-level2": "city",
                "billing address-level1": "state",
                "billing postal-code": "postal_code",
            }.items()
            if key in billing
        }
        preserve_billing = card.get("preserve_unsupplied_billing") is True
        if billing and (not preserve_billing or "line2" in billing):
            billing_values["billing address-line2"] = billing.get("line2", "")
        billing_values["preserve_unsupplied_billing"] = preserve_billing
        self.started = True
        result = self.invoke(
            self.csid,
            self.cg,
            "function(values){return this.write(values);}",
            (
                {
                    **billing_values,
                    "cc-number": card["number"],
                    "cc-exp-month": str(card["exp_month"]).zfill(2),
                    "cc-exp-year": str(card["exp_year"]),
                    "cc-exp": f"{card['exp_month']:02d}/{card['exp_year'] % 100:02d}",
                    "cc-csc": card.get("cvc"),
                },
            ),
        )
        try:
            self.check()
        except Exception:
            # Keep an actual writer refusal even when it invalidates its own
            # retained document. Never turn a failed postflight into success.
            raise WriteRefused(
                result if isinstance(result, dict) and result.get("valid") is False else {}
            ) from None
        if (
            not isinstance(result, dict)
            or result.get("valid") is not True
            or not isinstance(result.get("written"), int)
            or result["written"] < 2
        ):
            raise WriteRefused(result if isinstance(result, dict) else {})
        response = {"success": True, "status": "filled", "filled_fields": result["written"]}
        skipped = result.get("skipped", [])
        if skipped:
            if not isinstance(skipped, list) or any(
                not isinstance(token, str) or token not in WriteRefused.TOKENS
                for token in skipped
            ):
                raise WriteRefused({})
            response["skipped_optional_fields"] = skipped
        return response

    def close(self):
        self.closed = True
        for sid, obj in self.objects:
            try:
                self.call(
                    "Runtime.callFunctionOn",
                    {
                        "objectId": obj,
                        "functionDeclaration": "function(){this.close();}",
                        "returnByValue": True,
                    },
                    sid,
                    cleanup=True,
                )
            except Exception:
                pass
            try:
                self.call("Runtime.releaseObject", {"objectId": obj}, sid, cleanup=True)
            except Exception:
                pass
        self.objects.clear()
        for sid in {self.psid, self.csid}:
            try:
                self.call(
                    "Runtime.releaseObjectGroup",
                    {"objectGroup": self.group},
                    sid,
                    cleanup=True,
                )
            except Exception:
                pass
        sessions = ([self.csid] if self.attached else []) + (
            [self.psid] if self.parent_attached else []
        )
        for sid in sessions:
            try:
                self.call("Target.detachFromTarget", {"sessionId": sid}, cleanup=True)
            except Exception:
                pass
        self.attached = self.parent_attached = False
