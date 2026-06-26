#!/usr/bin/env node
"use strict";

// Headless CLI for the face-only stage: add ARKit-52 shape keys to a model.
//   npm run face -- <input> [output]
//   npm run face                       (uses a generated test figure)

const path = require("path");
const { runFace } = require("./blenderRunner");

async function main() {
  const args = process.argv.slice(2);
  const input = args[0] ? path.resolve(args[0]) : undefined;
  const output = args[1]
    ? path.resolve(args[1])
    : path.resolve("out_face.glb");

  console.log(`Adding face shape keys to ${input || "(test figure)"} -> ${output}`);
  try {
    await runFace({
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
