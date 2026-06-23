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
import csp_bones
import markers as markers_mod


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
    # Strip any prior rigging so re-rigging starts clean: an existing armature
    # modifier + leftover vertex groups make bone-heat weighting fail outright.
    for m in meshes:
        for mod in list(m.modifiers):
            if mod.type == "ARMATURE":
                m.modifiers.remove(mod)
        if m.parent:
            mw = m.matrix_world.copy()
            m.parent = None
            m.matrix_world = mw
        m.vertex_groups.clear()
        if m.data.shape_keys:
            m.shape_key_clear()
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

    # Voxel-remesh the overlapping boxes into ONE connected, deformable mesh.
    # (Separate boxes can't bend at joints — they have no geometry there.)
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    body = bpy.context.view_layer.objects.active
    mod = body.modifiers.new("Remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = 0.04
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.ops.object.shade_smooth()
    log("import", f"remeshed test figure -> {len(body.data.vertices)} verts")
    return [body]


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


# Finger layout: (internal name, lateral offset in spread-units, length scale).
# Four fingers fan across the hand width; the thumb is handled separately.
_FINGERS = [
    ("Index",  1.5, 0.95),
    ("Middle", 0.5, 1.00),
    ("Ring",  -0.5, 0.92),
    ("Pinky", -1.5, 0.78),
]
_SEG_FRACS = (0.45, 0.33, 0.22)   # three phalanges as fractions of finger length


def _build_fingers(eb, side, parent, wrist, tip, knuckle):
    """Add 5 fingers x 3 joints under the hand, matching the Mixamo hierarchy.

    Placement is heuristic (hands are usually low-detail blobs in input meshes):
    fingers fan across the hand width and point along the hand direction. The
    goal is a correctly-named, posable finger hierarchy, not per-vertex fit.
    """
    hand_vec = tip - wrist
    hand_len = hand_vec.length or 0.01
    hdir = hand_vec.normalized()
    spread = Vector((0, 1, 0))        # fan across front-back (Y)
    unit = hand_len * 0.10            # spacing between fingers
    finger_zone = hand_len * 0.4      # knuckle -> fingertip length (shorter)

    for fname, yoff, lmul in _FINGERS:
        base = knuckle + spread * (yoff * unit)
        flen = finger_zone * lmul
        prev, pos = parent, base
        for i in range(3):
            nxt = pos + hdir * (flen * _SEG_FRACS[i])
            prev = _bone(eb, f"{fname}{i + 1}_{side}", pos, nxt, prev, i > 0)
            pos = nxt

    # Thumb: rooted nearer the wrist, offset to the front (-Y) and angled out.
    thumb_dir = (hdir + spread * -0.7).normalized()
    pos = wrist + hand_vec * 0.25 + spread * (-2.0 * unit)
    prev = parent
    for i in range(3):
        nxt = pos + thumb_dir * (finger_zone * 0.8 * _SEG_FRACS[i])
        prev = _bone(eb, f"Thumb{i + 1}_{side}", pos, nxt, prev, i > 0)
        pos = nxt


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
        wrist_p = Vector((sign * lm["wrist_x"], 0, lm["wrist_z"]))
        tip_p = Vector((sign * lm["hand_x"], 0, lm["hand_z"]))
        # Hand bone spans wrist -> knuckles (most of the wrist->fingertip span);
        # fingers occupy the shorter remainder.
        knuckle = wrist_p.lerp(tip_p, 0.6)
        hand = _bone(eb, f"Hand_{side}", wrist_p, knuckle, la, True)
        _build_fingers(eb, side, hand, wrist_p, tip_p, knuckle)

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
def skin(obj, rig, lm, H):
    """Robust skinning via a watertight voxel proxy.

    Bone-heat auto-weighting fails outright on real character meshes
    (intersecting/non-manifold geometry from joined sub-meshes, hair, etc.) —
    producing zero weights. Instead we auto-weight a voxel-remeshed (watertight)
    copy, which bone-heat handles reliably, then transfer those weights onto the
    real mesh by nearest surface point.
    """
    log("skin", "building watertight weight proxy")
    proxy = obj.copy()
    proxy.data = obj.data.copy()
    proxy.name = "WeightProxy"
    bpy.context.collection.objects.link(proxy)
    bpy.context.view_layer.objects.active = proxy
    rm = proxy.modifiers.new("Remesh", "REMESH")
    rm.mode = "VOXEL"
    rm.voxel_size = 0.03
    bpy.ops.object.modifier_apply(modifier=rm.name)

    log("skin", "auto-weighting proxy")
    bpy.ops.object.select_all(action="DESELECT")
    proxy.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except RuntimeError as e:
        fail(f"proxy weighting failed: {e}")

    log("skin", "transferring weights to mesh")
    # Ensure the real mesh has a vertex group per bone for ARMATURE_NAME binding.
    existing = {vg.name for vg in obj.vertex_groups}
    for b in rig.data.bones:
        if b.name not in existing:
            obj.vertex_groups.new(name=b.name)

    bpy.ops.object.select_all(action="DESELECT")
    proxy.select_set(True)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = proxy   # source = active
    bpy.ops.object.data_transfer(
        data_type="VGROUP_WEIGHTS",
        vert_mapping="POLYINTERP_NEAREST",
        layers_select_src="ALL",
        layers_select_dst="NAME",
        mix_mode="REPLACE",
    )

    # Bind the real mesh using the transferred weights (no recompute).
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type="ARMATURE_NAME")

    bpy.data.objects.remove(proxy, do_unlink=True)
    _mask_weights(obj, lm, H)
    _cleanup_weights(obj)
    log("skin", "skinning complete")


def _mask_weights(obj, lm, H):
    """Force each limb to be self-contained by zeroing impossible weights.

    Bone-heat gives smooth, far-reaching weights that bleed across the body
    (left leg influencing the right, arms influencing the belly, neck pulling
    the torso). We hard-clear each bone's weight outside the region it can
    plausibly own:
      * left-side limb bones may only weight the body's left half, right-side
        the right half (this is what keeps the two legs/arms independent);
      * leg bones may not reach above the hip joint;
      * arm/hand/finger bones may not reach below the chest;
      * neck/head may not reach below the neck base.
    The central spine bones (Hips/Spine/Spine1/Spine2/Chest) are never masked,
    so every vertex keeps at least one valid influence; normalization restores
    a clean per-vertex sum afterwards.
    """
    fingers = [f"{f}{n}" for f in ("Thumb", "Index", "Middle", "Ring", "Pinky")
               for n in (1, 2, 3)]
    arm_parts = ["Shoulder", "UpperArm", "LowerArm", "Hand"] + fingers
    leg_parts = ["UpperLeg", "LowerLeg", "Foot", "Toe"]

    def named(parts, side):
        return [f"{p}_{side}" for p in parts]

    L_limbs = named(arm_parts, "L") + named(leg_parts, "L")
    R_limbs = named(arm_parts, "R") + named(leg_parts, "R")
    leg_bones = named(leg_parts, "L") + named(leg_parts, "R")
    arm_bones = named(arm_parts, "L") + named(arm_parts, "R")
    head_bones = ["Neck", "Head"]
    spine_bones = ["Hips", "Spine", "Spine1", "Chest"]

    groups = {vg.name: vg for vg in obj.vertex_groups}
    # Left/right masking (x) is strict — that's what keeps limbs independent.
    # The vertical bands are deliberately GENEROUS so the torso/neck keep their
    # natural blending (hard vertical cuts were regressing the spine region).
    x_margin = 0.015                        # keep a thin midline blend zone
    # Legs stay OFF the pelvis so the Hips bone owns it as ONE section (else
    # left/right leg weights split the pelvis down the middle).
    hips_top = lm["hips_z"] + 0.02 * H
    neck_bot = lm["neck_z"] - 0.12 * H
    arm_bot = lm["chest_z"] - 0.16 * H

    # Each spine bone owns a clean vertical band (with blend margin) so the torso
    # reads as hips / waist / lower-chest / upper-chest, and the chest can't reach
    # down into the belly and stretch it to a point.
    sm = 0.05 * H
    spine_bands = {
        "Hips":   (None, lm["spine_z"] + sm),
        "Spine":  (lm["hips_z"] - sm, lm["spine1_z"] + sm),
        "Spine1": (lm["spine_z"] - sm, lm["chest_z"] + sm),
        "Chest":  (lm["spine1_z"] - sm, None),
    }

    idx2name = {vg.index: vg.name for vg in obj.vertex_groups}
    rm = {name: set() for name in set(L_limbs + R_limbs + leg_bones
                                      + arm_bones + head_bones + spine_bones)}
    for v in obj.data.vertices:
        co = obj.matrix_world @ v.co
        i = v.index
        z = co.z
        remove = set()
        if co.x < -x_margin:                # right half -> no left-limb weight
            remove.update(L_limbs)
        elif co.x > x_margin:               # left half -> no right-limb weight
            remove.update(R_limbs)
        if z > hips_top:
            remove.update(leg_bones)
        if z < arm_bot:
            remove.update(arm_bones)
        if z < neck_bot:
            remove.update(head_bones)
        for n, (zmin, zmax) in spine_bands.items():
            if (zmin is not None and z < zmin) or (zmax is not None and z > zmax):
                remove.add(n)

        # Never strip a vertex of ALL its weight: an orphaned vertex binds to the
        # armature root / FBX neutral_bone at the origin and collapses to the
        # floor between the feet. Keep its dominant influence if masking empties it.
        cur = {idx2name[g.group]: g.weight for g in v.groups if g.weight > 0.0}
        if not cur:
            continue
        if not (set(cur) - remove):
            remove.discard(max(cur, key=cur.get))
        for n in remove:
            if n in cur:
                rm[n].add(i)

    for name, idxs in rm.items():
        vg = groups.get(name)
        if vg and idxs:
            vg.remove(list(idxs))


def _cleanup_weights(obj):
    """Normalize so each vertex's weights sum to 1 after masking.

    (Deliberately minimal — limiting/cleaning influences was found to smear
    separation between parts, so we only normalize.)
    """
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL",
                                              lock_active=False)


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


def export_fbx(path):
    """Export an engine-friendly FBX (armature + mesh, no baked animation).

    FBX 7.4 binary with a standard humanoid bone hierarchy works broadly —
    game engines, DCC tools, and figure apps (e.g. Clip Studio, which needs
    FBX <=7.4) alike. T-pose so downstream auto-mapping lines up.
    """
    log("export", f"writing {os.path.basename(path)}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        add_leaf_bones=False,        # our Hand/Toe/Head bones are the tips already
        bake_anim=False,
        mesh_smooth_type="FACE",
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_ALL",
        axis_forward="-Z",
        axis_up="Y",
        primary_bone_axis="Y",
        secondary_bone_axis="X",
    )
    log("export", "done (fbx)")


# --------------------------------------------------------------------------- #
# Front view for the Mixamo-style marker editor
# --------------------------------------------------------------------------- #
def render_front(obj, out_png, H):
    """Render an ortho front view and return the pixel<->world calibration."""
    import math
    scene = bpy.context.scene
    res, ortho, cz = 768, 1.95, H / 2.0

    d = bpy.data.lights.new("Sun", "SUN")
    d.energy = 3.0
    light = bpy.data.objects.new("Sun", d)
    scene.collection.objects.link(light)
    light.rotation_euler = (math.radians(55), 0, math.radians(25))

    cam_data = bpy.data.cameras.new("PrepCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho
    cam = bpy.data.objects.new("PrepCam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -5.0, cz)
    cam.rotation_euler = (math.radians(90), 0, 0)
    scene.camera = cam

    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light = "STUDIO"
    sh.color_type = "SINGLE"
    sh.single_color = (0.82, 0.82, 0.85)
    scene.render.resolution_x = res
    scene.render.resolution_y = res
    scene.render.filepath = out_png
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    bpy.ops.render.render(write_still=True)
    return {"res": res, "ortho": ortho, "center_z": cz, "height": H}


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

    # PREP: render a front view and emit draggable markers, then stop. The app
    # shows these for the user to nudge before the real rig is built.
    if job.get("mode") == "prep":
        front_png = job.get("front_png") or (os.path.splitext(output)[0] + "_front.png")
        calib = render_front(obj, front_png, target_height)
        world = markers_mod.to_markers(lm)
        px = {k: markers_mod.world_to_px(v[0], v[1], calib) for k, v in world.items()}
        with open(output, "w", encoding="utf-8") as f:
            json.dump({"front": front_png, "calib": calib, "markers": px}, f)
        log("prep", f"front view + {len(px)} markers written")
        return

    # RIG: if the app passed edited markers, they override detection.
    if job.get("markers") and job.get("calib"):
        calib = job["calib"]
        world = {k: markers_mod.px_to_world(v[0], v[1], calib)
                 for k, v in job["markers"].items()}
        lm = markers_mod.from_markers(world, lm, target_height)
        log("rig", "using edited markers")

    rig = build_skeleton(obj, lm)
    # Skin with internal bone names (so weight masking can find limbs by role),
    # then rename bones AND their vertex groups together for the target app.
    skin(obj, rig, lm, target_height)
    bone_naming = job.get("bone_naming", "mixamo")
    csp_bones.rename(rig, bone_naming, obj=obj, log=log)
    export_glb(output)
    # Also write an FBX sibling for Clip Studio Paint / Modeler. Non-fatal:
    # a flaky FBX export must not sink an otherwise-good rig + preview.
    fbx_path = os.path.splitext(output)[0] + ".fbx"
    try:
        export_fbx(fbx_path)
    except Exception as e:  # noqa: BLE001 - report and continue
        log("export", f"WARNING: FBX export failed, GLB still available: {e}")
    log("done", output)


if __name__ == "__main__":
    main()
