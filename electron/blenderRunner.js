"use strict";

const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

const PROJECT_ROOT = path.resolve(__dirname, "..");

/** Read config.json, with sane fallbacks and auto-detection of Blender. */
function loadConfig() {
  const cfgPath = path.join(PROJECT_ROOT, "config.json");
  let cfg = {};
  try {
    cfg = JSON.parse(fs.readFileSync(cfgPath, "utf-8"));
  } catch {
    /* fall through to detection */
  }
  if (!cfg.blenderPath || !fs.existsSync(cfg.blenderPath)) {
    cfg.blenderPath = detectBlender();
  }
  if (!cfg.targetHeight) cfg.targetHeight = 1.8;
  return cfg;
}

/** Best-effort discovery of blender.exe on Windows. */
function detectBlender() {
  const bases = [
    "C:/Program Files/Blender Foundation",
    "C:/Program Files (x86)/Blender Foundation",
  ];
  for (const base of bases) {
    if (!fs.existsSync(base)) continue;
    const versions = fs
      .readdirSync(base)
      .filter((d) => d.toLowerCase().startsWith("blender"))
      .sort()
      .reverse(); // newest first
    for (const v of versions) {
      const exe = path.join(base, v, "blender.exe");
      if (fs.existsSync(exe)) return exe;
    }
  }
  return "blender"; // hope it's on PATH
}

/**
 * Run the rigging pipeline on an input model.
 * @param {object}   opts
 * @param {string}   [opts.input]   absolute path to the source model (optional)
 * @param {string}   opts.output    absolute path for the rigged .glb
 * @param {function} [opts.onLog]   called with each parsed log line {stage,msg}
 * @returns {Promise<{output:string}>}
 */
function runRig({ input, output, onLog }) {
  return new Promise((resolve, reject) => {
    const cfg = loadConfig();
    const pipeline = path.join(PROJECT_ROOT, "backend", "pipeline.py");

    const job = {
      output,
      target_height: cfg.targetHeight,
    };
    if (input) job.input = input;

    const jobFile = path.join(os.tmpdir(), `rigjob_${process.pid}_${Date.now()}.json`);
    fs.writeFileSync(jobFile, JSON.stringify(job));

    const args = ["--background", "--python", pipeline, "--", jobFile];
    const proc = spawn(cfg.blenderPath, args, { windowsHide: true });

    let stderr = "";
    let failed = false;

    const handleLine = (line) => {
      const m = line.match(/^\[RIG\]\s+([^:]+):\s+(.*)$/);
      if (m) {
        const stage = m[1].trim();
        const msg = m[2].trim();
        if (stage === "ERROR") failed = true;
        if (onLog) onLog({ stage, msg });
      }
    };

    const pump = (buf) =>
      buf
        .toString()
        .split(/\r?\n/)
        .filter(Boolean)
        .forEach(handleLine);

    proc.stdout.on("data", pump);
    proc.stderr.on("data", (d) => {
      stderr += d.toString();
      pump(d);
    });

    proc.on("error", (err) =>
      reject(new Error(`Failed to launch Blender (${cfg.blenderPath}): ${err.message}`))
    );

    proc.on("close", (code) => {
      try {
        fs.unlinkSync(jobFile);
      } catch {
        /* ignore */
      }
      if (failed || code !== 0 || !fs.existsSync(output)) {
        reject(new Error(`Rigging failed (exit ${code}).\n${stderr.slice(-2000)}`));
      } else {
        resolve({ output });
      }
    });
  });
}

module.exports = { runRig, loadConfig, detectBlender };
