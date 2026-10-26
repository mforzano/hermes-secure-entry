# Explicit payment-field mapping (0.5.14)

This supersedes the old automatic-layout admission contract **for the two
registered plugin payment-fill tools**. It does not change Hermes's built-in
`browser_vault` filler, login/OTP/unlock bridge, vault format or core source.

## Workflow and tool contract

1. Connect/select the intended checkout through the current task's browser. Read
   only value-free descriptors: labels, IDs, tag/type, origin, frame identity,
   visibility and availability. Do not return field values, DOM/HTML dumps or
   secret-bearing screenshots, particularly after a prior fill.
2. Choose the intended active elements. Obtain each element's CDP
   **backendNodeId** in the selected payment document. These are not frontend
   `nodeId`s, CSS selectors, DOM `id` strings or arbitrary model-generated IDs.
   Browser-side inspection may use `DOM.describeNode` on an inspected element
   object and return only its `backendNodeId` and safe descriptors. Same-origin
   iframes share the parent CDP session; inspect their actual execution context,
   not the parent's default `document`. Cross-origin OOPIFs may require their own
   attached session. Never relabel a same-origin iframe as cross-origin.
3. Call the existing tool with the exact parent target, payment frame, merchant
   and payment-document origins, source metadata, and `field_mapping`.
4. Native code copies the mapping, captures the task's existing browser, resolves
   the selected backend IDs **once** into actual isolated-world element handles,
   verifies their document, and retains them before native consent. Consent names
   the page target/frame, origins, semantic mapping and selected-prefill overwrite.
5. Only after consent and target revalidation does native code retrieve the
   merchant-bound vault card or approved Link private file. Its private generated
   writer uses the retained elements and prototype value setters plus input/change
   events, then verifies the resulting private values. No secrets go through model
   arguments/results, terminal output, selectors or model-generated injection code.
6. Inspect value-free fill status and merchant acceptance separately. Native fill
   is not payment submission, reservation or purchase. Explicitly remove a
   temporarily saved card after verified checkout outcome or user cancellation.

Illustrative **metadata-only** saved-card call (IDs are examples, not reusable):

```json
{
  "handle": "<native payment metadata handle>",
  "parent": "<inspected page target ID>",
  "frame": "<inspected root or direct iframe ID>",
  "merchant_origin": "https://merchant.example",
  "frame_origin": "https://merchant.example",
  "field_mapping": {
    "cc-number": 101,
    "cc-exp-month": 102,
    "cc-exp-year": 103,
    "cc-csc": 104,
    "cc-name": 105
  }
}
```

For Link, call `secure_entry_payment_fill` with `spend_request_id` instead of
`handle`; independent Link spend approval is still required. No spend creation or
approval is performed by this fill tool. The private-file consumer and native
Windows ACL/ownership checks are unchanged.

### Semantics and behavior

- Canonical card semantics: `cc-number`, `cc-exp` (combined) or `cc-exp-month` /
  `cc-exp-year` (separate), `cc-csc` (CVC), `cc-name` (cardholder).
- Explicit billing: `billing country`, `billing address-line1`, `billing
  address-line2`, `billing address-level2` (city), `billing address-level1` (state),
  `billing postal-code`. Sources must actually provide requested data. Saved native
  cards supply name/postal, not a full street address. The legacy `billing tel`
  token remains in the schema, but neither current source supplies phone data;
  explicitly mapping it returns `source_missing`, not a read of the guest phone.
- Map only intended fields, including billing **only when explicitly wanted**.
  Unselected fields are neither inventoried, read for values, matched to card
  identity, written nor validated. Existing guest billing may remain untouched.
- Autocomplete is not required and is not rewritten. The agent can deliberately
  map an ordinary visible text/tel/number input or select regardless of its labels
  or autocomplete. Input type `month` supports combined `YYYY-MM` expiry.
- Selected prefills may be overwritten. Unrelated controls, additional forms,
  unknown data controls, checkboxes, alternate layouts and their mutations do not
  block the operation. There is no whole-form count/container/inventory gate and
  no page-wide duplicate-semantic rule. A mapping cannot assign two different
  secrets to the same actual node; multiple unselected same-semantic controls are
  fine. Partial mappings are allowed; the agent chooses the intended set.
- Native formatting supports numeric month/year selects, two-digit-year inputs,
  ordinary combined `MM/YY` and exact-semantic spaced slash masks, spaced/hyphenated
  PAN, and billing select values or exact case-insensitive option labels. Opaque
  option encodings or other masks are not guessed. Prototype setters bypass
  React-like instance trackers; actual values are checked after input/change.
- Selected fields must be visible and supported input/select controls. Disabled or
  readonly selected controls are never written; synchronous card events may enable
  selected dependent billing. Missing source values refuse before any write.
  Replacement, removal/reinsertion, reparenting, form reassociation, type changes,
  document navigation and origin changes invalidate the retained destination.
  No-op selected `type`/`form` assignments do not invalidate it; actual changes
  followed by restoration remain sticky. Mapped iframe guards ignore iframe and
  ancestor presentation rewrites, while retaining destination, document and node
  identity checks. The internal legacy path keeps its previous mutation policy.
- Parent/frame ownership, genuine native consent, authenticated DM/profile/session,
  lifecycle/deadline, task capture/takeover and private-secret fences remain.
  Parent/child checks are **not cross-document atomicity**. Changes after dispatch
  can produce `write_unknown`; no promise of zero disclosure accompanies that state.

`filled_fields` counts verified selected writes, not merely setter calls. Fixed
refusal categories may include `source_missing`, `select_mismatch`,
`billing_unavailable`, `write_mismatch` or `invalidated`. Target binding/check
failures in the mapped path set `reinspection_required: true`; inspect again and
obtain fresh native consent rather than retrying old IDs. `write_unknown` may mean
some selected values reached the merchant; do not dump those values to investigate.

The registered handlers refuse omitted `field_mapping` even if schema validation
is skipped. Explicit `null`, empty, malformed, unknown-token, foreign-document,
nonfield and unknown backend-ID mappings refuse. The old classifier is retained
only as an **internal compatibility/regression** path for direct legacy Python
callers; neither registered payment tool can silently fall back to it.

## Evidence and limits

The tests run in a disposable `HERMES_HOME`, isolated Python environment and actual
headless Chrome, with actual native `CapturedCDP`. They include registered native
handlers, genuine approval enqueue/resolution using synthetic human decisions,
a synthetic private-file producer process and a disposable actual encrypted native
vault. No live vault, merchant browser, card or Link spend is used.

Mapped tests cover arbitrary non-autocomplete fields, selected guest-prefill
overwrite, unrelated/multiple forms and mutations, unselected billing/consent,
combined masked expiry, separate expiry selects and two-digit years, prototype
React-like setters, top-level root, cross-origin OOPIF and same-origin direct iframe.
The same-origin fixture reproduces the supplied Gotham shape (raw `cc-cvc`, generic
`name`, street/city/postal/country/state, phone controls, separate TOS/marketing).
It proves synthetic compatibility with that shape, not a purchase by itself.
Unknown/foreign/nonfield IDs and selected-node replacement
are tested. A target changed during consent refuses before private retrieval.

Separate live evidence: the operator's completed Gotham checkout exercised the
mutation fix with a saved native card, reported five verified mapped fields,
passed merchant acceptance and reached purchase confirmation. Local temporary-card
deletion was verified afterward. This occurred before the 0.5.14 diagnostic/version
bump; the release preserves the observed working writer behavior. No order,
personal or card details are retained here. This is one live saved-card checkout,
not proof of universal checkout support or live Link acceptance.

Regression fixtures additionally exercise no-op selected attributes and iframe/
ancestor presentation mutations during genuine native consent, through registered
Link and saved-card dispatch. Actual type/form change-and-restore, selected-node
removal/reinsertion and iframe destination change-and-restore still refuse.

## Release verification

The final isolated-home regression run returned:

```text
Ran 283 tests in 240.340s
OK (skipped=4)
```

Command: `python -m unittest discover -s tests -q`, using the disposable
`payment-layout-venv`, a fresh scratch `HERMES_HOME`, and explicit core/plugin
roots on `PYTHONPATH`. Core imports came from the local Hermes source checkout;
this is not a separate pristine-core compatibility claim. Fatal-error lint passed
with `ruff check --isolated --select E9,F63,F7,F82 secure_entry tests`, and
`git diff --check` passed. The broader inherited lint selection is not clean;
this release does not undertake unrelated style/security-lint cleanup.

Two initial full runs exposed an order-dependent negative fixture: a backend ID
from the parent renderer could alias a valid OOPIF input. The fixture now uses
same-origin documents sharing a renderer for a real foreign-document node and
explicitly resolves its nonfield node. No production mapping/writer behavior was
changed to make that test pass. The final full run above includes this fixture fix.

## Installation and activation — separate from publication

- Publish/install the final reviewed **immutable tested plugin revision** only when
  separately authorized. This release is version **0.5.14**;
  successful native results expose `payment_diagnostic_version: "0.5.14"`.
- This is plugin-only: no Hermes core patch, source rebuild, new plugin or additional
  production dependency is required. Existing manifest bound remains
  `>=0.22.1,<0.22.2`; native private-card handling remains Windows-specific and
  requires `plugins.isolation=in_process`.
- Coordinate unloading/stopping the running middleware before replacing an active
  installation through the supported plugin manager. Do not copy over a loaded
  plugin. Enable and doctor the installed revision, then refresh plugin/tool
  registration and **start a fresh conversation/tool schema** so `field_mapping`
  is visible. A new gateway process is the fallback when safe unload/reload is not
  available. This publication does not install or reload the release; the live
  checkout used the earlier coordinated activation of the mutation fix.
- Existing Tailscale Serve URL/port and DM identity configuration need no payment
  mapping changes. Existing saved native card handles remain compatible. Link
  needs its existing operator-configured absolute `link_cli_command`; an empty
  command continues to disable Link but does not disable saved-card fill.
- Reconnect and re-inspect the intended live checkout **after activation**, obtaining
  current parent/frame/backend IDs. Have native consent show the exact mapping.
  Verify native fill, merchant widget acceptance and purchase outcome separately.
