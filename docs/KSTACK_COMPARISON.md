# K-stack comparison and adaptation

Reviewed 2026-10-02 against K-stack commit
[`243d27b`](https://github.com/Kasempiternal/K-stack/tree/243d27be93d76e946218cf5196ac492be769ac35).
This records inspected design choices, not a benchmark or an upstream endorsement.

The current entrypoint is `k-mode`, configured by `k-setup`. The inspected tree has
no `/suri` skill. K-stack targets Claude Code; copying its commands, agent aliases
or effort rules would not establish equivalent Codex behavior.

| Area | Inspected K-stack behavior | Ultra Hook decision |
| --- | --- | --- |
| First use | Short installation sequence, setup then mode | Document preview, installation, native hook approval, doctor and first task separately |
| Configuration | Setup writes a global routing block and checks tier agents | Preserve the user's profile and leader; use live native model/effort options and task constraints |
| Task guides | Separate playbooks for bugs, features, research, refactors and resumption | Add a compact task/evidence table and focused engineering guidance; load references only as needed |
| Delegation | Roles resolve to fixed Claude tier agents; lead mainly briefs/reviews | Native Codex workers for useful independent work; lead may implement and integrate directly |
| Follow-up | Rework brief goes to a fresh worker | Continue with a suitable existing teammate; transfer ownership when model/effort changes |
| Review | Panels vary with risk; several lenses for consequential changes | Review actual uncertainty; no compulsory panel or reviewer agreement as proof |
| Validation | Verification follows the affected surface; UI transports vary by platform | Real CLI/API/library checks; AgentController required for UI, unavailable target reported pending |
| Spending | Named presets and explicit high-spend mode | Task-selected modes with a per-prompt agent cap, least adequate role/effort and evidence-based escalation; agent counts are recorded, token savings are not claimed |
| Safety hooks | Claude hook protocol includes approval requests | Keep supported Codex decisions and regression tests; use `ask` only when the hook runs in Claude Code |
| Resumption | Playbook rebuilds state from repo and session artifacts | Compare scoped handoff to current diff and evidence; avoid collecting private transcripts |

The useful additions are a clearer path from installation to first task, explicit
completion evidence and guidance for common engineering decisions. Ultra Hook keeps
two public skills and the existing hook set. It does not import Claude-only aliases,
model benchmark assumptions, macOS process-killing hooks or notification scripts.

Primary material inspected:

- [README and installation](https://github.com/Kasempiternal/K-stack/blob/243d27be93d76e946218cf5196ac492be769ac35/README.md)
- [Setup skill](https://github.com/Kasempiternal/K-stack/blob/243d27be93d76e946218cf5196ac492be769ac35/kstack/skills/k-setup/SKILL.md)
- [Mode and playbook index](https://github.com/Kasempiternal/K-stack/blob/243d27be93d76e946218cf5196ac492be769ac35/kstack/skills/k-mode/SKILL.md)
- [Design skill](https://github.com/Kasempiternal/K-stack/blob/243d27be93d76e946218cf5196ac492be769ac35/kstack/skills/k-design/SKILL.md)
- [Review skill](https://github.com/Kasempiternal/K-stack/blob/243d27be93d76e946218cf5196ac492be769ac35/kstack/skills/k-review/SKILL.md)
- [Platform setup](https://github.com/Kasempiternal/K-stack/blob/243d27be93d76e946218cf5196ac492be769ac35/docs/claude-setup.md)

The wording and workflow here are independently adapted for Codex. Attribution is
retained in [NOTICE](../NOTICE). Validation establishes exercised behavior only;
comparison with vanilla Codex still requires controlled quality, usage and latency
measurements on equivalent tasks.
