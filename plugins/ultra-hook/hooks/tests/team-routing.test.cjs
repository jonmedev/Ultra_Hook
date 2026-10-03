"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { resolveModels, resolveCapabilities, contextFor, routingText } = require("../model-routing.cjs");

const model = (slug, efforts, visibility = "list") => ({ slug, visibility,
  supported_reasoning_levels: efforts.map(effort => ({ effort })) });
const catalog = { fetched_at:new Date().toISOString(), models: [model("gpt-6-luna", ["low", "medium"]),
  model("gpt-6-sol", ["medium", "high"]), model("gpt-6.1-sol", ["medium", "high"]),
  model("gpt-6-astra", ["high", "xhigh"])] };

test("keeps capability tiers and selects newest Sol", () => {
  const r = resolveModels(catalog);
  assert.equal(r.mechanical.model, "gpt-6-luna");
  assert.equal(r.implementation.model, "gpt-6.1-sol");
  assert.equal(r.architecture.model, "gpt-6-astra");
});
test("numeric version comparison; hidden and unknown IDs cannot win", () => {
  const r = resolveModels({ models: [...catalog.models,
    model("gpt-6.9-sol", ["high"]), model("gpt-6.10-sol", ["high"]),
    model("gpt-99-sol", ["high"], "hide"), model("fake-gpt-999-sol", ["high"])] });
  assert.equal(r.implementation.model, "gpt-6.10-sol");
});
test("does not invent missing family or unsupported effort", () => {
  assert.deepEqual(resolveModels(null), { mechanical: null, implementation: null, architecture: null });
  assert.equal(resolveModels({models: [model("gpt-6-astra", ["low"])]}).architecture, null);
});
test("newer catalog entry with incompatible effort does not hide usable fallback", () => {
  const r = resolveModels({models: [...catalog.models, model("gpt-7-sol", ["low"])]});
  assert.equal(r.implementation.model, "gpt-6.1-sol");
  assert.deepEqual(r.implementation.efforts, ["medium", "high"]);
});

function cleanup(tmp) {
  const resolved = path.resolve(tmp);
  assert.equal(path.dirname(resolved), path.resolve(os.tmpdir()));
  assert.ok(path.basename(resolved).startsWith("ultra-routing-"));
  fs.rmSync(resolved, {recursive:true,force:true});
}

function invoke(script, payload, cacheHome) {
  const r = spawnSync(process.execPath, [path.join(__dirname, "..", script)], {
    input: JSON.stringify(payload), encoding: "utf8", timeout: 5000,
    env: { ...process.env, CODEX_HOME: cacheHome }, windowsHide: true,
  });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stderr, "");
  return r.stdout.trim() ? JSON.parse(r.stdout) : null;
}
test("native spawn receives advice without permission or input rewrites; edits remain silent", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ultra-routing-"));
  try {
    fs.writeFileSync(path.join(tmp, "models_cache.json"), JSON.stringify(catalog));
    for (const name of ["spawn_agent", "Agent", "collaboration.spawn_agent"]) {
      const out = invoke("team-spawn.cjs", {hook_event_name:"PreToolUse",tool_name:name}, tmp);
      assert.equal(out.hookSpecificOutput.hookEventName, "PreToolUse");
      assert.equal(out.hookSpecificOutput.permissionDecision, undefined);
      assert.equal(out.hookSpecificOutput.updatedInput, undefined);
      assert.match(out.hookSpecificOutput.additionalContext, /gpt-6\.1-sol/);
    }
    assert.equal(invoke("team-spawn.cjs", {hook_event_name:"PreToolUse",tool_name:"apply_patch"}, tmp), null);
    assert.equal(invoke("team-spawn.cjs", {hook_event_name:"PreToolUse",tool_name:"Write"}, tmp), null);
  } finally { cleanup(tmp); }
});
test("prompt hook is scoped to team requests and startup emits portable advice", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ultra-routing-"));
  try {
    const ordinary = invoke("prompt-routing.cjs", {hook_event_name:"UserPromptSubmit",prompt:"Corrige esta errata"}, tmp);
    assert.equal(ordinary, null);
    const team = invoke("prompt-routing.cjs", {hook_event_name:"UserPromptSubmit",prompt:"Coordina el equipo de agentes"}, tmp);
    assert.match(team.hookSpecificOutput.additionalContext, /followup_task/);
    const start = invoke("session-start.cjs", {hook_event_name:"SessionStart",cwd:tmp}, tmp);
    assert.equal(start.hookSpecificOutput.hookEventName, "SessionStart");
    assert.match(start.hookSpecificOutput.additionalContext, /full protocol only when coordinating or escalating/);
  } finally { cleanup(tmp); }
});


test("escalation ceilings do not raise defaults and distinguish Luna max from Astra ultra", () => {
  const c = {models: [model("gpt-6-luna", ["low", "medium", "high", "max"]),
    model("gpt-6.1-sol", ["medium", "high", "xhigh", "max", "ultra"]),
    model("gpt-6-astra", ["high", "xhigh", "max", "ultra"])]};
  const r = resolveCapabilities(c);
  assert.equal(r.mechanical.highestSingleAgentEffort, "max");
  assert.equal(r.mechanical.ultraAvailable, false);
  assert.equal(r.architecture.highestSingleAgentEffort, "max");
  assert.equal(r.architecture.ultraAvailable, true);
  assert.deepEqual(resolveModels(c).architecture.efforts, ["high", "xhigh"]);
  assert.deepEqual(resolveModels(c).mechanical.efforts, ["low", "medium"]);
});
test("capability ceilings use the chosen visible version and supported efforts only", () => {
  const c = {models: [model("gpt-6-sol", ["high", "max", "ultra"]),
    model("gpt-6.1-sol", ["high", "xhigh", "imaginary"]),
    model("gpt-99-sol", ["high", "ultra"], "hide"),
    model("gpt-6-astra", ["high"])]};
  const r = resolveCapabilities(c);
  assert.equal(r.implementation.model, "gpt-6.1-sol");
  assert.deepEqual(r.implementation.efforts, ["high", "xhigh"]);
  assert.equal(r.implementation.highestSingleAgentEffort, "xhigh");
  assert.equal(r.implementation.ultraAvailable, false);
  assert.equal(r.architecture.highestSingleAgentEffort, "high");
  assert.equal(r.mechanical, null);
  assert.deepEqual(resolveCapabilities(null), {mechanical:null, implementation:null, architecture:null});
});
test("escalation prompts receive bounded advisory policy without granting tool permission", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ultra-routing-"));
  try {
    for (const prompt of ["Estoy atascado con el fallo, aumenta el razonamiento", "Aumenta el razonamiento", "Use a stronger model"]) {
      const out = invoke("prompt-routing.cjs", {hook_event_name:"UserPromptSubmit",prompt}, tmp);
      const context = out.hookSpecificOutput.additionalContext;
      assert.match(context, /task-scoped escalation/);
      assert.match(context, /explicit model\/effort caps/);
      assert.match(context, /do not change an existing worker's model or effort/);
      assert.match(context, /Missing data, permissions/);
      assert.match(context, /do not repeat maximum-effort calls/);
      assert.doesNotMatch(context, /gpt-6-astra|gpt-6-luna|gpt-6\.1-sol/);
      assert.equal(out.hookSpecificOutput.permissionDecision, undefined);
      assert.equal(out.hookSpecificOutput.updatedInput, undefined);
    }
  } finally { cleanup(tmp); }
});


test("partially malformed catalog keeps valid routing and capability advice", () => {
  const c = {fetched_at:new Date().toISOString(),models:[null, false, {},
    {slug:"gpt-6.1-sol",visibility:"list",supported_reasoning_levels:null},
    {slug:"gpt-6.1-sol",visibility:"list",supported_reasoning_levels:[null,{effort:"high"},{effort:"max"}]}]};
  assert.deepEqual(resolveModels(c).implementation, {model:"gpt-6.1-sol",efforts:["high"]});
  assert.equal(resolveCapabilities(c).implementation.highestSingleAgentEffort, "max");
  assert.match(routingText(c), /gpt-6\.1-sol/);
});
test("stale or missing timestamps never advertise cached IDs as current routing hints", () => {
  for (const fetched_at of [undefined,"bad","2000-01-01T00:00:00Z","2999-01-01T00:00:00Z"]) {
    const text = routingText({...catalog,fetched_at});
    assert.match(text, /missing\/stale/);
    assert.doesNotMatch(text, /gpt-6\.1-sol/);
  }
});
test("ordinary mentions and no-agent requests do not inject team instructions", () => {
  const {promptKind} = require("../prompt-routing.cjs");
  for (const prompt of ["Mi equipo Windows no arranca", "Renombra la variable agents",
    "Explica el razonamiento de 2+2", "No uses agentes, corrige esta errata",
    "Do not use agents for this task", "No use a stronger model", "Use max length 100", "Explica parallel arrays", "Estoy atascado al abrir un archivo",
    null, {}, ""]) assert.equal(promptKind(prompt), null, String(prompt));
});
test("explicit bilingual coordination and escalation still trigger, without interpreting generic mentions", () => {
  const {promptKind} = require("../prompt-routing.cjs");
  for (const prompt of ["$ultra-hook revisa", "/ultra-hook revisa", "Coordina el equipo de agentes", "Spawn two agents",
    "Paraleliza estas tareas", "Delega la revision", "Trabaja en paralelo"]) assert.equal(promptKind(prompt), "team", prompt);
  for (const prompt of ["Aumenta el razonamiento", "Use a stronger model", "Pasa a un modelo superior",
    "Sube el esfuerzo", "No uses agentes; aumenta el razonamiento"]) assert.equal(promptKind(prompt), "escalation", prompt);
});
test("context is event-specific, bounded, and retains coordination/cost boundaries", () => {
  const { modeText } = require("../model-routing.cjs");
  const start = contextFor("SessionStart");
  const team = modeText({ mode: "team", source: "auto", cap: 6, changed: true });
  const escalation = contextFor("UserPromptSubmit", "escalation");
  const spawn = contextFor("PreToolUse");
  assert.ok(start.length < 900, start.length);
  assert.ok(team.length < 650, team.length);
  assert.ok(escalation.length < 1100, escalation.length);
  assert.ok(spawn.length < 700, spawn.length);
  assert.equal(contextFor("unknown"), "");
  assert.equal(contextFor("UserPromptSubmit"), "");
  assert.notEqual(start, spawn);
  assert.match(start, /direct.*fast.*deep.*team/);
  assert.match(team, /smallest team that covers it/);
  assert.match(spawn, /followup_task/);
  assert.match(escalation, /strongest supported model at max\/ultra/);
  assert.match(escalation, /explicit model\/effort caps and budgets/);
});
