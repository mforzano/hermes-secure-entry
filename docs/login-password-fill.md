# Explicit saved sign-in password fill

`secure_entry_login_fill` is a fill-only fallback when an official **sign-in**
page's actual password input is unsuitable for ordinary `browser_vault` login
recognition, for example because its markup says `autocomplete="new-password"`.
It does not modify that markup or change stock classification. Do not use this
operation for registration, reset, password changes or confirmation fields.

## Calling it

Use the originating authenticated human DM (Photon, Discord or Telegram) and an
in-process plugin. Select/capture the official sign-in tab with the ordinary
browser tool in the current task. Confirm the page is a sign-in flow, inspect
only value-free control descriptors, and use native vault login **metadata** for
the exact account. Use `Target.getTargetInfo` for the selected page target,
`Page.getFrameTree` for the selected page's root frame `id` and `loaderId`, and
a value-free AX/DOM inspection for the password input's `backendDOMNodeId` /
`backendNodeId`. Take all IDs from the same captured document. This operation
supports only a top-level HTTPS document at the exact saved login origin: no
iframe, offsite destination, wildcard or subdomain matching.

All arguments are required; additional properties are rejected:

```json
{
  "handle": "vault_0123456789ab",
  "identifier": "synthetic@example.test",
  "origin": "https://login.example.test",
  "parent": "<inspected targetId>",
  "frame": "<inspected root frame id>",
  "loader_id": "<inspected root loaderId>",
  "password_node": 101
}
```

`password_node` is one positive integer backend node ID, not the frontend
`nodeId`, a selector, or the input's HTML `id`. Do not supply a password, CSS
selector, script or URL query. This tool does not type the identifier. Prepare
and verify the public account field separately, if present.

The tool retains the selected document and actual writable password element
before requesting fresh, one-time native approval. The approval identifies
sign-in intent, the saved handle and account, exact HTTPS origin, page, root
frame, loader and node; it explicitly says there is no submission. Neither
session/always approval nor YOLO substitutes for it. Only after acceptance and
revalidation is the password resolved from the native encrypted vault. The
native writer may replace the selected prefill and sends `input` and `change`
events. It checks equality and validity privately and never returns the value.
The agent's selection still matters: the approval and retained node do not prove
that the selected control belongs to a genuine sign-in flow. Like manually
entered passwords, a populated field is readable by the site's scripts; do not
read field values or capture secret-bearing artifacts with other browser tools.

- `filled` (`success: true`, `filled_fields: 1`, `submitted: false`) confirms
  fill only, not account access. Submit separately only when authorized and
  verify the actual authentication outcome.
- `consent_declined` means approval was not obtained, not a website rejection.
- `refused` means no password write was dispatched. A stale target requires new
  inspection, not a rerun with guessed IDs.
- `write_unknown` means a write may have occurred. Inspect only value-free state;
  do not retry blindly. No write is automatically retried.

`login_diagnostic_version` identifies the executing implementation. Wire debug
logging for `websockets.client` must be off. No new vault item, core change,
merchant-specific selector, or change to `secure_entry_signup_fill`'s contract
is required.

## Activation (only when separately authorized)

Use the exact tested plugin commit with Hermes 0.23.2 (manifest pin). Use the
supported Secure Entry [activation and rollback sequence](signup-password-fill.md#test-evidence-and-activation)
for the active profile, replacing the tool name in its verification step with
`secure_entry_login_fill`. For an unpublished Windows commit, the manager also
accepts `hermes plugins install file://C:/absolute/repository --ref <TESTED_SHA> --force --yes-deps --no-enable`.
Preflight the local source in a scratch profile; record the previous installed
source/pin for rollback and preserve any local plugin state before switching
sources. Confirm the old plugin is unloaded before replacement and avoid
interrupting pending private entry requests. Check that the new schema is visible in the originating chat;
use a fresh authenticated DM session if it still has a cached tool list. The
synthetic browser tests do not establish successful authentication on a live site.
