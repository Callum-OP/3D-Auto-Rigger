"""
Deformation validation: build the rig, apply a test pose, and render it.

The point is to SEE rig quality — are bones at real joints, do the skin weights
deform cleanly when posed — instead of guessing from bone coordinates. Renders
a posed front view (and a 3/4 view) to PNG so the result can be eyeballed.

    blender --background --python backend/preview_pose.py -- [input_model] [out.png]

With no input model, the generated test figure is used.
"""

import bpy
import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import pipeline
import landmarks

HEIGHT = 1.8


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    inp = argv[0] if len(argv) >= 1 and argv[0] else None
    out = argv[1] if len(argv) >= 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "test", "pose_preview.png")
    return inp, os.path.abspath(out)


def build(inp, standard=False):
    pipeline.reset_scene()
    meshes = pipeline.import_model(inp) if inp and os.path.exists(inp) else pipeline.make_test_human()
    obj = pipeline.join_meshes(meshes)
    obj = pipeline.normalize(obj, HEIGHT)
    pipeline.clean_mesh(obj)
    pts = pipeline.sample_points(obj)
    lm = landmarks.detect_landmarks(pts, HEIGHT, log=pipeline.log)
    rig = pipeline.build_skeleton(obj, lm, standard=standard)  # internal names kept
    pipeline.skin(obj, rig, lm, HEIGHT)
    return obj, rig


def apply_test_pose(rig):
    """Bend elbows, knees, shoulders, hip — a pose that exercises the joints.

    NOTE: a Blender bone's local Y runs along its length, so joint *bending*
    must rotate around local X or Z (rotating around Y only twists the bone).
    """
    # Asymmetric on purpose: only the RIGHT arm and RIGHT leg are posed, the
    # left side is left neutral. If the left limbs move at all, weights are
    # bleeding across sides.
    pose = {
        "UpperArm_R": (0, 0, 25), "LowerArm_R": (0, 0, 85),
        "UpperLeg_R": (35, 0, 0), "LowerLeg_R": (90, 0, 0),
        # bend the torso forward to test the spine sections + hips/chest weights
        "Spine": (15, 0, 0), "Spine1": (15, 0, 0), "Spine2": (12, 0, 0),
        "Neck": (22, 0, 0),
        "Toe_R": (55, 0, 0),
    }
    for name, (rx, ry, rz) in pose.items():
        pb = rig.pose.bones.get(name)
        if not pb:
            continue
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (math.radians(rx), math.radians(ry), math.radians(rz))
    bpy.context.view_layer.update()


def setup_scene_and_render(out_png):
    scene = bpy.context.scene

    # Camera — 3/4 view so forward/back joint bends are visible.
    from mathutils import Vector
    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (-2.8, -3.4, 1.3)
    target = Vector((0.0, 0.0, 0.95))
    direction = target - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam_data.lens = 50
    scene.camera = cam

    # Light
    light_data = bpy.data.lights.new("Sun", type="SUN")
    light_data.energy = 3.0
    light = bpy.data.objects.new("Sun", light_data)
    scene.collection.objects.link(light)
    light.rotation_euler = (math.radians(60), 0, math.radians(30))

    # Workbench: fast, shows geometry/deformation clearly.
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.show_cavity = True
    scene.display.shading.light = "STUDIO"
    scene.render.resolution_x = 640
    scene.render.resolution_y = 960
    scene.render.film_transparent = False
    scene.render.filepath = out_png

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    bpy.ops.render.render(write_still=True)
    pipeline.log("render", out_png)


def main():
    inp, out_png = parse_args()
    obj, rig = build(inp, standard="standard" in sys.argv)
    apply_test_pose(rig)
    setup_scene_and_render(out_png)


if __name__ == "__main__":
    main()
