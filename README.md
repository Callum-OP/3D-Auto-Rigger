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
                 (landmarks.py, markers.py, bone_naming.py, face_shapekeys.py)
tools/           dev/validation scripts run in Blender (preview_pose.py,
                 preview_face.py, read_bones.py)
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

To also generate facial blendshapes, tick **Facial shape keys (ARKit 52)** in the
editor, switch the overlay to **Face** (zooms onto the head), drag the face
anchors onto eyes / brows / nose / lips / chin, then Build. The output carries
both the armature and the 52 ARKit shape keys on one mesh.

Headless / no UI:

```sh
npm run rig -- path/to/model.glb  rigged.glb
npm run rig                       # rig a generated test figure
npm run face -- path/to/model.glb face.glb   # ARKit-52 shape keys only, no rig
```

## How it works

1. **Prep** — Blender renders a front view and auto-detects joint positions
   from horizontal mesh cross-sections (`backend/landmarks.py`).
2. **Edit** — the browser shows the front view with draggable markers
   (Mixamo-style); you correct any that are off (left/right mirror optional).
3. **Build** — Blender fits the humanoid skeleton to your markers, skins it via
   a watertight voxel-proxy weight transfer with region masking, and exports
   GLB + FBX.
4. **Face (optional)** — from the face markers, `backend/face_shapekeys.py`
   builds the 52 ARKit blendshapes as shape keys (marker-driven: each anchor
   snaps to the surface and defines a deformation region; jaw/eyes/brows/mouth
   recipes in `arkit.py` order). Validate with `tools/preview_face.py`.

## Supported input formats

`.glb` · `.gltf` · `.obj` · `.fbx`

## Notes on the rigging engine

The output skeleton uses a standard Mixamo-style **Humanoid** hierarchy
(`Hips → Spine → Spine1 → Spine2 → Neck → Head`, mirrored arms/legs with 3-bone
fingers and toes) so rigs are usable broadly — game engines, DCC tools, and
figure-posing apps alike. A "Standard bones" option emits a lowercase
`*_bb_` standard-bone naming so compatible figure apps auto-recognize the rig.
