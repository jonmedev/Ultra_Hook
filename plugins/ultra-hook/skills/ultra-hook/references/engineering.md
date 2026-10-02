# Engineering decisions

Read the section relevant to the requested work. These are decision aids, not a
required sequence or a reason to appoint additional agents.

## Architecture and implementation

Settle the contract that other work depends on: observable behavior, ownership of
mutable data, error handling and the interfaces between components. When two designs
have a consequential unknown, identify the smallest experiment that can distinguish
them. Split implementation after its boundaries are clear. A lead can perform design,
editing and integration directly; crossing files does not itself require an architect.

For a feature, settle the success path and an important failure path before splitting
work. Identify callers, compatibility constraints and the shared interface. A compact
plan is enough when those choices are clear; produce a separate design artifact only
when it helps implementation or review. For a refactor, name what must remain
observable before changing structure and avoid mixing unrelated behavior changes.

## Diagnosis

Tie a proposed fix to an observed failure and a falsifiable explanation. Use a relevant
reproduction, history or targeted instrumentation to narrow the cause. A failed attempt
should change the hypothesis or expose a missing prerequisite before another attempt.
Check the original failing behavior after the fix, then the regressions implicated by
the change. If the original environment cannot be exercised, state what remains unverified.

Start an unfamiliar regression with the relevant callers, recent changes and observed
inputs. Use instrumentation or a synthetic reproduction when appropriate, labeling
the latter as such. Stop repeating a failed premise: identify what the result ruled
out before choosing the next probe. Preserve the original acceptance condition.

## Review and security

Select review areas from the actual diff and risk. A useful finding identifies a
location, triggering condition, consequence and supporting evidence. Discuss uncertain
findings with the implementer and lead; reviewer agreement is not a correctness test.
Independent review is valuable for consequential uncertainty, not as a fixed reviewer
count. A review request does not authorize unrelated refactoring or publishing changes.

Prioritize findings by demonstrated impact. Verify consequential claims against the
code or a reproduction before acting; group related fixes and give the existing
implementer the evidence. Disagreement can expose a missing assumption. Reviewer
agreement or a reported model name is not independent proof of correctness.

For an authorized security review, establish which code, dependencies and configuration
are in scope. Report confirmed exposure with minimal evidence and avoid copying secrets
into outputs. Distinguish a potential weakness from a demonstrated exploit; do not run
intrusive probes or acquire additional access merely to strengthen a finding.

## Optimization and workflow comparisons

Define the workload, baseline, measurement unit and correctness condition before
optimizing. Compare under equivalent conditions and repeat measurements when noise can
change the decision. Revert only the task's own unsuccessful changes while preserving
concurrent work. An unchanged result calls for a different explanation or stopping,
not weaker acceptance criteria.

For agent-routing comparisons, count leader and worker usage together and distinguish
tool overhead from task quality and elapsed time. Different providers' credits and
API prices are not interchangeable units. Hook tests or a successful build do not
demonstrate superiority over the unmodified runtime.

## Validate the affected surface

Use relevant code, API or CLI checks for non-UI changes. For UI behavior and visual
changes, use the [AgentController skill](../../agentcontroller/SKILL.md); ordinary
tests provide additional evidence but cannot replace its required UI checks.
Report unsupported targets or missing transport as pending UI validation. Do not
create an unrelated GUI exercise for a task without a UI surface.
