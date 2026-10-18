# Unreleased local Link CLI payment facility

**Isolated candidate only. Not installed, activated, published, PR'd, or verified on a real merchant.** This extends the existing secure-entry plugin; it is not a second plugin or core override. Existing add-login/OTP/unlock behavior is unchanged. Payment is disabled unless the operator supplies `link_cli_command`.

## Research first

Reviewed `web3blind/hermes-secure-env-plugin` at immutable commit `96fac2a1295f51d45466276276af32e6d6059c41` (0.8.1): `secure_env_ingress/payment_fill.py`, `bound_cdp.py`, `parent_session.py`, manifest and tests. It already provides an actual local `secure_payment_fill`, not merely ENV entry. Its valuable design is captured native CDP, private isolated-world DOM/document closures, retained iframe lineage, explicit merchant/provider consent, per-operation cancellation/deadline guards, unknown-write outcomes and attachment cleanup. Its payment secret source is a native origin-bound saved payment item, not Link's transient private file. Its deployment/identity ingress is Telegram/Linux-oriented. We did not dismiss it merely for platform restrictions. No license is declared in its manifest/pyproject/repository metadata; no source was copied or vendored. This implementation independently composes the same native host contracts.

Reviewed Stripe's official `stripe/link-cli` at **`@stripe/link-cli@0.27.4`, SHA `686c4b5e02cd47c941c66d42d45840b8ca6ca536`**. `packages/cli/src/commands/spend-request/index.tsx:65-85` implements `--output-file`, with `spend_request_id`, `merchant_url`, and `card`; it strips the full card from stdout. `utils/credential-output.ts` creates exclusively and requests POSIX 0600, but explicitly notes Windows lacks full no-follow semantics. Therefore the native consumer creates a protected inherited Windows DACL *before* invoking Link; it does not equate chmod/0600 with Windows privacy. A successful retrieve must return exact request `id` and status `approved`. This facility never creates, approves, updates or pays a spend request.

Reviewed Browser Use's official local `examples/features/sensitive_data.py`: domain-specific placeholder substitution is existing local secret handling, but not a Hermes identity-bound native payment approval/private-file consumer. It does not substitute for the facility's host consent, exact retained frame/document binding or private Windows handoff. Browser Use Cloud Link payment is a different cloud route, not the requested local implementation.

The installed secure-entry 0.3.0 explicitly has no payment support: its genuine prompt bridge covers OTP and manager unlock, not payment consent. Here payment uses the existing native `tools.approval_prompt.request_elicitation_consent(surface='vault-payment')` unchanged. The host's authenticated gateway approval notification/resolution route is tested directly; no dummy unlock callbacks, approval registry edits, or synthetic approval bypass exists in production.

References:
- https://github.com/web3blind/hermes-secure-env-plugin/tree/96fac2a1295f51d45466276276af32e6d6059c41
- https://github.com/stripe/link-cli/tree/686c4b5e02cd47c941c66d42d45840b8ca6ca536
- https://github.com/browser-use/browser-use/blob/main/examples/features/sensitive_data.py
- https://hermes-agent.nousresearch.com/docs/developer-guide/plugins

## Pinned CLI JSON contract (0.4.1 fix)

Inspected installed `@stripe/link-cli@0.27.4` `dist/cli.js` without executing wallet operations: `spend-request retrieve` is an async generator (lines 9671–9742), whose JSON output is an array of records. The adapter accepts exactly one approved record matching the requested ID, or the legacy single object. Empty/multi-record arrays, nested arrays, non-object records, wrong IDs and unapproved statuses are refused.

`applyOutputFile` (lines 9284–9299) writes a **single object**, not an array: `{spend_request_id, merchant_name, merchant_url, context, created_at, card}`. It removes `card` from stdout metadata and adds `card_output_file`. The existing private-file consumer already matches that structure. A synthetic subprocess exercises the object/array split through the actual adapter and Windows private-file consumer, including billing and delete-on-close cleanup. No live credentials or checkout were accessed for this fix.

## Generic target binding compatibility (0.4.2)

Formless controls require one smallest shared container other than body/html,
no form owners, no unrelated controls, unique supported autocomplete tokens and
one complete payment shape. Container, field parents, nodes, document, context,
origins and sticky mutation checks remain retained; no provider/ID exceptions.
Ordinary one-form support is unchanged. Distinct groups joined only at the
document body, duplicate widgets and unrelated controls refuse.

An explicit parent page may differ from the capture's default page. The facility
uses only supported `CapturedCDP.call` on that same captured socket to inspect and
attach the exact supplied page, verifies its type/identity, then proves direct
iframe ownership. It does not discover endpoints, enumerate/focus pages or start
browsers. Both child and owned parent attachments are cleaned up, including late
attachment replies. Native approval still follows successful binding.

Safe `target_binding` refusal categories are `selected_parent`, `frame_lineage`
and `form_layout`; raw CDP errors and target/DOM data are never returned.
Regressions exercise real cross-origin formless billing/SELECT/React-like controls,
retained-container replacement, unrelated groups, and actual BrowserUse subprocess
IPC selection of a non-primary tab. The original tab stays empty. This is synthetic
fixture evidence, not live merchant acceptance.

0.4.2 verification: full suite **176 tests passed**; targeted real-browser suite
passed, including actual multi-tab harness integration. Targeted Ruff checks,
plugin doctor and all catalog checks passed. Catalog retains the existing
private-core-import warning. No installation or live payment interaction ran.

## Parent mutation scope and consent diagnostics (0.4.4)

The parent guard retains the exact iframe, document and complete ancestor chain.
Only records that remove a retained lineage node or change a non-`title`,
non-`aria-*` attribute on that lineage invalidate it. This includes iframe
`src`/`srcdoc`, `sandbox`, permissions, name, style/class and ancestor inert/hidden
changes. Removal/reparenting and security mutation followed by restoration remain
sticky refusals. Unrelated carousel subtree changes, sibling insertion, parent
page title/ARIA changes and mutations in another page do not invalidate the
retained iframe. Child field/document checks are unchanged.

Failures distinguish `native_consent`, `postconsent_current` and
`postconsent_target`. Fixed reasons include `consent_failed`, `consent_timeout`,
`operation_cancelled`, `operation_timeout`, `takeover_refused`,
`browser_capture_invalid`, `owner_changed`, `current_check_failed` and
`target_check_failed`; no exception text is returned. The native host maps some
internal timeouts/errors to a nonaccept verdict; these remain `payment_declined`
rather than inventing a finer reason the host did not supply.

The 180-second execution budget credits only the host's bounded recorded
human-wait delta during the genuine native consent call, capped by that call's
elapsed time. It does not exempt arbitrary stalls, extend the host approval
policy, bypass consent or suppress postconsent lifecycle/owner/target checks.

Targeted RED/GREEN exercised the unrelated-parent regression and consent
stage/reason/deadline regression. Full suite: **181 tests passed in 114.826s**,
including disposable real Chrome OOPIF mutation/revert and native consent tests;
targeted Ruff passed. No live browser, wallet, credential, install or core change
was used for this repair.

## Private-file diagnostics (0.4.5)

Private-artifact refusals now return an allowlisted `refusal` category at
`stage=private_file`: Windows API/open/info/ACL/owner failures, reparse/file type,
link count, size/read/JSON/object shape, request/merchant binding, card shape,
PAN type/format, CVC type/format, expiry type/range, and billing type/field
validation. Unknown exceptions become `private_file_failed`. No values, paths,
request identifiers, exception messages or producer output are returned.
All existing filesystem and exact request/merchant fences remain in force.

Contract audit: the official [SDK types](https://github.com/stripe/link-cli/blob/main/packages/sdk/src/types/index.ts)
declare PAN/CVC as strings, expiry as numbers, billing as optional, and
line2/city/state/postal_code as optional strings. Missing fields and empty
strings already work. That source does **not** declare nullable billing fields;
no null normalization is guessed in this diagnostic release. Unknown top-level
and card metadata remain ignored. Numeric PAN/CVC are refused explicitly instead
of accepting them via string coercion and failing later in the fill path.

RED/GREEN covered malformed nested shapes and secret-bearing unexpected errors,
then model-visible fixed diagnostics. Isolated full suite: **182 tests passed**
in 111.262s. No wallet, live browser, installation or runtime configuration changed.

## Windows default-owner compatibility (0.4.6)

Windows assigns a newly created file the effective token's `TokenOwner`, which
can be an owner-capable group rather than `TokenUser`. The consumer now queries
the effective thread token first (process fallback only for ERROR_NO_TOKEN).
It does **not** add Administrators or any other group to its accepted owner or
DACL principals. After validating the existing private user+SYSTEM DACL and
file shape through an exclusive no-follow handle, a differing owner is eligible
for normalization **only** when it equals that token's native `TokenOwner`.
`SetSecurityInfo` narrows it to `TokenUser` through that same handle; readback
must confirm the user owner and every unchanged DACL ACE before reading data.
Failure to normalize refuses. No privilege is enabled by production code.
Foreign owners and foreign DACL principals still refuse, without repair.

This removes existing group-owner implicit WRITE_DAC authority rather than
accepting it. It does not retroactively prove privacy before handle acquisition
or claim protection from the same OS user/admin; the protected parent directory,
exclusive handle and existing Windows threat boundary remain essential.
Diagnostics add only fixed `private_object` (directory/file), `owner_class`
(user/system/token_default/administrators/other), and `owner_normalize` refusal;
no identity, SID, path, exception or private data is returned.

Strict RED reproduced the actual `owner` refusal using a duplicated kernel
impersonation token whose TokenOwner is a real owner-capable group and a file
created by Windows under that token. GREEN covers handle normalization/readback,
full consumption of newly created default-owner files, directory normalization,
foreign-owner refusal, and no normalization of a foreign-principal DACL.
No wallet/API/credential reads or browser access were used for this fix.

## Registered native facility

`secure_entry_payment_fill(parent, frame, merchant_origin, frame_origin, spend_request_id)` accepts **metadata only**. The exact parent must exist on the native task supervisor's captured connection; `frame` must be that page's inspected root frame with matching merchant/frame origins, or a direct iframe owned by that parent. See [0.5.10 topology/semantic support](payment-topology-0510.md) for the current form contract. The authenticated same-profile supported DM, user/chat/session identity, native task and service lifecycle generation are checked. The existing public native capture pins the supervisor/WebSocket generation. No model-supplied endpoint, file path, script, selector, card or credential argument exists.

Sequence: capture exact documents/nodes in fresh isolated worlds; request real native explicit merchant+provider+Link-request consent; revalidate; retrieve the independently Link-approved request into an unpredictable protected inbox; validate request/merchant/file; register redactions before browser transmission; revalidate and fill over the *same* native CapturedCDP socket; read back counts only; remove private file/inbox and close/release remote objects/attachments. A same-origin reload invalidates remote objects instead of acquiring a replacement document. Child document/node identity and security-relevant mutation are checked synchronously within the child write closure, before each field; values of all retained fields are checked between events and at completion. Parent checks occur before and after the child CDP call, **not atomically with it**: a parent-only mutation after preflight can allow PAN disclosure to the retained child before the postcheck reports `write_unknown`. There is no cross-process atomic parent-mutation/no-disclosure guarantee. Stop/reset/unload, expired scope, reconnect and takeover refuse further dispatch when observed. Writes already started are `write_unknown`, never a promise that nothing happened. Do not blindly retry unknown outcomes.

There is no persistent per-site payment vault record, environment secret, CLI argv card data, model-visible stdout, click or Submit call. Websites can have their own automatic behavior; 'no Submit' is not a guarantee the merchant cannot react to an input event. Native approval must be obtained before any real fill. This test run accessed no wallet, real credential, real merchant or payment API.

### File security

Windows-only `pywin32` is a runtime prerequisite (present in the exercised isolated test environment). A new unpredictable directory has protected DACL allowing only the process user and SYSTEM, with inheritance to Link's output. Consumer opens no-sharing, OPEN_REPARSE_POINT and DELETE_ON_CLOSE handles, verifies owner and allowed DACL principals for directory/file, rejects reparse points, directories, hardlinks, oversized/malformed files and mismatched request/merchant. The private file is consumed once and deleted using its kernel handle. Directory cleanup also runs on refusal. This is best-effort memory release and normal filesystem deletion, not guaranteed forensic erasure or protection from the same OS user/admin. Abrupt process termination before consumption may leave a protected inbox; no restart sweeper is claimed.

## Scope limits / activation gates

**Current 0.5.10 form support supersedes the older direct-iframe/strict-autocomplete limitation below:** [top-level root binding, semantic expiry/CVC, hidden postback state, numeric SELECT defaults and exact retained authority](payment-topology-0510.md). Other private-file, approval, route, takeover and unknown-write boundaries below remain unchanged.

- Exactly one ordinary form or one cohesive formless container in one **direct** cross-origin iframe. Supports standard `cc-number`, either `cc-exp` (MM/YY) or both split expiry controls, optional `cc-csc`, `cc-name`, and billing country/address/city/state/postal/tel autocomplete. Country/state may be SELECT controls with one exact enabled matching option. Other controls, duplicates, mixed expiry shapes, multiple forms, nested frames and shadow DOM are not supported; no site-specific selectors exist. Name/address values come only from the issued Link `card.billing_address`. Matching prefilled public billing/cardholder fields are preserved; mismatches refuse before writing any field. Existing phone may be preserved privately, but an empty phone without a native source refuses (there is no model phone override yet). No guest profile address is substituted for issued billing. PAN/expiry/CVC must be empty initially. Native prototype setters dispatch bubbling input/change events, including React-like own-property value trackers. Mutation handling distinguishes destination/control authority from widget presentation. Class and validation feedback (`aria-invalid`, `aria-describedby`, `aria-errormessage`) do not invalidate retained controls. During synchronous native self-write events, retained INPUT length constraints (`minlength`/`maxlength`, including PAN-triggered CVC changes) and non-control ancestor accessible naming/announcement metadata (`role`, `aria-label`, `aria-labelledby`, `aria-description`, `aria-hidden`, `aria-live`, `aria-atomic`, `aria-relevant`, `aria-busy`) may update without changing the destination. This is not a blanket ARIA/constraint exemption: control semantics, ARIA ownership/control relationships, form/action/base, name/type/autocomplete, readOnly and credential disabled state remain sticky. Length/accessibility changes outside that event window remain sticky too. Presentation children can change only without adding/removing semantic inputs/forms/base or removing/reparenting retained ancestors. Actual control visibility/usability and exact expected values are rechecked after events; CSS hiding through an allowed class/ARIA update still refuses, and truncated values cannot count as successful writes. Initially disabled billing may synchronously enable under the existing retained availability model; asynchronous enabling remains unsupported. PAN verification accepts only exact expected digits with single spaces/hyphens separating digit groups, not arbitrary masking/content. **Cvent/Passkey live compatibility remains unverified.**
- Requires a live *already-selected* native task supervisor, captured through the existing public `SUPERVISOR_REGISTRY.capture(task_id)` API. No legacy `_active_sessions` metadata or new core patch is needed. It never creates/reselects a browser or obtains authority from a visible target/loopback endpoint. Default, named and hybrid BrowserUse dispatch work in the isolated native harness. Local/cloud CDP captures can satisfy the contract; LOCAL refers to the Link CLI/private-file source, not browser geography. Direct-cloud routes with no existing native capture refuse. There is no route-name selector or last-successful-dispatch receipt: the exact explicit parent/frame on the current task capture is the target, not an inferred daemon. Existing captures never retarget on supervisor replacement/reconnect. See [the corrected no-core-dependency decision](payment-route-blocker.md).
- Conservatively applies the genuine profile-specific native desktop lease to **all** payment routes, regardless of uncertain desktop classification. Active human takeover refuses before capture; the retained epoch also detects takeover-and-handback. Checks run around approval/retrieval, immediately before target CDP dispatch and after completion. This can over-refuse an unrelated cloud browser while a human holds the profile desktop, but does not bypass native protections.
- Uses native host adapters also used by existing vault tools. Doctor and catalog validation exercise real registration. Catalog validation can report **private-core-import warnings** for existing owner/OTP adapters and native modules; there is no core override, monkeypatch or new upstream dependency in production. Public capture is an existing native API, not a new PluginContext facade.
- `link_cli_command` is an operator-trusted argv prefix, e.g. absolute native `node.exe` plus absolute Link CLI JavaScript entrypoint. Empty disables. `.cmd`/`.bat`/shell prefixes are refused. No operator configuration or live executable was changed in this work. Real Link 0.27.4 invocation remains live-unverified; subprocess tests use a synthetic producer with the verified upstream file/metadata contract.
- Text redaction covers raw/formatted PAN, CVC and expiry before dispatch. This reuses the native text egress boundary. It does **not** promise image/screenshot pixel redaction; do not capture/display filled card fields to the model. There is no new arbitrary secret-read API.
- Photon native gateway consent is synthetic-integration-tested, not physically verified here. Actual accessible approval rendering, selected browser route, hotel widget, cancellation UI, and real independent Link authorization remain operator-approved acceptance gates. No installation/restart/release should precede parent review.

## Tests and reproduction

Tests use real isolated headless Chrome, genuine cross-process iframe attachment (asserted), actual native `SUPERVISOR_REGISTRY.capture().call`, actual generated fixed JavaScript, actual Windows kernel ACL/file handles, real native gateway consent enqueue/resolve, and a synthetic subprocess replacing only Link/API production. They do not connect to the user's browser or wallet. Additional tests cover same-origin reload, navigation between preflight and secret send, native-consent navigation, reverted mutation, input-event replacement, reconnect, late attachment cleanup, untracked remote object-group release, lifecycle admission race, post-admission takeover, unknown-after-write classification, foreign ACL/hardlink/oversized/malformed/wrong-merchant file refusal and nonapproved Link metadata. Real BrowserUse subprocess/IPC dispatch followed by public capture and native-consent OOPIF fill passes for default, named and hybrid routes with legacy session metadata absent. Only test browser provisioning and the Link API producer are replaced; native capture, dispatch, approval and private-file checks execute unchanged.

Development used vertical RED/GREEN runs before each new feature/fix: missing private-file consumer, missing browser facility, missing native operation, missing subprocess producer, missing registration; then lifecycle-admission, takeover-admission, browser-provenance, late-attachment cleanup, remote-object cleanup and unknown-write regressions. Existing protections also received negative tests, without weakening them to get green.

In Git Bash on this machine (all paths are native forward-slash paths):

```bash
# Set these to your isolated plugin/core/test-environment absolute paths.
export PYTHONPATH="$CORE;$PLUGIN"
export HERMES_HOME="$SCRATCH/secure-entry-link-validation-home"
export TMPDIR="$SCRATCH"
export TMP="$SCRATCH"
export TEMP="$TMP"
"$TEST_PYTHON" -m unittest discover -s tests -v
```

Final pristine-core validation output after the plugin-only route adaptation:

```text
Ran 167 tests in 65.789s

OK
```

The default/named/hybrid real BrowserUse dispatch tests also passed independently (`Ran 3 tests in 12.320s`, `OK`). Targeted Ruff checks on the adapted payment module, registration module and route/admission tests report `All checks passed!`. A whole-repository Ruff run still reports pre-existing style/unused-import findings outside this adaptation; no unrelated cleanup was mixed in. On Windows, the test harness waits for its identity-checked disposable daemon to release log handles after reload; it can terminate only that test daemon if native best-effort reload hits a port-file cleanup race. No runtime core fix is included.

Playwright was installed only in the preexisting isolated test interpreter, never the live runtime. Existing Chrome is launched with an ephemeral profile and remote debugging port 0. Parent verification should rerun the full suite plus doctor/catalog validation using this isolated home, then review the diff before any activation or publication.
