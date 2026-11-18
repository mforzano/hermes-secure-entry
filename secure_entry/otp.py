"""Manual OTP route: retained browser authority and one existing private DM form."""
import json
import logging
import re
import threading
import time

from .native import owner, validate_origin
from .signup import RetainedInputTarget, validate_nodes


OTP_FIELDS = r"""function(...fields) {
 const doc=document, href=location.href, origin=location.origin;
 const usable=e=>e instanceof HTMLInputElement && e.ownerDocument===doc && e.isConnected &&
   ['text','tel','number','password'].includes(e.type) && !e.matches(':disabled') && !e.readOnly &&
   e.getClientRects().length>0 && getComputedStyle(e).visibility==='visible' && !e.closest('[inert]');
 const text=e=>[e.name,e.id,e.placeholder,e.getAttribute('aria-label'),
   ...Array.from(e.labels||[],n=>n.textContent),
   ...(e.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>doc.getElementById(id)?.textContent)
 ].filter(Boolean).map(s=>s.replace(/_/g,' ').replace(/(?<=[a-z\d])-(?=[a-z])/gi,' ')
   .replace(/\s+/g,' ').trim().toLowerCase());
 const positive=s=>/\b(?:otp|passcode|one time (?:code|password)|(?:verification|authentication|security|login|sign in|2fa|mfa) code)\b/.test(s);
 const unrelated=s=>/\b(?:postal|zip|country|area|promo|coupon|discount|invitation|referral|gift|card|cvv|cvc)\b/.test(s);
 const countHint=/(?<![\w.+-])([+-]?\d+(?:\.\d+)?)\s*digits?\s+(?:(?:verification|security|authentication)\s+)?(?:code|passcode)\b/g;
 const positionHint=/\b(?:digit|character)\s+(?=[+-]?\d|of\b)/g;
 const position=/\b(?:digit|character)\s+(\d+)\s+of\s+(\d+)\b(?!\.\d)/g;
 // Argument order is not authority to permute a code. Retain DOM order.
 if(!fields.every(usable))throw Error('targets');
 fields.sort((a,b)=>a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING?-1:1);
 const same=(a,b)=>a.length===b.length && a.every((v,i)=>v===b[i]);
 const form=fields[0].form;
 let scope=fields[0].parentElement;
 while(scope && !fields.every(e=>scope.contains(e)))scope=scope.parentElement;
 // A real common form may supply ownership; otherwise require a container
 // smaller than the document, not merely null===null form ownership.
 if(form && fields.every(e=>form.contains(e)))scope=form;
 const otp=(e,hints)=>e.autocomplete.split(/\s+/).includes('one-time-code') || hints.some(positive);
 const splitLike=e=>e instanceof HTMLInputElement && (e.maxLength===1 || text(e).some(s=>[...s.matchAll(positionHint)].length));
 function positions(hints){
   let parts=[];
   for(const hint of hints){
     const matches=[...hint.matchAll(position)];
     if([...hint.matchAll(positionHint)].length!==matches.length)return null;
     parts.push(...matches.map(m=>`${Number(m[1])}/${Number(m[2])}`));
   }
   return [...new Set(parts)];
 }
 function plan(){
   const n=fields.length;
   if(!fields.every(usable))return null;
   const hints=fields.map(text);
   if(hints.some(h=>h.some(unrelated)))return null;
   const declared=[...new Set(hints.flat().flatMap(s=>[...s.matchAll(countHint)].map(m=>Number(m[1]))))];
   if(declared.length>1 || declared.some(x=>!Number.isInteger(x) || x<2 || x>256))return null;
   const numbered=hints.map(positions);
   if(numbered.some(x=>x===null))return null;
   const signs=fields.map((e,i)=>otp(e,hints[i]));
   if(n===1){
     const e=fields[0], count=declared[0]||0;
     if(numbered[0].length || e.maxLength===1 || !(count || signs[0]))return null;
     const min=Math.max(1,e.minLength), max=e.maxLength<0?256:e.maxLength;
     if(count && (count<min || count>max))return null;
     return {mode:'single', numeric:!!count || e.type==='number', min:count||min, max:count||max};
   }
   if(!scope || scope===doc.body || scope===doc.documentElement || fields.some(e=>e.form!==form))return null;
   // Adjacency is among rendered data controls, not labels or decoration.
   const row=[...scope.querySelectorAll('input, select, textarea, [contenteditable]')].filter(e=>
     e.getClientRects().length && getComputedStyle(e).visibility==='visible');
   const start=row.indexOf(fields[0]);
   if(start<0 || !same(fields,row.slice(start,start+n)) || splitLike(row[start-1]) || splitLike(row[start+n]))return null;
   if(declared.length && declared[0]!==n || fields.some(e=>e.maxLength===0 || e.minLength>1))return null;
   if(numbered.some(x=>x.length)){
     if(!numbered.every((parts,i)=>same(parts,[`${i+1}/${n}`])) ||
        !hints.every((h,i)=>signs[i] || h.some(s=>/\benter (?:the )?code\b/.test(s))))return null;
   } else if(!signs.some(Boolean) || !fields.every((e,i)=>e.maxLength===1 &&
     (signs[i] || (!hints[i].length && e.inputMode==='numeric' && !e.autocomplete))))return null;
   return {mode:'split', numeric:true, min:n, max:n};
 }
 const spec=plan();
 if(!spec || spec.max<spec.min)throw Error('targets');
 const baseline=JSON.stringify(spec), forms=fields.map(e=>e.form);
 const semantic=['type','name','id','form','autocomplete','maxlength','minlength','pattern','aria-label',
   'aria-labelledby','placeholder','readonly','disabled','inputmode'];
 let changed=false, used=false, expected=null;
 const relevant=records=>records.some((r,k)=>{
   if(r.type==='childList')return [...r.removedNodes].some(n=>fields.some(e=>n===e || n.contains(e)));
   if(!fields.includes(r.target) || !semantic.includes(r.attributeName))return false;
   const next=records.slice(k+1).find(n=>n.target===r.target && n.attributeName===r.attributeName);
   return r.oldValue!==(next?next.oldValue:r.target.getAttribute(r.attributeName));
 });
 const observer=new MutationObserver(rs=>{if(relevant(rs))changed=true;});
 observer.observe(doc,{subtree:true,childList:true,attributes:true,attributeOldValue:true});
 const valid=()=>{if(relevant(observer.takeRecords()))changed=true;
   return !changed && document===doc && location.href===href && location.origin===origin &&
     fields.every((e,i)=>e.form===forms[i]) && JSON.stringify(plan())===baseline;};
 const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
 return {origin, spec, valid, write(code){
   if(used || !valid())return false;
   used=true;
   const values=spec.mode==='single'?[code]:[...code];
   if(values.length!==fields.length)return false;
   for(const [i,e] of fields.entries()){
     if(!valid())return false;
     setter.call(e,values[i]);
     e.dispatchEvent(new Event('input',{bubbles:true}));
     if(!valid() || e.value!==values[i])return false;
     e.dispatchEvent(new Event('change',{bubbles:true}));
     if(!valid() || e.value!==values[i])return false;
   }
   if(!fields.every((e,i)=>e.value===values[i] && e.validity.valid))return false;
   expected=values;
   return true;
 },verify(){
   const values=expected;
   expected=null;
   return !!values && valid() && fields.every((e,i)=>e.value===values[i] && e.validity.valid);
 },close(){changed=true;expected=null;observer.disconnect();}};
}"""


class OtpTarget(RetainedInputTarget):
    field_key = 'otp_nodes'
    binding = OTP_FIELDS

    def spec(self):
        return self.invoke(self.csid, self.cg, 'function(){return this.spec;}')

    def fill_code(self, code):
        self.check()
        self.started = True  # A missing or failed reply is not evidence of no disclosure.
        verified = self.invoke(self.csid, self.cg, 'function(c){return this.write(c);}', (code,))
        self.check()
        if verified is not True or self.invoke(self.csid, self.cg, 'function(){return this.verify();}') is not True:
            raise ValueError('write_unverified')
        # The child readback cannot attest to its retained parent. Check the
        # exact parent last; this is a postflight, not an atomic frame fence.
        if self.invoke(self.psid, self.pg, 'function(){return this.valid();}') is not True:
            raise ValueError('write_unverified')


def fill(service, args, task):
    stage, status = 'admission', 'refused'
    capture = target = None
    requests = []
    active = threading.Event()
    active.set()
    try:
        from tools.approval_human_wait import human_wait_seconds
        from tools.approval_prompt import request_elicitation_consent
        from tools.bot_desktop import lease
        from tools.browser_supervisor import SUPERVISOR_REGISTRY
        from tools.interrupt import is_interrupted

        with service.lock:
            if service.closed:
                raise ValueError('closed')
            generation = service.generation
        bound = owner(service.home)
        bridge = service.bridge
        if bridge.bound_owner({'session_id': bound[-1]}) != bound:
            raise ValueError('owner_changed')
        if not isinstance(task, str) or not task or set(args) != {'origin','frame_origin','parent','frame','otp_nodes'}:
            raise ValueError('invalid_arguments')
        args = dict(args)
        origin = args['origin'] = validate_origin(args['origin'])
        document = args['frame_origin'] = validate_origin(args['frame_origin'])
        nodes = args['otp_nodes'] = validate_nodes(args['otp_nodes'])
        if len(nodes) > 12 or any(not isinstance(args[k], str) or not re.fullmatch(r'[0-9a-fA-F]{32}', args[k]) for k in ('parent','frame')):
            raise ValueError('invalid_targets')
        admitted = lease.assert_agent_may_act(str(service.home))
        deadline = time.monotonic() + bridge.timeout

        def current():
            if (service.closed or generation != service.generation or is_interrupted()
                    or time.monotonic() >= deadline or owner(service.home) != bound
                    or lease.assert_agent_may_act(str(service.home)).epoch != admitted.epoch
                    or (capture is not None and not capture.is_valid())):
                raise ValueError('operation_invalidated')
            # Stock WebSocket DEBUG tracing logs raw frames. Never send a code
            # through a supervisor in wire-debug mode.
            if logging.getLogger('websockets.client').isEnabledFor(logging.DEBUG):
                raise ValueError('browser_wire_debug')

        current()
        capture = SUPERVISOR_REGISTRY.capture(task)
        stage = 'target_binding'
        target = OtpTarget(capture, args, current)
        if getattr(target, 'offsite_root', False):
            raise ValueError('parent_origin_mismatch')
        spec = target.spec()
        stage = 'native_consent'
        target.check()
        if not service.claim_otp_prompt(bound, generation, (task, service.otp_turn.get())):
            return json.dumps({'success':False, 'status':'refused', 'stage':stage,
                               'error_type':'otp_prompt_already_attempted'})
        wait_before, started = human_wait_seconds(bound[-2]), time.monotonic()
        verdict = request_elicitation_consent(
            f'Manual verification-code fill at {document}',
            f'Page origin {origin}; code document {document}; exact page {target.parent}; frame {target.frame}; '
            f'selected verification-code backendNodeIds {", ".join(map(str, nodes))}. '
            'Enter the code once through a private DM link. Fill only the selected fields; no tool-driven submission.',
            surface='vault-login', title='Confirm manual verification-code fill?',
        )
        deadline += min(max(0, time.monotonic()-started), max(0, human_wait_seconds(bound[-2])-wait_before))
        if verdict != 'accept':
            status = 'consent_declined'
            return json.dumps({'success':False, 'status':status})
        stage = 'postconsent_target'
        target.check()
        stage = 'private_entry'
        code = bridge.prompt('code', document, bound, generation, requests, active,
                             service.broker.clock()+max(0, deadline-time.monotonic()), [], current=current)
        if code is None:
            status = requests[-1].status if requests and requests[-1].status in ('expired','cancelled') else 'refused'
            return json.dumps({'success':False, 'status':status, 'stage':stage})
        stage = 'validate_code'
        code = code.strip().replace(' ', '').replace('-', '')
        if (not re.fullmatch(r'[A-Za-z0-9]+', code) or not spec['min'] <= len(code) <= spec['max']
                or (spec['numeric'] and not re.fullmatch(r'[0-9]+', code))):
            status = 'code_mismatch'
            return json.dumps({'success':False, 'status':status, 'stage':stage})
        from agent.redact import register_vault_redaction_value
        register_vault_redaction_value(code)
        stage = 'prewrite_target'
        target.check()
        stage = 'write'
        target.fill_code(code)
        current()
        status = 'filled'
        return json.dumps({'success':True, 'status':status, 'filled_fields':len(nodes), 'submitted':False})
    except Exception:  # Never propagate raw CDP, transport or secret-bearing errors.
        status = 'write_unknown' if target is not None and target.started else 'refused'
        return json.dumps({'success':False, 'status':status, 'stage':stage})
    finally:
        active.clear()
        for request in requests:
            with service.broker.lock:
                if request.status == 'commit_unknown':
                    service.broker.finish(request.token, status)
                elif request.status in ('pending','received'):
                    service.broker.finish(request.token, 'cancelled')
        if target is not None:
            target.close()
