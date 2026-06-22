"""
3DAutoRigger — Blender headless rigging pipeline.

Run via:
    blender --background --python backend/pipeline.py -- <job.json>

The job JSON looks like:
    {
        "input":  "C:/path/to/model.glb",   // optional; omit to use a generated test mesh
        "output": "C:/path/to/rigged.glb",
        "target_height": 1.8                  // metres; mesh is scaled to this
    }

Stages: import -> normalize -> build skeleton -> skin -> export.

This is the v1 engine. The skeleton is fit heuristically from the mesh
bounding box using standard human body proportions. The `build_skeleton`
function is the single seam where a smarter rigger (RigNet / SMPL-fit /
landmark detection) plugs in later — everything up- and down-stream stays
the same.
"""

import bpy
import json
import sys
import os
from mathutils import Vector

# Make sibling modules importable when run via `blender --python backend/pipeline.py`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import landmarks


# --------------------------------------------------------------------------- #
# Logging — prefixed lines so the Electron side can parse progress.
# --------------------------------------------------------------------------- #
def log(stage, msg):
    print(f"[RIG] {stage}: {msg}", flush=True)


def fail(msg):
    print(f"[RIG] ERROR: {msg}", flush=True)
    sys.exit(1)


# --------------------------------------------------------------------------- #
# Scene helpers
# --------------------------------------------------------------------------- #
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_model(path):
    ext = os.path.splitext(path)[1].lower()
    log("import", f"loading {os.path.basename(path)} ({ext})")
    if ext == ".glb" or ext == ".gltf":
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        fail(f"unsupported input format: {ext}")
    # Drop anything that isn't mesh geometry (existing rigs, lights, cameras,
    # empties) so it can't leak into the rigged output.
    meshes = []
    for o in list(bpy.context.scene.objects):
        if o.type == "MESH":
            meshes.append(o)
        else:
            bpy.data.objects.remove(o, do_unlink=True)
    if not meshes:
        fail("no mesh found in the imported file")
    return meshes


def _add_box(name, center, dims):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    o = bpy.context.active_object
    o.name = name
    o.scale = dims
    bpy.ops.object.transform_apply(scale=True)
    return o


def make_test_human():
    """Build a blocky humanoid (T-pose) so landmark detection has real features."""
    log("import", "no input given — generating a test humanoid mesh")
    parts = []
    # head + neck
    parts.append(_add_box("head",  (0, 0, 1.63), (0.20, 0.22, 0.24)))
    parts.append(_add_box("neck",  (0, 0, 1.50), (0.10, 0.10, 0.10)))
    # torso + pelvis
    parts.append(_add_box("torso", (0, 0, 1.20), (0.34, 0.20, 0.50)))
    parts.append(_add_box("pelvis", (0, 0, 0.93), (0.30, 0.18, 0.16)))
    # arms (T-pose: horizontal along X) + hands
    parts.append(_add_box("arm_L",  (0.44, 0, 1.40), (0.52, 0.09, 0.09)))
    parts.append(_add_box("arm_R", (-0.44, 0, 1.40), (0.52, 0.09, 0.09)))
    parts.append(_add_box("hand_L",  (0.74, 0, 1.40), (0.10, 0.12, 0.12)))
    parts.append(_add_box("hand_R", (-0.74, 0, 1.40), (0.10, 0.12, 0.12)))
    # legs (separated so the crotch is detectable) + feet
    parts.append(_add_box("leg_L",  (0.10, 0, 0.45), (0.13, 0.15, 0.90)))
    parts.append(_add_box("leg_R", (-0.10, 0, 0.45), (0.13, 0.15, 0.90)))
    parts.append(_add_box("foot_L",  (0.10, -0.08, 0.03), (0.12, 0.26, 0.06)))
    parts.append(_add_box("foot_R", (-0.10, -0.08, 0.03), (0.12, 0.26, 0.06)))
    return parts


def join_meshes(meshes):
    """Combine all mesh objects into one so we bind a single skin."""
    bpy.ops.object.select_all(action="DESELECT")
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.name = "RigTarget"
    return obj


# --------------------------------------------------------------------------- #
# Normalize: center on origin (feet at Z=0) and scale to target height.
# --------------------------------------------------------------------------- #
def normalize(obj, target_height):
    log("normalize", "centering and scaling to target height")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Apply any existing transform so bbox is in world space.
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    coords = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    min_z = min(c.z for c in coords)
    max_z = max(c.z for c in coords)
    height = max_z - min_z
    if height <= 1e-6:
        fail("degenerate mesh height")

    scale = target_height / height
    obj.scale = (scale, scale, scale)
    bpy.ops.object.transform_apply(scale=True)

    # Re-evaluate bbox after scaling, then drop feet to Z=0 and center XY.
    coords = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    min_x = min(c.x for c in coords); max_x = max(c.x for c in coords)
    min_y = min(c.y for c in coords); max_y = max(c.y for c in coords)
    min_z = min(c.z for c in coords)
    obj.location.x -= (min_x + max_x) / 2.0
    obj.location.y -= (min_y + max_y) / 2.0
    obj.location.z -= min_z
    bpy.ops.object.transform_apply(location=True)
    log("normalize", f"height now ~{target_height:.2f}m, feet at Z=0")
    return obj


# --------------------------------------------------------------------------- #
# Build skeleton from detected landmarks.
#
# Bone hierarchy matches the common Mixamo / Unreal "Humanoid" layout so the
# output is engine-friendly. The landmark dict (see landmarks.py) provides the
# joint Z heights and X magnitudes; this function only assembles bones from it,
# so swapping the rigger (RigNet / SMPL-fit) means replacing detect_landmarks,
# not this code.
# --------------------------------------------------------------------------- #
def _bone(edit_bones, name, head, tail, parent=None, connected=False):
    b = edit_bones.new(name)
    b.head = head
    b.tail = tail
    if parent is not None:
        b.parent = parent
        b.use_connect = connected
    return b


def sample_points(obj):
    """World-space point cloud for analysis, densified if the mesh is low-poly.

    Cross-section detection samples points by height, so it needs points
    distributed over surfaces — not just at a box's corners. For low-poly
    meshes we temporarily apply a simple subdivision to fill them in.
    """
    nverts = len(obj.data.vertices)
    if nverts >= 5000:
        return [obj.matrix_world @ v.co for v in obj.data.vertices]

    mod = obj.modifiers.new("AnalyzeSubdiv", "SUBSURF")
    mod.subdivision_type = "SIMPLE"
    mod.levels = 3
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    eme = ev.to_mesh()
    pts = [obj.matrix_world @ v.co for v in eme.vertices]
    ev.to_mesh_clear()
    obj.modifiers.remove(mod)
    log("landmark", f"densified {nverts} -> {len(pts)} sample points")
    return pts


def build_skeleton(obj, lm):
    """Create a humanoid armature from a detected landmark dict `lm`."""
    log("skeleton", "assembling armature from landmarks")

    arm = bpy.data.armatures.new("AutoRig")
    rig = bpy.data.objects.new("AutoRig", arm)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones

    # Spine chain (centered on X=0): hips -> waist -> abdomen -> chest.
    hips   = _bone(eb, "Hips",   (0, 0, lm["hips_z"]),   (0, 0, lm["spine_z"]))
    spine  = _bone(eb, "Spine",  (0, 0, lm["spine_z"]),  (0, 0, lm["spine1_z"]), hips, True)
    spine1 = _bone(eb, "Spine1", (0, 0, lm["spine1_z"]), (0, 0, lm["chest_z"]),  spine, True)
    chest  = _bone(eb, "Chest",  (0, 0, lm["chest_z"]),  (0, 0, lm["neck_z"]),   spine1, True)
    neck   = _bone(eb, "Neck",   (0, 0, lm["neck_z"]),   (0, 0, lm["head_z"]),   chest, True)
    _bone(eb, "Head", (0, 0, lm["head_z"]), (0, 0, lm["head_top_z"]), neck, True)

    # Arms + legs, mirrored L/R. side sign: +X = left.
    for side, sign in (("L", 1), ("R", -1)):
        sh = _bone(eb, f"Shoulder_{side}",
                   (0, 0, lm["chest_z"]),
                   (sign * lm["shoulder_x"], 0, lm["shoulder_z"]), chest, False)
        ua = _bone(eb, f"UpperArm_{side}",
                   (sign * lm["shoulder_x"], 0, lm["shoulder_z"]),
                   (sign * lm["elbow_x"], 0, lm["elbow_z"]), sh, True)
        la = _bone(eb, f"LowerArm_{side}",
                   (sign * lm["elbow_x"], 0, lm["elbow_z"]),
                   (sign * lm["wrist_x"], 0, lm["wrist_z"]), ua, True)
        _bone(eb, f"Hand_{side}",
              (sign * lm["wrist_x"], 0, lm["wrist_z"]),
              (sign * lm["hand_x"], 0, lm["hand_z"]), la, True)

        ul = _bone(eb, f"UpperLeg_{side}",
                   (sign * lm["hip_x"], 0, lm["hips_z"]),
                   (sign * lm["knee_x"], 0, lm["knee_z"]), hips, False)
        ll = _bone(eb, f"LowerLeg_{side}",
                   (sign * lm["knee_x"], 0, lm["knee_z"]),
                   (sign * lm["ankle_x"], 0, lm["ankle_z"]), ul, True)
        ft = _bone(eb, f"Foot_{side}",
                   (sign * lm["ankle_x"], 0, lm["ankle_z"]),
                   (sign * lm["ankle_x"], lm["ball_y"], 0.0), ll, True)
        _bone(eb, f"Toe_{side}",
              (sign * lm["ankle_x"], lm["ball_y"], 0.0),
              (sign * lm["ankle_x"], lm["foot_tip_y"], 0.0), ft, True)

    bpy.ops.object.mode_set(mode="OBJECT")
    log("skeleton", f"created {len(arm.bones)} bones")
    return rig


# --------------------------------------------------------------------------- #
# Skin: bind mesh to armature with Blender's automatic (bone-heat) weights.
# --------------------------------------------------------------------------- #
def skin(obj, rig):
    log("skin", "binding mesh with automatic weights")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except RuntimeError as e:
        fail(f"automatic weighting failed: {e}")
    log("skin", "skinning complete")


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def export_glb(path):
    log("export", f"writing {os.path.basename(path)}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_skins=True,
        export_yup=True,
    )
    log("export", "done")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def parse_args():
    argv = sys.argv
    if "--" not in argv:
        fail("no job file passed (use: -- <job.json>)")
    job_path = argv[argv.index("--") + 1]
    with open(job_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    job = parse_args()
    output = job.get("output")
    if not output:
        fail("job is missing 'output' path")
    target_height = float(job.get("target_height", 1.8))

    reset_scene()

    input_path = job.get("input")
    if input_path and os.path.exists(input_path):
        meshes = import_model(input_path)
    else:
        meshes = make_test_human()

    obj = join_meshes(meshes)
    obj = normalize(obj, target_height)
    points = sample_points(obj)
    lm = landmarks.detect_landmarks(points, target_height, log=log)
    rig = build_skeleton(obj, lm)
    skin(obj, rig)
    export_glb(output)
    log("done", output)


if __name__ == "__main__":
    main()
