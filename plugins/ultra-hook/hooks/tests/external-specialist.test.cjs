"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { externalCall } = require("../sensitive-command-approval.cjs");

// No case contacts a provider. The runner is pointed at a fake CLI that records
// what it was given, and the hook only inspects command text.
const hooksDirectory = path.join(__dirname, "..");
const runner = path.join(hooksDirectory, "external-specialist.cjs");
function workspace() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ultra-external-test-"));
  return { directory, cleanup() {
    const resolved = path.resolve(directory);
    assert.equal(path.dirname(resolved), path.resolve(os.tmpdir()));
    assert.ok(path.basename(resolved).startsWith("ultra-external-test-"));
    fs.rmSync(resolved, { recursive: true, force: true });
  } };
}
// The fake prints one NDJSON result describing its own invocation.
function fakeCli(directory, behavior = "answer") {
  const file = path.join(directory, "fake-cli.cjs");
  fs.writeFileSync(file, `
const fs = require("node:fs");
const seen = { args: process.argv.slice(2), cwd: process.cwd(), listing: fs.readdirSync(process.cwd()), env: Object.keys(process.env).sort() };
fs.writeFileSync(${JSON.stringify(path.join(directory, "seen.json"))}, JSON.stringify(seen));
const behavior = ${JSON.stringify(behavior)};
if (behavior === "silent") process.exit(0);
console.log("startup banner that is not JSON");
console.log(JSON.stringify({ type: "event", event: { type: "model_request_start", model: "synthetic/model" } }));
if (behavior === "tool") { console.log(JSON.stringify({ type: "result", subtype: "max_turns", stopReason: "max_turns" })); process.exit(8); }
console.log(JSON.stringify({ type: "result", subtype: "success", stopReason: "end_turn", finalText: "synthetic answer", usage: { inputTokens: 5, outputTokens: 2 } }));
`);
  return file;
}
function run(args, extraEnv = {}) {
  const result = spawnSync(process.execPath, [runner, ...args], { encoding: "utf8", timeout: 20000, shell: false, windowsHide: true,
    env: { ...process.env, SYNTHETIC_PRIVATE_VARIABLE: "synthetic-private-payload", ...extraEnv } });
  assert.equal(result.stderr, "");
  return { code: result.status, output: JSON.parse(result.stdout) };
}

test("the runner sends one brief from an empty directory with a minimal environment", () => {
  const space = workspace();
  try {
    const brief = path.join(space.directory, "brief.txt");
    fs.writeFileSync(brief, "Summarize: synthetic text.\n");
    const { code, output } = run(["--brief-file", brief, "--cli", fakeCli(space.directory), "--model", "synthetic/model", "--effort", "low"]);
    assert.equal(code, 0);
    assert.deepEqual([output.status, output.model, output.text], ["answered", "synthetic/model", "synthetic answer"]);
    assert.deepEqual(output.usage, { inputTokens: 5, outputTokens: 2 });
    assert.equal(output.sent.repositoryFiles, false);
    assert.equal(output.sent.environmentVariables, false);
    assert.equal(output.sent.briefBytes, Buffer.byteLength("Summarize: synthetic text."));
    const seen = JSON.parse(fs.readFileSync(path.join(space.directory, "seen.json"), "utf8"));
    assert.deepEqual(seen.listing, []);
    assert.equal(path.dirname(seen.cwd), fs.realpathSync(os.tmpdir()));
    assert.ok(!fs.existsSync(seen.cwd), "temporary directory removed");
    assert.equal(seen.args[0], "-p");
    assert.match(seen.args[1], /^Answer from the brief below alone.*Do not call any tool[\s\S]*Summarize: synthetic text\.$/);
    for (const flag of ["--no-session", "--no-skills", "--skip-onboarding", "--no-auto-update"]) assert.ok(seen.args.includes(flag), flag);
    assert.equal(seen.args[seen.args.indexOf("--max-turns") + 1], "1");
    assert.equal(seen.args[seen.args.indexOf("--model") + 1], "synthetic/model");
    assert.ok(!seen.env.includes("SYNTHETIC_PRIVATE_VARIABLE"));
    assert.ok(seen.env.includes("COMMANDCODE_SKIP_UPDATES"));
    for (const flag of ["--yolo", "--tools-all", "--add-dir", "--accept-edits"]) assert.ok(!seen.args.includes(flag), flag);
  } finally { space.cleanup(); }
});

test("the runner refuses bad briefs before starting the CLI and withholds failures", () => {
  const space = workspace();
  try {
    const cli = fakeCli(space.directory);
    const write = (name, content) => { const file = path.join(space.directory, name); fs.writeFileSync(file, content); return file; };
    const refused = [
      [["--cli", cli], /brief file is required/],
      [["--brief-file", write("empty.txt", "  \n"), "--cli", cli], /brief is empty/],
      [["--brief-file", write("large.txt", "x".repeat(21 * 1024)), "--cli", cli], /at most/],
      [["--brief-file", write("key.txt", "use -----BEGIN OPENSSH PRIVATE " + "KEY----- here"), "--cli", cli], /credential-shaped/],
      [["--brief-file", write("token.txt", "token gh" + "p_" + "a".repeat(24)), "--cli", cli], /credential-shaped/],
      [["--brief-file", write("ok.txt", "fine"), "--cli", cli, "--effort", "max"], /Effort must be/],
      [["--brief-file", write("ok2.txt", "fine"), "--cli", cli, "--model", "bad model; rm"], /Invalid model/],
      [["--brief-file", write("ok3.txt", "fine"), "--cli", cli, "--yolo", "1"], /Usage/],
    ];
    for (const [args, message] of refused) {
      const { code, output } = run(args);
      assert.equal(code, 1);
      assert.equal(output.status, "error");
      assert.match(output.message, message);
      assert.ok(!fs.existsSync(path.join(space.directory, "seen.json")), "CLI not started: " + message);
    }
    const ok = write("ok4.txt", "synthetic-private-payload question");
    const tool = run(["--brief-file", ok, "--cli", fakeCli(space.directory, "tool")]);
    assert.match(tool.output.message, /tried to use a tool/);
    const silent = run(["--brief-file", ok, "--cli", fakeCli(space.directory, "silent")]);
    assert.match(silent.output.message, /returned no result/);
    const missing = run(["--brief-file", ok, "--cli", path.join(space.directory, "absent-cli")]);
    assert.equal(missing.output.status, "error");
    for (const result of [tool, silent, missing]) assert.ok(!JSON.stringify(result.output).includes("synthetic-private-payload"));
    assert.equal(run(["--check", "--cli", cli]).output.status, "available");
  } finally { space.cleanup(); }
});

test("the shell hook tells the bounded runner from a direct CLI call", () => {
  for (const command of ["commandcode -p 'summarize this repo'", "command-code \"fix the bug\"", "cmdc -p x --yolo",
    "npx command-code -p x", String.raw`C:\tools\npm\commandcode.cmd -p x`, "cd repo && commandcode -p x", "bash -c 'cmdc -p x'"]) {
    assert.equal(externalCall(command), "raw", command);
  }
  for (const command of ["node hooks/external-specialist.cjs --brief-file brief.txt",
    String.raw`node "C:\plugin root\hooks\external-specialist.cjs" --brief-file b.txt --effort low`]) {
    assert.equal(externalCall(command), "runner", command);
  }
  for (const command of ["commandcode --version", "cmdc status", "command-code --list-models", "node hooks/external-specialist.cjs --check",
    "cmd /c dir", "echo commandcode", "node other.cjs", "git status"]) {
    assert.equal(externalCall(command), null, command);
  }
});

test("a runner call takes a slot of the prompt's cap; a direct call is stopped", () => {
  const space = workspace();
  try {
    const hook = (script, payload, flags = []) => {
      const env = { ...process.env, PLUGIN_DATA: space.directory };
      delete env.CLAUDE_PLUGIN_DATA;
      const result = spawnSync(process.execPath, [path.join(hooksDirectory, script), ...flags], { input: JSON.stringify(payload), encoding: "utf8", env, windowsHide: true });
      assert.equal(result.status, 0, result.stderr);
      return JSON.parse(result.stdout || "{}").hookSpecificOutput || {};
    };
    const bash = command => ({ hook_event_name: "PreToolUse", tool_name: "Bash", tool_input: { command }, session_id: "synthetic-session" });
    const runnerCall = bash("node hooks/external-specialist.cjs --brief-file brief.txt");
    hook("prompt-routing.cjs", { hook_event_name: "UserPromptSubmit", prompt: "modo equipo 2", session_id: "synthetic-session" });
    const first = hook("sensitive-command-approval.cjs", runnerCall);
    assert.equal(first.permissionDecision, undefined);
    assert.match(first.additionalContext, /external specialist 1\/2 \(team\).*only the brief file/);
    // Native agents and external specialists share the same count.
    assert.match(hook("team-spawn.cjs", { hook_event_name: "PreToolUse", tool_name: "Agent", session_id: "synthetic-session" }).additionalContext, /spawn 2\/2/);
    assert.equal(hook("sensitive-command-approval.cjs", runnerCall).permissionDecision, "deny");
    assert.equal(hook("sensitive-command-approval.cjs", runnerCall, ["--runtime=claude"]).permissionDecision, "ask");
    const marker = "synthetic-private-payload";
    const raw = bash(`commandcode -p "${marker}"`);
    const codex = hook("sensitive-command-approval.cjs", raw);
    assert.equal(codex.permissionDecision, "deny");
    assert.match(codex.permissionDecisionReason, /external-specialist runner/);
    const claude = hook("sensitive-command-approval.cjs", raw, ["--runtime=claude"]);
    assert.equal(claude.permissionDecision, "ask");
    assert.ok(!JSON.stringify([codex, claude]).includes(marker));
    assert.deepEqual(hook("sensitive-command-approval.cjs", bash("commandcode --version")), {});
  } finally { space.cleanup(); }
});
