"use strict";

// Local web UI for the auto-rigger.
//
// Runs on Node's built-in http server (no extra binaries) and drives Blender
// through blenderRunner. The browser (Edge/Chrome) loads the page and talks to
// these endpoints via fetch — so nothing unsigned ever launches, which keeps it
// compatible with Windows Smart App Control / Device Guard.

const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");
const { runJob, loadConfig } = require("./blenderRunner");

const ROOT = path.resolve(__dirname, "..");
const WEB = path.join(ROOT, "web");
const PORT = 4317;

const sessions = new Map(); // session token -> { modelPath|null }
const files = new Map();    // file token   -> absolute temp path

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
  ".png": "image/png", ".glb": "model/gltf-binary", ".fbx": "application/octet-stream",
  ".json": "application/json",
};

const tmp = (name) => path.join(os.tmpdir(), name);
const tok = () => crypto.randomBytes(8).toString("hex");

function sendJSON(res, code, obj) {
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(JSON.stringify(obj));
}

function sendFile(res, abs, { download } = {}) {
  if (!abs || !fs.existsSync(abs)) { res.writeHead(404); return res.end("not found"); }
  const ext = path.extname(abs).toLowerCase();
  const headers = { "Content-Type": MIME[ext] || "application/octet-stream" };
  if (download) headers["Content-Disposition"] = `attachment; filename="rigged${ext}"`;
  res.writeHead(200, headers);
  fs.createReadStream(abs).pipe(res);
}

function registerFile(abs) {
  const t = tok() + path.extname(abs).toLowerCase();
  files.set(t, abs);
  return t;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

// --- handlers ------------------------------------------------------------- //
async function handlePrep(req, res, url) {
  const isTest = url.searchParams.get("test") === "1";
  const stamp = Date.now();
  let modelPath = null;
  if (!isTest) {
    const ext = (url.searchParams.get("ext") || "glb").replace(/[^a-z0-9]/gi, "");
    const body = await readBody(req);
    if (!body.length) return sendJSON(res, 400, { error: "empty model upload" });
    modelPath = tmp(`uprig_${stamp}.${ext}`);
    fs.writeFileSync(modelPath, body);
  }
  const markersJson = tmp(`uprig_markers_${stamp}.json`);
  const frontPng = tmp(`uprig_front_${stamp}.png`);
  const fields = { mode: "prep", output: markersJson, front_png: frontPng };
  if (modelPath) fields.input = modelPath;

  await runJob(fields, (e) => console.log(`[prep] ${e.stage}: ${e.msg}`));
  const data = JSON.parse(fs.readFileSync(markersJson, "utf-8"));

  const session = tok();
  sessions.set(session, { modelPath });
  sendJSON(res, 200, {
    token: session,
    markers: data.markers,
    calib: data.calib,
    frontUrl: "/files/" + registerFile(frontPng),
  });
}

async function handleRig(req, res) {
  const body = JSON.parse((await readBody(req)).toString("utf-8") || "{}");
  const sess = sessions.get(body.token);
  if (!sess) return sendJSON(res, 400, { error: "unknown session — run prep first" });

  const out = tmp(`uprig_rigged_${Date.now()}.glb`);
  const fields = { output: out, fingers: body.fingers !== false };
  if (sess.modelPath) fields.input = sess.modelPath;
  if (body.markers && body.calib) { fields.markers = body.markers; fields.calib = body.calib; }

  await runJob(fields, (e) => console.log(`[rig] ${e.stage}: ${e.msg}`));

  const glbTok = registerFile(out);
  const resp = { glbUrl: "/files/" + glbTok, glbDownload: "/download/" + glbTok };
  const fbx = out.replace(/\.glb$/i, ".fbx");
  if (fs.existsSync(fbx)) resp.fbxDownload = "/download/" + registerFile(fbx);
  sendJSON(res, 200, resp);
}

// --- router --------------------------------------------------------------- //
const STATIC = {
  "/": path.join(WEB, "index.html"),
  "/index.html": path.join(WEB, "index.html"),
  "/app.js": path.join(WEB, "app.js"),
  "/styles.css": path.join(WEB, "styles.css"),
  "/vendor/model-viewer.min.js":
    path.join(ROOT, "node_modules", "@google", "model-viewer", "dist", "model-viewer.min.js"),
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const p = url.pathname;
  try {
    if (req.method === "GET" && STATIC[p]) return sendFile(res, STATIC[p]);
    if (req.method === "GET" && p === "/api/config")
      return sendJSON(res, 200, { blender: loadConfig().blenderPath });
    if (req.method === "POST" && p === "/api/prep") return handlePrep(req, res, url);
    if (req.method === "POST" && p === "/api/rig") return handleRig(req, res);
    if (req.method === "GET" && p.startsWith("/files/"))
      return sendFile(res, files.get(p.slice(7)));
    if (req.method === "GET" && p.startsWith("/download/"))
      return sendFile(res, files.get(p.slice(10)), { download: true });
    res.writeHead(404); res.end("not found");
  } catch (e) {
    console.error(e);
    sendJSON(res, 500, { error: String(e.message || e) });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  const link = `http://localhost:${PORT}`;
  console.log(`\n  3D Auto Rigger — open in your browser:\n  ${link}\n`);
  // `start` is a cmd builtin (cmd.exe is a signed Windows binary), so opening
  // the default browser doesn't launch anything unsigned.
  if (!process.env.NO_OPEN) {
    try { require("child_process").exec(`start "" "${link}"`); } catch { /* ignore */ }
  }
});
