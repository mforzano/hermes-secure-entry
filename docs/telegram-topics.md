# Telegram topic → requester DM native bridge

The bridge admits a narrow set of native vault actions from an authorized Telegram
forum topic and sends any private-entry capability only to the requesting human's
DM. The original topic's native browser task continues; it is not moved to the DM.
No Hermes core patch is bundled. Standalone entry and payment tools remain DM-only.

## Scope and authorization

- Only native `browser_vault(action="enter_code")` **without a handle**, `list`,
  and `unlock` gain topic admission through this bridge. `list` returns native
  metadata; it is not a secret collector. Treat metadata returned to the topic as
  visible to that conversation. Standalone add-login/add-card, card fill/removal,
  Link payment fill, and plugin status/cancel tools remain DM-only. Other native
  browser actions keep their own native policy; this is not a general group grant.
- Admission requires `plugins.isolation: in_process` and native task-local identity
  matching the gateway's current cached authenticated source: home/profile,
  platform, group chat, human sender, positive numeric topic and initiating-message
  IDs, session key and session ID. The middleware task ID is retained separately.
  Model arguments and process-environment identity alone cannot grant admission.
- Only Telegram sources classified by Hermes as `group` with those bindings qualify.
  Bots, anonymous-admin/channel actors, missing bindings, rejected routes,
  cron/headless/delegated contexts and mismatches fail closed.
- The plugin rechecks native gateway authorization before issuance, at delivery,
  and before handing submitted input to the native callback. **A native group-chat
  grant can authorize identified human members of that group**; this is not an
  additional per-user allowlist or proof that the sender is separately authorized
  for a DM conversation. Review group membership and native grants accordingly.
- Delivery targets only the authenticated sender's numeric Telegram user ID. No
  model-supplied destination is accepted. The user must first start the bot in a
  private chat. A blocked/unreachable DM or ambiguous delivery result cancels the
  request: there is no group fallback, alternate destination or retry.
- The website uses **Tailscale access plus possession of the bearer link**, not
  phone identity, Telegram login or the identity of the submitting person, as
  submission authority. A recipient can forward the link; the plugin cannot
  prevent this. Do not forward it or put it in shared logs.

## Setup and use

1. Use a reviewed immutable plugin revision and a compatible Hermes source. Follow
   [installation and coordinated activation](../README.md#install-and-activation);
   install/enable alone is not proof that a running gateway has activated it.
2. Configure the originating profile's native Telegram bot and authorization policy.
   Review group grants and membership; do not loosen authorization to work around a
   refusal. Have the requesting user start the bot in a private chat.
3. Configure a dedicated, tailnet-only HTTPS root forwarded unchanged to the
   loopback listener, as described in [Tailscale deployment](../README.md#tailscale-deployment-operator-owned).
   The client device needs allowed tailnet access. Never use Funnel or a public proxy.
4. From the authorized topic, inspect the intended page using native browser tools.
   Use native `list` for metadata and, if needed, `unlock` for the genuine manager
   master-password prompt. Use `enter_code` without a handle for a detected code
   field. Native inspection, not a model-supplied site, arms the OTP form.
5. Open the capability received in the requester's DM and enter the value on the
   private page, never in Telegram messages or tool arguments. Do not send a new
   topic message while filling: a newer cached initiating message can invalidate
   the pending callback, even from the same sender.
6. Check the resulting browser/manager state. `filled` reports a native fill,
   **not website authentication**; `unlocked` reports a manager unlock, not login
   to a website. No Submit/Continue click is added by the plugin, though a website
   may auto-submit a filled code. App/passkey approval stays on the actual device.

## Expiry, cancellation and browser lifetime

Callback waits share a deadline of at most **180 seconds across native execution**;
opening the form does not restart it. GET/link previews are non-consuming. One-use,
CSRF and expiry checks apply to submission, including received input not yet consumed.
Use the web form's **Cancel** button for a topic request. Plugin status/cancel tools
remain DM-only and cannot adopt a topic-owned request from a separate DM session.

Delivered stop/reset/abnormal-session-end hooks, interruption and unload cancel
pending work. Normal successful turn-end is not itself a cancellation event.
**Idle `/stop` is not reliable revocation** when Hermes emits no stop hook; use the
web Cancel button, or coordinate service shutdown if a suspect link cannot be
cancelled. Restart invalidates in-memory links. Matching active topic callbacks
are scoped by session key/ID, so stopping one session does not intentionally stop
another. Admission races are conservatively refused.

Cached-source replacement/eviction or authorization changes can cancel at handoff,
even after a valid web submission. Once input is handed to native code, status is
`commit_unknown` until a verified native result; cancellation cannot promise to
undo an action already started. Inspect the browser or manager before retrying.
Native origin/inspection-nonce, redaction, supervisor and takeover checks remain
in force. Native tab-selection ambiguity and same-origin DOM limitations remain;
this bridge does not provide immutable browser target/frame/generation binding.

## Delivery implementation and private-API dependencies

Native `send_message_tool` can mirror sent content via `_mirror_sent_message` /
`gateway.mirror`, and its Telegram formatting path can retry. The **topic** path
bypasses tool dispatch and mirroring while retaining native active-profile config
resolution, relay-egress authorization and a single credential snapshot. It uses
native `_telegram_bot` and `_send_telegram_message_with_retry(attempts=1)`, plain
text and disabled previews. Delivery failures expose no exception text through
the bridge. **Existing DM delivery is unchanged and can mirror capability links
into model-visible session history.** Neither path returns submitted secret values
to the model; this is not a general transcript-free delivery claim.

Private dependencies include the gateway runner reference, source cache,
session-key derivation and authorization wrapper; native task-local identity,
vault callbacks/middleware; and the native config/egress/Telegram helpers above.
Missing dependencies or detected mismatches are refused, but changes to private
semantics require review, not just import checks. Rerun tests on each Hermes
update. Never repair compatibility by bypassing authorization, weakening egress,
adding a group-link fallback or editing core to force admission.

## Compatibility and evidence

The manifest remains `>=0.22.1,<0.22.6`. This inherited range is **not evidence that
this topic exception has been verified on every release in it**. Earlier topic
pilot tests used Hermes source `5b147ab036d6d19131bff8d20701b5001eab844a` (0.22.3).
The PR-preparation comparison instead uses the exact Windows workflow pin,
`046094df28b712f62a5e3c728a9e59da05dcbf1e`, and isolated PM-built Python 3.14.6 on macOS:

| Check | Recorded result |
|---|---|
| Focused candidate bridge/topic/DM compatibility tests | 109 passed, no skips; comparable upstream selection: 94 passed |
| Topic-only suite | 15 passed, no skips, in each of three fresh processes |
| Full unchanged upstream plugin suite | 282 tests; 20 failures, 23 errors, no skips |
| Full candidate suite | 297 tests; 20 failures, 23 errors, no skips |

The full-run failure/error heading multisets match, with no candidate-only heading;
the shared Windows ACL/private-file/payment-path failures on macOS mean **neither
full local suite is green**. Exact-candidate Windows CI is still required before
publication. An upstream green run does not validate this candidate.

Tests execute real pinned gateway cache/key/authorization methods, middleware,
native vault handlers/callbacks, relay policy and Telegram retry primitive, with
synthetic config, transport/supervisor and loopback HTTP. They cover source changes,
revoked authorization, blocked/ambiguous delivery, no mirror/dispatch/fallback,
expiry/cancellation and concurrent-topic isolation. The same-sender reset test
proves an unrelated admitted callback survives another session's reset; it does
not establish targeted pre-issuance cancellation. Log assertions cover collected
WARNING-and-higher output, not DEBUG/INFO or every possible logging configuration.
No production defect was reproduced or fixed by this test expansion.

Separately, an operator reported a successful live sequence from a Telegram topic
to a private web link, native fill and confirmed website login. No account details
are needed for that observation. It is not exact-candidate Windows CI, a general
security audit, live manager-unlock coverage, or proof of every cancellation/device
scenario. Synthetic results are not live transport/browser evidence. See the
[platform matrix](platforms.md) for the other transports.

## Troubleshooting and rollback

- No DM link: ensure the user started the configured bot privately and has not
  blocked it. A failed or ambiguous send is cancelled, not retried; request a new
  flow only after checking the prior browser outcome. Never post a fallback link
  to the topic.
- Expired/cancelled after opening: check the shared deadline, newer topic traffic,
  delivered lifecycle events, source-cache changes and authorization policy.
  Do not reuse the link or attempt to transfer it to a different session.
- `admission_unavailable`: inspect isolation, task/session/profile correlation,
  native authorization and lifecycle state using sanitized diagnostics. This is a
  fixed refusal category, **not a diagnosis**. Intermittent live instances have
  not been root-caused; do not relax checks or infer a credential problem.
- Blank/reset browser or `no_code_field`: inspect the actual native browser/task
  state and field recognition before creating another flow. Browser lifecycle
  resets have been observed, but their cause is unresolved; this PR does not claim
  a browser-reset fix. A native fill result alone cannot establish login.
- Update/rollback: keep a known-good immutable payload. Outside active requests,
  coordinate gateway stop/unload, supported plugin replacement, doctor/validation,
  then a new process and conversation. Never overwrite running middleware. Restore
  the previous reviewed revision to remove the topic exception; use the existing
  DM workflow. Keep unrelated profiles, HTTPS routes and native auth policy intact.
