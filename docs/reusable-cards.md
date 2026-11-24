# Explicitly reusable native cards

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
- `secure_entry_card_list()` returns handle, scope, origin and (for reusable
  cards) a nickname or `null`. It never
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

## Nicknames (0.5.20)

Use short, nonsecret names such as **Travel Card**. The private form accepts up
to 32 ASCII letters and single inter-word spaces. It rejects digits, punctuation,
control characters and formatting rather than echoing them. Do not put personal
information or secrets in a nickname: valid names are shown in the read-only
card list and in the native fill approval text. No last four or other payment
values are displayed. Card handles are for tool calls only, not chat or approval
prose.

- New reusable card: `add_reusable_card` has a **Card nickname (optional)** field.
  Leaving it empty preserves the existing unnamed save flow. A duplicate name
  (case-insensitive) is refused before saving a native card. If the status is
  `saved` with `nickname_status: unverified`, do not save again; inspect the list
  and label that same card via the rename form if necessary.
- Existing reusable card: use `secure_entry_request(operation="rename_reusable_card", handle=…)`
  without an origin, passing the exact user-selected handle internally. Use a
  unique existing nickname, a handle retained from an identified save, or the
  only unnamed reusable entry if the user confirms that is their target. Never
  pick by list position, recency or guesswork among indistinguishable cards.
  Send the one-use link only to the originating DM. The form identifies the
  current nickname (or that the card is unnamed), and takes only the new name.
  `secure_entry_status` reports `renamed`; read back via the card list. Changed
  or deleted entries reject stale forms; cancellation does not save a nickname.
- Fill by the selected internal handle as before. Verify the quoted nickname,
  HTTPS merchant and payment frame in the native approval. If the name changed
  while approval was pending, no card is retrieved; inspect again. An unnamed
  card is shown as such, not as a guessed identity.

Stock Hermes 0.23.2 has no public atomic metadata setter. The plugin stores only
handle-to-nickname mappings in `secure-entry-card-nicknames.sqlite3` in the active
profile. SQLite transactions serialize concurrent writes and enforce name
uniqueness. Rename does not resolve card payloads, alter the reserved native
marker, or rewrite the vault. Missing or ineligible native records cannot expose
stale names or receive a rename. Verified plugin deletion attempts sidecar cleanup
without changing the native deletion result; stale entries are never shown and
do not reserve a name against an eligible replacement. Older plugin versions
ignore the sidecar without changing the encrypted cards. If the sidecar is
unreadable, do not guess that a card is unnamed; restore access or resolve the
profile state before selecting a reusable card.

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
