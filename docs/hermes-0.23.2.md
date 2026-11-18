# Hermes 0.23.2 compatibility (Secure Entry 0.5.18 and 0.5.19)

The manifest targets `==0.23.2`; Secure Entry 0.5.17 remains the revision for
Hermes 0.22.1–0.22.5. The earlier manifest rejects 0.23.2 before `register()`.

The native send fallback follows Hermes's own `hermes send` command to
`gateway.outbound.send.send_message_tool`, replacing the old `tools` import.
If a registered send tool exists it still takes precedence. Neither route is
retried through the other after a failure. The sender import change did not
change identity, consent, destination binding, vault or browser write policy.

Secure Entry 0.5.19 adds [private manual OTP fill](manual-otp-fill.md) on this
stock host without a core patch. It fills and verifies selected controls
without submitting the form or adding restrictions on later browser access.

The Windows suite pins the upstream `v0.23.2` source revision
`ae2a81ccc00e9b7c06301523e5bb09608397149c`. The tests use a disposable
`HERMES_HOME`, native tool registry and generated browser code with synthetic
fixtures. Browser tests use the current capture and provisioning seams; there
is no legacy `browser_tool` session cache on this host. Native relay tests
replace only the `gateway.run` launcher reference and the network transport;
restoring all of `sys.modules` would discard deferred platform modules while
leaving the plugin manager's registry state behind.

Run `python -m unittest discover -s tests -v` from the plugin worktree with the
pinned core and plugin roots on `PYTHONPATH`, using a separate Python 3.14 test
environment with the host dependencies, Chrome/Playwright and the bot SDKs.
Run `hermes plugins doctor <plugin-path> --ci` and `hermes plugins validate
<plugin-path>` from the same isolated host. No plugin dependencies need to be
installed. The validator's private-core-import warnings are expected for the
existing native adapters; they are a portability concern, not a registration
failure.

This is synthetic compatibility evidence, not live-gateway or live-merchant
acceptance. No live activation, credential collection or remote publication
is required to run the tests.
