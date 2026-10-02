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
4. Perform the relevant AgentController UI check on a supported target. Retain
   evidence locally. Publish screenshots only if deliberately created for public
   use and reviewed for personal content. CLI tests are not a desktop QA pass.
5. Review the first commit's public author identity and the exact files to publish.
   Publishing requires the maintainer's explicit decision; preparing this repository
   does not itself push commits, create tags or publish a release.
6. Once publication is authorized, push the reviewed commits and an annotated
   version tag such as `v0.1.0`. The tag workflow reruns CI and verifies that the tag
   matches the manifest before creating the GitHub release with ZIP and checksum.

Never rewrite a public history or force-push as an automatic response to a leak.
Stop publication, assess exposure and handle any required revocation separately.
Use the GitHub-provided workflow token only in the release job; source validation
jobs need read access and no provider credentials or inference calls.

For updates, users should refresh their marketplace/install and review any changed
hook definitions. Do not tell users that a previous trust decision automatically
approves every future script update; review source changes as well as definitions.
