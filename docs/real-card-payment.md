# Real-card private entry, retained native fill, and explicit cleanup (0.5.0)

This is **in addition to Link**, not a replacement. Keep `secure_entry_payment_fill` for an already approved Link spend request. Choose the real-card route when the user chooses it or a temporary card is unsuitable (hotel guarantees, deferred charges, later incidentals). Never infer that a successful fill made a reservation or authorized a purchase.

## Reusable workflow

1. The agent determines the **official checkout merchant origin** from the intended site, rather than asking the user to choose a technical vault binding. For a hotel Passkey booking, inspect the official hotel checkout and its actual origin; do not assume a marketing page, booking link, redirector, or embedded payment provider is the merchant. This release performed no live hotel navigation or card collection.
2. In the authenticated originating human DM, call `secure_entry_request(operation="add_card", origin="https://merchant.example")`. Give the one-use private URL only to that conversation. The page identifies that exact merchant and explains storage. The URL expires in ten minutes; preview GET does not consume it. Native identity/profile/session, lifecycle, CSRF, bounded request, loopback/Tailscale, and no-secret-output fences match login entry. No card field is a tool parameter. Anyone with the capability URL and allowed tailnet access can submit: the web page itself does not authenticate the DM sender. URLs can appear in conversation history.
3. The user privately enters card number (digits only), cardholder name, month, four-digit year, CVC and billing postal code. The native `payment` kind is saved encrypted, never disguised as a login. Poll `secure_entry_status(request_id)`. Preserve the returned `handle` as the **cleanup handle**. `saved` requires metadata readback; `commit_unknown` requires inspection, not blind resubmission. Native `browser_vault(action="list")` can list native payment handles without exposing card payloads.
4. Inspect value-free merchant and direct payment-iframe descriptors. Call `secure_entry_card_fill(handle, parent, frame, merchant_origin, frame_origin)` on that same task's captured browser. `merchant_origin` must exactly match the saved vault origin; `frame_origin` is the **separate actual payment-provider HTTPS origin**. Native explicit `vault-payment` consent names both. It authorizes only the retained merchant document/direct-frame pair for this fill, not all domains or all same-origin tabs. No stored wildcard or provider-origin widening is added.
5. The existing retained payment-browser writer performs the fill. Same native supervisor capture, task-selected parent, isolated-world node/document retention, native lease/takeover epochs, postconsent lifecycle/owner rechecks, redaction, and no-submit rules apply to both routes. Only the card source differs. The real-card route does not call Link or write a plaintext handoff file. Its form support is documented in [the generic top-level/iframe and semantic-field contract](payment-topology-0510.md); it does not promise every hotel's widget works.
6. Verify the actual fill and reservation/checkout result separately before cleanup. **No automatic deletion occurs**, including on fill failure. A `write_unknown` result may mean fields were written: inspect rather than retry or claim nothing happened. Preserve the handle until outcome is understood. On explicit user cancellation, cleanup is appropriate even without a completed checkout.
7. Call `secure_entry_card_remove(handle, merchant_origin)`. This requires an authenticated human DM/profile, a syntactically valid local native handle, payment kind, and matching exact merchant origin. It is explicit removal authority, not possession of a link. `deleted` requires post-remove `get_meta(handle) is None`; already absent returns `absent` after readback. Exceptions once removal starts return `deletion_unknown`, never an unverified success. Reinspect/repeat the metadata-only cleanup after uncertainty. Removal does not clear page fields, revoke merchant possession, retract an already-started fill, securely erase storage media or remove backups. Do not race cleanup with a pending fill.

## Native API inventory and CVC contract

Inspected both canonical Hermes 0.22.1 source and the PM-selected workspace. Supported public APIs already exist in `agent.vault_store`:

- `VaultStore.add_item(kind="payment", label, secret, origin)`
- `list_items()`, `get_meta(handle)`, `resolve_secret(handle)` (server-side only), `remove_item(handle)`
- `PAYMENT_FIELDS` defines `card_number`, `cardholder_name`, `exp_month`, `exp_year`, `cvc`, `billing_postal_code`.
- `REQUIRED_FIELDS["payment"]` requires **card_number, month, year and CVC**. The supported CLI/Desktop payment contract persists CVC encrypted. This plugin explicitly uses that existing contract, with a disclosure on the entry page. **It does not claim nonpersistent CVC or PCI compliance.** Encrypted CVC persistence can still be inappropriate for a given operating/compliance context; do not enable that route where such retention is prohibited. Delete promptly after the verified intended operation.

The initial search for `add_card/save_card/delete_card` method names was insufficient: these operations use generic native payment-kind APIs. No second card store, private crypto call, login-storage workaround, external-manager mutation, or core patch is required. Native `browser_vault` payment fill also exists with consent and exact-origin binding, but its legacy page selection is not the plugin's retained cross-origin contract. The plugin reuses its stronger existing `LocalPayment`/`Target` writer, not per-site code or a native-tool override.

A **nonpersistent separately entered CVC** is preferable but is **not implemented**: current native add requires CVC. A CVC-less native record requires a supported native storage/schema change. No public generic encryption facade was found in the inspected native vault; `_fernet`, `_read_all` and `_write_all` are private. Do not fake CVC, store an incomplete card as a login, use private vault surgery or invent a plugin encryption API. Report that design blocker before attempting such a variant.

Native at-rest protection remains Hermes's existing Fernet vault/key and host filesystem contract. This plugin does not upgrade or claim stronger Windows vault ACL guarantees; Link's protected transient private-file DACL contract is a separate mechanism.

## Tests and honest verification

`tests/test_cards.py` exercises real loopback HTTP -> native Fernet add -> metadata list/reopen -> genuine native payment approval enqueue/resolution -> real isolated Chrome cross-origin iframe with `CapturedCDP` -> six field writes -> explicit native deletion with verified absence. All fixtures are disposable and synthetic. There are no actual user cards, live user profiles or live merchant browser operations.

RED -> GREEN slices were executed for missing add-card admission (`invalid_operation`), missing cleanup API, missing retained saved-card fill, missing tool registration, malformed cleanup handle leaking through `absent`, and missing cardholder-name mapping. Existing Link tests retain all behavior assertions; only the executing-module version marker changes to 0.5.0. Regression tests additionally cover CSRF, invalid expiry, reset/cancel before save, native decline, wrong merchant/provider, invalid handle, missing capture, reset during consent, retained card after fill, nonpayment/group cleanup refusal, and unknown native delete outcome.

Full suite: **194 tests pass** with a disposable `HERMES_HOME`, both against canonical and PM-selected Hermes source. An initial run inherited the active profile and loaded its installed middleware as well as the test middleware, producing 28 OTP bridge/multiplatform failures (also reproduced from the untouched 0.4.6 baseline). Isolating the profile removes that double-loading; no assertions or production fences were weakened. Always run validation with an explicit disposable home. See the release validation report.

## Install without activating a live gateway

Use the published **immutable commit SHA** from the release report:

```bash
hermes plugins install mforzano/hermes-secure-entry --ref <FULL_COMMIT_SHA> --yes-deps --no-enable
hermes plugins doctor secure-entry --ci
hermes plugins capabilities secure-entry
```

Do not add `--enable` during independent verification. On an existing loaded installation, first coordinate native unload/disable or stop the gateway; do not overwrite active middleware. Preserve existing Link command configuration and the trusted tailnet-only Tailscale Serve root route; never use Funnel. `plugins.isolation` must be `in_process`; the supported Hermes range remains `>=0.22.1,<0.22.2`. The parent/operator owns installation, coordinated activation/new session, live tool verification, official hotel-origin selection and actual private-link issuance. This task neither installs over nor activates the live plugin.
