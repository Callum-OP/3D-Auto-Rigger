"use strict";

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const browseBtn = document.getElementById("browseBtn");
const testBtn = document.getElementById("testBtn");
const rigBtn = document.getElementById("rigBtn");
const buildBtn = document.getElementById("buildBtn");
const backBtn = document.getElementById("backBtn");
const saveBtn = document.getElementById("saveBtn");
const saveFbxBtn = document.getElementById("saveFbxBtn");
const inputName = document.getElementById("inputName");
const viewer = document.getElementById("viewer");
const viewerPlaceholder = document.getElementById("viewerPlaceholder");
const editor = document.getElementById("editor");
const editorImg = document.getElementById("editorImg");
const markerLayer = document.getElementById("markerLayer");
const mirrorChk = document.getElementById("mirrorChk");
const logEl = document.getElementById("log");

let selectedFile = null;          // File or null (test figure)
let token = null;                 // prep session token
let markers = null, calib = null; // marker positions + pixel<->world calibration
let glbDownload = null, fbxDownload = null;
let busy = false;

const VALID_EXT = ["glb", "gltf", "obj", "fbx"];
const CENTER = new Set(["head_top", "neck", "chest", "hip"]);
const LABELS = {
  head_top: "head", neck: "neck", chest: "chest", hip: "hips",
  shoulder_l: "L shoulder", shoulder_r: "R shoulder",
  elbow_l: "L elbow", elbow_r: "R elbow",
  wrist_l: "L wrist", wrist_r: "R wrist",
  knee_l: "L knee", knee_r: "R knee",
  ankle_l: "L ankle", ankle_r: "R ankle",
};

// --- logging -------------------------------------------------------------- //
function addLog(stage, msg, kind = "") {
  const li = document.createElement("li");
  li.className = `log-line ${kind}`;
  li.innerHTML = `<span class="log-stage"></span><span class="log-msg"></span>`;
  li.querySelector(".log-stage").textContent = stage;
  li.querySelector(".log-msg").textContent = msg;
  logEl.appendChild(li);
  logEl.scrollTop = logEl.scrollHeight;
}
const clearLog = () => (logEl.innerHTML = "");

function setInput(file) {
  selectedFile = file;
  inputName.textContent = file ? file.name : "test figure (generated)";
  rigBtn.disabled = busy;
}

// --- phases --------------------------------------------------------------- //
function setPhase(phase) {
  const editing = phase === "editing";
  editor.classList.toggle("hidden", !editing);
  rigBtn.classList.toggle("hidden", editing);
  buildBtn.classList.toggle("hidden", !editing);
  backBtn.classList.toggle("hidden", !editing);
  if (editing) viewerPlaceholder.style.display = "none";
}

// --- drag & drop + browse ------------------------------------------------- //
["dragenter", "dragover"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("hover"); })
);
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("hover"); })
);
dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) acceptFile(file);
});
browseBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => { if (fileInput.files[0]) acceptFile(fileInput.files[0]); });

function acceptFile(file) {
  const ext = file.name.split(".").pop().toLowerCase();
  if (!VALID_EXT.includes(ext)) return addLog("ERROR", `Unsupported file type: .${ext}`, "error");
  setInput(file);
}

testBtn.addEventListener("click", () => { setInput(null); startPrep(); });
rigBtn.addEventListener("click", startPrep);
buildBtn.addEventListener("click", startRig);
backBtn.addEventListener("click", () => setPhase("input"));
saveBtn.addEventListener("click", () => { if (glbDownload) window.location.href = glbDownload; });
saveFbxBtn.addEventListener("click", () => { if (fbxDownload) window.location.href = fbxDownload; });

// --- phase 1: prep -------------------------------------------------------- //
async function startPrep() {
  if (busy) return;
  busy = true;
  rigBtn.disabled = true; testBtn.disabled = true;
  saveBtn.disabled = true; saveFbxBtn.disabled = true;
  clearLog();
  addLog("prep", "rendering front view + detecting joints… (~15s)");
  try {
    let url = "/api/prep", opts = { method: "POST" };
    if (selectedFile) {
      const ext = selectedFile.name.split(".").pop().toLowerCase();
      url += "?ext=" + encodeURIComponent(ext);
      opts.body = await selectedFile.arrayBuffer();
      opts.headers = { "Content-Type": "application/octet-stream" };
    } else {
      url += "?test=1";
    }
    const data = await jsonFetch(url, opts);
    token = data.token;
    markers = data.markers;
    calib = data.calib;
    editorImg.src = data.frontUrl;
    renderMarkers();
    setPhase("editing");
    addLog("prep", "drag the dots onto the joints, then Build rig", "ok");
  } catch (err) {
    addLog("ERROR", String(err.message || err), "error");
  } finally {
    busy = false;
    rigBtn.disabled = false; testBtn.disabled = false;
  }
}

function renderMarkers() {
  markerLayer.innerHTML = "";
  for (const name of Object.keys(markers)) {
    const dot = document.createElement("div");
    dot.className = "marker" + (CENTER.has(name) ? " marker-center" : "");
    dot.dataset.name = name;
    const label = document.createElement("span");
    label.className = "marker-label";
    label.textContent = LABELS[name] || name;
    dot.appendChild(label);
    positionDot(dot, markers[name]);
    attachDrag(dot, name);
    markerLayer.appendChild(dot);
  }
}

function positionDot(dot, [px, py]) {
  dot.style.left = (px / calib.res) * 100 + "%";
  dot.style.top = (py / calib.res) * 100 + "%";
}
function refreshDots() {
  for (const dot of markerLayer.children) positionDot(dot, markers[dot.dataset.name]);
}
function mirror(name, px, py) {
  if (!mirrorChk.checked) return;
  if (name.endsWith("_l")) {
    const r = name.slice(0, -2) + "_r";
    if (markers[r]) markers[r] = [calib.res - px, py];
  } else if (name.endsWith("_r")) {
    const l = name.slice(0, -2) + "_l";
    if (markers[l]) markers[l] = [calib.res - px, py];
  }
}
function attachDrag(dot, name) {
  dot.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    const move = (ev) => {
      const rect = markerLayer.getBoundingClientRect();
      let fx = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
      const fy = Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height));
      let px = fx * calib.res;
      const py = fy * calib.res;
      if (CENTER.has(name)) px = calib.res / 2;
      markers[name] = [px, py];
      mirror(name, px, py);
      refreshDots();
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  });
}

// --- phase 2: build rig --------------------------------------------------- //
async function startRig() {
  if (busy) return;
  busy = true;
  buildBtn.disabled = true; backBtn.disabled = true;
  addLog("rig", "building rig… (~15s)");
  try {
    const data = await jsonFetch("/api/rig", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, markers, calib }),
    });
    glbDownload = data.glbDownload;
    fbxDownload = data.fbxDownload || null;
    setPhase("result");
    viewer.src = data.glbUrl;
    viewerPlaceholder.style.display = "none";
    saveBtn.disabled = false;
    saveFbxBtn.disabled = !fbxDownload;
    addLog("ready", "Rigged model loaded in preview", "ok");
  } catch (err) {
    addLog("ERROR", String(err.message || err), "error");
  } finally {
    busy = false;
    buildBtn.disabled = false; backBtn.disabled = false;
  }
}

async function jsonFetch(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).error || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

// init
setInput(null);
setPhase("input");
fetch("/api/config").then((r) => r.json()).then((c) =>
  addLog("blender", c.blender || "(auto-detect)")
).catch(() => {});
