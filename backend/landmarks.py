"""
Landmark detection for humanoid auto-rigging.

Given a normalized mesh (Z up, feet at Z=0, facing -Y, arms extending along
+/-X in a T/A pose), find the real positions of skeletal joints by analyzing
horizontal cross-sections of the mesh.

The core idea: slice the body into thin horizontal slabs along Z and, for each
slab, measure width, depth, centroid, and how many separated X-clusters the
vertices form. From those profiles the key joints fall out:

  * crotch   -> highest Z where the legs are still two separate X-clusters
  * leg X    -> centers of those two clusters
  * hand     -> the slab whose vertices reach furthest out in X
  * neck     -> narrowest cross-section in the upper body
  * shoulder -> just below the neck, at the edge of the torso
  * head top -> the topmost vertex

Endpoints (hands, feet, crotch, neck) are mesh-derived; intermediate joints
(elbow, knee, spine) are interpolated between them. Anything detection can't
find confidently falls back to standard body proportions, so the function
always returns a complete, usable landmark set.

detect_landmarks(points, H) takes a world-space point cloud (anything with
.x/.y/.z, e.g. mathutils Vectors) and returns a flat dict of scalars consumed
by pipeline.build_skeleton(). X values are magnitudes (>=0); left/right sign is
applied by the skeleton builder.
"""


# --------------------------------------------------------------------------- #
# Small numeric helpers (kept dependency-free so this stays easy to test).
# --------------------------------------------------------------------------- #
def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    mid = n // 2
    return xs[mid] if n % 2 else 0.5 * (xs[mid - 1] + xs[mid])


def _lerp(a, b, t):
    return a + (b - a) * t


def _cluster_1d(xs, gap):
    """Split sorted X values into clusters separated by gaps larger than `gap`.

    Returns a list of (min, max, center, count) tuples, left-to-right.
    """
    xs = sorted(xs)
    clusters = []
    members = [xs[0]]
    prev = xs[0]
    for x in xs[1:]:
        if x - prev > gap:
            clusters.append(members)
            members = []
        members.append(x)
        prev = x
    clusters.append(members)
    return [(m[0], m[-1], sum(m) / len(m), len(m)) for m in clusters]


# --------------------------------------------------------------------------- #
# Proportional fallback — standard humanoid ratios as fractions of height H,
# measured from the floor. Used to seed the result and to fill any landmark
# that cross-section detection can't pin down.
# --------------------------------------------------------------------------- #
# Where the mid-limb joint sits along the limb, as a fraction from the root.
# >0.5 pulls the elbow toward the hand and the knee toward the foot, which
# reads more naturally (and matches Clip-Studio-style figures).
ELBOW_BIAS = 0.58
KNEE_BIAS = 0.58
# Spine segment heights as fractions of the trunk (hips -> chest).
SPINE_FRAC = 0.33    # waist
SPINE1_FRAC = 0.66   # abdomen / mid-back
# Ball of foot as a fraction of the foot's forward reach (rest goes to the toe).
BALL_FRAC = 0.6


def proportional_landmarks(H):
    return {
        # spine chain (centered on X=0): hips -> waist -> abdomen -> chest
        "hips_z":     0.53 * H,
        "spine_z":    0.59 * H,
        "spine1_z":   0.66 * H,
        "chest_z":    0.72 * H,
        "neck_z":     0.83 * H,
        "head_z":     0.88 * H,
        "head_top_z": 1.00 * H,
        # arms (x = magnitude from center)
        "shoulder_x": 0.10 * H, "shoulder_z": 0.82 * H,
        "elbow_x":    0.18 * H, "elbow_z":    0.61 * H,
        "wrist_x":    0.24 * H, "wrist_z":    0.45 * H,
        "hand_x":     0.27 * H, "hand_z":     0.42 * H,
        # legs
        "hip_x":      0.09 * H,
        "knee_x":     0.09 * H, "knee_z":     0.26 * H,
        "ankle_x":    0.09 * H, "ankle_z":    0.04 * H,
        "ball_y":     -0.07 * H,   # ball of foot (Foot -> Toe split)
        "foot_tip_y": -0.12 * H,   # toe tip
    }


# --------------------------------------------------------------------------- #
# Cross-section profiling
# --------------------------------------------------------------------------- #
def _build_profile(points, n_slabs, leg_gap):
    if not points:
        return None, None, None
    min_z = min(p.z for p in points)
    max_z = max(p.z for p in points)
    span = max_z - min_z
    if span <= 1e-6:
        return None, None, None

    slab_h = span / n_slabs
    slabs = [[] for _ in range(n_slabs)]
    for p in points:
        idx = int((p.z - min_z) / slab_h)
        if idx >= n_slabs:
            idx = n_slabs - 1
        slabs[idx].append(p)

    rows = []
    for i, sv in enumerate(slabs):
        z = min_z + (i + 0.5) * slab_h
        if not sv:
            rows.append(None)
            continue
        xs = [p.x for p in sv]
        ys = [p.y for p in sv]
        rows.append({
            "z": z,
            "xmin": min(xs), "xmax": max(xs),
            "xw": max(xs) - min(xs),
            "yw": max(ys) - min(ys),
            "ymin": min(ys),
            "cx": sum(xs) / len(xs),
            "clusters": _cluster_1d(xs, leg_gap),
        })
    return rows, min_z, max_z


def _central_width(row):
    """Width of the cluster nearest X=0 (the torso/limb-free trunk)."""
    c = min(row["clusters"], key=lambda c: abs(c[2]))
    return c[1] - c[0]


# --------------------------------------------------------------------------- #
# Main detection
# --------------------------------------------------------------------------- #
def detect_landmarks(points, H, n_slabs=160, log=lambda *a: None):
    lm = proportional_landmarks(H)
    leg_gap = 0.035 * H

    rows, min_z, max_z = _build_profile(points, n_slabs, leg_gap)
    if rows is None:
        log("landmark", "profiling failed — using proportional fallback")
        return lm

    valid = [r for r in rows if r]
    span = max_z - min_z

    # --- legs: crotch = highest Z (in lower body) with two X-clusters -------- #
    leg_rows = [r for r in valid
                if r["z"] < min_z + 0.55 * span and len(r["clusters"]) >= 2]
    if leg_rows:
        crotch_z = max(r["z"] for r in leg_rows)
        # leg X centers, sampled from the lower legs (most reliably separated)
        low = [r for r in leg_rows if r["z"] < min_z + 0.30 * span] or leg_rows
        leg_xs = [abs(c[2]) for r in low for c in r["clusters"]]
        leg_x = _median(leg_xs)
        if leg_x and leg_x > 1e-4:
            lm["hips_z"] = crotch_z
            lm["hip_x"] = leg_x
            lm["knee_x"] = leg_x
            lm["ankle_x"] = leg_x
            log("landmark", f"crotch @ {crotch_z:.2f}m, leg X +/-{leg_x:.2f}m")

    # --- ankle + foot: bottom slab geometry ---------------------------------- #
    bottom = [r for r in valid if r["z"] < min_z + 0.12 * span]
    if bottom:
        lm["ankle_z"] = min_z + 0.04 * span
        lm["foot_tip_y"] = min(r["ymin"] for r in bottom)  # forward (-Y) reach
        lm["ball_y"] = lm["foot_tip_y"] * BALL_FRAC        # Foot -> Toe split

    # knee: biased toward the ankle/foot
    lm["knee_z"] = _lerp(lm["hips_z"], lm["ankle_z"], KNEE_BIAS)

    # --- neck: narrowest central width in the upper body --------------------- #
    upper = [r for r in valid
             if min_z + 0.70 * span < r["z"] < min_z + 0.93 * span]
    if upper:
        neck = min(upper, key=_central_width)
        neck_z = neck["z"]
        lm["neck_z"] = neck_z
        lm["head_z"] = min(neck_z + 0.03 * H, max_z)
        lm["head_top_z"] = max_z
        # shoulders sit just below the neck, at the edge of the torso
        sh_z = neck_z - 0.04 * H
        below = [r for r in valid if abs(r["z"] - sh_z) < 0.03 * H]
        if below:
            torso_half = max(_central_width(r) for r in below) * 0.5
            lm["shoulder_z"] = sh_z
            lm["shoulder_x"] = max(torso_half * 0.85, 0.04 * H)
        # chest, then waist + abdomen interpolated up the trunk
        lm["chest_z"] = sh_z - 0.06 * H
        lm["spine_z"] = _lerp(lm["hips_z"], lm["chest_z"], SPINE_FRAC)
        lm["spine1_z"] = _lerp(lm["hips_z"], lm["chest_z"], SPINE1_FRAC)
        log("landmark", f"neck @ {neck_z:.2f}m, shoulders @ {lm['shoulder_z']:.2f}m")

    # --- hands: slab reaching furthest out in X ------------------------------ #
    reach = max(valid, key=lambda r: r["xmax"])
    hand_x = reach["xmax"]
    if hand_x > lm["shoulder_x"] * 1.2:  # arms actually extend outward
        hand_z = reach["z"]
        lm["hand_x"] = hand_x
        lm["hand_z"] = hand_z
        lm["wrist_x"] = hand_x * 0.88
        lm["wrist_z"] = hand_z
        # elbow biased toward the wrist/hand
        lm["elbow_x"] = _lerp(lm["shoulder_x"], lm["wrist_x"], ELBOW_BIAS)
        lm["elbow_z"] = _lerp(lm["shoulder_z"], lm["wrist_z"], ELBOW_BIAS)
        log("landmark", f"hand reach +/-{hand_x:.2f}m @ {hand_z:.2f}m")

    return lm
