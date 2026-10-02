# Migrating to Ultra Hook v0.1

Ultra Hook consolidates the earlier CAS workflow collection into two public skills:

- **ultra-hook** chooses a proportionate engineering or research workflow and coordinates
  native Codex teammates when authorized and useful.
- **agentcontroller** is our integration skill for application and web UI validation
  with [AgentController by Kasempiternal](https://github.com/Kasempiternal/agentcontroller).
  Install the external application from its [upstream downloads/setup](https://github.com/Kasempiternal/agentcontroller/releases).

Use the installation instructions in the [project README](../README.md). This release
does not rewrite existing personal instructions, select a new leader model, migrate
credentials or remove another plugin. Review any older orchestration instructions
before using both systems together; contradictory global policies are not reconciled
by installing a skill.

For an existing CAS installation, use the [script-managed migration](ADVANCED_INSTALL.md#3-preview-and-install)
with `--replace-cas`. The quick native installation does not disable CAS or create
a migration receipt; do not leave both orchestration plugins active together.

## Workflow mapping

The old names are migration guidance, not commands or aliases distributed in v0.1.

| Earlier entrypoints | Public replacement |
| --- | --- |
| systemcc, zk | ultra-hook; direct execution for small tasks |
| hydra, pcc, pcc-opus, faster | ultra-hook native coordination for independent work |
| legion, orchestrate, siege | ultra-hook bounded iterations and continuing teammate dialogue |
| gpt-architect | ultra-hook architecture and specialist handoff through native collaboration |
| review, cyberconan | ultra-hook scoped code or security review with evidence |
| spectre, l30 | ultra-hook research with source and date requirements |
| gonk-test, cccontrol, agentcontroller | agentcontroller for required UI validation |
| setup-hooks, setup-swarm | Installation/runtime checks described by this release; no setup skill alias |
| phoenix | No replacement; OS reboot and session restoration are outside this release |
| commandcode | Not distributed in v0.1 |

## Preserved behavior

Teammates discuss findings, questions, interface changes and disagreements with the
lead during work. Suitable idle workers resume through native follow-up tools. The
lead can inspect, edit and verify directly and remains responsible for integration.
There is no final-summary-only contract or requirement to keep workers in wait loops.

Model selection uses the live collaboration catalog and the least costly adequate
capability tier. Newer supported versions within a role's family are preferred subject
to explicit choices and constraints. No private model catalog, local cache, hidden model
ID or personal filesystem path is required.

Escalation follows evidence and actual authorization. Higher effort, a stronger model
or an independent branch can address a difficult question; none creates missing access
or permission. Maximum effort and ultra are options only when supported and justified
within the user's scope and caps. A new specialist receives an explicit handoff when
model or effort must change, and file ownership transfers after the previous writer stops.

AgentController remains the required UI validation backend. Missing transport or an
unsupported target leaves UI validation pending. Other test tools can provide additional
evidence but do not silently replace that backend. Non-UI tasks use their actual code,
API, CLI or document checks.

## Deliberately omitted

The release does not carry forward banners, prompt-optimization ceremonies, fixed team
sizes, mandatory triple reviews, forced model aliases, backend locks or write-count
limits. Historical helper scripts, templates and local session state are not bundled.

Command Code and external DeepSeek specialist runners are excluded until their context
isolation and process behavior can be verified portably. A public integration must
establish which prompts, local context, settings and metadata can reach an external
provider, preserve execution boundaries, and report usage honestly. A text-only tool
filter, timeout or turn limit alone is not proof of isolation or a hard spending cap.
This omission does not prevent a separate, explicitly authorized integration with its
own reviewed configuration and data-sharing boundaries.

Hook checks and routing instructions complement the native runtime. They are not a
complete security boundary, an automatic difficulty detector or an enforced budget.
Validation results establish only the behavior actually exercised, not universal
quality or cost improvements over an unmodified Codex session.
