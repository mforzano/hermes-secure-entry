# Hermes Secure Entry

**0.5.10 generic payment topology and semantics:** the plugin now binds either an explicitly inspected top-level root frame or the existing direct payment iframe. Missing expiry/CVC autocomplete can be resolved from conservative labels/structural rows; numeric expiry SELECTs, opaque hidden postback state and ordinary action controls are supported without changing merchant attributes. Native task/document authority, consent, private-file handling and no-submit behavior remain intact. No core changes, live spends, installation or gateway activation were performed for this repair. [Contract, real-Chrome regressions, limits and activation instructions](docs/payment-topology-0510.md).

**0.5.7 plugin-owned payment redaction:** PAN, CVC and complete expiry registration lives in `secure_entry.redaction` and uses only the existing native exact-value registration API. No new Hermes core helper, rebuild or dependency is required. Standalone expiry components and billing metadata do not become global substring rules. Generic password/OTP rules remain unchanged. Tests run against a pristine core snapshot without the new helper. Existing polluted process state is a separate recovery issue: reload prevents new pollution but cannot safely remove unattributed old entries. See [evidence and activation/recovery gates](docs/payment-redaction-repair.md).

**0.5.5 standard postal-code support:** the native Link/card writer maps only unsectioned `postal-code` to billing postal code internally, retaining original page attributes and document/control/origin authority. Real isolated Chrome regressions cover masked combined expiry, CVC and ZIP, duplicate aliases and invalid controls, sticky attribute changes, and canonical conflict diagnostics. No live payment was used for this validation.

**0.5.4 framework value-reflection fix:** permit only the current retained INPUT's exact-semantic self-write reflection, including normal PAN/expiry formatting; prewrite, foreign-field and mismatched/restored mutations still refuse. [Tests and limits](docs/payment-widget-054.md).

**0.5.3 widget-mutation fix:** tolerate card-brand/validation presentation updates after PAN input while retaining sticky control/ancestry/security-semantic mutation refusal. Supplied name/postal mismatch policy remains unchanged. [Tests and limits](docs/payment-widget-053.md). [Value-free diagnostics](docs/payment-writer-052.md).

**0.5.1 candidate — two payment routes:** approved temporary Link cards remain available unchanged. A new **real-card** route privately saves a native site-bound payment item, fills the explicitly consented merchant/payment-iframe pair through the same retained native browser writer, and offers explicit handle-based cleanup with verified absence. Choose it for user-selected real cards, hotel guarantees or deferred charges where temporary cards are unsuitable. Native payment storage encrypts **CVC too**; the entry page discloses persistence. No automatic deletion, purchase, reservation, live activation or live hotel verification is claimed. See [workflow, native APIs, CVC limitation, tests and installation](docs/real-card-payment.md).

Prefer core `browser_vault(action=fill, handle=...)` for supported current-document native card forms. The retained plugin writer is needed for the explicit cross-origin iframe case that core's document-only inspection cannot reach. [0.5.1 reproduction, native-handler comparison and validation](docs/payment-widget-051.md).

**Link route:** this branch includes the disabled-by-default native local Link CLI private-card handoff into an existing task-captured browser. It needs no new core patch and no per-site configuration. Default, named and hybrid BrowserUse routes are synthetic-integration-tested. It retains strict form/document binding and genuine native explicit payment consent; this route does not save a card or submit a purchase. “Local” describes the Link CLI source, not browser geography. See [research, security contract, tests and activation gates](docs/local-link-payment.md). Historical 0.3.0 behavior below describes the OTP/login/unlock preview.

A separate Windows-native Hermes plugin for private, one-use credential-entry pages reached through Tailscale Serve. It registers tools and lifecycle hooks through `PluginContext`; it does not modify Hermes core.

**Version 0.3.0 is a preview implementation for authorized Photon, Discord, and Telegram DMs.** It adds native encrypted vault logins and bridges native OTP and password-manager unlock callbacks to private forms. Photon add-login, OTP delivery and an authenticated browser page were operator-verified on installed 0.2.1; **the operator now reports successful live Discord verification with the patched Hermes core described below**. Telegram has synthetic integration tests only, not live verification. Real manager unlock and comprehensive physical Safari/VoiceOver testing remain unverified. OTP keeps the native browser protections; no new injector or core detector/tab-selection fix is bundled. Atomic update, sign-in-once, and save-and-sign-in remain unsupported. See the [tested versus live-verified platform matrix](docs/platforms.md), [core-fix scope](#related-hermes-core-fixes), and [native limits](docs/native-contract.md).

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
