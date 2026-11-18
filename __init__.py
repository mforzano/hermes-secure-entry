"""Windows-native Hermes secure-entry plugin. No core overrides or startup sockets."""
from .secure_entry.service import Service


def register(ctx):
    from hermes_constants import get_hermes_home
    service = Service(ctx.get_config('public_base_url', default='https://example.invalid:9443'),
                      str(get_hermes_home()), port=ctx.get_config('port', default=8769))
    from hermes_cli.plugin_isolation import isolation_mode
    from .secure_entry.native import dispatch_message
    service.configure_bridge(lambda name, args: dispatch_message(ctx, name, args), isolation=isolation_mode())
    from .secure_entry.payment import LocalPayment
    service.payment = LocalPayment(service, ctx.get_config('link_cli_command', default=[]))
    ctx.register_middleware('tool_execution', service.middleware)
    definitions = [
        ('secure_entry_otp_fill', service.otp_fill,
         'Private manual verification-code fill in the exact inspected browser document. Choose this OR native browser_vault enter_code before prompting; never fall back or retry after either route starts. '
         'Select only the intended OTP input or the complete scoped split widget by CDP backendNodeId. One native consent and one private DM link; no handle, seed, code, selector or script in arguments. '
         'Never submits. write_unknown means disclosure may have occurred; inspect only value-free state.',
         {'origin':{'type':'string','description':'Exact HTTPS origin of the inspected top-level page.'},
          'parent':{'type':'string','description':'Exact inspected page target ID on the task-captured browser.'},
          'frame':{'type':'string','description':'Exact root frame ID or direct iframe ID of the selected OTP document.'},
          'frame_origin':{'type':'string','description':'Exact HTTPS origin of the selected OTP document.'},
          'otp_nodes':{'type':'array','minItems':1,'maxItems':12,'uniqueItems':True,'items':{'type':'integer','minimum':1},
                       'description':'CDP backendNodeId for the intended OTP input or every member of one complete split widget; no other controls.'}},
         ['origin','parent','frame','frame_origin','otp_nodes']),
        ('secure_entry_signup_fill', service.signup_fill,
         'Explicitly consented REGISTRATION password fill from an existing saved native login handle. '
         'Inspect the exact selected page/frame and choose actual writable password backend node IDs, including confirmation if present. '
         'Generic: one or multiple password fields, formless controls, separate forms/steps, top-level or direct same/cross-origin iframe. '
         'Unselected fields, consent checkboxes and unrelated forms are untouched; selected prefills may be replaced. '
         'Fresh genuine native consent names registration origin, account, saved handle, password document and retained nodes before private retrieval. '
         'Writes the identical saved password and privately verifies equality/validity. Never types identifiers, submits, creates an account or deletes a login. '
         'write_unknown may mean partial disclosure: reinspect value-free state and do not blindly retry. '
         'Separate from ordinary browser_vault login filling; does not weaken its new/confirm-password safeguards. Never pass secrets, selectors or scripts.',
         {'handle':{'type':'string','description':'Exact existing native login metadata handle.'},
          'origin':{'type':'string','description':'Exact approved HTTPS registration origin, equal to the saved login origin.'},
          'identifier':{'type':'string','description':'Approved public account identifier, exactly equal to saved login metadata. This tool does not type it.'},
          'parent':{'type':'string','description':'Exact inspected task-selected page target ID on the currently captured browser.'},
          'frame':{'type':'string','description':'Exact inspected root frame ID for top-level controls, or direct iframe ID. Never a DOM node ID or guessed selector.'},
          'frame_origin':{'type':'string','description':'Exact HTTPS origin of the selected password document. A distinct iframe/offsite document is separately named in consent.'},
          'password_nodes':{'type':'array','minItems':1,'uniqueItems':True,'items':{'type':'integer','minimum':1},
                            'description':'Inspected CDP backendNodeId integers for ONLY intended actual INPUT type=password elements in this selected frame. One or more, confirmation if present. Not frontend nodeId, selectors, names or values.'}},
         ['handle','origin','identifier','parent','frame','frame_origin','password_nodes']),
        ('secure_entry_card_list', service.list_cards,
         'Discover native payment handles and scope only in an authenticated human DM. No secret retrieval. '
         'Lists explicitly reusable cards and exact HTTPS merchant-bound cards; excludes legacy originless entries. '
         'Reusable cards remain saved until explicit deletion; each mapped fill requires fresh exact-destination native consent.',
         {}, []),
        ('secure_entry_card_fill', service.selected_card_fill,
         'Fill a privately saved real card by native vault metadata handle. In addition to Link, not a replacement. '
         'First determine the official checkout merchant origin, request operation=add_card bound to that origin, '
         'and retain the saved cleanup handle. Native explicit consent authorizes this merchant and payment-frame pair only. '
         'Uses the same retained native browser writer as Link for top-level or direct iframe forms; standard autocomplete plus labeled expiry/CVC. Never submits, purchases, reserves or auto-deletes. '
         'Inspect checkout outcome before explicit cleanup; write_unknown is not proof of no fill. Never provide card values.',
         {'handle':{'type':'string','description':'Saved native payment handle, also used for cleanup.'},
          'parent':{'type':'string','description':'Exact task-selected merchant page target ID.'},
          'frame':{'type':'string','description':'Exact inspected payment frame ID: direct iframe, or this selected page root frame for a top-level form. Never omit or guess.'},
          'merchant_origin':{'type':'string','description':'Exact user-approved HTTPS merchant origin. Must match a bound card; reusable cards require fresh native consent for this exact destination.'},
          'frame_origin':{'type':'string','description':'Exact inspected HTTPS payment document origin, including an offsite top-level processor explicitly authorized in native consent.'}},
         ['handle','parent','frame','merchant_origin','frame_origin']),
        ('secure_entry_card_remove', service.remove_card,
         'Explicitly remove a saved native payment card by metadata handle and merchant origin in an authenticated human DM. '
         'Reusable cards: delete only when explicitly requested, not automatically after checkout. Bound cards: preserve the temporary cleanup workflow. '
         'Reports deleted/absent only after native metadata readback verifies absence. deletion_unknown requires inspection. '
         'Does not revoke browser copies, merchant retention, backups or an already-started fill.',
         {'handle':{'type':'string','description':'Exact native payment cleanup handle.'},
          'merchant_origin':{'type':'string','description':'Required exact saved HTTPS merchant origin for bound cards; omit for reusable cards.'}},
         ['handle']),
        ('secure_entry_payment_fill', service.selected_payment_fill,
         'Native local Link CLI private-card handoff into the existing task-captured browser. Requires an already user-approved Link spend request; '
         'asks separate native explicit payment consent. Binds the task-selected parent and explicit payment '
         'document before retrieval: top-level root frame or direct iframe. Windows only; standard cc autocomplete '
         'and semantically labeled expiry/CVC fields; no submission or vault save. '
         'Never provide card data, file paths, selectors or scripts. Refusal is not permission to bypass the facility.',
         {'parent':{'type':'string','description':'Exact task-selected page target ID.'},
          'frame':{'type':'string','description':'Exact inspected payment frame ID: direct iframe, or this selected page root frame for a top-level form. Never omit or guess.'},
          'merchant_origin':{'type':'string','description':'Exact HTTPS merchant origin.'},
          'frame_origin':{'type':'string','description':'Exact inspected HTTPS payment document origin, including an offsite top-level processor explicitly authorized in native consent.'},
          'spend_request_id':{'type':'string','description':'Already user-approved Link spend request ID.'}},
         ['parent','frame','merchant_origin','frame_origin','spend_request_id']),
        ('secure_entry_request', service.request,
         'Request a private one-use form to ADD a website login or real payment card to the native encrypted Hermes vault without a browser. '
         'For reusable storage use add_reusable_card without origin; the private page requires explicit opt-in to retain one cross-website card until explicit deletion. For add_card first determine the official merchant checkout origin (not the cross-origin payment iframe); bind it exactly. '
         'The native payment contract encrypts and persists CVC too; the private form discloses this. Retain saved handle for '
         'secure_entry_card_fill. Reusable cards remain until explicitly requested deletion, not automatic checkout cleanup. Bound cards retain explicit cleanup after verifying checkout outcome. Link remains available separately. '
         'Photon, Discord, or Telegram DM only (Discord/Telegram synthetic-tested; live verification pending). Does not sign in. For verification codes choose secure_entry_otp_fill or the existing browser_vault action=enter_code WITHOUT a handle before prompting; this request tool does not collect codes. '
         'Update, transient sign-in and save-and-sign-in '
         'remain unsupported. Never pass credentials or codes in tool arguments.',
         {'operation': {'type':'string', 'enum':['add_login','add_card','add_reusable_card','update_login','sign_in_once','save_and_sign_in','verification_code']},
          'origin': {'type':'string','description':'Required exact HTTPS website origin for add_login/add_card. Omit for add_reusable_card, which additionally requires explicit opt-in on the private form.'}},
         ['operation']),
        ('secure_entry_status', service.status, 'Read metadata-only request status in the same originating Photon, Discord, or Telegram DM session.',
         {'request_id':{'type':'string'}}, ['request_id']),
        ('secure_entry_cancel', service.cancel, 'Cancel a pending secure-entry request in the same originating Photon, Discord, or Telegram DM session.',
         {'request_id':{'type':'string'}}, ['request_id']),
    ]
    for name, handler, description, properties, required in definitions:
        if name in ('secure_entry_card_fill', 'secure_entry_payment_fill'):
            from .secure_entry.payment_browser import WriteRefused
            properties['field_mapping'] = {
                'type': 'object', 'minProperties': 1, 'additionalProperties': False,
                'properties': {token: {'type':'integer','minimum':1}
                               for token in sorted(WriteRefused.TOKENS)},
                'description': 'Explicit semantic-to-backendDOMNodeId mapping from value-free inspection of this exact payment document. '
                'Choose only the intended active fields; autocomplete is not required. Never include unrequested billing/contact fields. '
                'Native code retains these actual elements before consent, overwrites selected prefills, and never retargets selectors. '
                'Use cc-csc for CVC; cc-exp OR cc-exp-month plus cc-exp-year. Native refusal after a target change requires reinspection.',
            }
            required = [*required, 'field_mapping']
            description = ('Native payment fill of an agent-selected explicit field mapping in the exact inspected top-level root or direct iframe. '
                'Inspect value-free DOM/backend node IDs first, interpret the fields, then supply field_mapping. '
                'No whole-page/form classifier, autocomplete requirement, unknown-control or duplicate-layout gate applies to this mapping. '
                'Unselected billing, contact, consent and other forms are untouched. '
                'Separate native consent binds the exact retained targets, document and origins before private retrieval. '
                'Never supplies secrets to the model; never submits, purchases or deletes. write_unknown can mean a partial fill. '
                + ('Uses a merchant-bound or explicitly reusable native vault handle. Use secure_entry_card_list for scope. Reusable cards persist until explicit deletion; do not delete after each checkout unless requested. Bound cards keep their exact origin and temporary cleanup workflow.' if name=='secure_entry_card_fill' else
                   'Requires an already approved Link spend request; private native CLI handoff, no vault save.'))
        ctx.register_tool(name=name, toolset='secure_entry', handler=handler,
                          schema={'name':name, 'description':description,
                                  'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}})
    ctx.register_hook('agent_loop_stopped', service.stopped)
    ctx.register_hook('on_session_end', service.ended)
    ctx.register_hook('on_session_reset', service.reset)
    ctx.on_unload(service.close)
