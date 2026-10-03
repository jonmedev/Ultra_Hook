#!/usr/bin/env node
"use strict";
// Sets the work mode for this prompt and adds its playbook when that is news.
// A scoped reminder, never a grant of delegation or model-switching authority.
const { readEvent, runtime } = require("./hook-io.cjs");
const { emitContext, modeText, escalationText } = require("./model-routing.cjs");
const { beginTask, isHostNotice } = require("./session-mode.cjs");

function promptKind(prompt) {
  if (typeof prompt !== "string") return null;
  const p = prompt.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  // Conservative lexical trigger, not an intent classifier or delegation authority.
  if (/(?:^|\n)\s*[/$](?:ultra-hook:)?ultra-hook\b/.test(p)) return "team";
  if (/\b(?:no use|do not use|don't use|no uses|no utilices)\b[^;\n.!?]{0,50}\b(?:stronger model|modelo mas potente|modelo superior|astra|opus|max|ultra)\b/.test(p)) return null;
  if (/\b(?:aumenta|sube|incrementa|increase|raise)\b[^\n.!?]{0,35}\b(?:razonamiento|reasoning|esfuerzo)\b|\b(?:usa|use|cambia|pasa|switch)\b[^\n.!?]{0,40}\b(?:modelo (?:mas potente|superior)|stronger model|astra|opus|max(?!\s+(?:length|width|height|size|value|longitud|tamano)\b)|ultra)\b/.test(p)) return "escalation";
  if (/\b(?:no (?:uses?|utilices|crees)|sin|without|do not use|don't use)\b[^\n.!?]{0,30}\b(?:agentes?|agents?|equipo|team|subagents?)\b/.test(p)) return null;
  if (/\b(?:crea|lanza|usa|utiliza|coordina|organiza|forma|spawn|use|create|coordinate)\b[^\n.!?]{0,60}\b(?:agentes?|agents?|subagents?|equipo de agentes|agent team)\b|\b(?:paraleliza|parallelize|delega|delegate)\b|\b(?:trabaja|work|ejecuta|run)\b[^\n.!?]{0,30}\b(?:en paralelo|in parallel)\b/.test(p)) return "team";
  return null;
}

module.exports = { promptKind };
async function main() { try {
  const input = await readEvent();
  if (input.hook_event_name !== "UserPromptSubmit" || isHostNotice(input.prompt)) return;
  const host = runtime();
  const parts = [modeText(beginTask(input.session_id, input.prompt), host)];
  if (promptKind(input.prompt) === "escalation") parts.push(escalationText(host));
  const text = parts.filter(Boolean).join(" ");
  if (text) emitContext("UserPromptSubmit", text);
} catch { /* Advisory only; malformed input must not crash or authorize anything. */ } }
if (require.main === module) main();
