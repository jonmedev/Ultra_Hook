# External specialist

An optional worker on another provider's model, reached through the
[Command Code](https://commandcode.ai) CLI when the user has it installed and signed
in. It is a text-in, text-out helper, not a teammate: it sees one brief, has no
tools, keeps no context and cannot be continued.

## When it fits

Use it for mechanical or textual work that a self-contained brief fully describes:
rewriting or translating supplied text, drafting boilerplate from a stated contract,
summarizing an excerpt, proposing names or test cases from a pasted signature.
Do not use it for anything that needs the repository, tools, verification, UI
access or judgement about the user's project. Use a native agent for those.

It takes a slot of the mode's agent cap like any native agent. A call costs the
CLI's own system prompt on every request, so batching several small questions into
one brief is cheaper than several calls.

## What leaves the machine

Only what you write in the brief is task content. Before writing it, remove
credentials, personal data, customer data, private file paths and any repository
text the user has not cleared for an external provider. When in doubt, ask the user
or use a native agent instead. Availability of the CLI grants no authority to share.

The runner sends the brief from a new empty directory with one model turn, a minimal
environment and no skills or saved session. The CLI still adds, on its own: its
system prompt, that temporary directory's path, the operating system, the date and
the user's global Command Code taste profile when one exists. The runner's output
states this under `sent` for every call.

## How to call it

Write the brief to a file, then run the runner that ships in this plugin's `hooks`
directory, two levels above this skill's directory:

```sh
node <plugin hooks directory>/external-specialist.cjs --brief-file <brief file>
```

Optional: `--model <id>` for a model the CLI lists, `--effort low|medium|high`,
`--timeout <seconds>`. `--check` reports availability without sending anything.
The output is JSON with `status`, `model`, `text`, `usage` and `sent`.

Do not call `commandcode`, `command-code` or `cmdc` directly. A direct call attaches
the working directory listing, Git state and project instruction files, and can read
files; the shell hook stops it.

## Using the answer

Treat the answer as an unverified draft from a model that saw none of the project.
Check it against the code or the acceptance check before it enters a change, and
never let it decide permissions, publication or what to share. If the runner
reports that the specialist tried to use a tool, the brief was not self-contained:
add the missing material or give the work to a native agent.
