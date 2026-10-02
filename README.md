# Ultra Hook

Native Codex teamwork with proportionate model selection and continuing teammate
conversations. Small tasks stay direct. For UI validation, Ultra Hook integrates
**[AgentController by Kasempiternal](https://github.com/Kasempiternal/agentcontroller)**,
an independent third-party project. AgentController is not developed or distributed
by Ultra Hook; this repository provides the Codex integration skill.

**[Download Ultra Hook](https://github.com/jonmedev/Ultra_Hook/releases/latest)** ·
**[Installation guide](docs/GETTING_STARTED.md)** ·
**[AgentController downloads (Kasempiternal)](https://github.com/Kasempiternal/agentcontroller/releases)** ·
**[Usage examples](docs/GETTING_STARTED.md#5-give-the-skill-a-real-task)**

## Downloads

| What you need | Download / instructions | Maintainer |
| --- | --- | --- |
| Ultra Hook 0.1.3 plugin | [ZIP](https://github.com/jonmedev/Ultra_Hook/releases/download/v0.1.3/ultra-hook-0.1.3.zip) · [SHA-256](https://github.com/jonmedev/Ultra_Hook/releases/download/v0.1.3/ultra-hook-0.1.3.sha256) · [Verify](SECURITY.md#verify-a-download) | This repository |
| AgentController for macOS | [Official downloads](https://github.com/Kasempiternal/agentcontroller/releases) · [2.5.0 DMG](https://github.com/Kasempiternal/agentcontroller/releases/download/v2.5.0/AgentController-2.5.0.dmg) | Kasempiternal |
| AgentController for Windows | [Upstream build/setup guide](https://github.com/Kasempiternal/agentcontroller/blob/master/Windows/README.md) · [Source](https://github.com/Kasempiternal/agentcontroller/archive/refs/tags/v2.5.0.zip) | Kasempiternal |
| AgentController for Linux | [Upstream installation guide](https://github.com/Kasempiternal/agentcontroller/blob/master/Linux/README.md) · [Source](https://github.com/Kasempiternal/agentcontroller/archive/refs/tags/v2.5.0.zip) | Kasempiternal |

AgentController is optional for installing Ultra Hook and required for its UI
validation workflow. As checked on 2026-10-02, upstream 2.5.0 publishes a macOS DMG;
Windows/Linux use upstream source installation. Check the upstream releases for
later platform assets. The Ultra Hook ZIP contains no AgentController binary.

This is a portable plugin with two skills and five compact lifecycle hooks. It
preserves your chosen leader, model settings and native permissions. It has no
mandatory team size, prompt-rewriting ceremony, background agent loop or automatic
maximum-effort setting. It does not unlock models, enforce a monetary cap or claim
measured superiority over vanilla Codex.

## Install

Requires Python 3.11+, Node.js 18+ and a Codex CLI with plugin and app-server support.
Install and sign in to Codex separately. No API keys belong in this repository.

Download a versioned ZIP from [Releases](https://github.com/jonmedev/Ultra_Hook/releases),
[verify it](SECURITY.md#verify-a-download), and extract it into a directory you will
keep. Open a terminal in its root (or use a checkout of the reviewed tag):

```sh
python -B scripts/install.py --dry-run
python -B scripts/install.py
python -B scripts/doctor.py
```

On macOS/Linux, use `python3`; on Windows, `py -3` also works if it selects Python
3.11+. The [getting started guide](docs/GETTING_STARTED.md) covers prerequisites,
profiles, activation, examples, troubleshooting and upgrades.

The installer uses Codex's supported marketplace/plugin commands. It does not
replace your model, effort, permissions, global instructions or unrelated plugins.
Keep the checkout/extracted directory if using a local marketplace; it is the source
used for refreshes. Backups and installation state stay under your own Codex home.

Review the five hook definitions and their source, then open `/hooks` in Codex to
trust them. Installation is not hook approval: the doctor reports pending trust,
and no script writes trusted hashes or bypasses the native review. Start a new
session to refresh the skills and tool catalog.

Doctor returns **0** for ready plugin metadata, **2** for pending readiness and
**1** for an error. Add `--json` to install, doctor or uninstall for automation.
An install success does not mean hooks are trusted or a UI has been tested.

Read the [security policy and limits](SECURITY.md). Version 0.1.1 fixes an unsupported
hook response used in 0.1.0; update before relying on secret-access denials. For an
owned older installation, uninstall it from its original directory, keep your
backup/receipt, and install the new version from a separate extracted directory.
Review source changes even when hook definitions have not changed.

For an existing CAS installation, `--replace-cas` requests a reversible migration.
CAS is disabled only after the replacement skills and trusted hooks are verified.
If review is still pending, finish `/hooks` and rerun the installer with that flag.
See [migration](docs/MIGRATION.md) for the consolidated workflows.

## Set up AgentController for UI work

**AgentController belongs to [Kasempiternal](https://github.com/Kasempiternal), not
Ultra Hook.** Get it from the [upstream releases](https://github.com/Kasempiternal/agentcontroller/releases)
and follow the [upstream installation guide](https://github.com/Kasempiternal/agentcontroller#installation).
Our `$agentcontroller` skill supplies Codex usage and validation guidance for that
external tool; it is not the application itself.

The plugin requires actual AgentController evidence when validating UI/app flows.
Installation of the skills does not install a desktop controller or grant app access.

If you already have a working executable, register it while installing:

```sh
python -B scripts/install.py --agentcontroller-command /absolute/path/to/agentcontroller
```

On Windows, the optional source builder requires Git and the .NET 9 SDK:

```sh
python -B scripts/setup_agentcontroller.py --build-windows --destination ../ultra-agentcontroller
```

Choose a destination outside this repository when preparing a contribution or a
release. Register the resulting executable with `--agentcontroller-command`.
The builder pins the upstream source revision and preserves dependency licenses;
the release archive contains no machine-specific controller binary.
It builds the previously reviewed revision `bc6db97122d6adf07342d3efc87e7ac7c96b4889`
(2.4.2 source), not the latest upstream release. Use upstream instructions if you
want another version and validate its actual capabilities before relying on them.

For other platforms, install the appropriate upstream
[AgentController backend](https://github.com/Kasempiternal/agentcontroller) and verify
its actual target capabilities. The Windows backend supports UI Automation but has
unsupported operations and target-specific limits; see the
[platform guidance](plugins/ultra-hook/skills/agentcontroller/references/windows.md).
Tool discovery alone is not a successful UI test. Use assertions and relevant
screenshots on the actual target; if it is unreachable, report UI validation pending.
For changes without a UI, test the real CLI/API/library instead.

The doctor inspects hooks and skills with MCP servers disabled. To explicitly
start the registered AgentController server and check its tool catalog, run:

```sh
python -B scripts/doctor.py --json --check-agentcontroller
```

## Use

In a new Codex session:

```text
$ultra-hook Fix the importer dropping its last row. Reproduce it, preserve the
public API and verify the original input after the fix.
```

For substantial work, the skill establishes a completion check, selects relevant
engineering or research guidance, and coordinates only useful authorized work.
Give task-specific limits in your request, such as read-only review, no subagents,
allowed model efforts or no publication. See [more examples](docs/GETTING_STARTED.md#5-give-the-skill-a-real-task).

- Invoke `$ultra-hook` for a substantial implementation, architecture, review or
  research task. Normal skill discovery can also select it for a matching request.
- Invoke `$agentcontroller` for UI validation. Check the actual qualified names in
  your Codex skill catalog if another plugin defines the same short name.
- Give workers bounded ownership and acceptance criteria. They discuss discoveries
  with the lead and can resume their existing context for corrections.
- Model choices come from the live collaboration catalog. Deeper reasoning or a
  stronger specialist requires evidence and must fit your authorization and caps.

The hooks supply event-specific reminders and deny recognized secret access and
explicit destructive Git operations. Ordinary file/Git changes receive authorization
reminders; these do not force a permission prompt. Checks are heuristics, not a
sandbox or complete command interpreter. The hook code makes no network requests
and writes no logs. Native permission settings remain authoritative.

Command Code/DeepSeek is not bundled in this release: the inspected external CLI can
automatically add local context without a verified per-call isolation control. This
does not prevent using native Codex teammates or a separately reviewed integration.

## Uninstall and rollback

```sh
python -B scripts/uninstall.py
```

Uninstall removes the owned plugin through Codex and retains unrelated settings.
Consult the script help and installation receipt for explicit migration rollback
options. It does not delete an independently installed AgentController executable,
credentials or user work.

## Verify and build

```sh
python -B scripts/validate.py
python -B -m unittest discover -s tests
node --test plugins/ultra-hook/hooks/tests/team-routing.test.cjs plugins/ultra-hook/hooks/tests/safety-windows.test.cjs plugins/ultra-hook/hooks/tests/security-boundaries.test.cjs
python -B scripts/audit_release.py --git-staged --git-history --allow-github-noreply-identities
python -B scripts/build_release.py --output ../ultra-hook-release
```

The audit rejects common credential patterns, personal paths/identifiers and local
artifacts without echoing matched values. Packaging copies only reviewed source
directories into a fresh staging tree, audits that tree and emits a deterministic
ZIP plus SHA-256 checksum. Release CI signs build provenance; the
[security policy](SECURITY.md#verify-a-download) shows how to verify it against the
repository, release workflow and version tag. Review findings before publishing; pattern scans cannot
prove the absence of every possible private value. Use a deliberate public GitHub
noreply identity for release commits, never a private email address.

For an extracted ZIP without Git metadata, run `python -B scripts/audit_release.py`
without the Git options. Git audit modes require the repository root and never scan
an enclosing repository implicitly.

CI runs the portable checks on Windows and Linux. Tag releases run those checks
before building and publishing the archive. See [release procedure](docs/RELEASING.md).
UI behavior must be checked separately through AgentController; headless CI does not
claim to validate a desktop application.

## Provenance and compatibility

See [LICENSE](LICENSE) and [NOTICE](NOTICE) for upstream attribution. This is an
independent adaptation, not an official OpenAI, CAS or AgentController release.
Installation follows the [official plugin packaging documentation](https://developers.openai.com/plugins/build/plugins);
hook review follows [Codex hook documentation](https://learn.chatgpt.com/docs/hooks).
GitHub distribution is distinct from submission to the universal plugin directory,
whose [submission restrictions](https://developers.openai.com/plugins/deploy/submission)
currently exclude plugin ZIPs containing lifecycle hooks.

The [K-stack comparison](docs/KSTACK_COMPARISON.md) records the inspected upstream
revision, useful adaptations and Claude-specific behavior deliberately not imported.
