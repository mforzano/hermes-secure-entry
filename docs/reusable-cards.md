# Explicitly reusable native cards — 0.5.16

## Contract

- Request `add_reusable_card` without `origin` in the originating authenticated
  human DM. Origin-bearing reusable requests refuse rather than rebind a card.
- The private one-use form names cross-website storage, requires explicit checkbox
  opt-in, and discloses that CVC is encrypted and saved. GET does not consume it.
  CSRF, expiry, cancellation, reset, native commit serialization, unknown outcome
  reporting, tailnet routing and session/profile ownership use the existing path.
- One `VaultStore.add_item('payment', ...)` stores all supported card fields with
  `origin=None` and reserved metadata label `Hermes reusable payment v1`. There is
  no second vault, per-merchant copy, core patch or migration of existing entries.
- Only that exact label/origin/kind combination means reusable. Ordinary legacy
  originless payments are excluded from plugin discovery and filling. The label
  is an explicit metadata convention, not protection from trusted vault editors.
- `secure_entry_card_list()` returns only handle, scope and origin. It never
  resolves payloads. It is subject to the same authenticated DM/profile binding.
- `secure_entry_card_fill` still requires current captured browser admission,
  exact HTTPS merchant and payment document, explicit backend-node field mapping,
  retained document/element checks and fresh native consent before retrieval.
  Reusable metadata is checked again immediately before native secret resolution.
  It is permission to request filling at other approved merchants, **not** blanket
  destination consent. Wrong mapping remains the agent's interpretation risk.
- No fill auto-deletes, submits, purchases or rebinds the entry. Reusable records
  remain until explicitly requested deletion, not until checkout completion or
  pending-link expiry. Bound temporary cards retain their existing exact-origin
  checks and explicit post-outcome cleanup workflow. Link is unchanged.
- `secure_entry_card_remove(handle=...)` deletes a reusable record and reads back
  absence. Bound cards still require their exact `merchant_origin`. Cancellation
  of a pending entry prevents storage; cancellation after a save does not delete
  it. Use explicit removal. `deletion_unknown` is not successful deletion.
  Local deletion does not revoke merchant/browser copies or an in-flight fill.

## Synthetic acceptance

Tests use a disposable HERMES_HOME, actual native encrypted VaultStore and an
isolated real Chrome browser. A single saved handle fills five mapped fields in
an actual cross-origin `merchant.test` / `provider.test` iframe, then five fields
in a different `second.test` top-level HTTPS document. Genuine native approval
is enqueued/resolved at each attempt; denied consent leaves the selected prefill
untouched and never resolves the secret. The same record stays originless across
fills, and explicit deletion prevents further retrieval or consent prompts.

Additional tests cover real HTTP private submission, required opt-in, one-use
POST, ciphertext at rest, metadata-only discovery/deletion, pending cancellation
and session reset, group/unloaded service refusal, legacy originless exclusion,
metadata recheck before retrieval and unchanged merchant-bound restrictions.
The existing suite covers Link, mapped targets, replacement/navigation, native
browser capture and private-file ownership. These are synthetic integration
results, not a real merchant charge, physical accessibility test or live reusable
card acceptance.

## Runtime and activation

Implementation inspected the PM-selected Hermes 0.22.5 workspace and native
VaultItemMeta / VaultStore API. Validation uses a separate disposable interpreter;
no live vault, real card, core source or gateway activation is involved.

The parent/operator must install the published immutable Git revision using the
supported plugin manager, verify version **0.5.16**, enabled state and doctor,
then refresh registration/session schemas. Existing loaded handlers do not become
new handlers merely because a Git push succeeds. New registration includes
`secure_entry_card_list`, `add_reusable_card`, optional request `origin` (still
required by server validation for bound operations), and reusable handle-only
removal. No core rebuild is required. Do not collect a real card before that
installation and activation have been independently verified.
