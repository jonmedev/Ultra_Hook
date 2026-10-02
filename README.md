# Ultra Hook

A Codex plugin for implementation, debugging, reviews and research. It helps Codex
choose a proportionate workflow, coordinate useful native teammates and verify the
result. Small tasks stay direct.

**[Quick start](docs/GETTING_STARTED.md)** · **[Releases](https://github.com/jonmedev/Ultra_Hook/releases)**

## Install with two commands

You need [Codex CLI](https://developers.openai.com/codex/cli/) installed and signed in,
[Node.js LTS](https://nodejs.org/en/download), and [Git](https://git-scm.com/downloads/).
Already using Ultra Hook or CAS? Read [update and migration instructions](docs/GETTING_STARTED.md#update-or-remove) first.

Open **PowerShell on Windows** or **Terminal on macOS/Linux** and run each line:

```sh
codex plugin marketplace add jonmedev/Ultra_Hook --ref v0.1.4
codex plugin add ultra-hook@ultra-hook
```

**Codex downloads and installs Ultra Hook.** No manual ZIP download, extraction,
repository checkout or Python installation is needed for this method.

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
| Validate an app's buttons, windows or user flows | Install AgentController separately, then use `$agentcontroller` |

The plugin includes **two skills** (instructions Codex can follow) and **five hooks**
(workflow reminders and checks for recognized sensitive operations). It preserves
your lead model and native permissions. Teammates discuss findings with the lead;
it does not force a team or maximum reasoning for every request.

Hook checks are heuristic and do not replace Codex's security settings. The plugin
does not unlock models, enforce a spending cap or claim measured savings.

## AgentController: optional for UI validation

**[AgentController is developed by Kasempiternal](https://github.com/Kasempiternal/agentcontroller).**
Ultra Hook provides the integration skill; the controller is a separate project.
**You do not need it to start coding, debugging or reviewing with Ultra Hook.**

**[Download AgentController from its official releases](https://github.com/Kasempiternal/agentcontroller/releases)**

- **macOS:** use the DMG published by its maintainer.
- **Windows/Linux:** follow the upstream [Windows guide](https://github.com/Kasempiternal/agentcontroller/blob/master/Windows/README.md)
  or [Linux guide](https://github.com/Kasempiternal/agentcontroller/blob/master/Linux/README.md).
  Release 2.5.0 has no Windows executable asset; its source ZIP is not an installer.

After installing it, follow [Connect AgentController to Codex](docs/GETTING_STARTED.md#optional-agentcontroller).
Installing our skill does not install or connect the controller. UI validation
requires assertions on the real target; discovering tools alone is not a UI pass.

## Updates, removal and alternative downloads

[Update or uninstall](docs/GETTING_STARTED.md#update-or-remove)
· [Troubleshooting](docs/GETTING_STARTED.md#if-something-is-missing)
· [Download ZIP 0.1.4](https://github.com/jonmedev/Ultra_Hook/releases/download/v0.1.4/ultra-hook-0.1.4.zip)
· [Advanced ZIP installation and diagnostics](docs/ADVANCED_INSTALL.md)

The ZIP is an alternative for script-managed installations. Do not combine both
installation methods on an existing registration.

[Security and download verification](SECURITY.md) · [K-stack comparison](docs/KSTACK_COMPARISON.md)
· [Credits](NOTICE) · [License](LICENSE)

This is an independent adaptation, not an official OpenAI, CAS or AgentController release.

<details>
<summary>Development and validation</summary>

```sh
python -B scripts/validate.py
python -B -m unittest discover -s tests
node --test plugins/ultra-hook/hooks/tests/team-routing.test.cjs plugins/ultra-hook/hooks/tests/safety-windows.test.cjs plugins/ultra-hook/hooks/tests/security-boundaries.test.cjs
python -B scripts/audit_release.py --git-staged --git-history --allow-github-noreply-identities
python -B scripts/build_release.py --output ../ultra-hook-release
```

See the [release procedure](docs/RELEASING.md). UI changes require separate
AgentController evidence; headless checks do not validate desktop behavior.

</details>
