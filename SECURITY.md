# Security model

## Conversation scope and Telegram-topic exception

Standalone login/card entry, payment, card removal and plugin status/cancel remain
DM-only. Only the native OTP (without a handle)/list/unlock bridge admits authorized
Telegram group topics; see [the exact contract](docs/telegram-topics.md). Topic capabilities
use a separate non-mirroring, single-attempt native Telegram delivery path, never
`send_message` tool dispatch. Existing DM delivery behavior is unchanged. The
private page still trusts **Tailscale access plus possession of the bearer link**,
not the phone's identity, Telegram login, or identity of the submitting person.
Do not forward the link. The plugin does not patch Hermes core.

Native group-chat grants can authorize identified human members, not just a
separately allowlisted individual. The plugin adds no per-user allowlist or
independent DM authorization check for a topic sender. Review group membership
and native grants before enabling this workflow. Native `list` metadata and tool
results remain in the originating conversation and may be visible to topic
participants. This exception does not alter the native policy of other browser
actions or admit standalone credential/card/payment tools from a group.

## Payment routes added after the original preview

0.5.0 adds native `payment`-kind private card entry and explicit verified cleanup alongside the existing Link route. The real-card route resolves only a metadata-selected payment bound to the exact merchant, after genuine native consent for the retained merchant/payment-iframe pair; both sources use the existing captured native writer. Never pass secrets in tool arguments or use per-site browser scripts. The supported native schema **requires and encrypts CVC persistently**; the form discloses this. Nonpersistent one-use CVC is not implemented: no private crypto/storage surgery or login workaround is used. Do not use this route where CVC retention is prohibited; encryption is not a PCI compliance claim. Delete by the returned handle after verifying the intended checkout outcome or explicit cancellation. Unknown save/fill/delete outcomes require inspection. Cleanup verifies native metadata absence, not media erasure, browser copies, backups or merchant revocation; it cannot retract a started fill. See [complete payment contract and limitations](docs/real-card-payment.md). Original preview-only exclusions below do not exclude these narrowly implemented payment routes.

Enabling an in-process Hermes plugin trusts its Python code. Capability declarations are an audit/consent surface, not a sandbox.

## Boundaries

- Standalone requests originate only from an authorized native Photon, Discord or Telegram DM tool context. Native OTP/list/unlock additionally admit the narrowly bound Telegram topic above. Model parameters never confer sender identity, delivery destination or authorization; never pass credentials or browser injection code to entry tools. The native inspection supplies the OTP site.
- The broker has no HTTP creation API. It stores at most 64 active/tombstone requests; random URL tokens and independent CSRF nonces each have 256 bits of entropy.
- Links are bearer capabilities. Anyone who obtains one and can reach the allowed tailnet endpoint can submit. Tailscale ACLs, trusted HTTPS config, and not forwarding links are operational requirements. Standalone DM tool results and native DM mirroring can expose the opaque URL to the model; topic delivery avoids tool dispatch and native mirroring. Neither path returns the entered secret to the model. Do not publish real links or put them in shared logs; web possession is not proof of phone or Telegram identity.
- Browser Origin checks are not the only CSRF protection. Independent per-request nonce validation works with Safari/mobile/`Origin: null`; there is no CORS grant. Host validation rejects unrecognized names, but the loopback address is intentionally reachable by local programs.
- Native vault instance selection occurs in the originating tool context and captures its profile directory before serving the form. Existing saved passwords are never resolved by production plugin code. Redaction is registered before native storage.
- Request identity includes home/profile, platform, chat type, chat, user, thread and session key/ID; topics additionally bind the initiating message and middleware task. Tool status/cancel remain DM-only and refuse another owner, including a topic-owned request queried from a separate DM. Delivered core stop/reset/abnormal-end hooks cancel pending requests; normal completed-turn end does not. **Idle `/stop` does not reliably revoke a delivered link** because the host's no-active-agent path emits no stop hook. Use form **Cancel**, or `secure_entry_cancel(request_id)` for a standalone request in its originating DM. Initial admission is generation-fenced; indexed requests and active topic callbacks are cancelled by matching session key/ID. Unrelated admitted topic callbacks are not intentionally cancelled by another session's reset. Issuance/handoff recheck scope; a changed/evicted topic source or revoked authorization can cancel even after web input arrives. Unload permanently closes admission. Once a native action starts, cancellation cannot falsely promise it was prevented.
- Only native encrypted vault files persist passwords. The plugin does not copy vault keys, read `.env`/auth files, or maintain a secondary credential store. Native vault encryption is not protection against malware running as the same Windows user or theft of both encrypted file and its native key.
- Python strings cannot be reliably zeroized. Submitted data lives briefly in HTTP/native-call memory; the native redaction registry can retain matching values in process memory. Do not claim memory erasure guarantees.

## HTTP controls

Fixed IPv4 loopback bind; 16 KiB body cap; bounded fields; ten-second socket timeout; no transfer encoding; duplicate field rejection; no body/URL/access/error logging; `no-store`, no-referrer, nosniff, frame denial, restrictive CSP, no external assets or scripts, no telemetry. POST/redirect/GET avoids mobile resubmit. GET/link previews are non-consuming. Expiry is enforced on every lookup and submission, even for a form left open past its deadline. Request tables are process-memory only; restart invalidates every link.

The stdlib HTTP server is intentionally small, not an internet-facing hardened application stack. It has bounded request storage but no distributed rate limiting or per-tailnet-user identity verification. Never expose it to the public internet, Tailscale Funnel, or an untrusted LAN. Tailscale Serve must forward the dedicated HTTPS root unchanged and must not log full credential URLs/bodies.

## Current scope

The credential preview implements standalone **add new login**, native OTP callback entry without a handle, native list metadata and genuine password-manager unlock entry; the separate DM-only payment routes are described above. Atomic login update, transient sign-in and browser save-and-sign-in remain unsupported before collection. A native save with failed metadata verification is `commit_unknown`, not proof of no write; inspect the vault before retrying. Callback input handed to a native tool also becomes `commit_unknown` until a verified result, and cancellation cannot promise to prevent a native action already begun. `filled` and `unlocked` do not mean website authentication. The bridge adds no passkey emulation, auto-submit, arbitrary selector, generic secret resolution or generic injection endpoint. Native approval/origin/inspection-nonce/supervisor/takeover fences remain untouched. Native tab-selection ambiguity and same-origin DOM limitations remain; no immutable target/frame/generation binding is claimed. Nonempty OTP handles remain refused under the preview policy.

Native prompt middleware is in-process only. It requires genuine task-local
post-auth Photon, Discord or Telegram DM identity, or the narrowly admitted Telegram
topic, plus matching middleware/session correlation and profile. Topic admission
also correlates the current cached gateway source and rechecks native authorization
before issuance/delivery and before submitted input reaches the callback. Bots,
anonymous-admin/channel actors and rejected routes cannot use the topic exception.
Host isolation, stale captured callbacks, delegated, cron/headless, other group and
mismatched contexts cannot create collectors. Native code inspection supplies the
actual OTP site before a form exists. Native unlock uses a separately labeled
master-password form, not a dummy approval callback. HTTP input is redacted before
handoff, and callback slots/temporary buffers are cleared in finally. The native
redaction registry retains values in memory; zeroization is not promised.

Existing DM delivery uses context-derived DM targets only: the registered native
send handler via `ctx.dispatch_tool`, or the native CLI send function on snapshots
without that entry, selected before sending. Delivery errors never retry through
another path. Native DM mirroring can put capability URLs in model-visible session
history; this behavior is unchanged. Topic delivery instead targets the bound human
sender's numeric DM using native profile config/egress checks and a single credential
snapshot, then `_telegram_bot` / `_send_telegram_message_with_retry(attempts=1)`.
No send-tool dispatch, native mirror, group fallback or retry occurs on that path.
Delivery failure revokes the request. No general transcript-free URL claim is made.
Callback waits share a 180-second deadline; received-but-not-consumed input expires too.

These are private-API dependencies, including gateway cache/key/authorization and
native callback/middleware contracts. Missing APIs and detected mismatches are
refused, but future semantic changes still require review and tests. The manifest
range is not proof of topic compatibility across it. The [pinned comparison](docs/telegram-topics.md#compatibility-and-evidence)
records passing focused tests, not a green full suite or exact-candidate Windows
validation. Captured-log assertions cover WARNING and higher, not DEBUG/INFO.
Concurrent reset tests establish unrelated-callback survival, not targeted
pre-issuance cancellation. This is not a general security audit.

Synthetic supervisor/manager/transport tests do not prove real integration.
Historical Photon and patched-core Discord results are separate evidence. An
operator also reported Telegram topic → private web link → native fill → confirmed
login; no exact candidate/core revision or exhaustive scenario coverage is inferred.
Real manager unlock remains unverified. Intermittent `admission_unavailable` and
observed browser resets have not been root-caused or fixed by this contribution.
See [platform evidence](docs/platforms.md) and [native core-fix scope](README.md#related-hermes-core-fixes).
Each deployment requires coordinated activation: middleware can hotload into
current sessions, so never overwrite an active copy; coordinate stop/unload and a
new process/conversation separately.

Report a vulnerability privately to the repository maintainer rather than posting live credentials, bearer links, vault files, or complete gateway logs. Revoke/cancel a suspect request immediately and coordinate service shutdown if necessary.
