# Native teams and model selection

## Start with a useful division of work

For each proposed worker, identify a distinct deliverable, its acceptance check and
the expected benefit after startup, context and integration costs. Use direct tools
for deterministic inventories and exact transformations when sufficient. Start with
the smallest useful team; concurrency limits are ceilings rather than staffing goals.

Give each worker the working directory, objective, constraints, owned files or area,
lead task path, dependencies, peer interfaces and required evidence. Agree on shared
interfaces before concurrent edits. Where file ownership cannot be separated, serialize
the work or use isolated checkouts and plan their integration.

The lead controls admission and can delegate a bounded specialist assignment and slot
allowance when authorized. Workers must not create uncoordinated recursive teams.
An agent assignment carries the task's existing permissions, not broader authority.

## Choose from the live catalog

Use the models and reasoning efforts exposed by the current collaboration tools.
Choose the newest supported version within the appropriate capability family, subject
to the user's explicit choice, spending or latency limits, and the task's needs.
Treat family labels as guidance only when the live catalog identifies those tiers:

| Work | Starting capability and effort |
| --- | --- |
| Mechanical work that warrants an agent | Lightweight tier, such as Luna; low or medium |
| Implementation, diagnosis, tests and focused review | Workhorse tier, such as Sol; medium or high |
| Difficult architecture or consequential uncertainty | Strong reasoning tier, such as Astra; high or xhigh |

Select the least costly adequate option using available capability and price information;
do not infer exact cost from a family name. Do not spawn merely to reach a nominally
cheaper model. A short continuation may be cheaper overall with an existing teammate.
Do not enable a faster service tier or surcharge automatically.

Never invent a model ID, select a hidden entry, or treat a local model cache as proof
of access. If the live catalog does not establish a suitable override, inherit the
leader where permitted and disclose the limitation. If a required explicit selection
is unavailable, report it instead of silently replacing it. Consult official model
documentation when capabilities change, rather than on every routine call.

Pass supported model and reasoning-effort overrides explicitly. In runtimes exposing
`fork_turns`, use `none` or a supported small positive count for overrides; `all`
inherits the leader and does not accept overrides. A fresh context needs a self-contained
assignment. Do not fork unrelated conversation simply to pass a few relevant facts.

## Continue the conversation

Use `send_message` during work for findings that affect another area, interface changes,
questions, blockers, disagreement and verified results. Include the locations, reasoning
and tests needed for a decision. There is no arbitrary line cap, and a final summary
does not replace timely discussion. Avoid empty status messages and repeated full logs.

The lead reads and responds, resolves dependencies and integrates the evidence.
`send_message` steers a running worker; `followup_task` reactivates an idle one with its
context intact. Reuse a suitable teammate rather than replacing it because a turn ended.
Workers may finish their current turn after sharing evidence. Do not keep an idle
worker running in a wait loop to simulate availability.

## Escalate on evidence, within actual authorization

Difficulty can justify more effort, a stronger model or an independent branch. It does
not establish permission for any of them. Follow the user's task authorization and
applicable instructions; an explicit model, effort, budget or no-delegation limit wins.
The presence of this skill is not universal consent to maximum-cost execution.

Choose the intervention that addresses the remaining question:

- For a coherent hard question, consider more supported reasoning effort.
- For a demonstrated capability gap, consider a stronger supported family.
- For independent hypotheses or checks, consider scoped parallel workers.
- For missing data, permission, credentials or services, resolve that blocker.

A difficult task may start at an appropriate high tier; do not exhaust a fixed ladder.
Use `max` or `ultra` only when supported, justified and within the actual authorization
and caps. Where the runtime documents ultra as maximum reasoning with subagent work,
require useful independent work and available capacity. It grants neither extra slots
nor permission for nested teams, and does not guarantee parallel execution.

A worker proposes escalation to the lead with evidence, attempted hypotheses, the
unresolved question, expected benefit and a completion check. The lead responds and
allocates capacity. A worker may act under previously delegated bounded authority
while keeping the lead informed. Ask the user only if
the proposed intervention requires a choice or authorization not already available.
Announce material escalation briefly with its reason and chosen model/effort or split.

`send_message` and `followup_task` do not change a worker's model or effort. For such a
change, create an explicitly configured specialist with the relevant evidence, rejected
hypotheses, pending changes and owned scope. Stop or finish the previous writer and
inspect pending changes before transferring edit ownership. Keep the original teammate
as a read-only contact if useful. Without capacity, the worker hands off and finishes
its turn so the lead can reallocate; it must not wait for an impossible child slot.

After a costly attempt, reassess its evidence. A further attempt needs a new hypothesis,
new evidence or a distinct unresolved risk and a meaningful check. Do not repeat an
unchanged maximum-effort request. Stop redundant branches when their question is answered.
Use normal role choices for subsequent ordinary work; do not pretend follow-up changes
an existing agent's settings. Report usage only when measured: turn limits, timeouts and
shorter prompts are not monetary caps or proof of billed-token savings.
