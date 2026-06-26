"use strict";

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const browseBtn = document.getElementById("browseBtn");
const testBtn = document.getElementById("testBtn");
const rigBtn = document.getElementById("rigBtn");
const buildBtn = document.getElementById("buildBtn");
const backBtn = document.getElementById("backBtn");
const fingersChk = document.getElementById("fingersChk");
const fingersRow = document.getElementById("fingersRow");
const saveBtn = document.getElementById("saveBtn");
const saveFbxBtn = document.getElementById("saveFbxBtn");
const inputName = document.getElementById("inputName");
const viewer = document.getElementById("viewer");
const viewerPlaceholder = document.getElementById("viewerPlaceholder");
const editor = document.getElementById("editor");
const editorImg = document.getElementById("editorImg");
const editorStage = document.getElementById("editorStage");
const markerLayer = document.getElementById("markerLayer");
const mirrorChk = document.getElementById("mirrorChk");
const faceRow = document.getElementById("faceRow");
const faceChk = document.getElementById("faceChk");
const modeRow = document.getElementById("modeRow");
const bodyModeBtn = document.getElementById("bodyModeBtn");
const faceModeBtn = document.getElementById("faceModeBtn");
const editorHint = document.getElementById("editorHint");
const typeBodyBtn = document.getElementById("typeBodyBtn");
const typeHeadBtn = document.getElementById("typeHeadBtn");
const zoomCtl = document.getElementById("zoomCtl");
const zoomInBtn = document.getElementById("zoomInBtn");
const zoomOutBtn = document.getElementById("zoomOutBtn");
const groupCtl = document.getElementById("groupCtl");
const grpScaleUp = document.getElementById("grpScaleUp");
const grpScaleDown = document.getElementById("grpScaleDown");
const resetBtn = document.getElementById("resetBtn");
const logEl = document.getElementById("log");

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const cloneMarkers = (m) => (m ? JSON.parse(JSON.stringify(m)) : null);

let bodyMarkersOrig = null, faceMarkersOrig = null;  // auto-detected, for Reset
let selected = new Set();                            // box-selected marker names

let selectedFile = null;          // File or null (test figure)
let token = null;                 // prep session token
let bodyMarkers = null, faceMarkers = null;  // the two editable marker sets
let calib = null;                 // pixel<->world calibration (shared)
let editMode = "body";            // which set the overlay is editing
let inputType = "body";           // "body" (rig) or "head" (face shapes only)
let faceZoomMult = 1;             // user zoom multiplier on top of the auto-fit
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

// Face anchors (ARKit shape-key markers). Center anchors stay on the midline.
const FACE_CENTER = new Set(["nose_tip", "upper_lip", "lower_lip", "chin"]);
const FACE_LABELS = {
  nose_tip: "nose", upper_lip: "top lip", lower_lip: "bottom lip", chin: "chin",
  brow_inner_l: "L inner brow", brow_inner_r: "R inner brow",
  brow_outer_l: "L outer brow", brow_outer_r: "R outer brow",
  eye_inner_l: "L eye inner", eye_inner_r: "R eye inner",
  eye_outer_l: "L eye outer", eye_outer_r: "R eye outer",
  eye_top_l: "L lid top", eye_top_r: "R lid top",
  eye_bottom_l: "L lid bottom", eye_bottom_r: "R lid bottom",
  cheek_l: "L cheek", cheek_r: "R cheek",
  nostril_l: "L nostril", nostril_r: "R nostril",
  mouth_corner_l: "L mouth", mouth_corner_r: "R mouth",
};

// The active marker set / center-set / labels, per current edit mode.
const cur = () => (editMode === "face" ? faceMarkers : bodyMarkers);
const curCenter = () => (editMode === "face" ? FACE_CENTER : CENTER);
const curLabels = () => (editMode === "face" ? FACE_LABELS : LABELS);

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
  const head = inputType === "head";
  editor.classList.toggle("hidden", !editing);
  rigBtn.classList.toggle("hidden", editing);
  buildBtn.classList.toggle("hidden", !editing);
  backBtn.classList.toggle("hidden", !editing);
  resetBtn.classList.toggle("hidden", !editing);
  // Body-only controls: fingers + the "add face shapes" opt-in.
  fingersRow.classList.toggle("hidden", !editing || head);
  faceRow.classList.toggle("hidden", !editing || head);
  if (editing) viewerPlaceholder.style.display = "none";

  if (!editing) {
    modeRow.classList.add("hidden");
    zoomCtl.classList.add("hidden");
    setMode("body");
    return;
  }

  buildBtn.textContent = head ? "Build face shapes" : "Build rig from markers";
  modeRow.classList.add("hidden");      // the body/face switch is body-mode only
  if (head) {
    faceChk.checked = true;             // head-only always builds face shapes
    setMode("face");
  } else {
    setMode("body");
  }
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
    if (inputType === "head") url += "&headOnly=1";
    const data = await jsonFetch(url, opts);
    token = data.token;
    bodyMarkers = data.markers;
    faceMarkers = data.faceMarkers || null;
    calib = data.calib;
    editorImg.src = data.frontUrl;
    bodyMarkersOrig = cloneMarkers(data.markers);
    faceMarkersOrig = cloneMarkers(data.faceMarkers || null);
    selected.clear();
    faceChk.checked = false;
    faceZoomMult = 1;
    setPhase("editing");
    addLog("prep", "drag the markers into place, then Build", "ok");
  } catch (err) {
    addLog("ERROR", String(err.message || err), "error");
  } finally {
    busy = false;
    rigBtn.disabled = false; testBtn.disabled = false;
  }
}

function renderMarkers() {
  markerLayer.innerHTML = "";
  const set = cur(), center = curCenter(), labels = curLabels();
  if (!set) return;
  for (const name of Object.keys(set)) {
    const dot = document.createElement("div");
    dot.className = "marker" + (center.has(name) ? " marker-center" : "")
      + (selected.has(name) ? " selected" : "");
    dot.dataset.name = name;
    const label = document.createElement("span");
    label.className = "marker-label";
    label.textContent = labels[name] || name;
    dot.appendChild(label);
    positionDot(dot, set[name]);
    attachDrag(dot, name);
    markerLayer.appendChild(dot);
  }
}

function positionDot(dot, [px, py]) {
  dot.style.left = (px / calib.res) * 100 + "%";
  dot.style.top = (py / calib.res) * 100 + "%";
}
function refreshDots() {
  const set = cur();
  for (const dot of markerLayer.children) positionDot(dot, set[dot.dataset.name]);
}
function mirror(name, px, py) {
  if (!mirrorChk.checked) return;
  const set = cur();
  if (name.endsWith("_l")) {
    const r = name.slice(0, -2) + "_r";
    if (set[r]) set[r] = [calib.res - px, py];
  } else if (name.endsWith("_r")) {
    const l = name.slice(0, -2) + "_l";
    if (set[l]) set[l] = [calib.res - px, py];
  }
}
function attachDrag(dot, name) {
  dot.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    e.stopPropagation();              // don't also trigger the group-move drag
    // A dot that's part of a multi-selection drags the whole selection;
    // otherwise it clears the selection and moves just itself.
    if (selected.has(name) && selected.size > 0) {
      startGroupDrag(e, [...selected]);
      return;
    }
    if (selected.size) { selected.clear(); updateSelectionClasses(); }
    const move = (ev) => {
      const rect = markerLayer.getBoundingClientRect();
      let fx = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
      const fy = Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height));
      let px = fx * calib.res;
      const py = fy * calib.res;
      if (curCenter().has(name)) px = calib.res / 2;
      cur()[name] = [px, py];
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

// --- body/face mode switch + zoom-to-face --------------------------------- //
function setMode(mode) {
  editMode = faceMarkers ? mode : "body";
  bodyModeBtn.classList.toggle("active", editMode === "body");
  faceModeBtn.classList.toggle("active", editMode === "face");
  editorHint.textContent = editMode === "face"
    ? "Drag a dot · Shift-drag to box-select · drag empty space to move all/selection · ⊕/⊖ scale · scroll to zoom."
    : "Drag each dot onto the matching joint, then Build rig.";
  zoomCtl.classList.toggle("hidden", editMode !== "face");
  groupCtl.classList.toggle("hidden", editMode !== "face");
  selected.clear();
  applyZoom(editMode === "face");
  renderMarkers();
}

function updateSelectionClasses() {
  for (const dot of markerLayer.children)
    dot.classList.toggle("selected", selected.has(dot.dataset.name));
}

// Move a set of markers rigidly by a pixel delta. The delta is clamped to the
// group's bounding box so the cluster STOPS at the border instead of collapsing
// (each-marker clamping would distort the shape).
function moveSet(names, dpx, dpy) {
  const set = cur();
  let minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity;
  for (const k of names) {
    minx = Math.min(minx, set[k][0]); maxx = Math.max(maxx, set[k][0]);
    miny = Math.min(miny, set[k][1]); maxy = Math.max(maxy, set[k][1]);
  }
  dpx = clamp(dpx, -minx, calib.res - maxx);
  dpy = clamp(dpy, -miny, calib.res - maxy);
  for (const k of names) set[k] = [set[k][0] + dpx, set[k][1] + dpy];
  refreshDots();
}

const moveAll = (dpx, dpy) => moveSet(Object.keys(cur()), dpx, dpy);

// Scale markers about their centroid. The factor is capped so the bounding box
// stays in frame (keeps the shape rather than clamping individual dots).
function scaleSet(names, factor) {
  const set = cur();
  let cx = 0, cy = 0;
  names.forEach((k) => { cx += set[k][0]; cy += set[k][1]; });
  cx /= names.length; cy /= names.length;
  let hx = 1e-6, hy = 1e-6;
  names.forEach((k) => {
    hx = Math.max(hx, Math.abs(set[k][0] - cx));
    hy = Math.max(hy, Math.abs(set[k][1] - cy));
  });
  const maxf = Math.min(cx / hx, (calib.res - cx) / hx, cy / hy, (calib.res - cy) / hy);
  factor = Math.min(factor, maxf);
  for (const k of names)
    set[k] = [cx + (set[k][0] - cx) * factor, cy + (set[k][1] - cy) * factor];
  refreshDots();
}

const scaleAll = (factor) =>
  scaleSet(selected.size ? [...selected] : Object.keys(cur()), factor);

// Drag a group of markers rigidly; clears the selection on a click-without-move.
function startGroupDrag(e, names) {
  const rect = markerLayer.getBoundingClientRect();
  let last = { x: e.clientX, y: e.clientY }, moved = false;
  const move = (ev) => {
    const dpx = ((ev.clientX - last.x) / rect.width) * calib.res;
    const dpy = ((ev.clientY - last.y) / rect.height) * calib.res;
    if (dpx || dpy) moved = true;
    last = { x: ev.clientX, y: ev.clientY };
    moveSet(names, dpx, dpy);
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    if (!moved && selected.size) { selected.clear(); updateSelectionClasses(); }
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

// Shift+drag on empty space → rubber-band select markers inside the rectangle.
function startRubberBand(e) {
  const rect = markerLayer.getBoundingClientRect();
  const toPx = (ev) => [
    clamp(((ev.clientX - rect.left) / rect.width) * calib.res, 0, calib.res),
    clamp(((ev.clientY - rect.top) / rect.height) * calib.res, 0, calib.res),
  ];
  const [sx, sy] = toPx(e);
  const box = document.createElement("div");
  box.className = "select-box";
  markerLayer.appendChild(box);
  const move = (ev) => {
    const [cx, cy] = toPx(ev);
    const x0 = Math.min(sx, cx), x1 = Math.max(sx, cx);
    const y0 = Math.min(sy, cy), y1 = Math.max(sy, cy);
    box.style.left = (x0 / calib.res) * 100 + "%";
    box.style.top = (y0 / calib.res) * 100 + "%";
    box.style.width = ((x1 - x0) / calib.res) * 100 + "%";
    box.style.height = ((y1 - y0) / calib.res) * 100 + "%";
    const set = cur();
    selected.clear();
    for (const k in set) {
      const [px, py] = set[k];
      if (px >= x0 && px <= x1 && py >= y0 && py <= y1) selected.add(k);
    }
    updateSelectionClasses();
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    box.remove();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function resetMarkers() {
  if (editMode === "face") {
    if (faceMarkersOrig) faceMarkers = cloneMarkers(faceMarkersOrig);
  } else if (bodyMarkersOrig) {
    bodyMarkers = cloneMarkers(bodyMarkersOrig);
  }
  selected.clear();
  renderMarkers();
  if (editMode === "face") applyZoom(true);
}

/** Zoom the editor onto the face region (face markers are tiny on a full-body
 *  front view). A CSS scale on the stage keeps the existing drag math valid
 *  (getBoundingClientRect already reports the post-transform box); the dots are
 *  counter-scaled so they stay a constant on-screen size. faceZoomMult is the
 *  user's manual zoom on top of the auto-fit. */
function applyZoom(on) {
  if (!on || !faceMarkers || !calib) {
    editorStage.style.transform = "";
    editorStage.style.transformOrigin = "";
    markerLayer.style.setProperty("--marker-scale", 1);
    return;
  }
  const pts = Object.values(faceMarkers);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const span = Math.max(maxX - minX, maxY - minY) || calib.res;
  const pad = span * 1.1;                              // generous → modest default zoom
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const fit = Math.min(3.2, Math.max(1.2, calib.res / (span + 2 * pad)));
  const z = Math.min(6, Math.max(1, fit * faceZoomMult));
  editorStage.style.transformOrigin = `${(cx / calib.res) * 100}% ${(cy / calib.res) * 100}%`;
  editorStage.style.transform = `scale(${z})`;
  markerLayer.style.setProperty("--marker-scale", 1 / z);
}

function bumpZoom(factor) {
  faceZoomMult = Math.min(3, Math.max(0.5, faceZoomMult * factor));
  applyZoom(true);
}

faceChk.addEventListener("change", () => {
  modeRow.classList.toggle("hidden", !(faceChk.checked && faceMarkers));
  if (!faceChk.checked) setMode("body");
});
bodyModeBtn.addEventListener("click", () => setMode("body"));
faceModeBtn.addEventListener("click", () => setMode("face"));
zoomInBtn.addEventListener("click", () => bumpZoom(1.25));
zoomOutBtn.addEventListener("click", () => bumpZoom(1 / 1.25));
editorStage.addEventListener("wheel", (e) => {
  if (editMode !== "face") return;
  e.preventDefault();
  bumpZoom(e.deltaY < 0 ? 1.15 : 1 / 1.15);
}, { passive: false });
grpScaleUp.addEventListener("click", () => scaleAll(1.08));
grpScaleDown.addEventListener("click", () => scaleAll(1 / 1.08));

// Empty-space interactions in face mode:
//   Shift+drag → rubber-band select a subset · drag → move selection (or all if
//   none selected) · click → clear the selection.
editorStage.addEventListener("pointerdown", (e) => {
  if (editMode !== "face" || e.target.closest(".marker")) return;
  e.preventDefault();
  if (e.shiftKey) { startRubberBand(e); return; }
  startGroupDrag(e, selected.size ? [...selected] : Object.keys(cur()));
});
resetBtn.addEventListener("click", resetMarkers);

// --- input type (body vs head-only) --------------------------------------- //
function setInputType(t) {
  inputType = t;
  typeBodyBtn.classList.toggle("active", t === "body");
  typeHeadBtn.classList.toggle("active", t === "head");
  rigBtn.textContent = t === "head" ? "Place face markers" : "Rig model";
}
typeBodyBtn.addEventListener("click", () => setInputType("body"));
typeHeadBtn.addEventListener("click", () => setInputType("head"));

// --- phase 2: build rig --------------------------------------------------- //
async function startRig() {
  if (busy) return;
  busy = true;
  buildBtn.disabled = true; backBtn.disabled = true;
  addLog(inputType === "head" ? "face" : "rig",
    inputType === "head" ? "building face shapes… (~15s)" : "building rig… (~15s)");
  try {
    const data = await jsonFetch("/api/rig", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token, markers: bodyMarkers, calib, fingers: fingersChk.checked,
        headOnly: inputType === "head",
        faceShapekeys: faceChk.checked,
        faceMarkers: (inputType === "head" || faceChk.checked) ? faceMarkers : undefined,
      }),
    });
    glbDownload = data.glbDownload;
    fbxDownload = data.fbxDownload || null;
    setPhase("result");
    viewer.src = data.glbUrl;
    viewerPlaceholder.style.display = "none";
    saveBtn.disabled = false;
    saveFbxBtn.disabled = !fbxDownload;
    addLog("ready",
      inputType === "head" ? "Face shapes built — loaded in preview"
                           : "Rigged model loaded in preview", "ok");
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
setInputType("body");
setInput(null);
setPhase("input");
fetch("/api/config").then((r) => r.json()).then((c) =>
  addLog("blender", c.blender || "(auto-detect)")
).catch(() => {});
