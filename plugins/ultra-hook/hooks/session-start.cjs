#!/usr/bin/env node
"use strict";
const { readEvent } = require("./hook-io.cjs");
const { emitContext } = require("./model-routing.cjs");
async function main() { try {
  const input = await readEvent();
  if (input.hook_event_name === "SessionStart") emitContext("SessionStart");
} catch { /* Advisory only; never inspect previous sessions or start old work. */ } }
main();
