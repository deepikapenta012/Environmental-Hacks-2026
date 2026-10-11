"""Generate deterministic synthetic CSV/PDF/PNG fixtures for every backend testcase.

The testcase fixtures are for test coverage and format handling only. They are
not real evidence and are kept separate from claim labels/model-training rows.
Run from the repository root with: python datasets/generate_testcase_fixtures.py
"""
from __future__ import annotations

import csv
import hashlib
import re
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TESTS = ROOT.parent / "backend" / "tests"
MANIFEST = ROOT / "evidence_split_manifest.csv"
INDEX = "14_automated_testcase_fixture_index.csv"


def discover_cases() -> list[tuple[str, str]]:
    found = []
    for path in sorted(TESTS.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^\s*def\s+(test_[A-Za-z0-9_]+)\s*\(", text, re.MULTILINE):
            found.append((path.name, match.group(1)))
    return found


def assign_splits(cases: list[tuple[str, str]]) -> list[str]:
    # Stable 80/20 split, with at least one testcase per module in test.
    split = ["train"] * len(cases)
    by_module: dict[str, list[int]] = {}
    for i, (module, name) in enumerate(cases):
        by_module.setdefault(module, []).append(i)
    module_test_indices = []
    for indices in by_module.values():
        selected = min(indices, key=lambda i: hashlib.sha256(f"{cases[i][0]}:{cases[i][1]}".encode()).digest())
        split[selected] = "test"
        module_test_indices.append(selected)
    target_test_count = max(len(by_module), round(len(cases) * 0.2))
    remaining = [i for i in range(len(cases)) if split[i] != "test"]
    remaining.sort(key=lambda i: hashlib.sha256(f"split:{cases[i][0]}:{cases[i][1]}".encode()).digest())
    for i in remaining[:max(0, target_test_count - len(module_test_indices))]:
        split[i] = "test"
    return split


def scenario(module: str, name: str) -> str:
    key = f"{module} {name}".lower()
    if "security" in key or "authorization" in key or "access" in key:
        return "access_control"
    if "auth" in key or "login" in key:
        return "authentication"
    if "migration" in key or "schema" in key:
        return "database_migration"
    if "audit" in key or "history" in key:
        return "audit_history"
    if "document" in key or "quantity" in key or "image" in key or "pdf" in key:
        return "document_extraction_and_consistency"
    if "evidence" in key or "duplicate" in key or "replacement" in key or "upload" in key:
        return "evidence_lifecycle_and_integrity"
    if "transport" in key or "transit" in key or "gps" in key:
        return "transport_validation"
    if "mass" in key or "score" in key or "verification" in key or "claim" in key:
        return "claim_verification_and_scoring"
    return "workflow_and_data_integrity"


def safe_pdf_text(value: str) -> str:
    return value.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(lines: list[str]) -> bytes:
    commands = ["BT", "/F1 11 Tf", "50 750 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -22 Td")
        commands.append(f"({safe_pdf_text(line)}) Tj")
    commands += ["ET", "BT", "/F1 8 Tf", "50 45 Td", "(SYNTHETIC DEMO FIXTURE - NOT VALID EVIDENCE) Tj", "ET"]
    stream = "\n".join(commands).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for n, body in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{n} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def make_png(seed: int, title: str) -> bytes:
    # Draw a document-scan style preview using only the standard library.
    width, height = 720, 900
    pixels = bytearray([245, 246, 248] * width * height)

    def rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        x0, x1 = max(0, x0), min(width, x1)
        y0, y1 = max(0, y0), min(height, y1)
        row = bytes(color) * (x1 - x0)
        for y in range(y0, y1):
            start = (y * width + x0) * 3
            pixels[start:start + len(row)] = row

    rect(45, 35, 675, 865, (255, 255, 253))
    rect(45, 35, 675, 130, (20, 44, 78))
    # Header stripe and a serial-like barcode.
    rect(75, 158, 510, 168, (31, 115, 140))
    for bit in range(90):
        if (seed >> (bit % 24)) & 1 or bit % 3 == 0:
            x = 535 + bit * 1
            rect(x, 150, x + (1 if bit % 4 else 2), 208, (30, 37, 48))
    # Form fields, checkbox blocks, and a red review stamp.
    for i in range(9):
        y = 235 + i * 58
        rect(78, y, 205, y + 7, (112, 126, 145))
        rect(225, y, 625, y + 7, (207, 213, 220))
        rect(78, y + 16, 625, y + 20, (232, 235, 239))
    rect(76, 785, 290, 793, (44, 132, 98))
    rect(500, 725, 625, 805, (183, 50, 50))
    # Make testcase-specific scan texture variation deterministic.
    for i in range(1 + seed % 5):
        y = 210 + ((seed >> (i * 3)) % 600)
        rect(60, y, 660, y + 1, (250, 249, 246))
    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3:(y + 1) * width * 3]) for y in range(height))
    header = struct.pack(">2I", width, height) + bytes([8, 2, 0, 0, 0])
    return b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(raw, 9)) + png_chunk(b"IEND", b"")


def main() -> None:
    cases = discover_cases()
    if not cases:
        raise SystemExit(f"No pytest cases found under {TESTS}")
    splits = assign_splits(cases)
    for split in ("train", "test"):
        for subdir, suffix in (("pdf", "evidence.pdf"), ("images", "scan.png")):
            folder = ROOT / split / "evidence" / subdir
            if folder.exists():
                for stale in folder.glob(f"tc-????_{suffix}"):
                    stale.unlink()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0)
    manifest_rows = []
    counts = {"train": 0, "test": 0}
    index_rows: dict[str, list[dict[str, str]]] = {"train": [], "test": []}
    for index, ((module, test_name), split) in enumerate(zip(cases, splits), 1):
        testcase_id = f"TC-{index:04d}"
        counts[split] += 1
        split_index = counts[split]
        rng_seed = int.from_bytes(hashlib.sha256(testcase_id.encode()).digest()[:4], "big")
        declared = round(180 + (rng_seed % 182000) / 100, 2)
        variance = ((rng_seed >> 8) % 1500 - 400) / 10000
        received = round(declared * (1 + variance), 2)
        event_time = generated_at - timedelta(days=(index * 7) % 120, hours=index % 24)
        case_category = scenario(module, test_name)
        pdf_name = f"{testcase_id.lower()}_evidence.pdf"
        image_name = f"{testcase_id.lower()}_scan.png"
        pdf_rel = f"evidence/pdf/{pdf_name}"
        image_rel = f"evidence/images/{image_name}"
        base = ROOT / split
        (base / "evidence" / "pdf").mkdir(parents=True, exist_ok=True)
        (base / "evidence" / "images").mkdir(parents=True, exist_ok=True)
        (base / "datasets").mkdir(parents=True, exist_ok=True)
        lines = [
            "CHAIN GUARD SYNTHETIC E-WASTE RECORD",
            f"Test case: {test_name}",
            f"Test module: {module}",
            f"Scenario: {case_category.replace('_', ' ').title()}",
            f"Reference: {testcase_id}",
            f"Recorded (UTC): {event_time.isoformat()}",
            f"Declared shipment weight: {declared:.2f} kg",
            f"Recycler received weight: {received:.2f} kg",
            "Material: mixed electrical and electronic equipment",
            "Route: Bengaluru, Karnataka to Hyderabad, Telangana",
            "Record status: TEST FIXTURE - NOT A REAL TRANSACTION",
        ]
        (base / pdf_rel).write_bytes(make_pdf(lines))
        (base / image_rel).write_bytes(make_png(rng_seed, test_name))
        row = {
            "testcase_id": testcase_id,
            "test_module": module,
            "test_name": test_name,
            "scenario_category": case_category,
            "split": split,
            "fixture_index_in_split": split_index,
            "observed_at_utc": event_time.isoformat(),
            "origin": "Bengaluru, Karnataka",
            "destination": "Hyderabad, Telangana",
            "material_category": "Mixed E-Waste",
            "declared_weight_kg": f"{declared:.2f}",
            "received_weight_kg": f"{received:.2f}",
            "pdf_fixture": pdf_rel,
            "image_fixture": image_rel,
            "data_purpose": "AUTOMATED_TESTCASE_COVERAGE_ONLY",
            "synthetic_fixture": "YES",
        }
        index_rows[split].append(row)
        for rel, mime in ((pdf_rel, "application/pdf"), (image_rel, "image/png")):
            file_name = Path(rel).name
            manifest_rows.append({
                "file_name": file_name,
                "file_type": "pdf" if mime == "application/pdf" else "png",
                "split": split,
                "linked_claim_id": testcase_id,
                "source": f"synthetic automated testcase fixture ({module}:{test_name})",
            })

    fields = list(index_rows["train"][0])
    for split in ("train", "test"):
        with (ROOT / split / "datasets" / INDEX).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(index_rows[split])

    manifest_fields = ["file_name", "file_type", "split", "linked_claim_id", "source"]
    existing_rows = []
    if MANIFEST.exists():
        with MANIFEST.open(newline="", encoding="utf-8") as handle:
            existing_rows = [row for row in csv.DictReader(handle)
                             if not row.get("source", "").startswith("synthetic automated testcase fixture (")]
    with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=manifest_fields)
        writer.writeheader()
        writer.writerows(existing_rows)
        writer.writerows(manifest_rows)
    print(f"Generated {len(cases)} testcase fixtures: {counts['train']} train, {counts['test']} test.")


if __name__ == "__main__":
    main()
