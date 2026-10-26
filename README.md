# Hermes Secure Entry

**Private credential entry from a messaging DM, over your own Tailscale network.**
The agent sends a short-lived, one-use link; you enter the password, verification
code, manager-unlock password or card in the private page rather than in chat.
The plugin hands the secret to Hermes's native vault or waiting native callback
without returning its value to the model. It uses the **existing encrypted Hermes
vault**, not a separate credential store. The listener is loopback-only, reached
through an operator-configured, tailnet-only Tailscale Serve route. No Hermes core
changes are bundled.

Photon, Discord and Telegram **DMs** are implemented. Photon login/OTP and patched-core
Discord verification have operator-reported live evidence; Telegram has synthetic
integration evidence only. Real manager unlock and comprehensive physical
Safari/VoiceOver testing remain unverified. See the [platform matrix](docs/platforms.md).

## Additional payment filler: agent selects, native code fills

The plugin also ships a **custom payment filler**, distinct from Hermes's built-in
`browser_vault(action="fill")`. In **0.5.14**, both
`secure_entry_card_fill` and `secure_entry_payment_fill` require an explicit
`field_mapping`: the agent inspects value-free DOM descriptors and backend node
IDs, chooses the intended active controls and assigns their payment semantics.
Native code then retains those actual elements in the exact chosen document,
requests native consent naming the target/frame, origins and mapping, privately
retrieves the card and fills/verifies only those elements. It does not reinterpret
the layout, re-resolve selectors after consent, submit payment or complete checkout.

- **Why another filler?** The native filler in the tested Hermes contract inspects
  its current document; this plugin provides explicit top-level or direct-iframe
  targeting, including same-origin and cross-origin payment frames, and a native
  consumer for Link's protected private-card-file transfer. These are additional
  paths, not a replacement for the native vault or a claim about every Hermes version.
- **Less restrictive about layouts:** selected fields need not have autocomplete
  or belong to a single form/container. Other forms, alternative layouts, unknown
  controls, billing/contact fields, checkboxes and unrelated mutations do not
  block the selected mapping. Selected prefills can be overwritten. Unselected
  controls are neither filled nor required to match the card. The old whole-page
  classification rules were design choices, not inherent requirements for safe
  private entry.
- **Two card sources:** a merchant-bound saved native payment handle (with explicit
  cleanup), or an already user-approved Link spend request transferred privately
  by the local CLI. Native payment records encrypt and persist **CVC too**;
  the entry form discloses this. Link remains a separate supported route and
  does not save its temporary card in the vault.
- **Limits:** the agent must interpret and select the right fields; native code
  enforces the exact selected destination and verifies the private write, not the
  correctness of the agent's interpretation. Node replacement/navigation requires
  reinspection and renewed consent. Unsupported formatting, unavailable selected
  fields or missing source billing data can refuse. `write_unknown` can mean a
  partial fill. A successful native fill is not merchant acceptance or a purchase.

Real isolated Chrome tests cover the mapped writer, genuine native consent with
synthetic approval resolution, synthetic native-vault cards and Link private-file
production. A synthetic **same-origin iframe** reproduces the supplied Gotham
checkout shape; Gotham is not being classified as a cross-origin widget. These
tests do not establish live acceptance. Separately, the operator's completed live
Gotham checkout verified native mapped saved-card fill (five fields), merchant
acceptance and purchase confirmation, followed by verified local temporary-card
deletion. That checkout exercised the mutation fix before this release's version
bump; it does not establish universal merchant compatibility or live Link acceptance.
Version 0.5.14 preserves that working behavior: iframe/ancestor presentation
updates and no-op selected-field attribute assignments do not invalidate mapped
fills; actual selected destination/element changes still require reinspection.
Publishing this release does not itself install or reload the plugin.
See [mapping contract, evidence and activation needs](docs/payment-field-mapping.md).

For supported native current-document forms, the built-in vault filler remains
available. Login/OTP/unlock capabilities and their separate native protections are
unchanged. Atomic update, sign-in-once and save-and-sign-in remain unsupported.

## What works

- `secure_entry_request(operation="add_login", origin="https://example.com")` in an originating Photon, Discord, or Telegram **DM** creates a ten-minute, 256-bit bearer link. Return that link only in that conversation.
- The page explicitly names the exact website origin and says it will save a **new** native vault item, not sign in. The username is visible metadata; the password is not returned to the tool/model.
- On submission, the native `VaultStore.add_item` encrypts the login. The plugin reads back metadata only before reporting `saved`. If the native write outcome cannot be verified, `commit_unknown` preserves returned handle metadata when available: inspect the vault before retrying to avoid duplicates.
- `secure_entry_status(request_id)` and `secure_entry_cancel(request_id)` require the same home, platform, sender, chat, session key, and session ID. Delivered lifecycle stop/reset/abnormal-end hooks and plugin unload cancel pending entries; normal turn completion preserves the delivered link. **Idle `/stop` does not reliably revoke a delivered link**: the host emits no stop lifecycle hook when no agent is running. Use the form's **Cancel** button or `secure_entry_cancel(request_id)` in the originating session. Do not rely on idle `/stop`.
- The listener starts lazily for a valid add-login request or an actual native code/unlock callback, never during import/registration/doctor. It binds **127.0.0.1 only**. No network endpoint creates requests.
- Linear HTML with heading, labels, username/password autocomplete, natural keyboard order, no modal, no JavaScript, and explicit status/cancel/expired states. GET previews do not consume the link; valid POST consumes it once. Safari/VoiceOver device testing is still required.

## Scope and priorities

1. Ship the achievable **add-vault-login** path as a preview/testing-only partial implementation.
2. For replacement, add the new login and verify its metadata first. Inspect the new and old handles using the existing native vault tools. Remove the old item only through those existing tools **after explicit user approval**. The plugin never deletes automatically, never implements delete-then-add, and does not call this an atomic same-record update. If a save is `commit_unknown`, inspect the vault before retrying or considering any removal.
3. Exercise the implemented native **OTP callback preview** with synthetic data before real use. No OTP form exists until the native tool inspects an actual code field and supplies its site.

**Sign-in-once work is dropped for now**; it is not a delivery priority. Its unsupported-operation response remains only to refuse collection safely. Browser save-and-sign-in and atomic same-record update are also not delivered here.

## Native OTP and unlock preview

Requires `plugins.isolation: in_process`. The bridge refuses host isolation, cron, headless/API, delegated children, group chats, missing task-local identity, mismatched profile, and mismatched middleware/session correlation. It never changes `can_prompt_here` or installs a dummy unlock approval.

1. On a real inspected login page, use native `browser_vault(action="list")`. A locked manager can then be unlocked with native `browser_vault(action="unlock", backend="bitwarden")` (or `onepassword`); its genuine masked form asks for that manager's master password, never a website password.
2. When a page asks for a verification code, call native `browser_vault(action="enter_code")` **without a handle**. `secure_entry_request(operation="verification_code", ...)` only returns this instruction; it does not create a code collector for a model-supplied site. This preview continues to reject nonempty OTP handles before native execution; saved-seed automatic TOTP through a handle is not enabled or newly claimed by this compatibility repair.
3. Native inspection supplies the site and arms a one-use code form. The bridge calls native `send_message` with a destination constructed only from this authenticated DM context, then waits on the tool worker for up to 180 seconds across the execution. The gateway must remain able to send while the worker waits. Delivery failure revokes the request. No secret enters dispatch arguments or results.
4. Open the link and enter the code in its masked field. HTTP POST hands the value through memory to the waiting native callback; native redaction, origin/inspection-nonce checks, supervisor-only secret write and takeover fences remain in force. The plugin never types via browser JavaScript or clicks Submit. Some websites auto-submit after a code is filled.
5. `filled` means the native handler reported a fill, **not authenticated**. `unlocked` means the manager reported unlock. Cancel/expiry/unload before handoff accepts no later input. Once handed off, status is `commit_unknown` until a verified native result; cancellation cannot promise to undo a native action. Inspect the browser/manager before retrying an unknown outcome. No-code-field/passkey/app approval remains a typed native refusal: complete that approval on the actual device.

**The private capability URL may be visible to the model/session history**, because native `send_message` mirrors sent text. Codes and passwords are not included. This is not transcript-free link delivery. Anyone with a link and tailnet access can submit it. Native tab-selection ambiguity and same-origin DOM limitations are unresolved; inspect the intended page first and do not claim exact immutable target/frame/generation binding.

## Install and activation

Use **Hermes 0.22.1**; the manifest is bounded to `>=0.22.1,<0.22.2`. Python requirements are supplied by Hermes. The plugin declares no additional Python dependencies. Use the PM-prepared Hermes interpreter, not an unrelated system Python and not raw pip against the live runtime.

### Direct GitHub install (supported Hermes CLI)

For a fresh install in the intended active profile, coordinate a gateway stop before installing/enabling middleware, then run:

```bash
hermes plugins install mforzano/hermes-secure-entry --yes-deps --enable
hermes config set plugins.isolation in_process
hermes config set plugins.entries.secure-entry.settings.public_base_url https://your-machine.example-tailnet.ts.net:9443
hermes config set plugins.entries.secure-entry.settings.port 8769
hermes plugins doctor secure-entry --ci
hermes plugins capabilities secure-entry
```

The supported CLI accepts `owner/repo` directly; `--yes-deps` supplies dependency-preparation consent and `--enable` requests enablement. This is a direct GitHub install, not a claim of reviewed catalog admission. For a reproducible install, add `--ref` with a full immutable 40-character commit SHA.

**GitHub installation alone does not configure Tailscale Serve, select `in_process` isolation, or guarantee that every website's OTP form will work.** Configure the [dedicated tailnet-only HTTPS route](#tailscale-deployment-operator-owned) separately, preserve unrelated routes, and ensure the client device has authorized tailnet access. The settings above do not create that route. Then start a new gateway process and a new conversation; enablement alone is not verified activation. For an existing installation, coordinate unloading/stopping the running middleware before a supported update/reinstall; never overwrite its active copy. See [core-fix scope](#related-hermes-core-fixes) for affected native OTP detection/selection failures.

### Alternative: stage from source

From the source repository, in an environment where `import hermes_constants` resolves to your Hermes checkout:

```bash
python -m secure_entry.install --public-base-url https://your-machine.example-tailnet.ts.net:9443
```

This stages the plugin under the **active** `HERMES_HOME/plugins/secure-entry`, configures only this plugin using `hermes config set`, and leaves it disabled. It refuses to overwrite an existing installation. No other profile is selected or changed. To explicitly enable:

```bash
hermes plugins doctor secure-entry --ci
hermes plugins enable secure-entry --no-allow-tool-override
hermes plugins capabilities secure-entry
```

Or add `--enable` to the source staging command. Set `plugins.isolation` to `in_process` and configure the separate Tailscale Serve route as above. There is no tool-override grant. Plugin capability declarations are empty because it requests none of Hermes's capability-gated host facades; enabling it still trusts in-process native vault writes, native direct-message dispatch and the local listener. **A separately coordinated gateway restart/new process and new conversation are required. The installer does not restart anything.** Do not overwrite an active installed copy: middleware/hooks can hotload into existing sessions even when tool schemas are deferred. This release does not claim a safe live new-session-only activation gate.

`HERMES_HOME/plugins` survives normal Hermes updates; never put this plugin in the core checkout. This release is constrained to `>=0.22.1,<0.22.2`: the tested Hermes 0.22.1 consolidated vault-action contract, not a blanket promise about future releases. Rerun doctor and tests after host updates. It has no self-updater or dependency mutation path. See [the compatibility evidence and coordinated activation procedure](docs/hermes-0.22.1.md). Do not copy this upgrade over a running gateway's installed middleware.

## Related Hermes core fixes

**Stock Hermes 0.22.1 can use this bridge for OTP forms that its native detector selects and recognizes. Neither pending PR is a universal prerequisite, and add-login is independent of these OTP fixes.** The plugin transports native prompts; it does not patch browser selection or field recognition. Affected sites/widgets can need the corresponding core fix:

- [NousResearch/hermes-agent #136831](https://github.com/NousResearch/hermes-agent/pull/136831) — **open/pending**: selects visible OTP fields and, when a saved login handle is supplied to core, binds selection to that handle's allowed origins. It addresses false `no_code_field` failures caused by unrelated tabs with hidden postal/country-code controls. This plugin's preview still refuses nonempty OTP handles; the PR does not enable them here or establish immutable target binding.
- [NousResearch/hermes-agent #139405](https://github.com/NousResearch/hermes-agent/pull/139405) — **open/pending**: recognizes explicit “enter [the/a] [4–8] digit code” labels and complete, ordered, adjacent 1..N numbered OTP widgets (4–8 digits), with shared actual form/container identity. Invalid/incomplete/mixed groups and unrelated code-like fields are rejected. The updated PR reports 127 focused tests passing on Windows and a real United six-box challenge filled through native private entry; Continue reached the authenticated account menu. That is patched-core evidence, not stock 0.22.1 coverage or proof of all sites.

The operator's successful live Discord verification used patched core, including the additional numbered-widget fix in #139405. Do not infer that both PRs must be applied for every use, that they are merged into stock Hermes, or that Telegram is live verified. See the [platform evidence and stock-versus-patched limits](docs/platforms.md).

## Tailscale deployment (operator-owned)

Use a dedicated Tailscale Serve HTTPS port, e.g. 9443, forwarding the **root path unchanged** to `http://127.0.0.1:8769`. Set:

```bash
hermes config set plugins.entries.secure-entry.settings.public_base_url https://your-machine.example-tailnet.ts.net:9443
hermes config set plugins.entries.secure-entry.settings.port 8769
```

No hostnames, addresses, accounts, or personal paths ship in this repository. Bind host is not configurable. The operator must inspect current Serve configuration, preserve unrelated ports/routes, and explicitly authorize the dedicated route. **Never use Tailscale Funnel** or another public proxy. All tailnet devices permitted to reach this service are inside the trust boundary; use Tailscale ACLs. Anyone possessing the link on an allowed device can submit it. The plugin does not claim separate sender authentication in Safari.

`GET /health` returns only `{"status":"ok","version":"0.3.0"}`. The listener is lazy: before a request or explicit demo starts it, a refused health connection is expected.

Root `/r/<token>` paths avoid Serve-prefix ambiguity. Prefix-mounted URLs are rejected; do not deploy with prefix stripping or rewriting. No unrelated route needs modification.

## Diagnose and safe link test

Request/bridge failures expose only fixed `error_type` categories, never exception text,
identity values, request fields, tokens, or ports:

- `missing_session_id`: native session binding lacks `HERMES_SESSION_ID`. The plugin
  still refuses admission; it does not derive an ID from a session key or tool arguments.
- `missing_session_binding`: another required identity binding is absent, or bridge
  task-local identity does not match native ownership (process environment is insufficient).
- `listener_binding_failed`: the authorized lazy loopback listener could not start
  (`OSError` at listener startup); no form was issued by that attempt.
- `service_unloaded`: admission reached a closed service.
- `bridge_unavailable`: bridge not configured or its outer compatibility boundary failed.
- `admission_unavailable`: other bridge admission refusal, including session correlation,
  profile/isolation mismatch, interruption, or lifecycle invalidation.
- `service_unavailable`: other request failure; this is deliberately not attributed to
  identity or the listener without evidence (for example invalid origin or native store failure).

These are diagnostic refusals, not evidence of authentication or permission to bypass
the native checks. Status/cancel ownership misses remain opaque. Native terminal
outcomes, including `commit_unknown`, retain their existing meaning.

```bash
python -m secure_entry.cli diagnose
python -m secure_entry.cli demo --public-base-url https://your-machine.example-tailnet.ts.net:9443 --seconds 600
python -m secure_entry.cli health
```

Demo uses an actual native encrypted vault in a disposable scratch directory, **not the live vault**. It accepts only the printed synthetic username `synthetic@example.invalid` and password `SYNTHETIC-DEMO-ONLY`. Other values fail without saving. The dummy link is printed intentionally for operator testing and expires with the process. No real browser fill is attempted or claimed. After the operator enables the dedicated Serve route, open this link on the phone to test Safari/VoiceOver and Tailscale. `Ctrl+C`/automatic expiry stops the listener and deletes the dummy vault. Never enter real credentials in demo mode.

## Tests

Build an isolated test environment using Hermes's documented PM workflow, outside the live runtime:

```bash
# Run from the Hermes source checkout, using its prepared Python 3.14:
python -m pm.build_env --source . --out /absolute/scratch/secure-entry-env --group dev --group test
# Optional native bot SDKs for synthetic transport tests, in this test environment only:
uv pip install --python /absolute/scratch/secure-entry-env/Scripts/python.exe aiohttp python-telegram-bot discord.py
# From this plugin repository, with both repositories on PYTHONPATH:
# Windows uses ; between native forward-slash paths; POSIX uses :.
PYTHONPATH='/absolute/hermes-source;/absolute/hermes-secure-entry' /absolute/scratch/secure-entry-env/Scripts/python.exe -m unittest discover -s tests -v
hermes plugins doctor /absolute/hermes-secure-entry --ci
hermes plugins validate /absolute/hermes-secure-entry
```

The tests use synthetic inputs only and temporary native vaults. Coverage includes actual encryption/readback, HTTP guards, CSRF, one-use concurrency, expiry, cancellation-versus-commit, profile/session scope, source staging, socket-free registration, real registered native OTP execution against a synthetic supervisor, redaction before native writes, HTTP-to-callback transport, genuine unlock entry, callback restoration/thread propagation, captured-callback invalidation, and delivery/expiry/lifecycle races. Synthetic supervisor success is not real browser integration. See [recovery](docs/recovery.md) and [security](SECURITY.md).

## Disclosure

The plugin opens a local HTTP server, uses the native encrypted vault, and returns/sends opaque links and request metadata to the originating conversation. Password/code values travel only from the private page through memory to the native store or waiting native callback. No telemetry, external assets, third-party collection service, login auto-click, passkey emulation, saved-password reads, or generic credential-injection API. The unreleased payment candidate is a separate narrowly registered native facility, disabled by default; it does not reuse the OTP form as payment approval. OTP and unlock remain preview features, not production authentication claims.

Architecture/reference research included the Linux/Telegram `hermes-secure-env-plugin` project; no source was copied. This is an independent Windows/Photon/native-vault implementation, not an environment-variable ingress port.
