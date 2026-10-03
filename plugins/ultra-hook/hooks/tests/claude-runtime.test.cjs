"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { contextFor } = require("../model-routing.cjs");
const { runtime } = require("../hook-io.cjs");
const secrets = require("../protect-secrets.js");

// Commands below are data only. Each hook is spawned as Claude Code spawns it,
// with JSON on stdin; no sample command is sent to a shell.
const hooksDirectory = path.join(__dirname, "..");
const repository = path.resolve(hooksDirectory, "../../..");
function run(script, payload, flags = ["--runtime=claude"]) {
  const result = spawnSync(process.execPath, [path.join(hooksDirectory, script), ...flags], {
    input: JSON.stringify(payload), encoding: "utf8", timeout: 5000, shell: false, windowsHide: true,
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr, "");
  return JSON.parse(result.stdout || "{}");
}
const tool = (tool_name, tool_input) => ({ hook_event_name: "PreToolUse", tool_name, tool_input });

test("runtime defaults to Codex and needs the explicit Claude flag", () => {
  assert.equal(runtime(["node", "hook.cjs"]), "codex");
  assert.equal(runtime(["node", "hook.cjs", "--runtime=other"]), "codex");
  assert.equal(runtime(["node", "hook.cjs", "--runtime=claude"]), "claude");
});

test("Claude hook file runs the same scripts as the Codex file from the repository root", () => {
  const read = name => JSON.parse(fs.readFileSync(path.join(hooksDirectory, name), "utf8")).hooks;
  const scripts = (hooks, pattern) => Object.entries(hooks).flatMap(([event, groups]) =>
    groups.flatMap(group => group.hooks.map(handler => `${event}:${pattern.exec(handler.command)[1]}`))).sort();
  const claude = read("claude-hooks.json");
  assert.deepEqual(scripts(claude, /^node "\$\{CLAUDE_PLUGIN_ROOT\}\/plugins\/ultra-hook\/hooks\/([a-z-]+\.c?js)" --runtime=claude$/),
    scripts(read("hooks.json"), /^node "\$\{PLUGIN_ROOT\}\/hooks\/([a-z-]+\.c?js)"$/));
  const matchers = claude.PreToolUse.map(group => group.matcher);
  assert.ok(matchers.every(matcher => !/exec_command|spawn_agent|apply_patch/.test(matcher)), "Codex tool names");
  assert.ok(matchers.filter(matcher => /\bPowerShell\b/.test(matcher)).length === 2, "both safety hooks cover PowerShell");
  const manifest = JSON.parse(fs.readFileSync(path.join(repository, ".claude-plugin/plugin.json"), "utf8"));
  assert.equal(manifest.hooks, "./plugins/ultra-hook/hooks/claude-hooks.json");
  assert.ok(fs.existsSync(path.join(repository, manifest.skills, "ultra-hook/SKILL.md")));
  // A hooks/hooks.json at the Claude plugin root would be loaded automatically.
  assert.ok(!fs.existsSync(path.join(repository, "hooks")));
});

test("Claude advice names Claude primitives and no Codex ones", () => {
  const { modeText, capText } = require("../model-routing.cjs");
  const texts = [contextFor("SessionStart", "team", "claude"),
    modeText({ mode: "team", source: "explicit", cap: 6, changed: true }, "claude"),
    contextFor("UserPromptSubmit", "escalation", "claude"), contextFor("PreToolUse", "team", "claude"),
    capText({ mode: "fast", cap: 4, index: 5 }, "claude")];
  for (const text of texts) {
    const advice = text.replace(/: \S*teams-and-models\.md$/, "");
    assert.doesNotMatch(advice, /send_message|followup_task|fork_turns|gpt-|luna|astra|\bsol\b|max\/ultra|chosen leader/i);
  }
  for (const index of [1, 2, 3]) assert.match(texts[index], /SendMessage/);
  for (const index of [0, 2, 3]) assert.match(texts[index], /teams-and-models\.md$/);
  assert.match(texts[0], /session model/);
  assert.match(texts[4], /Approve to exceed the cap once/);
  assert.ok(texts[0].length < 900 && texts[1].length < 650 && texts[2].length < 1100 && texts[3].split("Full protocol")[0].length < 480);
  assert.match(texts[3], /haiku.*sonnet.*opus/);
  assert.match(texts[3], /only where the Agent tool lists them/);
  assert.equal(contextFor("unknown", "team", "claude"), "");
  assert.notEqual(texts[0], contextFor("SessionStart"));
});

test("lifecycle hooks emit Claude advice without decisions", () => {
  const start = run("session-start.cjs", { hook_event_name: "SessionStart", source: "startup" }).hookSpecificOutput;
  assert.equal(start.hookEventName, "SessionStart");
  assert.match(start.additionalContext, /session model/);
  for (const name of ["Agent", "Task"]) {
    const spawn = run("team-spawn.cjs", tool(name, { prompt: "synthetic" })).hookSpecificOutput;
    assert.match(spawn.additionalContext, /haiku/);
    assert.equal(spawn.permissionDecision, undefined);
    assert.equal(spawn.updatedInput, undefined);
  }
  assert.deepEqual(run("team-spawn.cjs", tool("Write", { file_path: "notes.md" })), {});
  const skill = run("prompt-routing.cjs", { hook_event_name: "UserPromptSubmit", prompt: "/ultra-hook:ultra-hook equipo revisa esto" });
  assert.match(skill.hookSpecificOutput.additionalContext, /mode: team \(set by the user/);
  assert.match(skill.hookSpecificOutput.additionalContext, /SendMessage/);
  const stronger = run("prompt-routing.cjs", { hook_event_name: "UserPromptSubmit", prompt: "Usa opus para esto" });
  assert.match(stronger.hookSpecificOutput.additionalContext, /strongest model the Agent tool lists/);
  assert.deepEqual(run("prompt-routing.cjs", { hook_event_name: "UserPromptSubmit", prompt: "No uses opus aqui" }), {});
  assert.deepEqual(run("prompt-routing.cjs", { hook_event_name: "UserPromptSubmit", prompt: "Corrige esta errata" }), {});
});

test("destructive Git asks the user in Claude Code and is denied in Codex", () => {
  const marker = "synthetic-private-payload";
  for (const command of [`git reset --hard; echo ${marker}`, "git clean -fd", `git push --force origin ${marker}`, "pwsh -Command 'git reset --hard'"]) {
    for (const name of ["Bash", "PowerShell"]) {
      const claude = run("sensitive-command-approval.cjs", tool(name, { command })).hookSpecificOutput;
      assert.equal(claude.permissionDecision, "ask", command);
      assert.ok(!claude.permissionDecisionReason.includes(marker));
      assert.equal(run("sensitive-command-approval.cjs", tool(name, { command }), []).hookSpecificOutput.permissionDecision, "deny");
    }
  }
  // Uninspectable input still fails closed rather than asking.
  assert.equal(run("sensitive-command-approval.cjs", tool("PowerShell", { command: "" })).hookSpecificOutput.permissionDecision, "deny");
  const reminder = run("sensitive-command-approval.cjs", tool("PowerShell", { command: "Remove-Item ./synthetic-temp.txt" })).hookSpecificOutput;
  assert.equal(reminder.permissionDecision, undefined);
  assert.match(reminder.additionalContext, /existing user authorization/);
  assert.deepEqual(run("sensitive-command-approval.cjs", tool("PowerShell", { command: "git status" })), {});
});

test("a Git clean dry run is not treated as destructive", () => {
  for (const command of ["git clean -n", "git clean -nfd", "git clean -fd --dry-run", "git clean -f -n"]) {
    assert.deepEqual(run("sensitive-command-approval.cjs", tool("Bash", { command })), {}, command);
    assert.deepEqual(run("sensitive-command-approval.cjs", tool("Bash", { command }), []), {}, command);
  }
  assert.equal(run("sensitive-command-approval.cjs", tool("Bash", { command: "git clean -fdx" })).hookSpecificOutput.permissionDecision, "ask");
});

test("secret checks cover Claude Code's PowerShell, NotebookEdit and Grep tools", () => {
  const denied = [
    tool("PowerShell", { command: String.raw`Get-Content -LiteralPath 'C:\project\.env'` }),
    tool("PowerShell", { command: "Get-ChildItem Env:" }),
    tool("NotebookEdit", { notebook_path: "C:/project/.env", new_source: "synthetic" }),
    tool("Grep", { pattern: "TOKEN", path: "C:/project/.env" }),
    tool("Grep", { pattern: "TOKEN", glob: "**/.env" }),
    tool("Grep", { pattern: "BEGIN", glob: "*.pem" }),
    tool("Read", { file_path: "C:/fixture-home/.claude/.credentials.json" }),
    tool("PowerShell", { command: "" }),
    tool("NotebookEdit", {}),
  ];
  for (const payload of denied) {
    assert.equal(run("protect-secrets.js", payload).hookSpecificOutput.permissionDecision, "deny", JSON.stringify(payload));
  }
  const allowed = [
    tool("PowerShell", { command: "Get-Content README.md" }),
    tool("NotebookEdit", { notebook_path: "analysis.ipynb", new_source: "synthetic" }),
    tool("Grep", { pattern: "auth.json" }),
    tool("Grep", { pattern: ".env", path: "docs", glob: "*.md" }),
    tool("Grep", { pattern: "x", glob: "**/.env.example" }),
    tool("Glob", { pattern: "**/.env" }),
  ];
  for (const payload of allowed) assert.deepEqual(run("protect-secrets.js", payload), {}, JSON.stringify(payload));
  assert.equal(secrets.check("Grep", { pattern: "x" }).blocked, false);
  assert.equal(secrets.checkFilePath(".claude/.credentials.json").blocked, true);
});
