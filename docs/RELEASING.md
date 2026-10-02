# Release procedure

1. Review the intended source changes and dependency attribution. Set the same
   semantic version in both plugin manifests. Keep generated binaries, local
   configuration, session logs, screenshots and credentials outside the repository.
2. Run the README's validation, tests and privacy audit. Check the working tree,
   complete index and reachable Git history. Use the extra `--deny-term` option for
   private identifiers only on your workstation; do not commit those values to a
   command log, config or CI workflow. Findings show types/locations, never matches.
3. Build the ZIP in an external directory. Inspect its file inventory, run its
   audit, verify the SHA-256, and install from that extracted copy in a fresh Codex
   home with spaces in its path. Test installation twice and uninstall. Hook trust
   remains a real user review step. An untrusted hook must stay pending.
   Also verify the quick-start native commands from a fresh profile outside this
   checkout: Git marketplace add with the release tag, plugin add, metadata discovery
   and native removal. Test upgrades through the documented remove/reinstall path.
   Test complete setup through `Install.cmd` / `install.sh` or the equivalent
   `install.py --with-agentcontroller`, including repeat acquisition and native
   registration. Release CI runs real acquisition on Windows, Linux and macOS;
   Windows/Linux probe MCP, while macOS verifies download integrity and pending
   manual setup. A Windows desktop flow requires separate AgentController assertions
   and a focused screenshot. Do not label macOS/Linux desktop UI validated by CI.
4. When a UI surface changed, perform the relevant AgentController check on a
   supported target and retain evidence locally. Otherwise state why UI QA is
   not applicable and exercise the affected CLI/API/library. Publish screenshots
   only if deliberately created for public use and reviewed for personal content.
   CLI tests are not a desktop QA pass.
5. Review the first commit's public author identity and the exact files to publish.
   Publishing requires the maintainer's explicit decision; preparing this repository
   does not itself push commits, create tags or publish a release.
6. Once publication is authorized, push the reviewed commits and an annotated
   version tag such as `v0.2.0`. The tag workflow reruns CI and verifies that the tag
   matches the manifest before creating the GitHub release with ZIP and checksum.
   It also signs build provenance. Download the published archive, verify its
   attestation against the expected repository/workflow/tag, compare its bytes with
   the reviewed local build and repeat installation in a fresh disposable profile.

The release builder uses an explicit file inventory: update it deliberately when
adding distributable files. Keep SECURITY.md current with actual controls and
limitations. Hook output must use supported Codex decisions; synthetic JSON tests
alone cannot establish host enforcement. No current PreToolUse hook may return
the unsupported `ask` decision.

Never rewrite a public history or force-push as an automatic response to a leak.
Stop publication, assess exposure and handle any required revocation separately.
Use the GitHub-provided workflow token only in the release job; source validation
jobs need read access and no provider credentials or inference calls.

For updates, users should refresh their marketplace/install and review any changed
hook definitions. Do not tell users that a previous trust decision automatically
approves every future script update; review source changes as well as definitions.
