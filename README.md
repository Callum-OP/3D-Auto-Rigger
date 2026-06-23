# 3D Auto Rigger

Takes a humanoid 3D model and automatically outputs a rigged, skinned model
ready for animation. **Local web app** front end (runs in your browser),
Blender (headless) as the rigging engine.

## Architecture

```
web/             Browser UI: drag-drop, draggable joint-marker editor,
                 3D preview via <model-viewer>
scripts/server.js  Local Node web server (built-in http) — serves web/ and
                   drives Blender; the browser talks to it over fetch
scripts/blenderRunner.js  spawns headless Blender with a job JSON
scripts/cli.js   headless CLI wrapper around the same pipeline
backend/         pipeline.py — the rigging pipeline, run inside Blender
                 (landmarks.py, markers.py, csp_bones.py, preview_pose.py)
config.json      Blender path + default target height
```

Nothing unsigned is ever launched: only `node.exe` (the server) and your
browser run — both signed/allowed by Windows Smart App Control. The server
writes a job JSON and spawns `blender --background --python backend/pipeline.py
-- job.json`; Blender does the rigging.

## Prerequisites

- **Blender 5.0** (auto-detected at `C:/Program Files/Blender Foundation/Blender 5.0`;
  override in `config.json`)
- **Node.js**

## Setup & run

```sh
npm install
npm start          # starts the local server and opens http://localhost:4317
```

Then in the browser: drop a model (or "Rig a test figure") → **Rig model** →
drag the joint markers onto the right spots → **Build rig** → download the
`.glb` / `.fbx`.

Headless / no UI:

```sh
npm run rig -- path/to/model.glb  rigged.glb
npm run rig                       # rig a generated test figure
```

## How it works

1. **Prep** — Blender renders a front view and auto-detects joint positions
   from horizontal mesh cross-sections (`backend/landmarks.py`).
2. **Edit** — the browser shows the front view with draggable markers
   (Mixamo-style); you correct any that are off (left/right mirror optional).
3. **Build** — Blender fits the humanoid skeleton to your markers, skins it via
   a watertight voxel-proxy weight transfer with region masking, and exports
   GLB + FBX.

## Supported input formats

`.glb` · `.gltf` · `.obj` · `.fbx`

## Notes on the rigging engine

The output skeleton uses a standard Mixamo-style **Humanoid** hierarchy
(`Hips → Spine → Spine1 → Spine2 → Neck → Head`, mirrored arms/legs with 3-bone
fingers and toes) so rigs are usable broadly — game engines, DCC tools, and
figure apps (e.g. Clip Studio) alike.
