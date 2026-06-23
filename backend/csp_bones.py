"""
Bone-naming schemes for downstream-tool compatibility.

Our pipeline builds bones with internal names (Hips, Spine, Spine1, Chest,
Neck, Head, Shoulder_L, UpperArm_L, ...). Different target apps expect
different naming conventions; this module renames the rig to match one.

Renaming happens AFTER build_skeleton but BEFORE skinning, so Blender's
automatic weights create vertex groups already matching the final bone names
(no vertex-group renaming needed).

Schemes
-------
- "mixamo": Mixamo-standard role names. Documented to map cleanly in Clip
  Studio Modeler's standard-bone mapping, so this is the safe default for
  Clip Studio Paint compatibility.
- "csp_bb": Clip Studio's "Standard Bone Specification" (the *_bb_* names).
  Only hips_bb_/spine_bb_/spine1_bb_ are publicly confirmed; the rest must be
  read from Clip Studio Modeler ("Create standard bones" / guide model) before
  this scheme is usable. INTENTIONALLY INCOMPLETE — not the default yet.
- "internal": keep our own readable names (good for debugging the preview).
"""

# Internal name -> Mixamo role name.
MIXAMO = {
    "Hips": "Hips",
    "Spine": "Spine",
    "Spine1": "Spine1",
    "Chest": "Spine2",
    "Neck": "Neck",
    "Head": "Head",
    "HeadFace": "HeadFace",
    "Shoulder_L": "LeftShoulder",
    "UpperArm_L": "LeftArm",
    "LowerArm_L": "LeftForeArm",
    "Hand_L": "LeftHand",
    "Shoulder_R": "RightShoulder",
    "UpperArm_R": "RightArm",
    "LowerArm_R": "RightForeArm",
    "Hand_R": "RightHand",
    "UpperLeg_L": "LeftUpLeg",
    "LowerLeg_L": "LeftLeg",
    "Foot_L": "LeftFoot",
    "Toe_L": "LeftToeBase",
    "UpperLeg_R": "RightUpLeg",
    "LowerLeg_R": "RightLeg",
    "Foot_R": "RightFoot",
    "Toe_R": "RightToeBase",
}

# Finger mappings: {Finger}{n}_{L|R} -> {Left|Right}Hand{Finger}{n}
# (matches the Mixamo finger hierarchy in the reference BVH exporter).
for _side, _prefix in (("L", "Left"), ("R", "Right")):
    for _finger in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
        for _n in (1, 2, 3):
            MIXAMO[f"{_finger}{_n}_{_side}"] = f"{_prefix}Hand{_finger}{_n}"

# Internal name -> Clip Studio Standard Bone Specification name.
# CONFIRMED from Celsys docs: hips_bb_, spine_bb_, spine1_bb_.
# Everything else below is a PLACEHOLDER following the observed pattern and
# MUST be verified against the Standard Bone Specification before use.
CSP_BB = {
    "Hips": "hips_bb_",         # confirmed
    "Spine": "spine_bb_",       # confirmed
    "Spine1": "spine1_bb_",     # confirmed
    # --- below: VERIFY against the spec / Modeler before enabling ---
    # "Chest":      "spine2_bb_",
    # "Neck":       "neck_bb_",
    # "Head":       "head_bb_",
    # "Shoulder_L": "shoulder_l_bb_",
    # "UpperArm_L": "arm_l_bb_",
    # "LowerArm_L": "forearm_l_bb_",
    # "Hand_L":     "hand_l_bb_",
    # "UpperLeg_L": "thigh_l_bb_",
    # "LowerLeg_L": "leg_l_bb_",
    # "Foot_L":     "foot_l_bb_",
    # "Toe_L":      "toe_l_bb_",
    # (+ R side)
}

SCHEMES = {"mixamo": MIXAMO, "csp_bb": CSP_BB, "internal": None}


def rename(rig, scheme_name, obj=None, log=lambda *a: None):
    """Rename the armature's bones (and a skinned mesh's matching vertex groups).

    Pass `obj` (the bound mesh) when the mesh is already skinned so its vertex
    groups are renamed in lockstep — otherwise the armature modifier can no
    longer match bones to groups by name.
    """
    scheme = SCHEMES.get(scheme_name, MIXAMO)
    if scheme is None:
        log("rename", f"keeping internal bone names ({scheme_name})")
        return

    bones = rig.data.bones
    unmapped = [b.name for b in bones if b.name not in scheme]
    for old, new in scheme.items():
        b = bones.get(old)
        if b:
            b.name = new
        if obj is not None:
            vg = obj.vertex_groups.get(old)
            if vg:
                vg.name = new
    if unmapped:
        log("rename", f"WARNING: {len(unmapped)} bones not in '{scheme_name}' "
                      f"scheme kept internal names: {', '.join(unmapped)}")
    log("rename", f"applied '{scheme_name}' naming to {len(scheme)} bones")
