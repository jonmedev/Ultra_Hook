# Ultra Hook

A plugin for Codex and Claude Code for implementation, debugging, reviews and
research. It helps the agent choose a proportionate workflow, coordinate useful
native teammates and verify the result. Small tasks stay direct. The sections below
describe Codex; [Claude Code](#claude-code) has its own short installation.

**[Quick start](docs/GETTING_STARTED.md)** · **[Releases](https://github.com/jonmedev/Ultra_Hook/releases)**

## Install Ultra Hook and AgentController together

**[Download the setup ZIP](https://github.com/jonmedev/Ultra_Hook/releases/download/v0.2.0/ultra-hook-0.2.0.zip)**

1. Extract it into a folder you will keep.
2. **Windows:** double-click `Install.cmd`. **macOS/Linux:** open Terminal in that
   folder and run `sh install.sh`.
3. Follow the result shown by the installer, then activate the hooks below.

The launcher installs Ultra Hook, downloads AgentController from Kasempiternal's
project and prepares the platform backend. On Windows it builds and registers the
stdio executable; on Linux it prepares and registers an isolated Python launcher.
On macOS it downloads and verifies the official DMG; installing the app and granting
desktop permissions remain explicit user steps. A pending step is reported as pending.
The official macOS app requires Apple Silicon and macOS 14 or newer; this DMG does
not support Intel Macs.

One-time prerequisites: signed-in [Codex CLI](https://developers.openai.com/codex/cli/),
[Node.js LTS](https://nodejs.org/en/download), [Python 3.11+](https://www.python.org/downloads/)
and [Git](https://git-scm.com/downloads/). Windows also needs the
[.NET 9 SDK](https://dotnet.microsoft.com/en-us/download/dotnet/9.0) to build the
upstream backend; there is no official Windows binary download. The installer
checks prerequisites before downloading and does not silently install system tools.

Already using Ultra Hook or CAS? Read [update and migration instructions](docs/GETTING_STARTED.md#update-or-remove) first.

### Only need the Codex plugin?

For code/research work without desktop UI testing, use the smaller native install.
It needs Codex CLI, Node.js and Git:

Open **PowerShell on Windows** or **Terminal on macOS/Linux** and run each line:

```sh
codex plugin marketplace add jonmedev/Ultra_Hook --ref v0.2.0
codex plugin add ultra-hook@ultra-hook
```

These two commands install only the plugin. To add automatic controller setup later,
follow the [controller setup guide](docs/GETTING_STARTED.md#optional-agentcontroller).

## Activate and start

1. Open Codex and enter `/hooks`. Review and approve the five Ultra Hook hooks:
   small checks and reminders that support the workflow.
2. Start a new Codex conversation.
3. Send your task, for example:

```text
$ultra-hook Reproduce the failing CSV import, fix its cause and verify the
original input. Use teammates only when independent work would help.
```

If the short name is unavailable, use `$ultra-hook:ultra-hook`. Check installation
with `codex plugin list --marketplace ultra-hook` in your terminal. The plugin
should be enabled and its five hooks approved in `/hooks`.

## What you get

| Your task | How to use it |
| --- | --- |
| Implement or debug | `$ultra-hook` followed by the behavior you want and how to check it |
| Review code | Add the review scope and `read-only; do not edit` if you only want findings |
| Research a decision | Describe the question, constraints and evidence you need |
| Work without extra agents | Add `without subagents` |
| Validate an app's buttons, windows or user flows | Complete AgentController setup above, then use `$agentcontroller` |

The plugin includes **two skills** (instructions Codex can follow) and **five hooks**
(workflow reminders and checks for recognized sensitive operations). It preserves
your lead model and native permissions. Teammates discuss findings with the lead;
it does not force a team or maximum reasoning for every request.

Hook checks are heuristic and do not replace Codex's security settings. The plugin
does not unlock models, enforce a spending cap or claim measured savings.

## Claude Code

The same two skills and five hook scripts run in Claude Code from this repository's
`.claude-plugin` manifests. It needs Claude Code and Node.js; the Python installer,
doctor and `/hooks` trust review above are Codex-only. In a terminal:

```sh
claude plugin marketplace add jonmedev/Ultra_Hook
claude plugin install ultra-hook@ultra-hook
```

Start a new session and invoke `/ultra-hook:ultra-hook` followed by your task.
Differences from Codex:

- Routing hints name the `Agent` tool's model aliases and `SendMessage`; no model
  cache is read and reasoning effort comes from the agent definition.
- Hard resets, forced cleaning and history-replacing pushes ask for your
  confirmation instead of being denied. Recognized secret access is still denied.
- Secret and Git checks also cover the `PowerShell`, `NotebookEdit` and `Grep` tools.
- AgentController is registered separately for each runtime, for example
  `claude mcp add --scope user agentcontroller -- <launcher>` with the launcher the
  complete setup prepared. A Codex registration is not visible to Claude Code.

Remove it with `claude plugin uninstall ultra-hook@ultra-hook`.

## AgentController: optional for UI validation

**[AgentController is developed by Kasempiternal](https://github.com/Kasempiternal/agentcontroller).**
Ultra Hook provides the integration skill; the controller is a separate project.
**You do not need it to start coding, debugging or reviewing with Ultra Hook.**

**[Download AgentController from its official releases](https://github.com/Kasempiternal/agentcontroller/releases)**

- **macOS:** use the DMG published by its maintainer.
- **Windows/Linux:** follow the upstream [Windows guide](https://github.com/Kasempiternal/agentcontroller/blob/master/Windows/README.md)
  or [Linux guide](https://github.com/Kasempiternal/agentcontroller/blob/master/Linux/README.md).
  Release 2.5.0 has no Windows executable asset; its source ZIP is not an installer.

The complete setup above downloads it for you; the native plugin-only route does
not. See [platform setup details](docs/GETTING_STARTED.md#optional-agentcontroller).
UI validation
requires assertions on the real target; discovering tools alone is not a UI pass.

## Updates, removal and alternative downloads

[Update or uninstall](docs/GETTING_STARTED.md#update-or-remove)
· [Troubleshooting](docs/GETTING_STARTED.md#if-something-is-missing)
· [Download setup ZIP](https://github.com/jonmedev/Ultra_Hook/releases/download/v0.2.0/ultra-hook-0.2.0.zip)
· [Advanced ZIP installation and diagnostics](docs/ADVANCED_INSTALL.md)

The ZIP launchers use script-managed installation with receipts and backups.
Do not combine installation methods on an existing registration.

[Security and download verification](SECURITY.md) · [K-stack comparison](docs/KSTACK_COMPARISON.md)
· [Credits](NOTICE) · [License](LICENSE)

This is an independent adaptation, not an official OpenAI, CAS or AgentController release.

<details>
<summary>Development and validation</summary>

```sh
python -B scripts/validate.py
python -B -m unittest discover -s tests
node --test plugins/ultra-hook/hooks/tests/team-routing.test.cjs plugins/ultra-hook/hooks/tests/safety-windows.test.cjs plugins/ultra-hook/hooks/tests/security-boundaries.test.cjs plugins/ultra-hook/hooks/tests/claude-runtime.test.cjs
python -B scripts/audit_release.py --git-staged --git-history --allow-github-noreply-identities
python -B scripts/build_release.py --output ../ultra-hook-release
```

See the [release procedure](docs/RELEASING.md). UI changes require separate
AgentController evidence; headless checks do not validate desktop behavior.

</details>
