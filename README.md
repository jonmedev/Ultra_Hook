# Ultra Hook

Native Codex teamwork with proportionate model selection, continuing teammate
conversations and AgentController-based UI validation. Small tasks stay direct.

This is a portable plugin with two skills and five compact lifecycle hooks. It
preserves your chosen leader, model settings and native permissions. It has no
mandatory team size, prompt-rewriting ceremony, background agent loop or automatic
maximum-effort setting. It does not unlock models, enforce a monetary cap or claim
measured superiority over vanilla Codex.

## Install

Requires Python 3.11+, Node.js 18+ and a Codex CLI with plugin and app-server support.
Install and sign in to Codex separately. No API keys belong in this repository.

Download and extract the source ZIP, or clone this repository. From its root:

```sh
python -B scripts/install.py --dry-run
python -B scripts/install.py
python -B scripts/doctor.py --json
```

The installer uses Codex's supported marketplace/plugin commands. It does not
replace your model, effort, permissions, global instructions or unrelated plugins.
Keep the checkout/extracted directory if using a local marketplace; it is the source
used for refreshes. Backups and installation state stay under your own Codex home.

Review the five hook definitions and their source, then open `/hooks` in Codex to
trust them. Installation is not hook approval: the doctor reports pending trust,
and no script writes trusted hashes or bypasses the native review. Start a new
session to refresh the skills and tool catalog.

For an existing CAS installation, `--replace-cas` requests a reversible migration.
CAS is disabled only after the replacement skills and trusted hooks are verified.
If review is still pending, finish `/hooks` and rerun the installer with that flag.
See [migration](docs/MIGRATION.md) for the consolidated workflows.

## Set up AgentController for UI work

The plugin requires actual AgentController evidence when validating UI/app flows.
Installation of the skills does not install a desktop controller or grant app access.

If you already have a working executable, register it while installing:

```sh
python -B scripts/install.py --agentcontroller-command /absolute/path/to/agentcontroller
```

On Windows, the optional source builder requires Git and the .NET 9 SDK:

```sh
python -B scripts/setup_agentcontroller.py --build-windows --destination ./local-agentcontroller
```

Choose a destination outside this repository when preparing a contribution or a
release. Register the resulting executable with `--agentcontroller-command`.
The builder pins the upstream source revision and preserves dependency licenses;
the release archive contains no machine-specific controller binary.

For other platforms, install the appropriate upstream
[AgentController backend](https://github.com/Kasempiternal/agentcontroller) and verify
its actual target capabilities. The Windows backend supports UI Automation but has
unsupported operations and target-specific limits; see the
[platform guidance](plugins/ultra-hook/skills/agentcontroller/references/windows.md).
Tool discovery alone is not a successful UI test. Use assertions and relevant
screenshots on the actual target; if it is unreachable, report UI validation pending.
For changes without a UI, test the real CLI/API/library instead.

## Use

- Invoke `$ultra-hook` for a substantial implementation, architecture, review or
  research task. Normal skill discovery can also select it for a matching request.
- Invoke `$agentcontroller` for UI validation. Check the actual qualified names in
  your Codex skill catalog if another plugin defines the same short name.
- Give workers bounded ownership and acceptance criteria. They discuss discoveries
  with the lead and can resume their existing context for corrections.
- Model choices come from the live collaboration catalog. Deeper reasoning or a
  stronger specialist requires evidence and must fit your authorization and caps.

The hooks supply event-specific reminders and literal checks for sensitive file or
shell operations. They are heuristics, not a sandbox or complete command interpreter.
There is no telemetry or network request in the hook code. Secret checks record only
classification IDs, tool names and timestamps locally, without command text or file
contents. Native permission settings remain authoritative.

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
node --test plugins/ultra-hook/hooks/tests/team-routing.test.cjs plugins/ultra-hook/hooks/tests/safety-windows.test.cjs
python -B scripts/audit_release.py --git-staged --git-history --allow-github-noreply-identities
python -B scripts/build_release.py --output ../ultra-hook-release
```

The audit rejects common credential patterns, personal paths/identifiers and local
artifacts without echoing matched values. Packaging copies only reviewed source
directories into a fresh staging tree, audits that tree and emits a deterministic
ZIP plus SHA-256 checksum. Review findings before publishing; pattern scans cannot
prove the absence of every possible private value. Use a deliberate public GitHub
noreply identity for release commits, never a private email address.

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
