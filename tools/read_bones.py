"""
Print the armature bone names + hierarchy from any 3D file (FBX / GLB / OBJ).

Useful for reading the exact "standard bone" names a figure-posing app expects
from one of its reference/sample models, so they can be matched in
bone_naming.STANDARD_BB (or overridden via backend/bone_names.json).

    blender --background --python tools/read_bones.py -- path/to/sample.fbx
"""

import bpy
import sys
import os


def _import(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    else:
        raise SystemExit(f"unsupported format: {ext}")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv or not argv[0]:
        print("usage: blender --background --python read_bones.py -- <file>")
        return
    path = os.path.abspath(argv[0])
    if not os.path.exists(path):
        print(f"not found: {path}")
        return

    bpy.ops.wm.read_factory_settings(use_empty=True)
    _import(path)

    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not armatures:
        print("NO ARMATURE FOUND in this file (it may be mesh-only).")
        return

    for arm in armatures:
        bones = arm.data.bones
        print(f"\n=== armature '{arm.name}' — {len(bones)} bones ===")
        print("HIERARCHY:")

        def walk(b, depth):
            print("  " * depth + b.name)
            for c in b.children:
                walk(c, depth + 1)

        for root in [b for b in bones if b.parent is None]:
            walk(root, 1)

        print("FLAT LIST (one per line):")
        for b in bones:
            print(b.name)


if __name__ == "__main__":
    main()
