"use strict";

// Offline, read-only routing hints. The live collaboration tool catalog wins.
const { readBoundedFile } = require("./hook-io.cjs");
const os = require("node:os");
const path = require("node:path");

const ROLES = {
  mechanical: { family: "luna", efforts: ["low", "medium"] },
  implementation: { family: "sol", efforts: ["medium", "high"] },
  architecture: { family: "astra", efforts: ["high", "xhigh"] },
};

function version(slug, family) {
  if (typeof slug !== "string" || slug.length > 80) return null;
  const match = new RegExp(`^gpt-(\\d+(?:\\.\\d+)*)-${family}$`).exec(slug || "");
  const parts = match ? match[1].split(".").map(Number) : null;
  return parts && parts.length <= 6 && parts.every(Number.isSafeInteger) ? parts : null;
}

function compareVersions(a, b) {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const delta = (a[i] || 0) - (b[i] || 0);
    if (delta) return delta;
  }
  return 0;
}

function resolveModels(catalog) {
  const models = Array.isArray(catalog?.models) && catalog.models.length <= 512 ? catalog.models : [];
  const result = {};
  for (const [role, rule] of Object.entries(ROLES)) {
    const candidates = models.filter(m => m?.visibility === "list" && version(m.slug, rule.family) &&
      Array.isArray(m.supported_reasoning_levels) &&
      m.supported_reasoning_levels.some(x => rule.efforts.includes(x?.effort)));
    candidates.sort((a, b) => compareVersions(version(b.slug, rule.family), version(a.slug, rule.family)));
    const chosen = candidates[0];
    if (!chosen) { result[role] = null; continue; }
    const supported = (chosen.supported_reasoning_levels || []).map(x => x?.effort);
    const efforts = rule.efforts.filter(e => supported.includes(e));
    result[role] = efforts.length ? { model: chosen.slug, efforts } : null;
  }
  return result;
}

// Capability ceilings are separate from the inexpensive default role choices.
// Never assume that all families support ultra or a future unknown effort.
function resolveCapabilities(catalog) {
  const roles = resolveModels(catalog);
  const order = ["low", "medium", "high", "xhigh", "max", "ultra"];
  return Object.fromEntries(Object.entries(roles).map(([role, choice]) => {
    if (!choice) return [role, null];
    const entry = catalog.models.find(m => m?.visibility === "list" && m.slug === choice.model &&
      Array.isArray(m.supported_reasoning_levels) && m.supported_reasoning_levels.some(x => choice.efforts.includes(x?.effort)));
    const supported = entry.supported_reasoning_levels.map(x => x?.effort);
    const efforts = order.filter(e => supported.includes(e));
    return [role, { model: choice.model, efforts,
      highestSingleAgentEffort: efforts.filter(e => e !== "ultra").at(-1),
      ultraAvailable: efforts.includes("ultra") }];
  }));
}

function loadCatalog() {
  const home = process.env.CODEX_HOME || path.join(os.homedir(), ".codex");
  try { return JSON.parse(readBoundedFile(path.join(home, "models_cache.json"))); }
  catch { return null; }
}

const POLICY_PATH = path.resolve(__dirname, "../skills/ultra-hook/references/teams-and-models.md");

function routingText(catalog = loadCatalog()) {
  const age = Date.now() - Date.parse(catalog?.fetched_at || "");
  const stale = !Number.isFinite(age) || age < -86400000 || age > 7 * 86400000;
  const choices = stale ? "Cache missing/stale; use the live supported model catalog" :
    Object.entries(resolveModels(catalog)).map(([role, value]) =>
      `${role}: ${value ? `${value.model} ${value.efforts.join("/")}` : "verify live options"}`).join("; ");
  return `${choices}. Live tool IDs/efforts override hints; preserve the user's leader and explicit caps. `;
}

function escalationText() {
  return "Ultra Hook escalation: task-scoped escalation may use the strongest supported model at max/ultra when justified and within the user's authorization. " +
    "Choose deeper reasoning, a stronger tier or independent branches from evidence; respect explicit model/effort caps and budgets. " +
    "Missing data, permissions or services are blockers, not reasons for more models. " +
    "One bounded costly attempt, then reassess; do not repeat maximum-effort calls without new evidence. " +
    "The lead coordinates slots and ownership. send_message/followup_task do not change an existing worker's model or effort; " +
    "a new specialist needs a handoff and the previous writer stopped. " +
    `Detailed protocol (read only when needed): ${POLICY_PATH}`;
}

function contextFor(eventName, kind = "team") {
  if (eventName === "SessionStart") {
    return "Ultra Hook: small work stays direct. Native teams only for authorized useful independent work; no fixed headcount. " +
      "Preserve the chosen leader. Prefer the least costly adequate role/effort; max/ultra require task evidence and a bounded attempt. " +
      "Teammates converse via send_message; followup_task preserves idle teammates. Native permissions and explicit task limits win. " +
      "UI validation requires AgentController and real target evidence; unavailable UI transport is not a pass. " +
      `Read the full protocol only when coordinating or escalating: ${POLICY_PATH}`;
  }
  if (eventName === "UserPromptSubmit") {
    if (kind === "escalation") return escalationText();
    return "Ultra Hook team request: delegate only authorized branches whose benefit outweighs startup and integration cost. " +
      "Start with the smallest useful team; add capacity only for independent work or necessary review. " +
      "Keep dialogue via send_message/followup_task; the lead integrates and honors explicit task limits. " +
      `Read coordination details only if needed: ${POLICY_PATH}`;
  }
  if (eventName === "PreToolUse") {
    return "Ultra Hook spawn check: " + routingText() +
      "Reuse a suitable teammate via followup_task; use a new agent for changed model/effort or independent scope. " +
      "For overrides use fork_turns none or a small positive count with a self-contained assignment; all inherits the lead. " +
      "Assign owned files, cwd, lead/peer contacts, acceptance check and a bounded objective; use send_message during work. " +
      "Justify each extra worker against context/startup/integration cost. Reserve useful capacity, not a fixed headcount. " +
      "Max/ultra require authorization and evidence; ultra needs independent work and free capacity. " +
      "After one costly attempt reassess before another. For transfer, stop the old writer and inspect changes. " +
      `Do not change permissions. Full protocol if needed: ${POLICY_PATH}`;
  }
  return "";
}

// Retained for callers of the previous advisory API; full policy is now on demand.
function teamContext() { return contextFor("SessionStart"); }

function emitContext(eventName, text = contextFor(eventName)) {
  if (text) process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: eventName, additionalContext: text } }) + "\n");
}

module.exports = { contextFor, resolveCapabilities, escalationText, resolveModels, compareVersions, loadCatalog, routingText, teamContext, emitContext };
if (require.main === module) console.log(JSON.stringify({ roles: resolveModels(loadCatalog()), capabilities: resolveCapabilities(loadCatalog()), note: routingText() }, null, 2));
