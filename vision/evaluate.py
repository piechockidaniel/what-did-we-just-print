"""Evaluate held-out labelled captures without changing workflow state.

Manifest example is in docs/evaluation-manifest.example.json. Paths are relative to
the manifest. Dataset collection, tuning and test splits are the operator's job.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import statistics
import time
from server.db import make_engine, ROOT
from server.domain import allocation_rows
from .matching import match, VERSION


def evaluate(engine, root, manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("split") != "held-out" or not manifest.get("captureSession"):
        raise ValueError(
            "Label a held-out capture session; do not use reference artwork as test captures"
        )
    with engine.connect() as conn:
        rows = allocation_rows(conn, True)
    results, timings, hashes = [], [], set()
    for case in manifest["cases"]:
        path = (manifest_path.parent / case["file"]).resolve()
        if not path.is_relative_to(manifest_path.parent.resolve()):
            raise ValueError("Capture must be within the manifest directory")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in hashes:
            raise ValueError("Duplicate capture bytes in held-out set")
        hashes.add(digest)
        if any(row["artwork_id"] == digest for row in rows):
            raise ValueError("A reference image was supplied as a held-out capture")
        expected = set(case["acceptableVariantIds"])
        if not expected and case.get("expected") != "unknown":
            raise ValueError("Unknown cases must be explicitly labelled")
        started = time.perf_counter()
        mime = (
            "image/jpeg"
            if path.suffix.lower() in [".jpg", ".jpeg"]
            else "image/webp"
            if path.suffix.lower() == ".webp"
            else "image/png"
        )
        result = match(
            root,
            f"data:{mime};base64," + base64.b64encode(raw).decode(),
            rows,
            case.get("corners"),
            case.get("autoCrop", False),
        )
        timings.append((time.perf_counter() - started) * 1000)
        candidates = result["candidates"]
        top_ids = [row["variant_id"] for row in candidates]
        # Counts retrieval separately from any suggestion or operator acceptance.
        results.append(
            {
                "file": case["file"],
                "sha256": digest,
                "expected": sorted(expected),
                "decision": result["decision"],
                "framing": result["framing"],
                "top1Correct": bool(top_ids and top_ids[0] in expected),
                "top5Correct": bool(expected.intersection(top_ids[:5])),
                "unknownRejected": not expected and result["decision"] == "unknown",
                "ambiguityPreserved": case.get("expected") != "ambiguous"
                or result["decision"] == "ambiguous",
                "candidateVariants": top_ids,
                "durationMs": round(timings[-1], 2),
            }
        )
    known = [r for r in results if r["expected"]]
    unknown = [r for r in results if not r["expected"]]
    sorted_times = sorted(timings)
    return {
        "algorithm": VERSION,
        "physicalValidationClaim": False,
        "warning": "Ground truth and physical provenance are supplied by the dataset owner. No operator acceptance experiment was run.",
        "session": manifest["captureSession"],
        "activeAllocations": len(rows),
        "sampleCount": len(results),
        "knownCount": len(known),
        "unknownCount": len(unknown),
        "top1Retrieval": sum(r["top1Correct"] for r in known) / len(known)
        if known
        else None,
        "top5Retrieval": sum(r["top5Correct"] for r in known) / len(known)
        if known
        else None,
        "unknownRejection": sum(r["unknownRejected"] for r in unknown) / len(unknown)
        if unknown
        else None,
        "operatorReviewRate": 1.0 if results else None,
        "wrongAcceptedAssignments": None,
        "latencyP50Ms": statistics.median(timings) if timings else None,
        "latencyP95Ms": sorted_times[min(len(timings) - 1, int(0.95 * len(timings)))]
        if timings
        else None,
        "cases": results,
    }


def main():
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output exists; choose a new evidence filename")
    result = evaluate(
        make_engine(),
        Path(os.getenv("PRINT_DATA_DIR", ROOT / "data")),
        args.manifest.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        f"Evaluated {result['sampleCount']} captures; report written. Physical reliability is not established automatically."
    )


if __name__ == "__main__":
    main()
