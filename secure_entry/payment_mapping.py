"""Explicit model-selected semantics, native-retained DOM nodes only.

No selectors, form classifier, autocomplete inference or page inventory gates.
The host resolves inspected backendNodeIds into this exact isolated document
before consent. Secrets enter only the private writer closure after consent.
"""

MAPPED = r"""function(tokens, ...fields) {
 const doc=document, href=location.href, origin=location.origin;
 const parents=fields.map(e=>e.parentNode), forms=fields.map(e=>e.form), types=fields.map(e=>e.type);
 const visible=e=>e.getClientRects().length>0 && getComputedStyle(e).visibility==='visible';
 const eligible=e=>e.ownerDocument===doc && e.isConnected &&
   (e.tagName==='INPUT' && ['text','tel','number','month'].includes(e.type) || e.tagName==='SELECT');
 if(fields.some(e=>!eligible(e) || !visible(e)))throw Error('target_changed');
 let changed=false, used=false;
 // Only selected node identity matters. Unrelated forms, labels, options,
 // billing fields, accessibility feedback and DOM mutations are not authority.
 const relevant=records=>records.some(r=>r.type==='childList'
   ? Array.from(r.removedNodes).some(n=>fields.some(e=>n===e || n.contains(e)))
   : fields.includes(r.target) && ['type','form'].includes(r.attributeName));
 const observer=new MutationObserver(rs=>{if(relevant(rs))changed=true;});
 observer.observe(doc,{subtree:true,childList:true,attributes:true});
 const valid=()=>{
   if(relevant(observer.takeRecords()))changed=true;
   return !changed && document===doc && location.href===href && location.origin===origin &&
     fields.every((e,i)=>eligible(e) && visible(e) && e.parentNode===parents[i] &&
       e.form===forms[i] && e.type===types[i]);
 };
 const setters={INPUT:Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set,
   SELECT:Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set};
 const equivalent=(actual,want,token)=>actual===want ||
   token==='cc-number' && /^[0-9]+(?:[ -][0-9]+)*$/.test(actual) && actual.replace(/[ -]/g,'')===want ||
   token==='cc-exp' && /^\d{2} *\/ *\d{2}$/.test(actual) && actual.replace(/ /g,'')===want;
 return {origin,valid,
   write(card){let written=0;
     const refuse=(reason,i=-1)=>({valid:false,written,reason,...(i>=0?{field:tokens[i]}:{})});
     if(used)return refuse('already_used');
     if(!valid())return refuse('invalidated');
     const values=tokens.map(t=>card[t]);
     const missing=values.findIndex(v=>typeof v!=='string');
     if(missing>=0)return refuse('source_missing',missing);
     const expected=new Map();
     used=true;
     // Card events may enable selected dependent billing. No unselected control
     // is read, preserved, validated or filled by this operation.
     const order=fields.map((e,i)=>i).sort((a,b)=>Number(tokens[b].startsWith('cc-'))-Number(tokens[a].startsWith('cc-')));
     while(order.length){
       const available=i=>!fields[i].matches(':disabled') && !fields[i].readOnly;
       const next=order.findIndex(available), i=order.splice(next<0?0:next,1)[0], e=fields[i], token=tokens[i];
       if(!valid())return refuse('invalidated');
       if(!available(i))return refuse('billing_unavailable',i);
       let want=values[i];
       if(e.tagName==='INPUT' && token==='cc-exp-year' && e.maxLength===2)want=want.slice(-2);
       if(e.tagName==='INPUT' && token==='cc-exp' && e.type==='month')want=card['cc-exp-year']+'-'+card['cc-exp-month'];
       if(e.tagName==='SELECT'){
         const normalize=s=>s.trim().toLowerCase();
         const matches=Array.from(e.options).filter(o=>!o.disabled && !o.parentElement.disabled && (
           token==='cc-exp-month' ? /^(?:0?[1-9]|1[0-2])$/.test(o.value) && Number(o.value)===Number(want) :
           token==='cc-exp-year' ? /^(?:\d{2}|\d{4})$/.test(o.value) && Number(o.value)===(o.value.length===2?Number(want)%100:Number(want)) :
           o.value===want || normalize(o.text)===normalize(want)));
         if(matches.length!==1)return refuse('select_mismatch',i);
         want=matches[0].value;
       }
       setters[e.tagName].call(e,want);
       e.dispatchEvent(new Event('input',{bubbles:true}));
       if(!valid())return refuse('invalidated');
       e.dispatchEvent(new Event('change',{bubbles:true}));
       if(!valid())return refuse('invalidated');
       if(!equivalent(e.value,want,token))return refuse('write_mismatch',i);
       expected.set(i,{want,token});written++;
     }
     if(!valid())return refuse('invalidated');
     for(const [i,{want,token}] of expected)if(!equivalent(fields[i].value,want,token))return refuse('field_changed',i);
     return {valid:true,written};
   },
   close(){changed=true;observer.disconnect();}
 };
}"""


def validate_mapping(mapping, allowed):
    """Validate metadata, not inferred page semantics or whole-form completeness."""
    if not isinstance(mapping, dict) or not mapping or any(
        not isinstance(token, str) or token not in allowed or type(node) is not int or node <= 0
        for token, node in mapping.items()
    ) or len(set(mapping.values())) != len(mapping):
        raise ValueError('invalid_field_mapping')
    return mapping
