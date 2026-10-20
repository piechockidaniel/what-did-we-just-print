"""Generate synthetic reference artwork and printable sheets, never customer data.

Run with the project's Python environment. Output is a new directory and is not
imported automatically. Actual printing and camera capture are separate steps.
"""

import argparse
import base64
import html
import io
import json
from pathlib import Path
from uuid import UUID, uuid5
from PIL import Image, ImageDraw, ImageFont

NAMESPACE = UUID("b33a4d0b-bb3f-4af1-a4b2-e6efde79ebf1")


def identity(value):
    return str(uuid5(NAMESPACE, value))


def font(size):
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size=size)


def artwork(name, unknown=False):
    image = Image.new("RGB", (900, 500), "#eee9de")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 900, 95), fill="#15120e" if not unknown else "#114477")
    draw.text(
        (45, 26),
        "SYNTHETIC PRINT STUDIO" if not unknown else "UNREGISTERED TEST DESIGN",
        font=font(34),
        fill="#ff5b20",
    )
    for index in range(15):
        x = 55 + index * 54
        draw.rectangle(
            (x, 135, x + 28, 165 + (index % 4) * 12),
            fill=["#114477", "#ff5b20", "#333333"][index % 3],
        )
    draw.text((55, 240), name, font=font(48), fill="#15120e")
    draw.text(
        (55, 330),
        "Production demonstration / fictional identity",
        font=font(24),
        fill="#555555",
    )
    draw.text((55, 390), "example.invalid", font=font(26), fill="#555555")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def generate(destination):
    if destination.exists():
        raise ValueError(
            "Choose a new output directory; existing assets are never overwritten"
        )
    images = destination / "references"
    images.mkdir(parents=True)
    variants, printable, cases = [], [], []
    for index in range(50):
        name = f"Alex Example {index + 1:02d}"
        raw = artwork(name)
        filename = f"card-{index + 1:02d}.png"
        (images / filename).write_bytes(raw)
        variant_id = identity(f"name-{index + 1:02d}")
        variants.append(
            {
                "id": variant_id,
                "name": name,
                "destination": f"Synthetic destination {index + 1:02d}",
                "quantity": 100,
                "side": "front",
                "image": "data:image/png;base64," + base64.b64encode(raw).decode(),
            }
        )
        printable.append(filename)
        cases.append(
            {
                "file": f"captures/physical-{index + 1:02d}.jpg",
                "acceptableVariantIds": [variant_id],
                "expected": "known",
                "autoCrop": True,
            }
        )
    duplicate = {
        **variants[0],
        "id": identity("identical-artwork-other-order"),
        "destination": "Different synthetic destination",
    }
    cases[0]["acceptableVariantIds"].append(duplicate["id"])
    cases[0]["expected"] = "ambiguous"
    printable.append("card-01.png")
    for index in range(3):
        filename = f"unknown-{index + 1}.png"
        (images / filename).write_bytes(artwork(f"Unknown Sample {index + 1}", True))
        printable.append(filename)
        cases.append(
            {
                "file": f"captures/unknown-{index + 1}.jpg",
                "acceptableVariantIds": [],
                "expected": "unknown",
                "autoCrop": True,
            }
        )
    orders = []
    for key, number, members in [
        ("kit-main", "SYNTHETIC-50-NAMES", variants),
        ("kit-ambiguous", "SYNTHETIC-IDENTICAL-ARTWORK", [duplicate]),
    ]:
        orders.append(
            {
                "id": identity(key),
                "orderNumber": number,
                "customer": "Fictional evaluation studio",
                "widthMm": 90,
                "heightMm": 50,
                "variants": members,
            }
        )
    (destination / "catalog.json").write_text(
        json.dumps({"schemaVersion": 1, "imageEncoding": "data-url", "orders": orders}),
        encoding="utf-8",
    )
    # Six separate production sheets, ten placements each, rather than an impossible giant sheet.
    sheets = []
    members = variants + [duplicate]
    for page in range(6):
        selected = members[page * 10 : page * 10 + 10]
        sheets.append(
            {
                "number": f"SYNTHETIC-SHEET-{page + 1}",
                "widthMm": 210,
                "heightMm": 297,
                "impressions": 100,
                "placements": [
                    {
                        "variantId": v["id"],
                        "x": 10 + (i % 2) * 95,
                        "y": 10 + (i // 2) * 55,
                        "rotation": 0,
                        "side": "front",
                    }
                    for i, v in enumerate(selected)
                ],
            }
        )
        (destination / f"sheet-{page + 1}.json").write_text(
            json.dumps(sheets[-1], indent=2), encoding="utf-8"
        )
    pages = []
    for offset in range(0, len(printable), 10):
        images_html = "".join(
            f'<img src="references/{html.escape(name)}" alt="Synthetic evaluation artwork">'
            for name in printable[offset : offset + 10]
        )
        pages.append(f'<section class="sheet">{images_html}</section>')
    document = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Synthetic 50-name print kit</title><style>@page{size:A4;margin:10mm}body{margin:0;background:#ddd}.instructions{font:16px sans-serif;padding:20px}.sheet{width:190mm;display:grid;grid-template-columns:90mm 90mm;gap:5mm 5mm;background:white;margin:10mm auto;padding:0;break-after:page}.sheet img{width:90mm;height:50mm;display:block}@media print{body{background:white}.instructions{display:none}.sheet{margin:0;break-after:page}.sheet:last-child{break-after:auto}}</style><div class="instructions"><h1>Synthetic evaluation kit</h1><p>Print A4 at 100% / actual size. Measure a card: 90 × 50 mm. Cut the cards, capture photographs in a separate session, and label using the manifest. Do not use these reference PNGs as held-out captures. All identities are fictional; one artwork intentionally maps to two destinations.</p></div>'
        + "".join(pages)
        + "</html>"
    )
    (destination / "print.html").write_text(document, encoding="utf-8")
    (destination / "captures").mkdir()
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "split": "held-out",
                "captureSession": "REPLACE-WITH-ACTUAL-PHYSICAL-CAPTURE-SESSION",
                "cases": cases,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (destination / "README.txt").write_text(
        "Synthetic fixtures only. Import catalog.json with preview, then each sheet-N.json and release. The duplicate artwork remains ambiguous. Unknown designs are not imported as references. Print print.html at 100%, measure dimensions, cut and photograph real prints into captures/. Update manifest session and capture paths. No physical validation or printing was performed by generating this kit. Repeated runs use stable UUIDs; do not import alongside modified versions under the same IDs. Fonts depend on available system fonts; use the exact generated references for this print batch.",
        encoding="utf-8",
    )
    return {
        "referenceVariants": 51,
        "distinctKnownArtworks": 50,
        "nearIdenticalNames": 50,
        "unknownDesigns": 3,
        "physicalCapturesCreated": 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.destination)))
