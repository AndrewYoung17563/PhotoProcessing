#!/usr/bin/env python3
"""
Unit tests for process_photos.py
Run with:  python -m pytest test_process_photos.py -v
"""

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from process_photos import (
    DATE_FORMATS,
    get_photo_pairs,
    ocr_photo_back,
    parse_date,
    update_exif_metadata,
    write_xmp_sidecar,
    load_image_as_base64,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_jpeg(path: Path, size=(200, 150), color=(200, 180, 160)):
    """Create a minimal JPEG file at the given path."""
    img = Image.new("RGB", size, color=color)
    img.save(str(path), format="JPEG")


def make_png(path: Path, size=(200, 150), color=(200, 180, 160)):
    img = Image.new("RGB", size, color=color)
    img.save(str(path), format="PNG")


# ---------------------------------------------------------------------------
# get_photo_pairs
# ---------------------------------------------------------------------------


class TestGetPhotoPairs:
    def test_even_number_of_files(self, tmp_path):
        for name in ("a_001.jpg", "a_002.jpg", "b_001.jpg", "b_002.jpg"):
            make_jpeg(tmp_path / name)

        pairs = get_photo_pairs(tmp_path)
        assert len(pairs) == 2
        # First pair
        assert pairs[0][0].name == "a_001.jpg"
        assert pairs[0][1].name == "a_002.jpg"
        # Second pair
        assert pairs[1][0].name == "b_001.jpg"
        assert pairs[1][1].name == "b_002.jpg"

    def test_odd_number_of_files_last_has_no_back(self, tmp_path):
        for name in ("img_01.jpg", "img_02.jpg", "img_03.jpg"):
            make_jpeg(tmp_path / name)

        pairs = get_photo_pairs(tmp_path)
        assert len(pairs) == 2
        assert pairs[0][1].name == "img_02.jpg"
        assert pairs[1][1] is None  # odd one out

    def test_empty_directory(self, tmp_path):
        pairs = get_photo_pairs(tmp_path)
        assert pairs == []

    def test_ignores_non_image_files(self, tmp_path):
        make_jpeg(tmp_path / "photo_01.jpg")
        make_jpeg(tmp_path / "photo_02.jpg")
        (tmp_path / "notes.txt").write_text("hello")
        (tmp_path / "report.json").write_text("{}")

        pairs = get_photo_pairs(tmp_path)
        assert len(pairs) == 1

    def test_mixed_extensions_sorted_together(self, tmp_path):
        make_jpeg(tmp_path / "scan_01.jpg")
        make_png(tmp_path / "scan_02.png")

        pairs = get_photo_pairs(tmp_path)
        assert len(pairs) == 1
        assert pairs[0][0].name == "scan_01.jpg"
        assert pairs[0][1].name == "scan_02.png"


# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    @pytest.mark.parametrize("date_str,expected_year,expected_month,expected_day", [
        ("1965-07-04", 1965, 7, 4),
        ("1965-07",    1965, 7, 1),
        ("1965",       1965, 1, 1),
        ("07/04/1965", 1965, 7, 4),
        ("July 4, 1965", 1965, 7, 4),
        ("Jul 4, 1965",  1965, 7, 4),
        ("July 1965",    1965, 7, 1),
        ("4 July 1965",  1965, 7, 4),
    ])
    def test_valid_formats(self, date_str, expected_year, expected_month, expected_day):
        result = parse_date(date_str)
        assert result is not None
        assert result.year == expected_year
        assert result.month == expected_month
        assert result.day == expected_day

    def test_none_input(self):
        assert parse_date(None) is None

    def test_empty_string(self):
        assert parse_date("") is None

    def test_unrecognised_string(self):
        assert parse_date("not a date at all!!") is None


# ---------------------------------------------------------------------------
# load_image_as_base64
# ---------------------------------------------------------------------------


class TestLoadImageAsBase64:
    def test_returns_base64_string_and_media_type(self, tmp_path):
        p = tmp_path / "test.jpg"
        make_jpeg(p)
        data, media_type = load_image_as_base64(p)
        assert media_type == "image/jpeg"
        assert isinstance(data, str) and len(data) > 0

    def test_large_image_is_downsampled(self, tmp_path):
        p = tmp_path / "big.jpg"
        img = Image.new("RGB", (4000, 3000), color=(100, 100, 100))
        img.save(str(p), format="JPEG")

        data, _ = load_image_as_base64(p)
        import base64, io
        decoded = base64.b64decode(data)
        reloaded = Image.open(io.BytesIO(decoded))
        assert max(reloaded.size) <= 1568


# ---------------------------------------------------------------------------
# update_exif_metadata
# ---------------------------------------------------------------------------


class TestUpdateExifMetadata:
    def test_writes_date_and_notes_to_jpeg(self, tmp_path):
        p = tmp_path / "photo.jpg"
        make_jpeg(p)
        dt = datetime(1965, 7, 4, 12, 0, 0)

        result = update_exif_metadata(p, dt, "Grandma at the beach")
        assert result is True

        import piexif
        exif = piexif.load(str(p))
        raw_date = exif["Exif"].get(piexif.ExifIFD.DateTimeOriginal, b"")
        assert raw_date == b"1965:07:04 12:00:00"

    def test_skips_non_jpeg(self, tmp_path):
        p = tmp_path / "photo.png"
        make_png(p)
        result = update_exif_metadata(p, datetime(1965, 1, 1), "notes")
        assert result is False

    def test_no_date_no_notes_does_not_crash(self, tmp_path):
        p = tmp_path / "photo.jpg"
        make_jpeg(p)
        result = update_exif_metadata(p, None, None)
        assert result is True  # still succeeds, just writes nothing new


# ---------------------------------------------------------------------------
# write_xmp_sidecar
# ---------------------------------------------------------------------------


class TestWriteXmpSidecar:
    def test_creates_xmp_file(self, tmp_path):
        p = tmp_path / "photo.jpg"
        make_jpeg(p)
        xmp = write_xmp_sidecar(p, datetime(1970, 6, 15), "Family reunion")
        assert xmp.exists()
        content = xmp.read_text(encoding="utf-8")
        assert "1970-06-15" in content
        assert "Family reunion" in content

    def test_escapes_special_chars_in_notes(self, tmp_path):
        p = tmp_path / "photo.jpg"
        make_jpeg(p)
        xmp = write_xmp_sidecar(p, None, "<Script> & 'injection'")
        content = xmp.read_text(encoding="utf-8")
        assert "<Script>" not in content  # should be escaped
        assert "&lt;Script&gt;" in content

    def test_no_date_no_notes_still_creates_file(self, tmp_path):
        p = tmp_path / "photo.jpg"
        make_jpeg(p)
        xmp = write_xmp_sidecar(p, None, None)
        assert xmp.exists()


# ---------------------------------------------------------------------------
# ocr_photo_back (mocked)
# ---------------------------------------------------------------------------


class TestOcrPhotoBack:
    def _make_mock_client(self, response_text: str):
        client = MagicMock()
        msg = MagicMock()
        msg.content = [MagicMock(text=response_text)]
        client.messages.create.return_value = msg
        return client

    def test_parses_well_formed_json(self, tmp_path):
        p = tmp_path / "back.jpg"
        make_jpeg(p)
        payload = json.dumps({
            "raw_text": "July 4, 1965. Grandma at the beach.",
            "date": "1965-07-04",
            "notes": "Grandma at the beach.",
        })
        client = self._make_mock_client(payload)
        result = ocr_photo_back(client, p)
        assert result["date"] == "1965-07-04"
        assert "Grandma" in result["notes"]

    def test_handles_json_wrapped_in_markdown(self, tmp_path):
        p = tmp_path / "back.jpg"
        make_jpeg(p)
        payload = '```json\n{"raw_text": "Test", "date": "1980", "notes": "Test note"}\n```'
        client = self._make_mock_client(payload)
        result = ocr_photo_back(client, p)
        assert result["date"] == "1980"

    def test_fallback_on_invalid_json(self, tmp_path):
        p = tmp_path / "back.jpg"
        make_jpeg(p)
        client = self._make_mock_client("Not JSON at all")
        result = ocr_photo_back(client, p)
        # Should not crash; raw_text should contain something
        assert result is not None
        assert "date" in result
