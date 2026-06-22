# 3D Auto Rigger

Desktop app that takes a humanoid 3D model and automatically outputs a rigged,
skinned model ready for animation. Electron front end, Blender (headless) as the
rigging engine.

## Status — v0.1 (scaffold)

End-to-end pipeline works: **import → normalize → fit humanoid skeleton →
automatic skin weights → export GLB**. The skeleton is currently fit
*heuristically* from the mesh bounding box using standard body proportions.
This is the seam where a smarter rigger (RigNet / SMPL-fit / landmark detection)
will plug in — see `backend/pipeline.py:build_skeleton`.

## Architecture

```
renderer/        Electron UI (drag-drop, 3D preview via <model-viewer>, log)
electron/        Electron main process + Blender runner (spawns headless Blender)
backend/         pipeline.py — the actual rigging pipeline, run inside Blender
scripts/cli.js   headless CLI wrapper around the same pipeline
config.json      Blender path + default target height
```

The UI never touches Blender directly: it writes a job JSON, spawns
`blender --background --python backend/pipeline.py -- job.json`, and parses the
`[RIG] stage: message` log lines for progress.

## Prerequisites

- **Blender 5.0** (detected at `C:/Program Files/Blender Foundation/Blender 5.0`;
  override in `config.json`)
- **Node.js** (for Electron)

## Setup & run

```sh
npm install
npm start          # launch the desktop app
```

Headless / no UI:

```sh
npm run rig -- path/to/model.glb  rigged.glb
npm run rig                       # rig a generated test figure
```

## Supported input formats

`.glb` · `.gltf` · `.obj` · `.fbx`

## Roadmap

1. **(done)** End-to-end pipeline + UI scaffold with heuristic skeleton.
2. Pose/scale normalization hardening (T/A-pose detection, up-axis).
3. Real auto-rig: integrate RigNet (non-commercial) or a Blender-native
   landmark-fit rigger for production-safe licensing.
4. Manual landmark-nudge fallback (Mixamo-style) for tricky meshes.
5. Add a test idle/wave animation clip so the preview visibly moves.
6. Facial shape-keys module (ARKit blendshape transfer).

## Notes on the rigging engine

The output skeleton uses a Mixamo/Unreal-style **Humanoid** bone hierarchy
(`Hips → Spine → Chest → Neck → Head`, mirrored arms/legs) so rigs are usable
in Unity/Unreal/game engines downstream.
