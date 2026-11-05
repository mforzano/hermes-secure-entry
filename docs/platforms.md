# Platform scope and verification

Secure Entry supports **Photon, Discord and Telegram DMs**, plus the narrow
**Telegram topic → requester DM native OTP/list/unlock bridge**. It is not an
all-platform prompt provider. Hermes must authenticate and authorize the source;
platform, home/profile, chat type, chat/sender and session identity come from native
task-local context, never model arguments or process-environment fallback.

## Evidence matrix

| Surface | Standalone entry / payment / status / cancel | Native OTP / list / unlock bridge | Capability delivery | Real-site evidence |
|---|---|---|---|---|
| Photon DM | Supported; native-store/owner tests | Synthetic native callback/lifecycle tests | Native DM target and gateway-loop adapter | Historical operator verification of add-login, OTP and authenticated page on 0.2.1; not revalidation of this candidate |
| Discord DM | Supported; native-store/owner tests | Synthetic native callback/lifecycle tests | Native numeric channel resolution, egress guard and REST sender; synthetic network in tests | Historical operator-reported verification on 0.3.0 with patched core; not stock-core/all-site coverage |
| Telegram DM | Supported; native-store/owner tests | Synthetic native callback/lifecycle tests | Native numeric chat resolution, egress guard and one-shot sender; synthetic network in tests | Separate DM-originated live login is not established by the topic result |
| Authorized Telegram group topic with identified human sender | Refused by plugin tools | Native `enter_code` without a handle, `list`, `unlock` only | Private DM to the authenticated sender; non-mirroring single attempt | Operator reported topic → private web link → native fill → confirmed login; not comprehensive or exact-candidate validation |
| Other group/channel/thread contexts, bot/anonymous/channel senders, unknown transports, cron/API/headless/delegated contexts | Refused | No bridge admission | No bridge prompt delivery | Not supported by this bridge |

This table describes **plugin admission**, not a replacement for the native policy
of other browser-vault actions. `list` returns native metadata to the originating
conversation; topic participants may see it. Native group-chat grants can authorize
identified human group members without a separate plugin per-user allowlist or
independent DM authorization check. The web form is authorized by **bearer-link
possession plus tailnet access**, not proof of phone/Telegram identity. Forwarding
is possible. See the [complete topic contract](telegram-topics.md).

`filled` is a native fill result, not website authentication. No live manager-unlock
or comprehensive physical Safari/VoiceOver validation is claimed. Historical live
results and the operator's topic result are separate from synthetic regression
coverage and do not prove that any reader's installation is active.

## Stock versus patched Hermes core

The bridge transports native prompts; it does not replace browser selection or OTP
field recognition. Stock Hermes 0.22.1 can support forms its native detector selects
and recognizes; add-login is independent of the following site/widget-specific fixes:

- [#136831: visible OTP fields on bound login origins](https://github.com/NousResearch/hermes-agent/pull/136831)
  addresses wrong-tab selection from unrelated hidden code-like controls and uses
  saved-handle origins when core receives a handle. This plugin still refuses
  nonempty OTP handles and does not gain immutable target binding from that work.
- [#139405: digit-count labels and numbered OTP widgets](https://github.com/NousResearch/hermes-agent/pull/139405)
  addresses explicit digit-count labels and complete ordered adjacent numbered
  groups. Historical patched-core test/live evidence is not this plugin's suite or
  a claim of universal native recognition.

The historical Discord result used patched core, including the numbered-widget fix.
Neither linked change is bundled here or asserted to be a universal prerequisite;
this document does not assert their current merge/release status. The reported
Telegram topic login does not identify an exact core revision, so it cannot extend
stock-core compatibility claims. Native inspection must find the actual field
before a code collector is armed.

## Inspected native routing contract

Current PR-preparation tests use Hermes source
`046094df28b712f62a5e3c728a9e59da05dcbf1e`, the existing Windows workflow pin. The
manifest's `>=0.22.1,<0.22.6` range remains unchanged; topic coverage at one pin does
not validate every version in that range or promise future private-API compatibility.

- Native Telegram sources distinguish `dm` from `group`, carry the real sender,
  topic and initiating-message IDs, and reject unsuitable actors in topic admission.
  Usernames are display metadata, not delivery authority. Discord channel ID is
  distinct from sender/user ID.
- Gateway ContextVars bind identity; the topic bridge also checks the current
  cached source, session-key derivation and profile-aware native authorization.
  It retains the original middleware/native browser task, not a rewritten DM task.
- Existing DM delivery targets `bound_PLATFORM + ':' + bound_CHAT_ID`. It uses
  registered native send dispatch when available, otherwise the native CLI send
  implementation selected before delivery. It never retries through an alternate
  route on error. **Native DM send can mirror the capability URL into session
  history.** This behavior is unchanged.
- Topic delivery targets only the authenticated numeric **user ID**. It uses the
  native active-profile config resolver, relay-egress guard and single credential
  snapshot, then the native Telegram helper with `attempts=1`. No model-tool
  dispatch, mirror, group fallback or retry is used for topic capabilities.
- Native bot credentials must already be configured for the profile. Synthetic
  relay-fronted refusal tests do not establish successful connector-only relay
  delivery. Egress authorization is not bypassed.

Slack, Signal, WhatsApp, Matrix and other transports are not added merely because
native send adapters exist; their identity, routing and callback contracts are
not established by this contribution.

## Test evidence and activation

The isolated PM-built Python 3.14.6/macOS comparison recorded **109 focused
candidate tests passing** (94 in the upstream selection), and **15 topic tests
passing in each of three fresh processes**, all without skips. Full discovery is
**not green**: upstream 282 tests and candidate 297 tests each have 20 failures and
23 errors, with matching failure/error heading multisets in inherited Windows
ACL/private-file/payment paths. Exact-candidate Windows CI remains a publication
gate. See [topic compatibility and evidence](telegram-topics.md#compatibility-and-evidence)
for the private-API and coverage limits; no general audit or production fix is claimed.

Tests use disposable native vaults, real middleware and pinned gateway/native
methods, loopback HTTP and synthetic config/transport/supervisor boundaries. No
external bot messages are sent. Collected-log checks cover WARNING and higher,
not every verbosity. Concurrent reset coverage includes survival of an unrelated
admitted callback, not targeted pre-issuance cancellation. Optional SDKs belong
only in the isolated test environment; no new plugin dependencies are introduced.

Use the [supported installation procedure](../README.md#direct-github-install-supported-hermes-cli)
and a reviewed immutable revision. Set in-process isolation, configure the separate
tailnet-only HTTPS root, and coordinate gateway stop, update/install, doctor and
validation, then a new gateway process and conversation. Never overwrite an active
middleware copy. Install/enable alone does not configure Tailscale or prove live
activation. Before sensitive use, validate authorized synthetic delivery, blocked
DM behavior, cancellation, topic isolation and an existing DM flow. Live checks
require separate user authorization; never send unsolicited tests or share links.

Intermittent `admission_unavailable` and observed browser resets remain unresolved,
not diagnoses or claimed fixes. Inspect native state and sanitized diagnostics;
do not bypass authorization or equate a successful fill with authenticated login.
