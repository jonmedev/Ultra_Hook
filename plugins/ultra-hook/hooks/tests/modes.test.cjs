"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const modes = require("../session-mode.cjs");
const { modeText, spawnText, capText } = require("../model-routing.cjs");

// Every case uses its own temporary state directory. Prompts are synthetic and
// no hook here executes a command.
const hooksDirectory = path.join(__dirname, "..");
function workspace() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ultra-modes-"));
  return { directory, sessions: path.join(directory, "sessions"), cleanup() {
    const resolved = path.resolve(directory);
    assert.equal(path.dirname(resolved), path.resolve(os.tmpdir()));
    assert.ok(path.basename(resolved).startsWith("ultra-modes-"));
    fs.rmSync(resolved, { recursive: true, force: true });
  } };
}
function environment(directory) {
  const env = { ...process.env, PLUGIN_DATA: directory };
  delete env.CLAUDE_PLUGIN_DATA;
  return env;
}
function run(script, payload, directory, flags = []) {
  const result = spawnSync(process.execPath, [path.join(hooksDirectory, script), ...flags], {
    input: JSON.stringify(payload), encoding: "utf8", timeout: 5000, shell: false, windowsHide: true, env: environment(directory),
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr, "");
  return JSON.parse(result.stdout || "{}").hookSpecificOutput || {};
}
const prompt = (text, session_id = "synthetic-session") => ({ hook_event_name: "UserPromptSubmit", prompt: text, session_id });
const agent = (session_id = "synthetic-session", tool_name = "Agent") => ({ hook_event_name: "PreToolUse", tool_name, tool_input: {}, session_id });

test("the task selects the mode; unrecognized work stays direct", () => {
  const cases = {
    team: ["Paraleliza estas tareas", "Coordina el equipo de agentes", "Spawn two agents for this", "Delega la revision"],
    deep: ["Haz la migracion de la base de datos", "Fix the authentication bypass", "Revisa a fondo los cambios de la rama",
      "Prepara el despliegue a produccion", "There is a race condition in the queue", "Audita el modulo de pagos"],
    fast: ["Investiga como funciona el planificador", "Where is the retry logic?", "Explora el repo y resume la arquitectura",
      "Compara las dos librerias", "Find all callers of parseConfig"],
  };
  for (const [mode, prompts] of Object.entries(cases)) {
    for (const text of prompts) assert.deepEqual(modes.classify(text), { mode, source: "auto", size: null }, text);
  }
  for (const text of ["Corrige esta errata", "Renombra la variable agents", "Mi equipo Windows no arranca",
    "Anade un boton de guardar al formulario", "Enable fast mode in the settings page", "Explica parallel arrays"]) {
    assert.equal(modes.classify(text).mode, null, text);
  }
  for (const value of [null, {}, "", "   "]) assert.equal(modes.classify(value).mode, null);
});

test("a named mode wins over the task and accepts Spanish and English", () => {
  const explicit = (text, mode, size = null) => assert.deepEqual(modes.classify(text), { mode, source: "explicit", size }, text);
  explicit("/ultra-hook rapido investiga el fallo", "fast");
  explicit("$ultra-hook:ultra-hook deep fix the importer", "deep");
  explicit("/ultra-hook:ultra-hook modo directo paraleliza esto", "direct");
  explicit("Modo a fondo: revisa la migracion", "deep");
  explicit("mode team of 8, split the refactor", "team", 8);
  explicit("modo equipo 40", "team", modes.MAX_TEAM);
  explicit("modo equipo de 0", "team", 1);
  explicit("Mode auto", "auto");
  explicit("Sin agentes, investiga como funciona", "direct");
  explicit("Do not use subagents; explore the repo", "direct");
  assert.equal(modes.capFor("direct", "explicit"), 0);
  assert.equal(modes.capFor("direct", "auto"), 2);
  assert.equal(modes.capFor("team", "explicit", 8), 8);
  assert.ok(modes.capFor("fast", "auto") > modes.capFor("deep", "auto"));
});

test("an explicit mode holds for the session; inferred modes follow each prompt", () => {
  const space = workspace();
  try {
    const begin = text => modes.beginTask("synthetic-session", text, space.sessions);
    assert.deepEqual(begin("Corrige esta errata"), { mode: "direct", source: "auto", cap: 2, changed: false, released: false });
    assert.equal(begin("Investiga como funciona la cola").mode, "fast");
    // A short reply continues the task; a long unrelated one returns to direct.
    assert.equal(begin("si, sigue").mode, "fast");
    assert.equal(begin("Ahora anade un boton de guardar al formulario de alta de clientes y actualiza el texto de ayuda").mode, "direct");
    const fixed = begin("modo a fondo");
    assert.deepEqual([fixed.mode, fixed.source, fixed.cap], ["deep", "explicit", 2]);
    const kept = begin("Paraleliza estas tareas");
    assert.deepEqual([kept.mode, kept.source, kept.changed], ["deep", "explicit", false]);
    assert.equal(begin("modo equipo 3").cap, 3);
    const released = begin("mode auto");
    assert.deepEqual([released.mode, released.source, released.released], ["direct", "auto", true]);
    assert.equal(begin("Paraleliza estas tareas").mode, "team");
  } finally { space.cleanup(); }
});

test("spawns are counted per prompt and stopped over the cap", () => {
  const space = workspace();
  try {
    assert.match(run("prompt-routing.cjs", prompt("Investiga como funciona la cola"), space.directory).additionalContext, /mode: fast \(inferred from the task; at most 4 agents/);
    for (let index = 1; index <= 4; index += 1) {
      const allowed = run("team-spawn.cjs", agent(), space.directory);
      assert.equal(allowed.permissionDecision, undefined);
      assert.match(allowed.additionalContext, new RegExp(`spawn ${index}/4 \\(fast\\)`));
      assert.match(allowed.additionalContext, /stay read-only/);
    }
    const codex = run("team-spawn.cjs", agent("synthetic-session", "spawn_agent"), space.directory);
    assert.equal(codex.permissionDecision, "deny");
    assert.match(codex.permissionDecisionReason, /agent 5 for this prompt and fast mode allows 4/);
    const claude = run("team-spawn.cjs", agent(), space.directory, ["--runtime=claude"]);
    assert.equal(claude.permissionDecision, "ask");
    assert.match(claude.permissionDecisionReason, /agent 6 .* Approve to exceed the cap once/);
    // A host notice arriving through the prompt event is not a new task.
    for (const notice of ["<task-notification>\n<task-id>synthetic</task-id>", "  <system-reminder>synthetic</system-reminder>"]) {
      assert.deepEqual(run("prompt-routing.cjs", prompt(notice), space.directory), {});
    }
    assert.equal(run("team-spawn.cjs", agent(), space.directory).permissionDecision, "deny");
    // The next prompt starts a fresh count.
    run("prompt-routing.cjs", prompt("ok, sigue"), space.directory);
    assert.match(run("team-spawn.cjs", agent(), space.directory).additionalContext, /spawn 1\/4 \(fast\)/);
    // Another session has its own record.
    assert.match(run("team-spawn.cjs", agent("other-session"), space.directory).additionalContext, /spawn 1\/2 \(direct\)/);
  } finally { space.cleanup(); }
});

test("explicit direct mode stops the first agent; an ordinary prompt adds no context", () => {
  const space = workspace();
  try {
    assert.deepEqual(run("prompt-routing.cjs", prompt("Corrige esta errata"), space.directory), {});
    assert.deepEqual(run("prompt-routing.cjs", prompt("Renombra la variable total"), space.directory), {});
    const direct = run("prompt-routing.cjs", prompt("modo directo"), space.directory);
    assert.match(direct.additionalContext, /mode: direct \(set by the user; at most 0 agents.*do not spawn agents/);
    assert.equal(run("team-spawn.cjs", agent(), space.directory).permissionDecision, "deny");
    assert.equal(run("team-spawn.cjs", agent(), space.directory, ["--runtime=claude"]).permissionDecision, "ask");
    assert.deepEqual(run("team-spawn.cjs", { ...agent(), tool_name: "Write" }, space.directory), {});
    const escalation = run("prompt-routing.cjs", prompt("modo equipo 3; usa un modelo mas potente"), space.directory);
    assert.match(escalation.additionalContext, /mode: team .*at most 3 agents.*Ultra Hook escalation/);
  } finally { space.cleanup(); }
});

test("concurrent spawn attempts never share a slot", async () => {
  const space = workspace();
  try {
    modes.beginTask("synthetic-session", "modo equipo 3", space.sessions);
    const results = await Promise.all(Array.from({ length: 8 }, () => new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [path.join(hooksDirectory, "team-spawn.cjs")], { env: environment(space.directory), stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
      let output = "";
      child.stdout.on("data", data => { output += data; });
      child.on("error", reject);
      child.on("close", () => resolve(JSON.parse(output || "{}").hookSpecificOutput || {}));
      child.stdin.end(JSON.stringify(agent()));
    })));
    assert.equal(results.filter(result => result.permissionDecision === undefined).length, 3);
    assert.equal(results.filter(result => result.permissionDecision === "deny").length, 5);
  } finally { space.cleanup(); }
});

test("state failures degrade to advice and the record holds no prompt text", () => {
  const space = workspace();
  try {
    const marker = "synthetic-private-payload";
    run("prompt-routing.cjs", prompt(`Investiga ${marker} en la cola`), space.directory);
    run("team-spawn.cjs", agent(), space.directory);
    const files = fs.readdirSync(space.sessions);
    assert.equal(files.length, 1);
    assert.match(files[0], /^[0-9a-f]{32}\.state$/);
    const stored = fs.readFileSync(path.join(space.sessions, files[0]), "utf8");
    assert.ok(!stored.includes(marker) && !stored.includes("synthetic-session"));
    // No session id: the mode is still announced and a spawn is only advised.
    const anonymous = { hook_event_name: "UserPromptSubmit", prompt: "Paraleliza estas tareas" };
    assert.match(run("prompt-routing.cjs", anonymous, space.directory).additionalContext, /mode: team/);
    const advised = run("team-spawn.cjs", { hook_event_name: "PreToolUse", tool_name: "Agent" }, space.directory);
    assert.equal(advised.permissionDecision, undefined);
    assert.match(advised.additionalContext, /^Ultra Hook spawn check:/);
    // An unusable data directory never blocks a spawn.
    const blocked = path.join(space.directory, "not-a-directory");
    fs.writeFileSync(blocked, "synthetic");
    assert.equal(run("team-spawn.cjs", agent(), blocked).permissionDecision, undefined);
    assert.match(run("prompt-routing.cjs", prompt("Paraleliza estas tareas"), blocked).additionalContext, /mode: team/);
    // A corrupted record is replaced rather than trusted.
    fs.writeFileSync(path.join(space.sessions, files[0]), "{not json\n");
    assert.match(run("team-spawn.cjs", agent(), space.directory).additionalContext, /spawn 1\/2 \(direct\)/);
  } finally { space.cleanup(); }
});

test("usage totals cover finished and open prompts; old records are pruned", () => {
  const space = workspace();
  try {
    modes.beginTask("one", "Investiga como funciona la cola", space.sessions);
    for (let index = 0; index < 6; index += 1) modes.recordSpawn("one", space.sessions);
    modes.beginTask("one", "modo directo", space.sessions);
    modes.recordSpawn("one", space.sessions);
    modes.beginTask("two", "Corrige esta errata", space.sessions);
    const { sessions, totals } = modes.report(space.sessions);
    assert.equal(sessions, 2);
    assert.deepEqual(totals.fast, { prompts: 1, spawns: 6, overCap: 2 });
    assert.deepEqual(totals.direct, { prompts: 2, spawns: 1, overCap: 1 });
    const cli = spawnSync(process.execPath, [path.join(hooksDirectory, "usage-report.cjs"), "--dir", space.sessions, "--json"], { encoding: "utf8", windowsHide: true });
    assert.equal(cli.status, 0, cli.stderr);
    assert.deepEqual(JSON.parse(cli.stdout).totals, totals);
    const table = spawnSync(process.execPath, [path.join(hooksDirectory, "usage-report.cjs"), "--dir", space.sessions], { encoding: "utf8", windowsHide: true });
    assert.match(table.stdout, /fast\s+1\s+6\s+2/);
    const old = path.join(space.sessions, "0".repeat(32) + ".state");
    fs.writeFileSync(old, "{}\n");
    fs.utimesSync(old, new Date(0), new Date(0));
    fs.writeFileSync(path.join(space.sessions, "unrelated.txt"), "keep");
    modes.prune(space.sessions);
    assert.ok(!fs.existsSync(old));
    assert.equal(fs.readdirSync(space.sessions).length, 3);
    assert.deepEqual(modes.report(path.join(space.directory, "absent")).sessions, 0);
  } finally { space.cleanup(); }
});

test("mode texts are compact and name the cap", () => {
  const fast = modeText({ mode: "fast", source: "auto", cap: 4, changed: true });
  assert.ok(fast.length < 450, fast.length);
  assert.match(fast, /no parallel writers/);
  assert.match(fast, /say 'mode <name>'/);
  const deep = modeText({ mode: "deep", source: "explicit", cap: 2, changed: true });
  assert.match(deep, /did not write the change/);
  assert.doesNotMatch(deep, /say 'mode <name>'/);
  assert.equal(modeText(null), "");
  assert.equal(modeText({ mode: "direct", source: "auto", cap: 2, changed: false }), "");
  assert.match(modeText({ mode: "direct", source: "auto", cap: 2, changed: false, released: true }), /mode: direct/);
  assert.match(modeText({ mode: "direct", source: "auto", cap: 1, changed: true }), /at most 1 agent for/);
  assert.match(spawnText({ mode: "deep", cap: 2, index: 1 }), /spawn 1\/2 \(deep\).*must not be the author/);
  assert.ok(spawnText({ mode: "team", cap: 6, index: 2 }, "claude").length < 600);
  assert.match(capText({ mode: "deep", cap: 2, index: 3 }), /do not retry through another tool/);
});
