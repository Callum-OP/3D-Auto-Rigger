#!/usr/bin/env node
"use strict";

// Headless CLI wrapper around the same pipeline the app uses.
//   npm run rig -- <input> [output]
//   npm run rig                       (rigs a generated test figure)

const path = require("path");
const { runRig } = require("../electron/blenderRunner");

async function main() {
  const args = process.argv.slice(2);
  const input = args[0] ? path.resolve(args[0]) : undefined;
  const output = args[1]
    ? path.resolve(args[1])
    : path.resolve("out_rigged.glb");

  console.log(`Rigging ${input || "(test figure)"} -> ${output}`);
  try {
    await runRig({
      input,
      output,
      onLog: ({ stage, msg }) => console.log(`  ${stage.padEnd(10)} ${msg}`),
    });
    console.log(`\nDone: ${output}`);
  } catch (err) {
    console.error(`\nFailed: ${err.message}`);
    process.exit(1);
  }
}

main();
