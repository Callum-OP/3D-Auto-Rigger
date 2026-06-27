"""
Shape-key validation: build the ARKit face shapes and render the head with
several of them applied, so quality is eyeballed — not guessed from numbers
(same principle as preview_pose.py for the body rig).

    blender --background --python backend/preview_face.py -- [input_model] [out_dir]

With no input model the generated test humanoid is used (a smooth blob head:
enough to confirm regions move in the right place and direction, not facial
detail). Writes face_neutral.png + one PNG per sampled expression.
"""

import bpy
import sys
import os
import math
from mathutils import Vector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import pipeline
import landmarks
import face_markers
import face_shapekeys

HEIGHT = 1.8

# Representative shapes covering each deformation mechanism.
SAMPLES = [
    "jawOpen", "mouthSmileLeft", "mouthFunnel", "mouthPucker",
    "browInnerUp", "browDownLeft", "eyeBlinkLeft", "cheekPuff",
    "noseSneerLeft", "mouthShrugUpper",
]


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    inp = argv[0] if len(argv) >= 1 and argv[0] else None
    out_dir = argv[1] if len(argv) >= 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "test", "face")
    return inp, os.path.abspath(out_dir)


def build(inp):
    pipeline.reset_scene()
    meshes = pipeline.import_model(inp) if inp and os.path.exists(inp) \
        else pipeline.make_test_human()
    obj = pipeline.join_meshes(meshes)
    obj = pipeline.normalize(obj, HEIGHT)
    pipeline.clean_mesh(obj)
    pts = pipeline.sample_points(obj)
    lm = landmarks.detect_landmarks(pts, HEIGHT, log=pipeline.log)
    base_z, top_z, head_only = face_markers.head_band(pts, lm)
    if head_only:
        pipeline.log("face", "no neck detected — treating the whole input as a head")
    det_base, det_top = face_markers.detection_band(base_z, top_z, head_only, HEIGHT)
    face = face_markers.detect_face(pts, det_base, det_top)
    markers = face_markers.default_markers(face)
    face_shapekeys.build(obj, markers, HEIGHT, head_base=base_z, log=pipeline.log)
    return obj, base_z, top_z


def setup_camera(base_z, top_z):
    scene = bpy.context.scene
    head_h = max(top_z - base_z, 0.1)
    cz = base_z + 0.5 * head_h          # frame on the face region

    cam_data = bpy.data.cameras.new("FaceCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = head_h * 1.15
    cam = bpy.data.objects.new("FaceCam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -5.0, cz)
    cam.rotation_euler = (math.radians(90), 0, 0)   # look toward +Y at the face
    scene.camera = cam

    d = bpy.data.lights.new("Sun", "SUN")
    d.energy = 3.0
    light = bpy.data.objects.new("Sun", d)
    scene.collection.objects.link(light)
    light.rotation_euler = (math.radians(50), 0, math.radians(20))

    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.show_cavity = True
    sh.light = "STUDIO"
    sh.color_type = "SINGLE"               # neutral gray so deformations read
    sh.single_color = (0.82, 0.82, 0.85)   # regardless of the model's material
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512


def render_to(path):
    scene = bpy.context.scene
    scene.render.filepath = path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.render.render(write_still=True)


def main():
    inp, out_dir = parse_args()
    obj, base_z, top_z = build(inp)
    setup_camera(base_z, top_z)

    kb = obj.data.shape_keys.key_blocks
    render_to(os.path.join(out_dir, "face_neutral.png"))
    for name in SAMPLES:
        if name not in kb:
            pipeline.log("face", f"WARNING: sample '{name}' missing — skipped")
            continue
        kb[name].value = 1.0
        bpy.context.view_layer.update()
        render_to(os.path.join(out_dir, f"face_{name}.png"))
        kb[name].value = 0.0
    pipeline.log("face", f"rendered {1 + len(SAMPLES)} previews -> {out_dir}")


if __name__ == "__main__":
    main()
