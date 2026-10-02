#!/usr/bin/env node
"use strict";
// A scoped reminder, never a grant of delegation or model-switching authority.
const { readEvent } = require("./hook-io.cjs");
const { emitContext, contextFor } = require("./model-routing.cjs");

function promptKind(prompt) {
  if (typeof prompt !== "string") return null;
  const p = prompt.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  // Conservative lexical trigger, not an intent classifier or delegation authority.
  if (/(?:^|\n)\s*[/$](?:ultra-hook:)?ultra-hook\b/.test(p)) return "team";
  if (/\b(?:no use|do not use|don't use|no uses|no utilices)\b[^;\n.!?]{0,50}\b(?:stronger model|modelo mas potente|modelo superior|astra|max|ultra)\b/.test(p)) return null;
  if (/\b(?:aumenta|sube|incrementa|increase|raise)\b[^\n.!?]{0,35}\b(?:razonamiento|reasoning|esfuerzo)\b|\b(?:usa|use|cambia|pasa|switch)\b[^\n.!?]{0,40}\b(?:modelo (?:mas potente|superior)|stronger model|astra|max(?!\s+(?:length|width|height|size|value|longitud|tamano)\b)|ultra)\b/.test(p)) return "escalation";
  if (/\b(?:no (?:uses?|utilices|crees)|sin|without|do not use|don't use)\b[^\n.!?]{0,30}\b(?:agentes?|agents?|equipo|team|subagents?)\b/.test(p)) return null;
  if (/\b(?:crea|lanza|usa|utiliza|coordina|organiza|forma|spawn|use|create|coordinate)\b[^\n.!?]{0,60}\b(?:agentes?|agents?|subagents?|equipo de agentes|agent team)\b|\b(?:paraleliza|parallelize|delega|delegate)\b|\b(?:trabaja|work|ejecuta|run)\b[^\n.!?]{0,30}\b(?:en paralelo|in parallel)\b/.test(p)) return "team";
  return null;
}

module.exports = { promptKind };
async function main() { try {
  const input = await readEvent();
  const kind = promptKind(input.prompt);
  if (input.hook_event_name === "UserPromptSubmit" && kind) {
    emitContext("UserPromptSubmit", contextFor("UserPromptSubmit", kind));
  }
} catch { /* Advisory only; malformed input must not crash or authorize anything. */ } }
if (require.main === module) main();
