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

const TOOLS = {
  codex: { leader: "the chosen leader", resume: "followup_task" },
  claude: { leader: "the session model", resume: "SendMessage" },
};

function escalationText(runtime = "codex") {
  if (runtime === "claude") {
    return "Ultra Hook escalation: task-scoped escalation may use the strongest model the Agent tool lists when justified and within the user's authorization. " +
      "Choose a stronger model, a defined higher-effort agent type or independent branches from evidence; respect explicit model/effort caps and budgets. " +
      "Missing data, permissions or services are blockers, not reasons for more models. " +
      "One bounded costly attempt, then reassess; do not repeat maximum-effort calls without new evidence. " +
      "The lead coordinates ownership. SendMessage does not change an existing agent's model or effort; " +
      "a new specialist needs a self-contained handoff and the previous writer stopped. Do not change the session model or settings. " +
      `Detailed protocol (read only when needed): ${POLICY_PATH}`;
  }
  return "Ultra Hook escalation: task-scoped escalation may use the strongest supported model at max/ultra when justified and within the user's authorization. " +
    "Choose deeper reasoning, a stronger tier or independent branches from evidence; respect explicit model/effort caps and budgets. " +
    "Missing data, permissions or services are blockers, not reasons for more models. " +
    "One bounded costly attempt, then reassess; do not repeat maximum-effort calls without new evidence. " +
    "The lead coordinates slots and ownership. send_message/followup_task do not change an existing worker's model or effort; " +
    "a new specialist needs a handoff and the previous writer stopped. " +
    `Detailed protocol (read only when needed): ${POLICY_PATH}`;
}

// Claude Code exposes no local model catalog and no per-call reasoning effort.
// Name only the tier aliases; the Agent tool's own model option stays authoritative.
function claudeRoutingText() {
  return "mechanical: haiku; implementation: sonnet; architecture: opus, only where the Agent tool lists them. " +
    "Effort comes from the agent definition, not the call. Live tool options override hints; preserve the session model and explicit caps. ";
}

function startText(runtime = "codex") {
  return "Ultra Hook: each prompt gets a work mode from its task. direct: you do it. fast: parallel read-only scouts, you implement. " +
    "deep: you implement, one independent strong reviewer checks. team: separable work with owned files. " +
    "The user can say 'mode <name>' to fix one or 'mode auto' to release it. Agent spawns beyond the mode's cap are stopped; do not work around the cap. " +
    `Preserve ${TOOLS[runtime].leader}; native permissions and explicit task limits win. ` +
    "UI validation requires AgentController and real target evidence; unavailable UI transport is not a pass. " +
    `Read the full protocol only when coordinating or escalating: ${POLICY_PATH}`;
}

function playbook(state, runtime) {
  if (state.mode === "direct") {
    return state.cap === 0 ? "Do the work yourself; do not spawn agents." :
      "Do the work yourself. Spawn an agent only for an independent lookup that pays for its own startup.";
  }
  if (state.mode === "fast") {
    return "Send independent read-only questions to scouts on the lightest adequate model, in one batch, " +
      "each with a self-contained brief and the evidence to return. You implement and verify; no parallel writers.";
  }
  if (state.mode === "deep") {
    return "Implement it yourself. Then give one reviewer on the strongest justified model, which did not write the change, " +
      "the diff and the acceptance check rather than your conclusion. Act on findings that name a location, trigger and consequence, then recheck the original failure.";
  }
  return "Split only separable work: one owner per file set, interfaces agreed before concurrent edits, the smallest team that covers it. " +
    `Continue a teammate via ${TOOLS[runtime].resume} instead of respawning it. You integrate and verify.`;
}

// Emitted only when it tells the lead something new: an ordinary prompt that
// stays in inferred direct mode adds nothing to the context.
function modeText(state, runtime = "codex") {
  if (!state || (state.mode === "direct" && state.source === "auto" && !state.changed && !state.released)) return "";
  const agents = state.cap === 1 ? "1 agent" : `${state.cap} agents`;
  const origin = state.source === "explicit" ? "set by the user" : "inferred from the task";
  return `Ultra Hook mode: ${state.mode} (${origin}; at most ${agents} for this prompt). ` + playbook(state, runtime) +
    (state.source === "auto" ? " The user can say 'mode <name>' to change it." : "");
}

// slot is null when the session state is unavailable; advice still applies.
function spawnText(slot, runtime = "codex") {
  const role = slot?.mode === "fast" ? "Scouts take the mechanical tier and stay read-only. " :
    slot?.mode === "deep" ? "The reviewer takes the architecture tier and must not be the author. " : "";
  const head = slot ? `Ultra Hook spawn ${slot.index}/${slot.cap} (${slot.mode}): ` : "Ultra Hook spawn check: ";
  return head + role + (runtime === "claude" ? claudeRoutingText() : routingText()) +
    "Brief it with goal, owned files or cwd, what is ruled out and the acceptance check; " +
    `continue an existing agent via ${TOOLS[runtime].resume} instead of a new one. ` +
    `Full protocol if needed: ${POLICY_PATH}`;
}

function capText(slot, runtime = "codex") {
  const head = `Ultra Hook: this would be agent ${slot.index} for this prompt and ${slot.mode} mode allows ${slot.cap}. `;
  return head + (runtime === "claude" ? "Approve to exceed the cap once, or say 'mode team' for a larger one." :
    "Finish with the agents already running or do the work directly. The user can say 'mode team' to raise the cap; do not retry through another tool.");
}

function contextFor(eventName, kind = "team", runtime = "codex") {
  if (eventName === "SessionStart") return startText(runtime);
  if (eventName === "UserPromptSubmit" && kind === "escalation") return escalationText(runtime);
  if (eventName === "PreToolUse") return spawnText(null, runtime);
  return "";
}

// Retained for callers of the previous advisory API; full policy is now on demand.
function teamContext() { return contextFor("SessionStart"); }

function emitContext(eventName, text = contextFor(eventName)) {
  if (text) process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: eventName, additionalContext: text } }) + "\n");
}

module.exports = { contextFor, modeText, spawnText, capText, startText, resolveCapabilities, escalationText, resolveModels, compareVersions, loadCatalog, routingText, teamContext, emitContext };
if (require.main === module) console.log(JSON.stringify({ roles: resolveModels(loadCatalog()), capabilities: resolveCapabilities(loadCatalog()), note: routingText() }, null, 2));
