"use strict";

const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("rigger", {
  getConfig: () => ipcRenderer.invoke("config:get"),
  // Electron 32+ removed File.path; resolve a dropped File to its disk path.
  pathForFile: (file) => webUtils.getPathForFile(file),
  openModel: () => ipcRenderer.invoke("dialog:openModel"),
  saveModel: (srcPath) => ipcRenderer.invoke("dialog:saveModel", srcPath),
  runRig: (inputPath) => ipcRenderer.invoke("rig:run", inputPath),
  onLog: (cb) => {
    const listener = (_e, entry) => cb(entry);
    ipcRenderer.on("rig:log", listener);
    return () => ipcRenderer.removeListener("rig:log", listener);
  },
});
