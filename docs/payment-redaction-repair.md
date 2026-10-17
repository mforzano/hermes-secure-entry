# Plugin-owned payment redaction repair (0.5.7 candidate)

## Change and evidence

`secure_entry.redaction.register_payment_redaction_values` owns payment field selection and formatting. It calls the already-existing `agent.redact.register_vault_redaction_value`; it does not import a new core helper, replace core functions, weaken exact-substring matching, or mutate/clear registry entries. Add-card, saved-card fill and Link-issued fill use it before storage/write. PAN/CVC, grouped PAN and complete expiry variants remain protected. Standalone month/year, billing metadata and policy booleans are not registered as passwords. Generic password/OTP paths are unchanged. Existing real credential collisions still redact unrelated text intentionally.

The historical plugin `add_card` loop registered every submitted field before `store.add_item`. `Service.request` supplies that callback directly to the private card form. It therefore could poison the registry on form submission **before any browser_vault list or fill**. A synthetic execution of the historical module reproduced URL corruption before metadata listing. Native `VaultStore.list_items` reads metadata and does not register payment values. This establishes a plugin-owned cause and a reproducible ordering; it does not identify or print any live secrets or prove that no other registration source ran historically.

Compatibility was exercised against a pristine archive of canonical core HEAD, not the modified checkout or selected PM snapshot. That core has no `register_payment_redaction_values`. The previous plugin failed its storage/fill regression there; this candidate passes. Disposable HERMES_HOME and the isolated test interpreter are required. Use unittest discovery, not pytest collection from the hyphenated plugin root.

The unnecessary uncommitted core helper, payment-fill helper call and task-only core tests were removed; unrelated core OTP/tab-selection and PM source-rebuild edits were preserved. This does not roll back an already-published PM runtime snapshot or alter the serving process.

## Existing polluted running state: no unsafe cleanup

The native registry is profile-scoped, memory-only and stores `{value: None}` without caller ownership or reference counts. The historical plugin did not retain registration provenance. Even an exact month match is not proof that the same bytes were not also registered as a real password/OTP. Consequently this patch does not remove arbitrary short entries, enumerate the live registry, resolve stored credentials to reconstruct it, flood it to force eviction, or call `clear_vault_redaction_values`.

Source inspection found `clear_vault_redaction_values` defined, but no production caller in the inspected core. Its lock/teardown docstring is not a working lifecycle guarantee: `agent.vault_backends.unlock.lock`, `release_session` and `lock_all_profiles` forget manager tokens, not redaction entries. Plugin unload/reload does not clear this core-owned state either. No safe in-place cleanup of historical unattributed entries has been demonstrated. Do not promise no-restart recovery. A coordinated ordinary gateway process replacement after deploying the independent plugin is the available process-lifecycle recovery, **not a new core dependency**; it must be explicitly coordinated, not performed by the test harness.

Stock native `browser_vault` payment fill still registers all payment values. That is an independent legacy caller, not patched or monkeypatched by this bounded plugin fix. Use the plugin saved-card/Link paths for this workflow; do not claim that this patch corrects stock native payment fill. Metadata listing does not have that problem.

## Activation handoff (not executed)

1. Review/test the final plugin bytes, commit and publish the immutable revision when authorized. No changes are needed to the running core for this plugin's imports.
2. Verify the active profile/home. Use supported plugin disable and `gateway.control_socket.reload_gateway_plugins(home)` to unload middleware; verify listener shutdown. Install/enable the immutable candidate through the supported plugin manager, doctor it, read back version/bytes, and reload tools in a fresh session. Do not write directly into the active installed directory.
3. Treat prevention and recovery separately. Hotload can activate prevention without a core rebuild, but cannot safely repair existing polluted state. Coordinate one process replacement only if recovery is needed and authorized; preserve pending transaction/card handles, revoke or resolve pending forms, and verify the exact serving gateway generation afterward. An already-published selected PM snapshot may still contain the now-unnecessary helper; removing that snapshot is a separate deployment action, not required to run this plugin.
4. Verify a fresh private-entry URL through exact-request metadata and non-consuming HTTP status/form-presence checks, then verify the delivered message separately. Do not rewrite opaque tokens or infer successful delivery from server availability. Do not claim payment acceptance or a completed purchase from these tests.

The final candidate passed all **222 tests** with `python -m unittest discover -s tests -q`, including nine direct payment-redaction tests and the existing disposable native/Chrome integration suite. Imported-path verification confirmed the native redactor came from the pristine archive and the payment helper from this plugin; the new core helper was absent. Both repository diffs passed `git diff --check`.

No push, install, core rebuild, gateway restart, live-registry operation or live payment was performed during this preparation.
