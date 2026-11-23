# Weekly Hermes stable-support proposals

The [stable-support workflow](../.github/workflows/hermes-stable-support.yml) checks the latest published release from `NousResearch/hermes-agent` on Mondays. It proposes only the next consecutive patch in the currently supported minor. It never guesses support across a gap, admits a future stable patch, or drops an already supported patch. An already admitted version is a no-op; a different minor, gap, invalid manifest, unknown release, or more than eight hosts requires maintainer review.

The workflow constructs the exact one-line manifest change without committing it. Windows runners validate that candidate against every admitted version, including the pinned baseline and the new official tag, with exact tag/commit and reported-version checks, real loader admission, doctor and registered tool names, catalog validation, and the synthetic regressions. The upstream-main forward workflow remains separate and informational for this promotion. The current Hermes loader compares numeric base versions; the workflow's stable-only policy is about official release selection, not a promise that the runtime rejects nightly builds reporting the same base version.

Pull requests touching the automation and manual dispatches are **dry runs**. After this workflow is on `main`, use `gh workflow run hermes-stable-support.yml --ref main -f tag=v0.23.3` to select an official tag, or omit `tag` to use the current latest release. Check that all candidate jobs actually ran, not just the workflow's aggregate result. No runtime files or plugin version change in the automation PR.

## Enabling publication

The separate writer runs only on the scheduled `main` event after all validation jobs pass. It needs no custom secret, consumes no test artifacts or cache, and recomputes the exact plan before creating a manifest-only branch and PR. It refuses stale `main`, duplicate proposals, and pre-existing unmatched candidate branches; it never overwrites branches, merges, tags, releases, or installs anything.

Publication is off until the maintainer authorizes both of these repository changes:

1. In **Settings → Actions → General → Workflow permissions**, enable **Allow GitHub Actions to create and approve pull requests**. The GitHub setting is combined; this workflow never approves a PR. Leave default workflow permissions read-only.
2. Set the Actions variable `HERMES_STABLE_PR_WRITES` to `true` only after that setting is approved. Remove it to stop writes without disabling dry-run validation.

GitHub may require a maintainer with write access to select **Approve workflows to run** on a bot-created PR. The pre-PR validation is linked in its body and does not replace the normal PR checks or human review. Once authorized, verify the first scheduled write by reading back the bot PR, its manifest-only diff, and its checks. If GitHub denies PR creation after creating the branch, the writer stops and leaves that branch for maintainer inspection; it does not bypass the denial or rewrite the branch.
