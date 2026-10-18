# Generic retained payment documents — 0.5.10

Plugin-only repair. No Hermes core source/configuration change, dependency installation,
real credential read, real spend, live checkout submission or gateway activation.
Synthetic success is not merchant acceptance or a completed payment.

## Metadata-only target contract

Both `secure_entry_payment_fill` and `secure_entry_card_fill` retain all existing
required arguments. `parent` is the exact inspected page target on this task's
native capture. `frame` is either:

- the explicitly inspected **root frame ID** of that page, with
  `frame_origin == merchant_origin`; or
- the existing exact direct payment iframe ID, with its separately inspected
  HTTPS origin.

Inspect `Page.getFrameTree` for the selected page to obtain the root frame ID.
Do not substitute a target ID, omit the frame, select by URL, guess an ID or
fall back to the root after an iframe refusal. Binding uses existing native
`CapturedCDP.call`, isolated worlds and retained remote objects. A non-primary
selected parent uses the existing explicit attachment path. No core primitive
or provider/domain/ID selector is added.

Root mode retains the single payment document as both merchant/destination;
iframe mode keeps the existing parent-lineage guard and child-document guard.
Same-origin reload, navigation, form/action changes, control replacement,
reparenting, duplicate fields and sticky change-and-restore mutations refuse.
Native owner/profile/task capture, takeover epochs, lifecycle, bounded native
consent, private-file ACL validation and redaction are unchanged. Existing
cross-process parent-check limitations and `write_unknown` semantics remain.

## Generic field handling

- One ordinary form or cohesive formless container; one explicit `cc-number`
  anchor and one complete split or combined expiry shape are required.
- Standard supported autocomplete remains authoritative. Missing, `off`, or
  `on` expiry/CVC autocomplete can use conservative English semantic labels:
  explicit/wrapping HTML labels, `aria-label`, `aria-labelledby`, or the nearest
  non-form structural row/group containing exactly one data control and text
  outside inputs/options/buttons. This supports a plain table-row `Month`/`Year`
  and `Card Verification Value(CVV2)` without merchant attribute edits.
- Combined expiry uses MM/YY, including the existing exact MM / YY mask support.
  Split expiry INPUTs use two-digit month/four-digit year. Split SELECTs accept
  unique enabled numeric month options (`1` or `01`) and two-/four-digit years.
  Opaque option IDs and duplicate numeric equivalents refuse before any write.
- Existing SELECT defaults may be replaced under native consent, but their
  initial values, option nodes and mutation fences are retained. PAN, CVC and
  expiry INPUTs must still be empty, enabled, visible and writable.
- Hidden INPUTs with no autocomplete are non-fill postback state. Their values
  are neither collected nor modified. They cannot change type/autocomplete to
  become credential controls, including change-and-restore. Hidden credential
  controls still refuse.
- Buttons, submit/reset/button/image INPUTs, FIELDSET and OUTPUT stay non-fill
  controls. No action control is clicked. Billing source/identity, retained
  availability and form ownership checks remain unchanged.
- Labels used for inference retain exact node/text authority, with sticky
  label changes/removal/insertion. No broad unknown-input ignore policy exists.

Not universal: multiple forms, unrelated extra data controls, split credentials
across documents, nested payment frames, shadow DOM, canvas widgets, arbitrary
languages/labels, opaque select values and asynchronous billing availability
remain unsupported. Expiry INPUTs expecting YYYY or another combined format
are not newly supported. The plugin never changes merchant autocomplete to
force admission. An input event can trigger merchant behavior even though the
plugin never clicks or submits.

## Reproducible verification

Use a disposable `HERMES_HOME`, disposable Chrome profile and isolated test
interpreter with Playwright/Chrome provisioned. Never run these against the
active home or vault. From the plugin checkout, with the intended Hermes core
and plugin roots on `PYTHONPATH`:

```bash
HERMES_HOME="$SCRATCH/payment-topology-test-home" "$TEST_PYTHON" -m unittest discover -s tests -q
"$TEST_PYTHON" -m ruff check secure_entry/payment.py secure_entry/payment_browser.py tests/test_payment_topology.py
```

`tests/test_payment_topology.py` exercises actual isolated Chrome, native
CapturedCDP, root/iframe documents, labels/structural rows, split/combined expiry,
SELECT aliases/defaults, hidden postback state, billing, no action clicks or
submission, ambiguity, control/form/label mutation and navigation refusals.
The registered Link dispatch uses genuine native gateway consent and a synthetic
private-file producer. `tests/test_cards.py` additionally exercises registered
saved-card root filling using an actual disposable encrypted native vault, then
explicit cleanup/readback. Existing OOPIF, BrowserUse default/named/hybrid and
non-primary selection, owner/lifecycle/takeover and private-file tests remain.
A pre-existing test flake was exposed when a random opaque vault handle happened
to contain the synthetic three-digit CVC. The test now checks short CVC leakage
in content fields rather than random identifier bytes; long PAN/name checks
still inspect the full result.

## Verified results

Final full suite against the **selected installed Hermes workspace**, using the
separate existing isolated test interpreter and explicit disposable home:

```text
Ran 261 tests in 182.158s

OK
```

The imported `tools.browser_supervisor` path was verified to be the selected
immutable PM workspace, not the canonical checkout. Targeted Ruff returned
`All checks passed!`; `git diff --check` was clean. Clean-payload plugin doctor
reported secure-entry 0.5.10, successful import/registration, six tools and three
hooks. Catalog validation returned `ok: true`, including `no core override`;
the existing private-core-import compatibility warning remains. Validation did
not install dependencies or activate anything.

## Activation — deliberately not executed

1. Review/commit verification, then publish the approved immutable commit and
   verify the remote SHA. The local candidate cannot yet be fetched by GitHub
   installation until separately authorized publication.
2. In the intended active profile (not the disposable test home), coordinate
   gateway stop or an explicitly verified native middleware unload. Never
   overwrite an actively loaded middleware plugin. Preserve existing settings.
3. After publication, install that exact SHA disabled:

   ```bash
   hermes plugins install mforzano/hermes-secure-entry --ref FULL_40_CHARACTER_SHA --force --yes-deps --no-enable
   hermes plugins doctor secure-entry --ci
   hermes plugins capabilities secure-entry
   hermes plugins enable secure-entry --no-allow-tool-override
   ```

4. Start the gateway/new process and a fresh conversation. Read back installed
   version `0.5.10` and tool schemas describing explicit top-level root frames.
   Native payment results identify `payment_diagnostic_version: 0.5.10`.
5. Reinspect the actual merchant document/root or iframe, then obtain the existing
   genuine native consent for an authorized fill. No core rebuild/config patch
   is needed for this repair. Treat real-site acceptance and purchase outcome as
   separate verification gates. Do not infer either from synthetic tests.

Existing `in_process`, Link executable and private-entry/Tailscale configuration
remain prerequisites where applicable, not changes performed by this repair.
