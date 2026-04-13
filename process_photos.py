#!/usr/bin/env python3
"""
Photo OCR Batch Processor
=========================
Processes batches of scanned double-sided photos.
  - Odd-indexed files (1st, 3rd, 5th…) = front of photo
  - Even-indexed files (2nd, 4th, 6th…) = back of photo

For each pair:
  1. OCRs the back image using Claude vision (handles printed + handwritten text)
  2. Extracts any date found on the back
  3. Updates the front photo's EXIF metadata with the date and any notes

Usage:
    python process_photos.py <input_dir> [--output-dir <dir>]

Requires:
    ANTHROPIC_API_KEY environment variable (or --api-key argument)
"""

import anthropic
import argparse
import base64
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import piexif
from PIL import Image


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff", ".png"}

MEDIA_TYPE_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

# Claude's API max image size recommendation (resize if larger)
MAX_IMAGE_DIMENSION = 1568

DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m",
    "%Y",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m-%d-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %Y",
    "%b %Y",
    "%d %B %Y",
    "%d %b %Y",
]


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def load_image_as_base64(image_path: Path) -> tuple[str, str]:
    """
    Load an image, downsample if needed, and return (base64_data, media_type).
    Images are always converted to JPEG for API transmission to save tokens.
    """
    with Image.open(image_path) as img:
        # Convert palette/RGBA to RGB for JPEG compatibility
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Resize if either dimension exceeds the recommended max
        w, h = img.size
        if w > MAX_IMAGE_DIMENSION or h > MAX_IMAGE_DIMENSION:
            scale = MAX_IMAGE_DIMENSION / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        import io
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        data = base64.standard_b64encode(buf.getvalue()).decode("utf-8")

    return data, "image/jpeg"


# ---------------------------------------------------------------------------
# OCR via Claude vision
# ---------------------------------------------------------------------------

OCR_PROMPT = """\
This is the back of an old photograph. It may contain printed text, stamps, \
handwritten notes, dates, or captions.

Please:
1. Transcribe ALL visible text exactly as written, including both printed/typed \
text and handwritten text.
2. Identify any date or year mentioned (look for patterns like "Summer 1965", \
"July 4th 1952", "12/25/78", etc.).
3. Collect all remaining non-date content as notes.

Respond with ONLY a valid JSON object — no markdown fences, no extra text:
{
  "raw_text": "<full verbatim transcription of everything visible>",
  "date": "<YYYY-MM-DD | YYYY-MM | YYYY | null>",
  "notes": "<all non-date text, cleaned up; empty string if none>"
}

If the back is blank or no text is readable, return:
{"raw_text": "", "date": null, "notes": ""}
"""


def ocr_photo_back(client: anthropic.Anthropic, back_image_path: Path) -> dict:
    """Use Claude vision to OCR the back of a photo. Returns structured dict."""
    image_data, media_type = load_image_as_base64(back_image_path)

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": "You are an expert at reading and transcribing text from old photographs, "
                        "including faded ink, handwriting, stamps, and printed captions. "
                        "Always respond with valid JSON only.",
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": OCR_PROMPT,
                    },
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()

    # Defensively extract the JSON object even if the model wraps it
    json_match = re.search(r"\{[\s\S]*\}", raw)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Fallback: return the raw text with no structured fields
    return {"raw_text": raw, "date": None, "notes": raw}


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Try to parse a flexible date string into a datetime object."""
    if not date_str:
        return None

    date_str = date_str.strip()

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# EXIF metadata writing
# ---------------------------------------------------------------------------


def update_exif_metadata(
    image_path: Path,
    date: Optional[datetime],
    notes: Optional[str],
) -> bool:
    """
    Write date and notes into the EXIF metadata of a JPEG.
    Returns True on success, False if unsupported or failed.
    """
    if image_path.suffix.lower() not in {".jpg", ".jpeg"}:
        return False

    try:
        try:
            exif_dict = piexif.load(str(image_path))
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

        # Ensure required sub-dicts exist
        for key in ("0th", "Exif", "GPS", "1st"):
            exif_dict.setdefault(key, {})

        if date:
            # Use Jan 1 at noon when only a year was available
            dt_str = date.strftime("%Y:%m:%d %H:%M:%S")
            encoded = dt_str.encode("ascii")
            exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = encoded
            exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = encoded
            exif_dict["0th"][piexif.ImageIFD.DateTime] = encoded

        if notes:
            # ImageDescription (ASCII, safe truncation)
            description = notes.encode("ascii", errors="replace")[:2000]
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = description

            # UserComment (Unicode with header bytes)
            user_comment = b"UNICODE\x00" + notes[:500].encode("utf-16-le", errors="replace")
            exif_dict["Exif"][piexif.ExifIFD.UserComment] = user_comment

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, str(image_path))
        return True

    except Exception as exc:
        print(f"    Warning: EXIF update failed for {image_path.name}: {exc}")
        return False


def write_xmp_sidecar(image_path: Path, date: Optional[datetime], notes: Optional[str]):
    """
    Write a minimal XMP sidecar file so non-JPEG formats (TIFF, PNG) also get
    structured metadata that tools like Lightroom / digiKam can read.
    """
    xmp_path = image_path.with_suffix(image_path.suffix + ".xmp")

    date_tag = ""
    if date:
        date_tag = f"<xmp:CreateDate>{date.strftime('%Y-%m-%dT%H:%M:%S')}</xmp:CreateDate>\n        " \
                   f"<xmp:ModifyDate>{date.strftime('%Y-%m-%dT%H:%M:%S')}</xmp:ModifyDate>\n        " \
                   f"<photoshop:DateCreated>{date.strftime('%Y-%m-%dT%H:%M:%S')}</photoshop:DateCreated>"

    notes_tag = ""
    if notes:
        escaped = (notes
                   .replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;")
                   .replace('"', "&quot;"))
        notes_tag = f"<dc:description><rdf:Alt><rdf:li xml:lang='x-default'>{escaped}</rdf:li></rdf:Alt></dc:description>"

    xmp_content = f"""<?xpacket begin='\xef\xbb\xbf' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x='adobe:ns:meta/'>
  <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
    <rdf:Description rdf:about=''
        xmlns:xmp='http://ns.adobe.com/xap/1.0/'
        xmlns:dc='http://purl.org/dc/elements/1.1/'
        xmlns:photoshop='http://ns.adobe.com/photoshop/1.0/'>
        {date_tag}
        {notes_tag}
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>"""

    xmp_path.write_text(xmp_content, encoding="utf-8")
    return xmp_path


# ---------------------------------------------------------------------------
# Batch pairing logic
# ---------------------------------------------------------------------------


def get_photo_pairs(input_dir: Path) -> list[tuple[Path, Optional[Path]]]:
    """
    Sort all supported image files alphabetically and pair them:
      position 0 (odd file 1) → front
      position 1 (even file 2) → back
      position 2 (odd file 3) → front
      …

    Returns a list of (front_path, back_path | None).
    """
    files = sorted(
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    pairs: list[tuple[Path, Optional[Path]]] = []
    for i in range(0, len(files), 2):
        front = files[i]
        back = files[i + 1] if i + 1 < len(files) else None
        pairs.append((front, back))

    return pairs


# ---------------------------------------------------------------------------
# Core batch processor
# ---------------------------------------------------------------------------


def process_batch(input_dir: Path, output_dir: Optional[Path] = None) -> list[dict]:
    """
    Process all photo pairs in input_dir.
    If output_dir is given, copies files there before modifying; otherwise edits in-place.
    Returns a list of result dicts for the summary report.
    """
    client = anthropic.Anthropic()

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    pairs = get_photo_pairs(input_dir)
    if not pairs:
        print(f"No supported image files found in: {input_dir}")
        return []

    print(f"Found {len(pairs)} photo pair(s) to process.\n")

    results = []

    for idx, (front_path, back_path) in enumerate(pairs, start=1):
        print(f"[{idx}/{len(pairs)}]  Front: {front_path.name}")

        result: dict = {
            "index": idx,
            "front": front_path.name,
            "back": back_path.name if back_path else None,
            "raw_text": None,
            "date_extracted": None,
            "notes_extracted": None,
            "exif_updated": False,
            "xmp_written": False,
        }

        if not back_path:
            print("         (no back image — skipping OCR)\n")
            results.append(result)
            continue

        print(f"         Back:  {back_path.name}")

        # --- OCR -------------------------------------------------------
        print("         Running OCR via Claude vision…")
        try:
            ocr = ocr_photo_back(client, back_path)
        except Exception as exc:
            print(f"         ERROR during OCR: {exc}\n")
            results.append(result)
            continue

        raw_text = ocr.get("raw_text", "") or ""
        date_str = ocr.get("date") or None
        notes = ocr.get("notes", "") or ""

        result["raw_text"] = raw_text
        result["date_extracted"] = date_str
        result["notes_extracted"] = notes

        # Pretty-print findings
        preview = raw_text[:120].replace("\n", " ")
        print(f"         Text:  {preview!r}{'…' if len(raw_text) > 120 else ''}")
        print(f"         Date:  {date_str or '(none found)'}")
        if notes:
            note_preview = notes[:100].replace("\n", " ")
            print(f"         Notes: {note_preview!r}{'…' if len(notes) > 100 else ''}")

        # --- Determine working copies ------------------------------------
        if output_dir:
            target_front = output_dir / front_path.name
            target_back = output_dir / back_path.name
            shutil.copy2(str(front_path), str(target_front))
            shutil.copy2(str(back_path), str(target_back))
        else:
            target_front = front_path
            target_back = back_path

        # --- Parse date and write metadata --------------------------------
        parsed_date = parse_date(date_str)
        notes_value = notes if notes else None

        # EXIF (JPEG only)
        exif_ok = update_exif_metadata(target_front, parsed_date, notes_value)
        result["exif_updated"] = exif_ok
        if exif_ok:
            print(f"         EXIF metadata written to {target_front.name}")

        # XMP sidecar for any format (also useful alongside JPEG)
        xmp_path = write_xmp_sidecar(target_front, parsed_date, notes_value)
        result["xmp_written"] = True
        print(f"         XMP sidecar written: {xmp_path.name}")

        # Save raw OCR JSON alongside the back image
        ocr_json_path = target_back.with_suffix(".ocr.json")
        ocr_json_path.write_text(
            json.dumps(ocr, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"         OCR JSON saved:  {ocr_json_path.name}\n")

        results.append(result)

    # --- Summary report ---------------------------------------------------
    report_path = (output_dir or input_dir) / "processing_report.json"
    report_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    total = len(results)
    ocr_done = sum(1 for r in results if r["back"] is not None)
    with_dates = sum(1 for r in results if r["date_extracted"])
    with_notes = sum(1 for r in results if r["notes_extracted"])

    print("=" * 60)
    print(f"Done.  {total} pair(s) processed.")
    print(f"  OCR'd:        {ocr_done}")
    print(f"  Dates found:  {with_dates}")
    print(f"  Notes found:  {with_notes}")
    print(f"  Report:       {report_path}")

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Batch-process scanned double-sided photos.\n"
            "Odd-numbered files are fronts; even-numbered files are backs.\n"
            "Backs are OCR'd with Claude vision; dates and notes are written\n"
            "into EXIF metadata (JPEG) and XMP sidecar files."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input_dir",
        help="Directory containing the scanned photos (sorted alphabetically).",
    )
    parser.add_argument(
        "--output-dir", "-o",
        metavar="DIR",
        help=(
            "Write modified copies here instead of editing files in-place. "
            "The directory will be created if it does not exist."
        ),
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        help="Anthropic API key (overrides the ANTHROPIC_API_KEY environment variable).",
    )

    args = parser.parse_args()

    if args.api_key:
        os.environ["ANTHROPIC_API_KEY"] = args.api_key

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Error: Anthropic API key not found.\n"
            "Set the ANTHROPIC_API_KEY environment variable or use --api-key."
        )
        sys.exit(1)

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        print(f"Error: '{input_dir}' is not a directory.")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else None

    process_batch(input_dir, output_dir)


if __name__ == "__main__":
    main()
