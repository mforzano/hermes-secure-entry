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
        ('secure_entry_card_fill', service.card_fill,
         'Fill a privately saved real card by native vault metadata handle. In addition to Link, not a replacement. '
         'First determine the official checkout merchant origin, request operation=add_card bound to that origin, '
         'and retain the saved cleanup handle. Native explicit consent authorizes this merchant and payment-frame pair only. '
         'Uses the same retained native browser writer as Link for top-level or direct iframe forms; standard autocomplete plus labeled expiry/CVC. Never submits, purchases, reserves or auto-deletes. '
         'Inspect checkout outcome before explicit cleanup; write_unknown is not proof of no fill. Never provide card values.',
         {'handle':{'type':'string','description':'Saved native payment handle, also used for cleanup.'},
          'parent':{'type':'string','description':'Exact task-selected merchant page target ID.'},
          'frame':{'type':'string','description':'Exact inspected payment frame ID: direct iframe, or this selected page root frame for a top-level form. Never omit or guess.'},
          'merchant_origin':{'type':'string','description':'Exact HTTPS merchant origin matching the saved card binding.'},
          'frame_origin':{'type':'string','description':'Exact inspected HTTPS payment document origin; must equal merchant_origin for a top-level root form.'}},
         ['handle','parent','frame','merchant_origin','frame_origin']),
        ('secure_entry_card_remove', service.remove_card,
         'Explicitly remove a saved native payment card by metadata handle and merchant origin in an authenticated human DM. '
         'Use after verifying fill/checkout outcome or explicit user cancellation; no automatic pre-checkout deletion. '
         'Reports deleted/absent only after native metadata readback verifies absence. deletion_unknown requires inspection. '
         'Does not revoke browser copies, merchant retention, backups or an already-started fill.',
         {'handle':{'type':'string','description':'Exact native payment cleanup handle.'},
          'merchant_origin':{'type':'string','description':'Exact saved HTTPS merchant origin.'}},
         ['handle','merchant_origin']),
        ('secure_entry_payment_fill', service.payment_fill,
         'Native local Link CLI private-card handoff into the existing task-captured browser. Requires an already user-approved Link spend request; '
         'asks separate native explicit payment consent. Binds the task-selected parent and explicit payment '
         'document before retrieval: top-level root frame or direct iframe. Windows only; standard cc autocomplete '
         'and semantically labeled expiry/CVC fields; no submission or vault save. '
         'Never provide card data, file paths, selectors or scripts. Refusal is not permission to bypass the facility.',
         {'parent':{'type':'string','description':'Exact task-selected page target ID.'},
          'frame':{'type':'string','description':'Exact inspected payment frame ID: direct iframe, or this selected page root frame for a top-level form. Never omit or guess.'},
          'merchant_origin':{'type':'string','description':'Exact HTTPS merchant origin.'},
          'frame_origin':{'type':'string','description':'Exact inspected HTTPS payment document origin; must equal merchant_origin for a top-level root form.'},
          'spend_request_id':{'type':'string','description':'Already user-approved Link spend request ID.'}},
         ['parent','frame','merchant_origin','frame_origin','spend_request_id']),
        ('secure_entry_request', service.request,
         'Request a private one-use form to ADD a website login or real payment card to the native encrypted Hermes vault without a browser. '
         'For add_card first determine the official merchant checkout origin (not the cross-origin payment iframe); bind it exactly. '
         'The native payment contract encrypts and persists CVC too; the private form discloses this. Retain saved handle for '
         'secure_entry_card_fill and explicit secure_entry_card_remove after verifying checkout outcome. Link remains available separately. '
         'Photon, Discord, or Telegram DM only (Discord/Telegram synthetic-tested; live verification pending). Does not sign in. For verification codes call browser_vault action=enter_code WITHOUT a handle; '
         'its native inspection arms a private form and sends its link to this DM. Update, transient sign-in and save-and-sign-in '
         'remain unsupported. Never pass credentials or codes in tool arguments.',
         {'operation': {'type':'string', 'enum':['add_login','add_card','update_login','sign_in_once','save_and_sign_in','verification_code']},
          'origin': {'type':'string','description':'Exact HTTPS website origin, without path or trailing slash. Visible to the user before entry.'}},
         ['operation','origin']),
        ('secure_entry_status', service.status, 'Read metadata-only request status in the same originating Photon, Discord, or Telegram DM session.',
         {'request_id':{'type':'string'}}, ['request_id']),
        ('secure_entry_cancel', service.cancel, 'Cancel a pending secure-entry request in the same originating Photon, Discord, or Telegram DM session.',
         {'request_id':{'type':'string'}}, ['request_id']),
    ]
    for name, handler, description, properties, required in definitions:
        ctx.register_tool(name=name, toolset='secure_entry', handler=handler,
                          schema={'name':name, 'description':description,
                                  'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}})
    ctx.register_hook('agent_loop_stopped', service.stopped)
    ctx.register_hook('on_session_end', service.ended)
    ctx.register_hook('on_session_reset', service.reset)
    ctx.on_unload(service.close)
