# Explicit registration password fill (0.5.17)

`secure_entry_signup_fill` is a distinct native operation, not a change to
`browser_vault` login recognition. Ordinary login filling still excludes new and
confirmation passwords. No page labels, autocomplete, names or types are rewritten
to defeat that classifier. This operation saves nothing and submits nothing.

## Usage contract

From the authenticated originating human DM, first reconnect the task's existing
browser with its normal browser tool. Inspect value-free field descriptors and
CDP backend IDs in the intended registration document. Choose the actual writable
`INPUT type=password` nodes, including confirmation when it exists. Do not read
password values, take secret-bearing screenshots or send passwords in tool args.

Required arguments (all metadata):

- `handle`: existing native `vault_[0-9a-f]{12}` login handle.
- `origin`: exact approved HTTPS registration origin, equal to saved metadata.
- `identifier`: approved public email/username/phone, exactly equal to saved metadata.
  This tool does not type the identifier; prepare public fields separately.
- `parent`: inspected page **target ID**, on the current captured browser socket.
- `frame`: inspected **frame ID**, either the selected page's root or a direct
  iframe. Not a DOM ID, backend node ID or selector.
- `frame_origin`: actual HTTPS origin of that selected password document. A distinct
  iframe or offsite root is separately named in consent, never treated as the
  saved login's origin. An offsite root explicitly discloses absent live ancestry.
- `password_nodes`: nonempty unique list of positive integer CDP **backendNodeId**
  values, all in that exact selected document. Not frontend nodeId, CSS selectors,
  field names or values. No arbitrary two-field limit.

Example with synthetic metadata only:

```json
{"handle":"vault_0123456789ab","origin":"https://registration.test",
 "identifier":"synthetic@example.test","parent":"INSPECTED_PAGE_TARGET",
 "frame":"INSPECTED_FRAME_ID","frame_origin":"https://registration.test",
 "password_nodes":[101,104]}
```

Backend IDs are renderer-scoped. Inspect in the correct document; an ID copied
from a foreign renderer may alias another real node and cannot prove intended
selection. The agent owns interpretation; native identity retention cannot prove
that the agent chose the right password field or registration provider.

There is no whole-form classifier, mandatory autocomplete, fixed label, shared
container, adjacency, empty-unselected-field or page-stability requirement. One
password, optional confirmation, more explicitly selected password controls,
separate forms, formless controls and later steps are allowed. Each step needs
fresh inspection/consent. Unselected controls (including passwords, search,
billing, consent and other forms) are irrelevant and untouched. Selected prefilled
passwords may be replaced. Native input/change events support ordinary framework
listeners, exact value reflection and class/ARIA presentation updates.

The handler retains actual nodes in isolated worlds before asking genuine native
consent. Consent names account, saved handle, registration origin, actual password
document, selected page/frame/backend IDs and **fill only, no submission**.
Only after consent, owner/profile/lifecycle/takeover/deadline/capture and selected
target checks does it privately retrieve the saved password. It registers native
redaction, writes identical bytes to selected controls and privately checks exact
equality and validity. Every dispatch remains fenced. A changed selected node,
document/navigation, selected type/name/form/autocomplete binding, origin,
owner/profile or takeover generation refuses instead of retargeting. No secret is
returned, printed, logged or exposed through raw exception text by this adapter.

## Outcomes and recovery

- `filled`, `success=true`, `filled_fields=N`, `submitted=false`: exact private
  verification completed; **not registration, authentication, API-key creation or
  provider acceptance**. The parent must separately inspect public validity,
  submit only if authorized and verify the actual account outcome.
- `consent_declined`: native approval was not obtained. Not a provider rejection.
  Never automatically repeat it or substitute ordinary login injection.
- `refused`: no native write dispatch started. `stage` is fixed, value-free
  diagnostic metadata. Reinspect the affected destination or account metadata.
- `write_unknown`: dispatch started and may have filled some/all controls. Never
  infer no disclosure or blindly retry. Inspect only booleans/validity and public
  errors, then obtain renewed authorization/inspection and fresh consent for a
  retry. No automatic clearing, submission or retry is performed.

Every result includes fixed `signup_diagnostic_version=0.5.17`. The lifetime is
180 seconds plus only host-recorded bounded human waiting during that consent.
Native per-call elicitation does not bypass approval in auto-approve/YOLO mode.
Parent pre/post checks across an iframe are not cross-document atomicity: a
parent-only navigation racing between them can make an already-dispatched write
unknown. Captured remote identities never reselect a replacement document.

## Native adapter compatibility, not a stable public SDK

Tool registration and browser capture use existing host seams. Native
`agent.vault_store.VaultStore`, `get_vault_store`,
`tools.approval_prompt.request_elicitation_consent`, owner/lease and redaction
imports are version-specific server-side APIs, not a promised public plugin
password SDK. The existing bounded Hermes manifest range remains unchanged.
Catalog private-import warnings are expected and must not be described as public
SDK certification. No core changes, monkeypatches, new credential collector,
second password store or alternative secret script/tool-argument path are used.

## Test evidence and activation

`tests/test_signup.py` uses disposable actual Chrome, real native CapturedCDP,
a disposable encrypted native vault and genuine native approval enqueue/resolve
with synthetic identities. It exercises single/confirmation, unrelated forms,
formless and multiple layouts, more than two selected targets, selected prefill,
framework events/reflection/presentation, top-level and direct same/cross-origin
iframe, denial-before-retrieval, account/origin/handle/kind mismatches, target
replacement/navigation/type change, unavailable controls, lifecycle/profile,
takeover/handback, expiry, exact equality/validity and lost/partial write replies.
Tests do not retrieve a real user's login or establish acceptance on a real site.
Run the entire existing payment/OTP/login-regression suite in an isolated home.

Install the exact tested **pushed** 40-character SHA with the supported manager:

```text
hermes plugins disable secure-entry
# Call gateway.control_socket.reload_gateway_plugins(active_home), verify unload.
hermes plugins install mforzano/hermes-secure-entry --ref <TESTED_SHA> --force --yes-deps --no-enable
hermes plugins enable secure-entry
# Call reload_gateway_plugins(active_home), inspect returned activation state.
hermes plugins list --plain --no-bundled
```

Do not edit installed files or core. Preserve the existing vault and browser
workloads. Disable/reload cancels plugin-private pending entry links; do not
replace a plugin in use by another private entry request. Never restart the
gateway without specific authorization. Existing agent sessions retain their
tool/schema snapshot: hot reload registers handlers, not necessarily new tools
in an old conversation. Read `tool_describe("secure_entry_signup_fill")` from the
originating human session; if absent, a fresh human DM session is required. Do
not bypass this by terminal-based real credential dispatch, a delegated identity
or modifying login-classifier attributes. Rollback uses the same supported
sequence with the previous immutable SHA; it does not touch vault data.
