---
name: agentcontroller
description: Validate UI behavior using Kasempiternal's AgentController, an external tool integrated with Ultra Hook. Use for UI changes and application QA; ordinary code or CLI checks remain separate.
---

# AgentController integration and UI validation

AgentController is developed by **[Kasempiternal](https://github.com/Kasempiternal/agentcontroller)**.
This skill is Ultra Hook's integration guidance, not the controller application.
Use the [upstream downloads](https://github.com/Kasempiternal/agentcontroller/releases)
and [platform setup instructions](https://github.com/Kasempiternal/agentcontroller#installation).
Ultra Hook's [complete setup](https://github.com/jonmedev/Ultra_Hook/blob/main/docs/GETTING_STARTED.md#install-the-complete-setup)
can acquire the upstream controller when installation is requested. Check existing
registrations first and retain any reported platform or permission steps as pending.
When setup is missing, include those links and identify the target platform; do not
imply that installing this skill installed the application or that Ultra Hook owns it.

Use actual AgentController tools and results for UI validation. Do not present another
browser or desktop controller as an equivalent backend. Code tests can supplement
these checks, but a build, HTTP response or interaction success alone is not a UI pass.
For a change without a UI surface, validate its real interface and mark UI validation
not applicable with the reason.

## Discover and probe

Discover the connected AgentController MCP tools through the current tool catalog or
tool search. Read only the schemas needed for the target and flow. Tool names, selectors
and supported operations can differ across versions and operating systems; do not
assume an executable path, bridge, tray application or server connection.

Use the available readiness and capability tools, such as `check_permissions` and
`inspect_capabilities`, then confirm access to the actual target with a snapshot or
assertion. A capability declaration or installed executable is not proof of working
target access. On Windows, first read [platform boundaries](references/windows.md).

If the server is unavailable or cannot support the requested target, name the missing
capability and leave that UI check pending while completing independent authorized work.
Do not silently install a service, change configuration or substitute another controller.

## Exercise and verify

Take a compact snapshot, reuse its element identities and exercise the smallest flow
that demonstrates the changed behavior. Refresh identities after a meaningful UI
change. Use a supported batch operation such as `run_steps` when the sequence is known.
Do not let parallel workers control the same interactive session without coordination.

Check observable postconditions using supported assertions, for example visibility or
value checks. Treat tool errors, unsupported results and warnings as evidence to resolve,
not as successful interactions. For appearance or rendering changes, inspect a relevant
window screenshot as well; an accessibility element may exist without visible pixels.

Keep assertions, focused screenshots and useful flow details as task evidence. Avoid
repeated full trees, full-screen captures and schema dumps. Report the target, actions,
assertion outcomes, visual observations and any gaps. Distinguish connection/protocol
smoke tests from an exercised user flow.

## Interaction scope

Prefer supported background actions. Foreground input can change focus and requires
applicable authorization; do not enable it merely to bypass a failed background action.
Permission to validate one target does not extend to unrelated applications, clipboard
contents, messages, publication, purchases or destructive operations. Preserve only
the screenshots and target data needed for the authorized task.
