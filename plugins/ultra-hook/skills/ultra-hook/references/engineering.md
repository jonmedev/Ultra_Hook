# Engineering decisions

Read the section relevant to the requested work. These are decision aids, not a
required sequence or a reason to appoint additional agents.

## Architecture and implementation

Settle the contract that other work depends on: observable behavior, ownership of
mutable data, error handling and the interfaces between components. When two designs
have a consequential unknown, identify the smallest experiment that can distinguish
them. Split implementation after its boundaries are clear. A lead can perform design,
editing and integration directly; crossing files does not itself require an architect.

## Diagnosis

Tie a proposed fix to an observed failure and a falsifiable explanation. Use a relevant
reproduction, history or targeted instrumentation to narrow the cause. A failed attempt
should change the hypothesis or expose a missing prerequisite before another attempt.
Check the original failing behavior after the fix, then the regressions implicated by
the change. If the original environment cannot be exercised, state what remains unverified.

## Review and security

Select review areas from the actual diff and risk. A useful finding identifies a
location, triggering condition, consequence and supporting evidence. Discuss uncertain
findings with the implementer and lead; reviewer agreement is not a correctness test.
Independent review is valuable for consequential uncertainty, not as a fixed reviewer
count. A review request does not authorize unrelated refactoring or publishing changes.

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
