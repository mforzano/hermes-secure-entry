# Generic native payment form inventory and billing lifecycle

Classify by HTML semantics, never merchant selectors. BUTTON, FIELDSET, OUTPUT and INPUT submit/reset/button/image are not fill targets. Hidden **data** inputs, unknown controls, duplicate/unsupported autocomplete tokens and external data controls outside the retained container still refuse. Unsectioned `postal-code` maps privately to `billing postal-code`; original attributes remain unchanged. Every INPUT type transition is sticky, including action-to-data-and-back.

## Retained-field policy

- Retain exact document/origins, form/container, nodes, parents, ancestry and autocomplete strings. Never mutate merchant attributes to bypass a control.
- PAN/expiry/CVC must initially be visible, enabled, writable and empty. Effective `:disabled` includes FIELDSET inheritance. Prefilled or unavailable credential controls never admit.
- Retain supported visible billing (including cardholder name) even initially disabled/readonly, with initial values and state. Supplied billing conflicts still refuse before any write.
- Only initially disabled, not-yet-settled billing can change disabled state during synchronous native self-write/input/change events. Direct attributes and inherited FIELDSET transitions share the policy, including the first-LEGEND exemption. No exception covers readonly, required, type, semantics, ownership, replacements, new controls or credentials. Other mutation records remain fully checked.
- Check state immediately before each write and after each input/change event. Process credentials first, then currently writable pending billing before unavailable billing: an expiry/CVC/cardholder event can unlock billing that appeared earlier in DOM.
- Never call setters or dispatch fill events on disabled/readonly controls. Preserve matching enabled readonly billing. Explicitly report unavailable optional controls in `skipped_optional_fields`, excluded from `filled_fields`. Required disabled billing, or required readonly billing not already satisfied, refuses as `billing_unavailable`. Native results retain `write_unknown` and the bounded `written_fields` count after writes begin, without claiming rollback or no disclosure.
- Preserve source differences: Link requires its issued billing; saved cards can preserve valid unsupplied billing and blank optional line2. Validation exemption cannot manufacture valid blank required billing. Revalidate preserved billing when enabled.
- Keep prewrite state changes (including change-and-restore), foreign semantic changes, removal/reparenting, replacements, new/duplicate controls and navigation rejected. Settled billing cannot gain new disabled-state authority in later events.

## Executed acceptance coverage

Real disposable Chrome OOPIF tests execute generated isolated-world JavaScript and native CapturedCDP. Native Link tests retain genuine approval enqueue/resolution and a synthetic private-file producer. A saved-card regression creates a synthetic encrypted native vault entry via private HTTP entry, dispatches the registered card-fill tool with genuine native consent, then deletes/verifies the synthetic entry.

Coverage includes whole forms with hidden submits/buttons; unsupported hidden data; PAN-triggered ZIP enabling together with PAN/expiry masks, value-attribute reflection and presentation updates; optional ZIP remaining disabled with explicit skip; required ZIP remaining disabled with honest three-write refusal; ZIP before credentials in DOM; enabling/toggling on expiry/CVC/cardholder events; inherited FIELDSET and first-LEGEND cases; readonly match/skip/conflict/required; source-specific preservation and validation after enabling; prewrite state changes; replacements, removal, reparenting, duplicate/unknown controls, action-input classification changes and foreign semantic/property changes. Existing navigation/origin/consent/unknown-write regressions remain in the full suite.

## Concrete limits

This is a synchronous retained-widget adapter. Asynchronous enabling outside the self-write window invalidates authority rather than silently extending consent. Hidden billing, new/replaced controls, changed readonly/required semantics and disabled-state changes to initially writable controls remain unsupported. Required billing that never enables refuses after credential writes already made; retry needs normal fresh-binding/partial-write recovery.

Parent pre/post checks are not an atomic cross-document no-disclosure fence. `filled` means verified native writes, not merchant acceptance or purchase. Fixtures prove the generic lifecycle policy, not the real merchant's exact enabling trigger/timing. No real saved card, merchant DOM, active plugin, deployment, commit or push is touched.
