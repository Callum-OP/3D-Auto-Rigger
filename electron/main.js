"use strict";

const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const path = require("path");
const os = require("os");
const fs = require("fs");
const { runRig, loadConfig } = require("./blenderRunner");

let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    backgroundColor: "#1a1a1f",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.setMenuBarVisibility(false);
  mainWindow.loadFile(path.join(__dirname, "..", "renderer", "index.html"));
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// --- IPC ------------------------------------------------------------------ //

ipcMain.handle("config:get", () => loadConfig());

ipcMain.handle("dialog:openModel", async () => {
  const res = await dialog.showOpenDialog(mainWindow, {
    title: "Select a 3D model",
    properties: ["openFile"],
    filters: [{ name: "3D models", extensions: ["glb", "gltf", "obj", "fbx"] }],
  });
  if (res.canceled || !res.filePaths.length) return null;
  return res.filePaths[0];
});

ipcMain.handle("rig:run", async (event, inputPath) => {
  const base = inputPath
    ? path.basename(inputPath).replace(/\.[^.]+$/, "")
    : "test_human";
  const output = path.join(os.tmpdir(), `${base}_rigged_${Date.now()}.glb`);

  await runRig({
    input: inputPath || undefined,
    output,
    onLog: (entry) => event.sender.send("rig:log", entry),
  });

  return { output };
});

ipcMain.handle("dialog:saveModel", async (event, srcPath) => {
  const res = await dialog.showSaveDialog(mainWindow, {
    title: "Save rigged model",
    defaultPath: "rigged.glb",
    filters: [{ name: "glTF binary", extensions: ["glb"] }],
  });
  if (res.canceled || !res.filePath) return null;
  fs.copyFileSync(srcPath, res.filePath);
  return res.filePath;
});
