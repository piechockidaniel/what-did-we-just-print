import cv2
import numpy as np
from server.storage import decode_image
from fastapi import HTTPException

VERSION = "orb-2000-gray-1200-v1"


def grayscale(image):
    image = np.asarray(image)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    scale = min(1, 1200 / max(gray.shape))
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale)
    return gray


def features(gray):
    points, descriptors = cv2.ORB_create(nfeatures=2000).detectAndCompute(gray, None)
    return np.array([p.pt for p in points], dtype=np.float32).reshape(
        -1, 2
    ), descriptors


def cache_path(root, artwork_id):
    return root / "features" / VERSION / f"{artwork_id}.npz"


def prepare(root, artwork_id, source):
    from PIL import Image

    with Image.open(source) as image:
        points, descriptors = features(grayscale(image.convert("RGB")))
    if descriptors is None or len(points) < 8:
        raise ValueError(
            "Too few useful visual features. Use clearer artwork or manual identification."
        )
    path = cache_path(root, artwork_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Reader sees a complete cache file or no file, including after worker interruption.
    import io, os, tempfile

    buffer = io.BytesIO()
    np.savez_compressed(buffer, points=points, descriptors=descriptors)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(buffer.getvalue())
        name = temporary.name
    os.replace(name, path)


def detect_boundary(image):
    """Experimental large quadrilateral detection; operator must inspect its outline."""
    gray = grayscale(image)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        fraction = cv2.contourArea(contour) / (gray.shape[0] * gray.shape[1])
        if not 0.2 < fraction < 0.97:
            continue
        polygon = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        points = polygon.reshape(4, 2).astype(np.float32)
        centre = points.mean(axis=0)
        angles = np.arctan2(points[:, 1] - centre[1], points[:, 0] - centre[0])
        points = points[np.argsort(angles)]
        points = np.roll(points, -int(np.argmin(points.sum(axis=1))), axis=0)
        points[:, 0] *= image.width / gray.shape[1]
        points[:, 1] *= image.height / gray.shape[0]
        return points.tolist()
    return None


def match(root, image_data, rows, corners=None, auto_crop=False):
    _, image, _ = decode_image(image_data)
    framing_mode = "manual" if corners else "whole-image"
    if corners is None and auto_crop:
        corners = detect_boundary(image)
        framing_mode = "auto-experimental" if corners else "auto-not-found-whole-image"
    if corners is not None:
        points = np.array(corners, dtype=np.float32)
        if (
            not np.isfinite(points).all()
            or (points < 0).any()
            or (points[:, 0] >= image.width).any()
            or (points[:, 1] >= image.height).any()
        ):
            raise HTTPException(422, "Corners must be inside the captured image")
        contour = points.reshape(-1, 1, 2)
        if not cv2.isContourConvex(contour) or abs(cv2.contourArea(contour)) < 100:
            raise HTTPException(
                422, "Corners must form a non-degenerate convex quadrilateral"
            )
        width = max(
            np.linalg.norm(points[1] - points[0]), np.linalg.norm(points[2] - points[3])
        )
        height = max(
            np.linalg.norm(points[3] - points[0]), np.linalg.norm(points[2] - points[1])
        )
        width, height = int(width), int(height)
        transform = cv2.getPerspectiveTransform(
            points,
            np.array(
                [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                dtype=np.float32,
            ),
        )
        pixels = cv2.warpPerspective(np.asarray(image), transform, (width, height))
    else:
        pixels = np.asarray(image)
    gray = grayscale(pixels)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    exposure = float(gray.mean())
    query_points, query_descriptors = features(gray)
    quality = {
        "sharpness": round(sharpness, 2),
        "meanExposure": round(exposure, 2),
        "keypoints": len(query_points),
    }
    base = {
        "algorithm": VERSION,
        "quality": quality,
        "candidates": [],
        "experimental": True,
        "note": "Uncalibrated feature evidence; operator confirmation required. No stack verification.",
        "framing": {
            "mode": framing_mode,
            "corners": corners,
            "sourceSize": [image.width, image.height],
            "version": "quadrilateral-v1",
        },
    }
    if (
        sharpness < 30
        or exposure < 15
        or exposure > 245
        or query_descriptors is None
        or len(query_points) < 8
    ):
        return {
            **base,
            "decision": "insufficient-evidence",
            "reason": "Recapture: blur, exposure or too few useful details.",
        }
    by_artwork = {}
    for row in rows:
        by_artwork.setdefault(row["artwork_id"], []).append(row)
    candidates, unavailable = [], 0
    for artwork_id, allocations in by_artwork.items():
        path = cache_path(root, artwork_id)
        if not path.exists() or allocations[0]["readiness"] != "ready":
            unavailable += len(allocations)
            continue
        with np.load(path, allow_pickle=False) as data:
            reference_points, descriptors = data["points"], data["descriptors"]
        pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(
            query_descriptors, descriptors, k=2
        )
        good = [
            a
            for pair in pairs
            if len(pair) == 2
            for a, b in [pair]
            if a.distance < 0.72 * b.distance
        ]
        # Each reference point contributes at most once to geometric evidence.
        unique = {}
        for pair in good:
            if (
                pair.trainIdx not in unique
                or pair.distance < unique[pair.trainIdx].distance
            ):
                unique[pair.trainIdx] = pair
        good = list(unique.values())
        inliers, evidence, coverage = 0, [], 0.0
        if len(good) >= 4:
            source = np.float32([query_points[m.queryIdx] for m in good])
            target = np.float32([reference_points[m.trainIdx] for m in good])
            homography, mask = cv2.findHomography(source, target, cv2.RANSAC, 4.0)
            if homography is not None and mask is not None:
                selected = mask.ravel().astype(bool)
                inliers = int(selected.sum())
                evidence = [
                    {"capture": source[i].tolist(), "reference": target[i].tolist()}
                    for i in np.flatnonzero(selected)[:80]
                ]
                if inliers >= 3:
                    hull = cv2.convexHull(source[selected])
                    coverage = float(
                        cv2.contourArea(hull) / (gray.shape[0] * gray.shape[1])
                    )
        for allocation in allocations:
            candidates.append(
                {
                    **allocation,
                    "tentativeMatches": len(good),
                    "inliers": inliers,
                    "inlierRatio": round(inliers / len(good), 4) if good else None,
                    "coverage": round(coverage, 4),
                    "evidence": evidence,
                    "distinguishingEvidence": "Not evaluated; common layouts may tie.",
                }
            )
    candidates.sort(key=lambda c: (c["inliers"], c["coverage"]), reverse=True)
    eligible = [
        c
        for c in candidates
        if c["inliers"] >= 12
        and (c["inlierRatio"] or 0) >= 0.4
        and c["coverage"] >= 0.02
    ]
    decision, reason = (
        "unknown",
        "No candidate passed the experimental evidence thresholds.",
    )
    if eligible:
        top = eligible[0]
        tied = [
            c
            for c in eligible[1:]
            if c["artwork_id"] == top["artwork_id"]
            or c["inliers"] >= top["inliers"] * 0.85
        ]
        # Conservative baseline: no visual destination suggestion before distinguishing-region validation.
        decision = "ambiguous" if tied else "review-required"
        reason = (
            "Multiple plausible allocations; inspect production context."
            if tied
            else "Feature correspondence found; distinguishing detail needs operator inspection."
        )
    if unavailable:
        reason += f" {unavailable} active allocation(s) unavailable for matching."
        if not candidates:
            decision = "unavailable"
    # Keep every allocation sharing the best artwork, even when more than top-k.
    top = candidates[:5]
    if top:
        selected_ids = {c["id"] for c in top}
        top += [
            c
            for c in candidates[5:]
            if c["artwork_id"] == top[0]["artwork_id"] and c["id"] not in selected_ids
        ]
    return {
        **base,
        "decision": decision,
        "reason": reason,
        "candidates": top,
        "activeAllocations": len(rows),
        "unavailableAllocations": unavailable,
        "captureSize": [gray.shape[1], gray.shape[0]],
    }
