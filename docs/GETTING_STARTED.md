# Install, activate and use Ultra Hook

**[Ultra Hook download](https://github.com/jonmedev/Ultra_Hook/releases/latest)** ·
**[AgentController downloads by Kasempiternal](https://github.com/Kasempiternal/agentcontroller/releases)**

Ultra Hook is the Codex plugin. AgentController is Kasempiternal's separate desktop
automation project; our integration skill does not include or claim authorship of it.

## 1. Check prerequisites

Install Python 3.11+, Node.js 18+ and a signed-in Codex CLI with `plugin` and
`app-server` support. Use the [official Codex setup](https://developers.openai.com/codex/cli/)
for Codex itself. Ultra Hook does not install these prerequisites or request API keys.

On Windows PowerShell:

```powershell
python --version
node --version
codex --version
codex plugin --help
codex app-server --help
```

On macOS/Linux, use `python3` in place of `python` throughout this guide. If Windows
only provides the Python launcher, use `py -3` and check that its version is 3.11+.
If a command is missing, install that prerequisite and reopen your terminal.

## 2. Choose a stable source directory

Download the versioned `ultra-hook-VERSION.zip` and its `.sha256` from
[Releases](https://github.com/jonmedev/Ultra_Hook/releases). Verify them using
[the security instructions](../SECURITY.md#verify-a-download) before running scripts.
Extract into a directory you will keep, then open a terminal in the extracted root
(the directory containing `README.md` and `scripts`). Avoid a temporary Downloads
cleanup folder: Codex registers this directory as a local marketplace source.

A Git checkout also works. For reproducible installation, check out the reviewed
release tag. Updating files in place does not by itself update the installed cache.

## 3. Preview and install

```sh
python -B scripts/install.py --dry-run
python -B scripts/install.py
```

The preview checks prerequisites and prints proposed CLI actions without installing.
Receipt ownership and concurrent changes are rechecked under a lock during actual
installation, so a successful preview does not guarantee the transaction can proceed.
Installation registers the local marketplace and plugin through Codex's native CLI.
It preserves your leader, effort, permissions, personal instructions and unrelated
plugins. Repeating installation from the same directory/version reuses registrations.

By default the scripts use `CODEX_HOME` when set, otherwise your standard Codex home.
For another profile, pass `--codex-home "path to profile"` consistently to install,
doctor and uninstall, and launch Codex with that same profile. A fresh profile must
be signed in separately for model work; never copy credentials into this repository.
`--codex-command "path to executable"` selects a Codex executable absent from PATH.

If migrating from CAS, use `--replace-cas` on both the preview and install commands.
CAS remains enabled until the replacement is verified ready. After hook approval,
rerun installation with `--replace-cas` to complete migration, then start a new
session. Avoid running both orchestration plugins together during migration.
See [migration details](MIGRATION.md).

## 4. Review hooks and check readiness

In Codex, open `/hooks`, inspect the five Ultra Hook definitions and their source,
and approve them through the native interface. The installer does not grant trust.
Then run:

```sh
python -B scripts/doctor.py
```

Start a new Codex session so skills and hooks refresh. Check the actual skill names
in its catalog; the portable plugin normally exposes `$ultra-hook:ultra-hook` and
`$ultra-hook:agentcontroller`. The short names work when unambiguous.

| State | What it establishes |
| --- | --- |
| Installed | Native CLI registered the plugin; trust may still be pending |
| Doctor ready | Plugin enabled, five matching trusted hooks and two expected skills |
| AgentController catalog discovered | Explicit diagnostic reached its MCP tools |
| UI validated | Actual target flow exercised with assertions and relevant screenshots |

Doctor returns **0** when plugin metadata is ready, **2** when readiness is pending
(including unavailable runtime metadata), and **1** on a fatal inspection/setup
error. Invalid command-line arguments return **2** with an error on stderr rather
than a readiness result. AgentController is optional for non-UI
work; doctor readiness is not a UI pass. Default doctor starts no configured MCP
servers and makes no model inference calls.

For automation, add `--json` to install, doctor or uninstall. Install/uninstall
return 0 for a successful transaction or preview; use doctor to gate readiness.
JSON errors go to stderr. Keep profile paths and diagnostic output private when
sharing support reports.

## 5. Give the skill a real task

Examples to paste in Codex, adapting paths and criteria to your project:

```text
$ultra-hook Fix the CSV importer that drops the last row. Reproduce it, keep the
public API unchanged, and check the original failing input after the fix.
```

```text
$ultra-hook Add pagination to the search API. Keep existing callers compatible.
Use native teammates only for useful independent work; preserve my leader model.
```

```text
$ultra-hook Review this branch for data loss and race conditions. Read-only:
report evidence and affected locations; do not edit or publish.
```

```text
$ultra-hook Investigate why startup is slow. Establish a baseline first. Work
directly, without subagents or model changes, and stop after identifying the cause.
```

The skill selects a proportionate workflow; it does not spawn a team for every
request. Workers discuss findings with the lead and can resume for follow-up.
Choose task-specific limits in the request when needed: read-only, no delegation,
permitted models/efforts, a bounded experiment or no publication. Maximum effort
requires evidence and existing authorization. These instructions are routing
constraints, not a metered spending cap. No global preset or profile rewrite is
required. See [teams and models](../plugins/ultra-hook/skills/ultra-hook/references/teams-and-models.md).

## Optional: enable AgentController for UI work

Download AgentController from **[Kasempiternal's releases](https://github.com/Kasempiternal/agentcontroller/releases)**.
The published 2.5.0 asset is a [macOS DMG](https://github.com/Kasempiternal/agentcontroller/releases/download/v2.5.0/AgentController-2.5.0.dmg).
For Windows, use the [upstream Windows guide](https://github.com/Kasempiternal/agentcontroller/blob/master/Windows/README.md);
for Linux, the [upstream Linux guide](https://github.com/Kasempiternal/agentcontroller/blob/master/Linux/README.md).
[Source download](https://github.com/Kasempiternal/agentcontroller/archive/refs/tags/v2.5.0.zip)
is source code, not a ready-to-run Windows executable. Check release assets for newer
versions and platform support. Ultra Hook does not rehost these downloads.

If you already have a reviewed local stdio executable:

```sh
python -B scripts/install.py --agentcontroller-command "absolute path to executable"
python -B scripts/doctor.py --check-agentcontroller
```

The explicit controller option opts into starting that server to inspect its tool
catalog. Unrelated MCP servers remain disabled during diagnostics. An existing
conflicting registration is not overwritten. Avoid wrapper commands that inject
unreviewed context or credentials.

Windows can build the pinned upstream source with Git and .NET 9 SDK:

The helper builds reviewed AgentController 2.4.2 source at
`bc6db97122d6adf07342d3efc87e7ac7c96b4889`; it does not track the latest release.
It is an Ultra Hook build helper for Kasempiternal's code, not an official upstream
installer. To build a different version, follow upstream's platform instructions.

```powershell
python -B scripts/setup_agentcontroller.py --build-windows --destination ../ultra-agentcontroller
```

Choose a fresh destination outside this repository. The builder reports the resulting
executable; pass that exact absolute path to installation as above. Build dependencies
execute code and require network access. It does not silently register a server.
For other platforms, follow [AgentController upstream](https://github.com/Kasempiternal/agentcontroller)
and probe capabilities on the actual target. Windows-specific limits are documented
[here](../plugins/ultra-hook/skills/agentcontroller/references/windows.md).

Then ask for a bounded flow, for example:

```text
$agentcontroller Validate the search filter in my local app: enter a known query,
assert the expected result, clear it and assert the full list returns. Retain a
focused screenshot. Report unsupported operations or missing access.
```

If the backend cannot reach the target, UI validation remains pending. CLI and
library tasks use their own interfaces; no unrelated desktop test is necessary.

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| `plugin` or metadata command unsupported | Update Codex through its official installation method; rerun the preview |
| Pending hooks or missing skills | Inspect `/hooks` and plugin enablement, confirm profile, start a new session, rerun doctor |
| Different source or version registered | Follow the upgrade steps below; do not overwrite the receipt or trust data |
| CAS migration pending | Approve the replacement hooks, rerun `install.py --replace-cas`, start a new session |
| Linked path or hardlink rejected | Use an ordinary directory; do not bypass the path checks |
| Controller missing/unreachable | Check the registered executable and target permissions; run the explicit controller diagnostic |
| Secret access denied | Use redacted/synthetic inputs; do not retry the same access through a different tool |
| Interrupted transaction or concurrent edit | Stop competing installers, inspect retained state/backups; do not delete a lock that may belong to a running process |

Use each script's `--help` for supported flags. Never publish your whole Codex
profile, receipts, config or screenshots to troubleshoot an installation.

## Upgrade or remove

For an installation owned by these scripts, use its original source directory and
profile to preview removal:

```sh
python -B scripts/uninstall.py --dry-run
python -B scripts/uninstall.py
```

Removal preserves backups, source files, independent controller binaries and
unrelated settings. If this installation disabled CAS, removal restores it when
the recorded state still matches. Registrations the installer did not create are
not its property; changed ownership/version requires review instead of forced removal.

For an upgrade, first complete the old-source uninstall steps above. Keep the old
source and backups, extract the reviewed new release
into a different stable directory, and repeat installation there with the same
profile and desired optional flags. Review the new hook source, even if definitions
look unchanged, then repeat readiness checks and start a new session. If the new
installation fails, uninstall any owned replacement before reinstalling the retained
old source. Do not use an older release with a known security defect as a fallback.
There is no automatic updater or download-and-execute bootstrap.
