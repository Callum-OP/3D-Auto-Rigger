"use strict";

const dropzone = document.getElementById("dropzone");
const browseBtn = document.getElementById("browseBtn");
const testBtn = document.getElementById("testBtn");
const rigBtn = document.getElementById("rigBtn");
const saveBtn = document.getElementById("saveBtn");
const inputName = document.getElementById("inputName");
const viewer = document.getElementById("viewer");
const viewerPlaceholder = document.getElementById("viewerPlaceholder");
const logEl = document.getElementById("log");

let inputPath = null; // null === use the generated test figure
let lastOutput = null;
let busy = false;

const VALID_EXT = ["glb", "gltf", "obj", "fbx"];

function setInput(p) {
  inputPath = p;
  inputName.textContent = p ? p.replace(/^.*[\\/]/, "") : "test figure (generated)";
  rigBtn.disabled = busy;
}

function addLog(stage, msg, kind = "") {
  const li = document.createElement("li");
  li.className = `log-line ${kind}`;
  li.innerHTML = `<span class="log-stage">${stage}</span><span class="log-msg"></span>`;
  li.querySelector(".log-msg").textContent = msg;
  logEl.appendChild(li);
  logEl.scrollTop = logEl.scrollHeight;
}

function clearLog() {
  logEl.innerHTML = "";
}

function fileToPath(file) {
  try {
    return window.rigger.pathForFile(file);
  } catch {
    return null;
  }
}

// --- drag & drop ---------------------------------------------------------- //
["dragenter", "dragover"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.add("hover");
  })
);
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.remove("hover");
  })
);
dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (!file) return;
  const ext = file.name.split(".").pop().toLowerCase();
  if (!VALID_EXT.includes(ext)) {
    addLog("ERROR", `Unsupported file type: .${ext}`, "error");
    return;
  }
  const p = fileToPath(file);
  if (!p) {
    addLog("ERROR", "Could not resolve dropped file path.", "error");
    return;
  }
  setInput(p);
});

// --- buttons -------------------------------------------------------------- //
browseBtn.addEventListener("click", async () => {
  const p = await window.rigger.openModel();
  if (p) setInput(p);
});

testBtn.addEventListener("click", () => {
  setInput(null);
  runRig();
});

rigBtn.addEventListener("click", runRig);

saveBtn.addEventListener("click", async () => {
  if (!lastOutput) return;
  const dest = await window.rigger.saveModel(lastOutput);
  if (dest) addLog("saved", dest, "ok");
});

// --- run the pipeline ----------------------------------------------------- //
async function runRig() {
  if (busy) return;
  busy = true;
  rigBtn.disabled = true;
  testBtn.disabled = true;
  saveBtn.disabled = true;
  clearLog();
  addLog("start", inputPath ? inputName.textContent : "test figure");

  try {
    const { output } = await window.rigger.runRig(inputPath);
    lastOutput = output;
    showResult(output);
    saveBtn.disabled = false;
    addLog("ready", "Rigged model loaded in preview", "ok");
  } catch (err) {
    addLog("ERROR", String(err.message || err), "error");
  } finally {
    busy = false;
    rigBtn.disabled = false;
    testBtn.disabled = false;
  }
}

function showResult(outPath) {
  // model-viewer needs a URL; build a file:// URL from the absolute path.
  const url = "file:///" + outPath.replace(/\\/g, "/").replace(/^\/+/, "");
  viewer.src = url;
  viewerPlaceholder.style.display = "none";
}

// --- pipeline log stream -------------------------------------------------- //
window.rigger.onLog(({ stage, msg }) => {
  addLog(stage, msg, stage === "ERROR" ? "error" : "");
});

// init
setInput(null);
window.rigger.getConfig().then((cfg) => {
  addLog("blender", cfg.blenderPath || "(auto-detect)");
});
