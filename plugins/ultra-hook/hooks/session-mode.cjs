"use strict";
// Per-prompt work mode and agent-spawn accounting for one session.
// The state holds a mode name, counters and a timestamp. It never holds prompt
// text, commands, paths or tool input. Any state failure degrades to advice:
// a budget guard must not block work because a directory is unwritable.
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { readBoundedFile } = require("./hook-io.cjs");

// cap: agent spawns allowed per user prompt. autoCap applies when the mode was
// inferred rather than requested, so a misread task is not left without help.
const MODES = {
  direct: { cap: 0, autoCap: 2 },
  fast: { cap: 4 },
  deep: { cap: 2 },
  team: { cap: 6 },
};
const MAX_TEAM = 12;
const MAX_STATE_BYTES = 64 * 1024;
const RETENTION_MS = 30 * 86400000;
const CONTINUATION_LENGTH = 80;

const ALIASES = {
  direct: "direct|directo", fast: "fast|rapido|quick", deep: "deep|thorough|profundo|a fondo|fondo",
  team: "team|equipo", auto: "auto|automatico|automatic",
};
const ALIAS = Object.values(ALIASES).join("|");
const modeOf = word => Object.keys(ALIASES).find(mode => ALIASES[mode].split("|").includes(word));

const EXPLICIT = [
  new RegExp(String.raw`(?:^|\n)\s*[/$](?:ultra-hook:)?ultra-hook\s+(?:(?:modo|mode)\s+)?(${ALIAS})\b(?:\s+(?:de\s+|of\s+)?(\d{1,2})\b)?`),
  new RegExp(String.raw`\b(?:modo|mode)\s+(${ALIAS})\b(?:\s+(?:de\s+|of\s+)?(\d{1,2})\b)?`),
];
const NO_AGENTS = /\b(?:no (?:uses?|utilices|crees)|sin|without|do not use|don't use)\b[^\n.!?]{0,30}\b(?:agentes?|agents?|equipo|team|subagents?|subagentes?)\b/;
const TEAM = /\b(?:crea|lanza|usa|utiliza|coordina|organiza|forma|spawn|use|create|coordinate)\b[^\n.!?]{0,60}\b(?:agentes?|agents?|subagents?|subagentes?|equipo de agentes|agent team)\b|\b(?:paraleliza|parallelize|delega|delegate)\b|\b(?:trabaja|work|ejecuta|run)\b[^\n.!?]{0,30}\b(?:en paralelo|in parallel)\b/;
// Consequential work: an independent check is worth its cost.
const DEEP = /\b(?:migra(?:cion|ciones|tion|tions|r|te)|seguridad|security|vulnerab\w*|autenticacion|authentication|autorizacion|authorization|pagos?|payments?|billing|facturacion|produccion|production|deploy\w*|despliegue\w*|concurren\w*|race condition|condicion de carrera|data loss|perdida de datos|esquema de (?:la )?base de datos|database schema|audit\w*|code review|revis(?:a|ar|ion)\b[^\n.!?]{0,30}\b(?:a fondo|seguridad|cambios|rama|diff|pr)|review\b[^\n.!?]{0,30}\b(?:branch|diff|pr|changes|security))\b/;
// Independent read-only questions: parallel scouts shorten the wait.
const FAST = /\b(?:investiga\w*|research|explora\w*|explore|como funciona|how does|donde (?:esta|se)|where (?:is|does|are)|busca(?:r)? en (?:todo|el repo|el codigo)|search the (?:repo|codebase)|compara\w*|compare|onboard\w*|entiende (?:el|este) (?:repo|codigo|proyecto)|understand (?:the|this) (?:repo|codebase|project)|encuentra tod[oa]s|find (?:all|every))\b/;

function normalize(prompt) {
  return prompt.slice(0, 4000).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

// Conservative lexical reading of the task. It is not an intent classifier:
// an unrecognized task stays direct and the user can name a mode.
function classify(prompt) {
  if (typeof prompt !== "string" || !prompt.trim()) return { mode: null };
  const text = normalize(prompt);
  for (const pattern of EXPLICIT) {
    const match = pattern.exec(text);
    if (!match) continue;
    const mode = modeOf(match[1]);
    const size = mode === "team" && match[2] ? Math.min(MAX_TEAM, Math.max(1, Number(match[2]))) : null;
    return { mode, source: "explicit", size };
  }
  if (NO_AGENTS.test(text)) return { mode: "direct", source: "explicit", size: null };
  for (const [mode, pattern] of [["team", TEAM], ["deep", DEEP], ["fast", FAST]]) {
    if (pattern.test(text)) return { mode, source: "auto", size: null };
  }
  return { mode: null, short: text.trim().length <= CONTINUATION_LENGTH };
}

// Hosts deliver background-agent completions and similar notices through the
// prompt event. They are not a new user task and must not reset the count.
function isHostNotice(prompt) {
  return typeof prompt === "string" && /^\s*<(?:task-notification|system-reminder|local-command-[a-z]+|command-name)[\s>]/.test(prompt);
}

function capFor(mode, source, size) {
  if (mode === "team" && size) return size;
  const rule = MODES[mode];
  return source === "auto" && rule.autoCap !== undefined ? rule.autoCap : rule.cap;
}

function dataDirectory() {
  const base = process.env.CLAUDE_PLUGIN_DATA || process.env.PLUGIN_DATA || path.join(os.tmpdir(), "ultra-hook-state");
  return path.join(base, "sessions");
}

function statePath(sessionId, directory = dataDirectory()) {
  if (typeof sessionId !== "string" || !sessionId || sessionId.length > 256) return null;
  return path.join(directory, crypto.createHash("sha256").update(sessionId).digest("hex").slice(0, 32) + ".state");
}

function emptyTotals() {
  return Object.fromEntries(Object.keys(MODES).map(mode => [mode, { prompts: 0, spawns: 0, overCap: 0 }]));
}

function parse(text) {
  const [first, ...rest] = text.split("\n");
  const header = JSON.parse(first);
  if (!header || typeof header !== "object" || !MODES[header.mode] || !Number.isSafeInteger(header.cap)) throw new Error("state");
  const totals = emptyTotals();
  for (const mode of Object.keys(totals)) {
    for (const key of Object.keys(totals[mode])) {
      const value = header.totals?.[mode]?.[key];
      if (Number.isSafeInteger(value) && value >= 0) totals[mode][key] = value;
    }
  }
  const spawns = rest.filter(line => /^S [0-9a-f]{16}$/.test(line)).map(line => line.slice(2));
  return { mode: header.mode, source: header.source === "explicit" ? "explicit" : "auto", cap: header.cap,
    sticky: header.sticky === true, totals, spawns };
}

function load(file) {
  try { return parse(readBoundedFile(file, MAX_STATE_BYTES)); } catch { return null; }
}

// Fold the finished prompt into the per-mode totals.
function settle(state) {
  const totals = state.totals;
  totals[state.mode].prompts += 1;
  totals[state.mode].spawns += state.spawns.length;
  totals[state.mode].overCap += Math.max(0, state.spawns.length - state.cap);
  return totals;
}

function store(file, state) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = file + "." + crypto.randomBytes(6).toString("hex") + ".tmp";
  const header = { v: 1, mode: state.mode, source: state.source, cap: state.cap, sticky: state.sticky,
    totals: state.totals, updated: new Date().toISOString() };
  try {
    fs.writeFileSync(temporary, JSON.stringify(header) + "\n", { flag: "wx", mode: 0o600 });
    fs.renameSync(temporary, file);
  } catch (error) {
    try { fs.unlinkSync(temporary); } catch { /* nothing to clean */ }
    throw error;
  }
}

// Called once per user prompt. Returns the mode in force. Without a usable
// session record the mode still comes from the prompt; only counting is lost.
function beginTask(sessionId, prompt, directory = dataDirectory()) {
  try {
    const file = statePath(sessionId, directory);
    const previous = file ? load(file) : null;
    const decision = classify(prompt);
    const totals = previous ? settle(previous) : emptyTotals();
    let next;
    if (decision.mode === "auto") next = { mode: "direct", source: "auto", sticky: false };
    else if (decision.source === "explicit") next = { mode: decision.mode, source: "explicit", sticky: true, size: decision.size };
    else if (previous?.sticky) next = { mode: previous.mode, source: "explicit", sticky: true, cap: previous.cap };
    else if (decision.mode) next = { mode: decision.mode, source: "auto", sticky: false };
    // A short reply without its own signal continues the task it answers.
    else if (previous && decision.short) next = { mode: previous.mode, source: previous.source, sticky: false, cap: previous.cap };
    else next = { mode: "direct", source: "auto", sticky: false };
    const cap = next.cap ?? capFor(next.mode, next.source, next.size);
    const state = { mode: next.mode, source: next.source, cap, sticky: next.sticky, totals };
    try { if (file) store(file, state); } catch { /* advice survives a failed write */ }
    return { mode: state.mode, source: state.source, cap,
      changed: previous ? previous.mode !== state.mode || previous.cap !== cap : !(state.mode === "direct" && state.source === "auto"),
      released: decision.mode === "auto" };
  } catch { return null; }
}

// Called once per spawn attempt. Appending first and reading the position back
// keeps concurrent attempts from sharing a slot.
function recordSpawn(sessionId, directory = dataDirectory()) {
  try {
    const file = statePath(sessionId, directory);
    if (!file) return null;
    if (!load(file)) {
      // No prompt was recorded for this session. Create the default without
      // replacing a record a concurrent attempt has just written to.
      const initial = { mode: "direct", source: "auto", cap: MODES.direct.autoCap, sticky: false, totals: emptyTotals() };
      try {
        fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
        fs.writeFileSync(file, JSON.stringify({ v: 1, ...initial, updated: new Date().toISOString() }) + "\n", { flag: "wx", mode: 0o600 });
      } catch { if (!load(file)) store(file, initial); }
    }
    const token = crypto.randomBytes(8).toString("hex");
    fs.appendFileSync(file, `S ${token}\n`);
    const state = load(file);
    // An unreadable or oversized record cannot show a free slot.
    if (!state) return { mode: "direct", source: "auto", cap: 0, index: 1, unreadable: true };
    const index = state.spawns.indexOf(token) + 1;
    return { mode: state.mode, source: state.source, cap: state.cap, index: index || state.spawns.length + 1 };
  } catch { return null; }
}

function prune(directory = dataDirectory(), now = Date.now()) {
  try {
    for (const name of fs.readdirSync(directory).slice(0, 2000)) {
      if (!/^[0-9a-f]{32}\.state(?:\.[0-9a-f]{12}\.tmp)?$/.test(name)) continue;
      const file = path.join(directory, name);
      const info = fs.lstatSync(file);
      if (info.isFile() && now - info.mtimeMs > RETENTION_MS) fs.unlinkSync(file);
    }
  } catch { /* housekeeping only */ }
}

// Totals across retained sessions, including each session's open prompt.
function report(directory = dataDirectory()) {
  const totals = emptyTotals();
  let sessions = 0;
  let names = [];
  try { names = fs.readdirSync(directory).slice(0, 2000); } catch { return { sessions, totals }; }
  for (const name of names) {
    if (!/^[0-9a-f]{32}\.state$/.test(name)) continue;
    const state = load(path.join(directory, name));
    if (!state) continue;
    sessions += 1;
    const settled = settle(state);
    for (const mode of Object.keys(totals)) {
      for (const key of Object.keys(totals[mode])) totals[mode][key] += settled[mode][key];
    }
  }
  return { sessions, totals };
}

module.exports = { MODES, MAX_TEAM, isHostNotice, classify, capFor, dataDirectory, statePath, beginTask, recordSpawn, prune, report };
