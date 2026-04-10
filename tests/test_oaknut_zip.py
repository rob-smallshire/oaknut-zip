"""Extensive tests for oaknut-zip - Acorn metadata ZIP extractor."""

from __future__ import annotations

import io
import os
import struct
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

requires_xattr = pytest.mark.skipif(
    sys.platform == "win32", reason="Extended attributes not supported on Windows"
)


def get_xattr(filepath: Path, name: str) -> bytes:
    """Read an extended attribute, using os.getxattr on Linux or xattr package on macOS."""
    if hasattr(os, "getxattr"):
        return os.getxattr(str(filepath), name)
    else:
        import xattr

        return xattr.xattr(str(filepath)).get(name)


def list_xattrs(filepath: Path) -> list[str]:
    """List extended attribute names on a file."""
    if hasattr(os, "listxattr"):
        return os.listxattr(str(filepath))
    else:
        import xattr

        return xattr.xattr(str(filepath)).list()


from click.testing import CliRunner

from oaknut_zip import (
    AcornMeta,
    MetaFormat,
    build_filename_suffix,
    build_inf_index,
    build_mos_filename_suffix,
    extract_member,
    format_access,
    format_pieb_inf_line,
    format_trad_inf_line,
    parse_encoded_filename,
    parse_inf_line,
    parse_sparkfs_extra,
    resolve_metadata,
    sanitise_extract_path,
    write_econet_xattrs,
)
from oaknut_zip.cli import cli

FIXTURES_DIRPATH = Path(__file__).resolve().parent / "fixtures"
NETUTILS_ZIP_FILEPATH = FIXTURES_DIRPATH / "NetUtils.zip"
NETUTILB_ZIP_FILEPATH = FIXTURES_DIRPATH / "NetUtilB.zip"
SWEH_ZIP_FILEPATH = FIXTURES_DIRPATH / "sweh_econet_system.zip"
MASTER_ZIP_FILEPATH = FIXTURES_DIRPATH / "MASTER.zip"
TESTDIR_UNIX_ZIP_FILEPATH = FIXTURES_DIRPATH / "testdir-unix.zip"
TESTDIR_RO_ZIP_FILEPATH = FIXTURES_DIRPATH / "testdir-ro.zip"


# ---------------------------------------------------------------------------
# Helpers for building synthetic ZIPs with SparkFS extra fields
# ---------------------------------------------------------------------------


def build_sparkfs_extra(
    load_addr: int,
    exec_addr: int,
    attr: int = 0x03,
    reserved: int = 0,
) -> bytes:
    """Build a SparkFS/ARC0 extra field block."""
    arc0_data = b"ARC0" + struct.pack("<IIII", load_addr, exec_addr, attr, reserved)
    return struct.pack("<HH", 0x4341, len(arc0_data)) + arc0_data


def make_zip_bytes(entries: list[tuple[str, bytes, bytes | None]]) -> bytes:
    """Create a ZIP in memory. entries = [(filename, data, extra_or_None), ...]"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for filename, data, extra in entries:
            info = zipfile.ZipInfo(filename)
            if extra:
                info.extra = extra
            zf.writestr(info, data)
    return buf.getvalue()


def make_zip_file(
    tmp_path: Path,
    entries: list[tuple[str, bytes, bytes | None]],
    name: str = "test.zip",
) -> Path:
    """Write a synthetic ZIP to tmp_path and return its path."""
    filepath = tmp_path / name
    filepath.write_bytes(make_zip_bytes(entries))
    return filepath


# =========================================================================
# AcornMeta dataclass
# =========================================================================


class TestAcornMeta:
    def test_has_metadata_when_load_addr_set(self):
        meta = AcornMeta(load_addr=0x1900, exec_addr=0x801F)
        assert meta.has_metadata is True

    def test_has_metadata_false_when_none(self):
        meta = AcornMeta()
        assert meta.has_metadata is False

    def test_filetype_stamped_when_fff_prefix(self):
        meta = AcornMeta(load_addr=0xFFFFF000)
        assert meta.is_filetype_stamped is True

    def test_filetype_stamped_false_for_plain_address(self):
        meta = AcornMeta(load_addr=0x00001900)
        assert meta.is_filetype_stamped is False

    def test_filetype_stamped_false_when_none(self):
        meta = AcornMeta()
        assert meta.is_filetype_stamped is False

    def test_infer_filetype_from_load_addr(self):
        # RISC OS BASIC = type FFB
        meta = AcornMeta(load_addr=0xFFFFB00)
        assert meta.infer_filetype() is None  # not fff prefix

        meta = AcornMeta(load_addr=0xFFFFB00)
        assert meta.is_filetype_stamped is False

    def test_infer_filetype_basic(self):
        # load_addr = 0xFFFFFB00 -> filetype FFB (BASIC)
        meta = AcornMeta(load_addr=0xFFFFFB00)
        assert meta.infer_filetype() == 0xFFB

    def test_infer_filetype_text(self):
        # load_addr = 0xFFFFFF52 -> filetype FFF (Text)
        meta = AcornMeta(load_addr=0xFFFFFF52)
        assert meta.infer_filetype() == 0xFFF

    def test_infer_filetype_fdd(self):
        # load_addr = 0xFFFFDD00 -> filetype FDD (BASIC stored)
        meta = AcornMeta(load_addr=0xFFFFDD00)
        assert meta.infer_filetype() == 0xFDD

    def test_infer_filetype_f0e(self):
        # Utility command, type F0E
        meta = AcornMeta(load_addr=0xFFFF0E10)
        assert meta.infer_filetype() == 0xF0E

    def test_infer_filetype_f09(self):
        meta = AcornMeta(load_addr=0xFFFF0900)
        assert meta.infer_filetype() == 0xF09

    def test_infer_filetype_falls_back_to_explicit(self):
        meta = AcornMeta(load_addr=0x00001900, filetype=0xFFB)
        assert meta.infer_filetype() == 0xFFB

    def test_infer_filetype_none_when_no_data(self):
        meta = AcornMeta()
        assert meta.infer_filetype() is None


# =========================================================================
# SparkFS extra field parsing
# =========================================================================


class TestParseSparkfsExtra:
    def test_valid_extra_field(self):
        extra = build_sparkfs_extra(0xFFFF0E10, 0xFFFF0E10, 0x03)
        meta = parse_sparkfs_extra(extra)
        assert meta is not None
        assert meta.load_addr == 0xFFFF0E10
        assert meta.exec_addr == 0xFFFF0E10
        assert meta.attr == 0x03
        assert meta.filetype == 0xF0E

    def test_different_load_and_exec(self):
        extra = build_sparkfs_extra(0xFFFF0900, 0xFFFF091A, 0x17)
        meta = parse_sparkfs_extra(extra)
        assert meta is not None
        assert meta.load_addr == 0xFFFF0900
        assert meta.exec_addr == 0xFFFF091A
        assert meta.attr == 0x17

    def test_text_file(self):
        extra = build_sparkfs_extra(0xFFFFFF52, 0x2FEEAFD0, 0x0B)
        meta = parse_sparkfs_extra(extra)
        assert meta is not None
        assert meta.filetype == 0xFFF

    def test_non_filetype_stamped(self):
        extra = build_sparkfs_extra(0x00001900, 0x0000801F, 0x03)
        meta = parse_sparkfs_extra(extra)
        assert meta is not None
        assert meta.load_addr == 0x00001900
        assert meta.exec_addr == 0x0000801F
        assert meta.is_filetype_stamped is False
        assert meta.filetype is None

    def test_empty_extra(self):
        assert parse_sparkfs_extra(b"") is None

    def test_no_sparkfs_field(self):
        # Unix timestamp extra field (0x5455) - not SparkFS
        extra = struct.pack("<HH", 0x5455, 5) + b"\x01\x00\x00\x00\x00"
        assert parse_sparkfs_extra(extra) is None

    def test_wrong_signature(self):
        # Correct header ID but wrong signature
        bad_data = b"XXXX" + struct.pack("<IIII", 0, 0, 0, 0)
        extra = struct.pack("<HH", 0x4341, len(bad_data)) + bad_data
        assert parse_sparkfs_extra(extra) is None

    def test_truncated_extra(self):
        # Header says 20 bytes but data is shorter
        extra = struct.pack("<HH", 0x4341, 20) + b"ARC0" + b"\x00" * 4
        assert parse_sparkfs_extra(extra) is None

    def test_sparkfs_among_other_fields(self):
        # Unix timestamp field, then SparkFS field
        unix_extra = struct.pack("<HH", 0x5455, 5) + b"\x01\x00\x00\x00\x00"
        sparkfs_extra = build_sparkfs_extra(0xFFFF0E23, 0xFFFF0E23, 0x0C)
        combined = unix_extra + sparkfs_extra
        meta = parse_sparkfs_extra(combined)
        assert meta is not None
        assert meta.load_addr == 0xFFFF0E23

    def test_sparkfs_field_with_larger_data_size(self):
        # data_size > 20 should still work
        arc0_data = b"ARC0" + struct.pack("<IIII", 0xFFFF0E10, 0xFFFF0E10, 0x03, 0)
        arc0_data += b"\x00" * 8  # extra padding
        extra = struct.pack("<HH", 0x4341, len(arc0_data)) + arc0_data
        meta = parse_sparkfs_extra(extra)
        assert meta is not None
        assert meta.load_addr == 0xFFFF0E10

    def test_zero_addresses(self):
        extra = build_sparkfs_extra(0x00000000, 0x00000000, 0x00)
        meta = parse_sparkfs_extra(extra)
        assert meta is not None
        assert meta.load_addr == 0
        assert meta.exec_addr == 0

    def test_max_addresses(self):
        extra = build_sparkfs_extra(0xFFFFFFFF, 0xFFFFFFFF, 0xFF)
        meta = parse_sparkfs_extra(extra)
        assert meta is not None
        assert meta.load_addr == 0xFFFFFFFF
        assert meta.exec_addr == 0xFFFFFFFF
        assert meta.attr == 0xFF


# =========================================================================
# Encoded filename parsing
# =========================================================================


class TestParseEncodedFilename:
    def test_filetype_suffix(self):
        clean, meta = parse_encoded_filename("HELLO,ffb")
        assert clean == "HELLO"
        assert meta is not None
        assert meta.filetype == 0xFFB
        assert meta.is_filetype_stamped is True

    def test_filetype_uppercase(self):
        clean, meta = parse_encoded_filename("README,FFF")
        assert clean == "README"
        assert meta.filetype == 0xFFF

    def test_filetype_mixed_case(self):
        clean, meta = parse_encoded_filename("File,fFb")
        assert clean == "File"
        assert meta.filetype == 0xFFB

    def test_load_exec_suffix(self):
        clean, meta = parse_encoded_filename("PROG,ffff0e10,0000801f")
        assert clean == "PROG"
        assert meta is not None
        assert meta.load_addr == 0xFFFF0E10
        assert meta.exec_addr == 0x0000801F

    def test_load_exec_uppercase(self):
        clean, meta = parse_encoded_filename("PROG,FFFF0E10,0000801F")
        assert clean == "PROG"
        assert meta.load_addr == 0xFFFF0E10
        assert meta.exec_addr == 0x0000801F

    def test_plain_filename_no_comma(self):
        clean, meta = parse_encoded_filename("README")
        assert clean == "README"
        assert meta is None

    def test_plain_filename_with_non_hex_suffix(self):
        clean, meta = parse_encoded_filename("notes,txt")
        assert clean == "notes,txt"
        assert meta is None

    def test_filetype_too_short(self):
        clean, meta = parse_encoded_filename("file,ff")
        assert clean == "file,ff"
        assert meta is None

    def test_filetype_too_long(self):
        clean, meta = parse_encoded_filename("file,ffff")
        assert clean == "file,ffff"
        assert meta is None

    def test_load_exec_too_short(self):
        clean, meta = parse_encoded_filename("file,ffff0e1,0000801f")
        assert clean == "file,ffff0e1,0000801f"
        assert meta is None

    def test_path_with_directories(self):
        clean, meta = parse_encoded_filename("dir/subdir/FILE,ffb")
        assert clean == "dir/subdir/FILE"
        assert meta.filetype == 0xFFB

    def test_path_with_load_exec(self):
        clean, meta = parse_encoded_filename("path/to/PROG,ffff0e10,0000801f")
        assert clean == "path/to/PROG"
        assert meta.load_addr == 0xFFFF0E10

    def test_filetype_synthesises_load_addr(self):
        _, meta = parse_encoded_filename("FILE,f0e")
        # 0xFFF00000 | (0xF0E << 8) = 0xFFFF0E00
        assert meta.load_addr == 0xFFFF0E00
        assert meta.exec_addr == 0
        assert meta.is_filetype_stamped is True
        assert meta.infer_filetype() == 0xF0E

    def test_load_exec_with_filetype_in_load(self):
        _, meta = parse_encoded_filename("FILE,ffff0e10,ffff0e10")
        assert meta.infer_filetype() == 0xF0E

    def test_load_exec_without_filetype_in_load(self):
        _, meta = parse_encoded_filename("FILE,00001900,0000801f")
        assert meta.infer_filetype() is None

    def test_mos_dash_form(self):
        clean, meta = parse_encoded_filename("PROG,1900-801F")
        assert clean == "PROG"
        assert meta is not None
        assert meta.load_addr == 0x1900
        assert meta.exec_addr == 0x801F

    def test_mos_dash_form_full_width(self):
        clean, meta = parse_encoded_filename("FILE,FFFF0E10-FFFF0E10")
        assert clean == "FILE"
        assert meta.load_addr == 0xFFFF0E10
        assert meta.exec_addr == 0xFFFF0E10
        assert meta.infer_filetype() == 0xF0E

    def test_mos_dash_form_short(self):
        clean, meta = parse_encoded_filename("DATA,0-0")
        assert clean == "DATA"
        assert meta.load_addr == 0
        assert meta.exec_addr == 0

    def test_mos_dash_form_with_path(self):
        clean, meta = parse_encoded_filename("dir/FILE,1900-801F")
        assert clean == "dir/FILE"
        assert meta.load_addr == 0x1900

    def test_mos_dash_form_lowercase(self):
        clean, meta = parse_encoded_filename("file,ffff0e10-ffff0e10")
        assert clean == "file"
        assert meta.load_addr == 0xFFFF0E10

    def test_mos_dash_no_comma(self):
        """Dash without comma prefix is not a MOS encoding."""
        clean, meta = parse_encoded_filename("file-1900")
        assert clean == "file-1900"
        assert meta is None


# =========================================================================
# INF line parsing
# =========================================================================


class TestParseInfLine:
    def test_trad_inf_with_access(self):
        result = parse_inf_line("SetStation  FFFFDD00 FFFFDD00 000002E3 03")
        assert result is not None
        source, meta = result
        assert source == "inf-trad"
        assert meta.load_addr == 0xFFFFDD00
        assert meta.exec_addr == 0xFFFFDD00
        assert meta.attr == 0x03

    def test_trad_inf_without_access(self):
        result = parse_inf_line("README      FFFFF004 FFFFF004 00000100")
        assert result is not None
        source, meta = result
        assert source == "inf-trad"
        assert meta.load_addr == 0xFFFFF004
        assert meta.attr is None

    def test_pieb_inf(self):
        result = parse_inf_line("0 fffff93a c7524201 33")
        assert result is not None
        source, meta = result
        assert source == "inf-pieb"
        assert meta.load_addr == 0xFFFFF93A
        assert meta.exec_addr == 0xC7524201
        assert meta.attr == 0x33

    def test_pieb_inf_zero_owner(self):
        result = parse_inf_line("0 ffffdd00 ffffdd00 3")
        assert result is not None
        source, meta = result
        assert source == "inf-pieb"
        assert meta.load_addr == 0xFFFFDD00

    def test_trad_inf_hex_filename(self):
        # A filename like "FF" is valid hex but should be detected as traditional
        # when field[3] is 8 digits (the length field)
        result = parse_inf_line("FF          FFFFDD00 FFFFDD00 00000010 03")
        assert result is not None
        source, meta = result
        assert source == "inf-trad"
        assert meta.load_addr == 0xFFFFDD00

    def test_too_few_fields(self):
        assert parse_inf_line("only three fields") is None
        assert parse_inf_line("a b c") is None

    def test_empty_line(self):
        assert parse_inf_line("") is None

    def test_invalid_hex(self):
        assert parse_inf_line("FILE ZZZZ0000 00000000 00000010") is None

    def test_filetype_inferred(self):
        result = parse_inf_line("0 ffffdd00 ffffdd00 3")
        assert result is not None
        _, meta = result
        assert meta.filetype == 0xFDD

    def test_pieb_inf_with_homeof(self):
        result = parse_inf_line("0 fffff93a c7524201 33 0")
        assert result is not None
        source, meta = result
        assert source == "inf-pieb"


class TestBuildInfIndex:
    def _make_zip_with_inf(self, tmp_path, entries):
        """Create a ZIP with data files and companion .inf files.

        entries is a list of (filename, data, inf_content) tuples.
        If inf_content is None, no .inf file is created.
        """
        zip_filepath = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_filepath, "w") as zf:
            for filename, data, inf_content in entries:
                zf.writestr(filename, data)
                if inf_content is not None:
                    zf.writestr(filename + ".inf", inf_content)
        return zip_filepath

    def test_pieb_inf_detected(self, tmp_path):
        zip_filepath = self._make_zip_with_inf(
            tmp_path, [("FILE", b"\x00" * 8, "0 ffffdd00 ffffdd00 3")]
        )
        with zipfile.ZipFile(zip_filepath) as zf:
            index, consumed = build_inf_index(zf)
        assert "FILE" in index
        source, meta = index["FILE"]
        assert source == "inf-pieb"
        assert meta.load_addr == 0xFFFFDD00
        assert "FILE.inf" in consumed

    def test_trad_inf_detected(self, tmp_path):
        zip_filepath = self._make_zip_with_inf(
            tmp_path,
            [("PROG", b"\x00" * 16, "PROG        FFFF0E10 FFFF0E10 00000010 03")],
        )
        with zipfile.ZipFile(zip_filepath) as zf:
            index, consumed = build_inf_index(zf)
        assert "PROG" in index
        source, meta = index["PROG"]
        assert source == "inf-trad"
        assert meta.load_addr == 0xFFFF0E10
        assert meta.attr == 0x03

    def test_orphan_inf_not_consumed(self, tmp_path):
        """An .inf with no corresponding data file is not consumed."""
        zip_filepath = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_filepath, "w") as zf:
            zf.writestr("ORPHAN.inf", "0 ffffdd00 ffffdd00 3")
        with zipfile.ZipFile(zip_filepath) as zf:
            index, consumed = build_inf_index(zf)
        assert len(index) == 0
        assert len(consumed) == 0

    def test_unparseable_inf_not_consumed(self, tmp_path):
        zip_filepath = self._make_zip_with_inf(
            tmp_path, [("FILE", b"\x00", "not valid inf content")]
        )
        with zipfile.ZipFile(zip_filepath) as zf:
            index, consumed = build_inf_index(zf)
        assert len(index) == 0
        assert len(consumed) == 0

    def test_nested_path(self, tmp_path):
        zip_filepath = self._make_zip_with_inf(
            tmp_path,
            [("Library/FILE", b"\x00" * 8, "0 ffffdd00 ffffdd00 3")],
        )
        with zipfile.ZipFile(zip_filepath) as zf:
            index, consumed = build_inf_index(zf)
        assert "Library/FILE" in index
        assert "Library/FILE.inf" in consumed


# =========================================================================
# resolve_metadata with INF index
# =========================================================================


class TestResolveMetadataWithInf:
    def _make_info(
        self, filename: str, extra: bytes = b"", file_size: int = 100
    ) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(filename)
        info.extra = extra
        info.file_size = file_size
        return info

    def test_inf_used_when_no_sparkfs(self):
        info = self._make_info("FILE")
        inf_index = {"FILE": ("inf-pieb", AcornMeta(load_addr=0xFFFFDD00, exec_addr=0xFFFFDD00, attr=3))}
        source, clean, meta = resolve_metadata(info, inf_index=inf_index)
        assert source == "inf-pieb"
        assert meta.load_addr == 0xFFFFDD00

    def test_sparkfs_beats_inf(self):
        extra = build_sparkfs_extra(0xFFFF0E10, 0xFFFF0E10, 0x03)
        info = self._make_info("FILE", extra=extra)
        inf_index = {"FILE": ("inf-pieb", AcornMeta(load_addr=0xFFFFDD00, exec_addr=0xFFFFDD00, attr=3))}
        source, clean, meta = resolve_metadata(info, inf_index=inf_index)
        assert source == "sparkfs"
        assert meta.load_addr == 0xFFFF0E10

    def test_inf_beats_filename_encoding(self):
        info = self._make_info("FILE,ffb")
        inf_index = {"FILE,ffb": ("inf-trad", AcornMeta(load_addr=0xFFFF0E10, exec_addr=0xFFFF0E10, attr=3))}
        source, clean, meta = resolve_metadata(info, inf_index=inf_index)
        assert source == "inf-trad"
        assert meta.load_addr == 0xFFFF0E10


# =========================================================================
# resolve_metadata
# =========================================================================


class TestResolveMetadata:
    def _make_info(
        self, filename: str, extra: bytes = b"", file_size: int = 100
    ) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(filename)
        info.extra = extra
        info.file_size = file_size
        return info

    def test_sparkfs_preferred_over_filename(self):
        extra = build_sparkfs_extra(0xFFFF0E10, 0xFFFF0E10, 0x03)
        info = self._make_info("FILE,ffb", extra=extra)
        source, clean, meta = resolve_metadata(info)
        assert source == "sparkfs"
        # Encoded suffix still stripped from filename
        assert clean == "FILE"
        assert meta.load_addr == 0xFFFF0E10

    def test_filename_when_no_sparkfs(self):
        info = self._make_info("FILE,ffb")
        source, clean, meta = resolve_metadata(info)
        assert source == "filename"
        assert clean == "FILE"
        assert meta.filetype == 0xFFB

    def test_plain_file_no_metadata(self):
        info = self._make_info("README")
        source, clean, meta = resolve_metadata(info)
        assert source is None
        assert clean == "README"
        assert meta is None

    def test_decode_filenames_disabled(self):
        info = self._make_info("FILE,ffb")
        source, clean, meta = resolve_metadata(info, decode_filenames=False)
        assert source is None
        assert clean == "FILE,ffb"
        assert meta is None

    def test_sparkfs_still_works_when_decode_disabled(self):
        extra = build_sparkfs_extra(0xFFFF0E10, 0xFFFF0E10, 0x03)
        info = self._make_info("FILE,ffb", extra=extra)
        source, clean, meta = resolve_metadata(info, decode_filenames=False)
        assert source == "sparkfs"
        assert clean == "FILE,ffb"  # Encoded suffix preserved
        assert meta.load_addr == 0xFFFF0E10


# =========================================================================
# INF formatting
# =========================================================================


class TestFormatTradInfLine:
    def test_basic_format(self):
        line = format_trad_inf_line("UTILS", 0xFFFF0E00, 0x0000801F, 0x100, 0x03)
        assert line == "UTILS       FFFF0E00 0000801F 00000100 03"

    def test_without_attr(self):
        line = format_trad_inf_line("FILE", 0xFFFF0E10, 0xFFFF0E10, 0x80)
        assert line == "FILE        FFFF0E10 FFFF0E10 00000080"

    def test_long_filename(self):
        line = format_trad_inf_line("VERYLONGNAME", 0x1900, 0x801F, 0x100)
        assert line.startswith("VERYLONGNAME ")
        assert "00001900" in line

    def test_short_filename_padded(self):
        line = format_trad_inf_line("A", 0, 0, 0)
        assert line.startswith("A          ")

    def test_zero_addresses(self):
        line = format_trad_inf_line("FILE", 0, 0, 0, 0)
        assert "00000000 00000000 00000000 00" in line

    def test_max_addresses(self):
        line = format_trad_inf_line("FILE", 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFF)
        assert "FFFFFFFF FFFFFFFF FFFFFFFF FF" in line


class TestFormatPibridgeInfLine:
    def test_basic_format(self):
        line = format_pieb_inf_line(0xFFFF0E23, 0xFFFF0E23, 0x15, owner=0)
        assert line == "0 ffff0e23 ffff0e23 15"

    def test_with_owner(self):
        line = format_pieb_inf_line(0xFFFF0E10, 0xFFFF0E10, 0x03, owner=5)
        assert line == "5 ffff0e10 ffff0e10 3"

    def test_default_perm_for_none_attr(self):
        line = format_pieb_inf_line(0xFFFF0E10, 0xFFFF0E10, attr=None)
        assert line == "0 ffff0e10 ffff0e10 17"

    def test_zero_addresses(self):
        line = format_pieb_inf_line(0, 0, 0, owner=0)
        assert line == "0 0 0 0"


class TestFormatAccess:
    def test_none(self):
        assert format_access(None) == ""

    def test_zero(self):
        assert format_access(0) == "00"

    def test_typical(self):
        assert format_access(0x03) == "03"
        assert format_access(0x17) == "17"
        assert format_access(0xFF) == "FF"


# =========================================================================
# Path safety
# =========================================================================


class TestSanitiseExtractPath:
    def test_simple_path(self, tmp_path):
        result = sanitise_extract_path(tmp_path, "file.txt")
        assert result == tmp_path / "file.txt"

    def test_subdirectory(self, tmp_path):
        result = sanitise_extract_path(tmp_path, "dir/file.txt")
        assert result == tmp_path / "dir" / "file.txt"

    def test_strips_dotdot(self, tmp_path):
        result = sanitise_extract_path(tmp_path, "../../../etc/passwd")
        assert result == tmp_path / "etc" / "passwd"

    def test_strips_leading_slash(self, tmp_path):
        result = sanitise_extract_path(tmp_path, "/absolute/path")
        assert result == tmp_path / "absolute" / "path"

    def test_empty_after_sanitise(self, tmp_path):
        result = sanitise_extract_path(tmp_path, "../..")
        assert result == tmp_path / "_"

    def test_backslash_stripped(self, tmp_path):
        result = sanitise_extract_path(tmp_path, "\\dir\\file")
        assert "dir" in str(result)


# =========================================================================
# Extraction with real ZIP fixtures
# =========================================================================


class TestNetUtilsZip:
    """Tests using the real NetUtils.zip from MDFS (SparkFS extra fields)."""

    def test_fixture_exists(self):
        assert NETUTILS_ZIP_FILEPATH.is_file()

    def test_is_valid_zip(self):
        assert zipfile.is_zipfile(NETUTILS_ZIP_FILEPATH)

    def test_all_entries_have_sparkfs(self):
        with zipfile.ZipFile(NETUTILS_ZIP_FILEPATH) as zf:
            for info in zf.infolist():
                meta = parse_sparkfs_extra(info.extra)
                assert meta is not None, f"{info.filename} missing SparkFS extra"

    def test_entry_count(self):
        with zipfile.ZipFile(NETUTILS_ZIP_FILEPATH) as zf:
            assert len(zf.infolist()) == 12

    def test_known_entries_metadata(self):
        """Verify metadata for specific files matches known values."""
        expected = {
            "Free": (0xFFFF0E10, 0xFFFF0E10, 0xF0E, 486),
            "FSList": (0xFFFF0900, 0xFFFF0900, 0xF09, 512),
            "PSList": (0xFFFF0900, 0xFFFF0900, 0xF09, 437),
            "Notify": (0xFFFF0E23, 0xFFFF0E23, 0xF0E, 298),
            "Remote": (0xFFFF0E10, 0xFFFF0E10, 0xF0E, 493),
            "Servers": (0xFFFF0900, 0xFFFF091A, 0xF09, 463),
            "SetStation": (0xFFFFDD00, 0xFFFFDD00, 0xFDD, 512),
            "Stations": (0xFFFF08D5, 0xFFFF08E1, 0xF08, 555),
            "SJMon": (0xFFFF1B00, 0xFFFF1B00, 0xF1B, 3454),
            "Users": (0xFFFF0E23, 0xFFFF0E23, 0xF0E, 313),
            "View": (0xFFFF0900, 0xFFFF0904, 0xF09, 511),
            "ReadMe": (0xFFFFFF52, 0x2FEEAFD0, 0xFFF, 597),
        }
        with zipfile.ZipFile(NETUTILS_ZIP_FILEPATH) as zf:
            for info in zf.infolist():
                meta = parse_sparkfs_extra(info.extra)
                exp = expected[info.filename]
                assert meta.load_addr == exp[0], f"{info.filename} load"
                assert meta.exec_addr == exp[1], f"{info.filename} exec"
                assert meta.infer_filetype() == exp[2], f"{info.filename} type"
                assert info.file_size == exp[3], f"{info.filename} size"

    def test_extract_creates_files(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", str(NETUTILS_ZIP_FILEPATH), "-d", str(tmp_path / "out")],
        )
        assert result.exit_code == 0
        out = tmp_path / "out"
        assert (out / "Free").is_file()
        assert (out / "SetStation").is_file()
        assert (out / "ReadMe").is_file()

    def test_extract_trad_inf(self, tmp_path):
        runner = CliRunner()
        out = tmp_path / "out"
        runner.invoke(
            cli,
            [
                "extract",
                str(NETUTILS_ZIP_FILEPATH),
                "-d",
                str(out),
                "--meta-format",
                "inf-trad",
            ],
        )
        inf = (out / "Free.inf").read_text()
        assert "FFFF0E10" in inf
        assert "FFFF0E10" in inf
        # Check format: filename load exec length [attr]
        parts = inf.strip().split()
        assert parts[0] == "Free"
        assert parts[1] == "FFFF0E10"
        assert parts[2] == "FFFF0E10"
        # Length should be file size in hex
        assert int(parts[3], 16) == 486

    def test_extract_pieb_inf(self, tmp_path):
        runner = CliRunner()
        out = tmp_path / "out"
        runner.invoke(
            cli,
            [
                "extract",
                str(NETUTILS_ZIP_FILEPATH),
                "-d",
                str(out),
                "--meta-format",
                "inf-pieb",
            ],
        )
        inf = (out / "Free.inf").read_text().strip()
        parts = inf.split()
        # PiEconetBridge format: owner load exec perm
        assert parts[0] == "0"  # default owner
        assert parts[1] == "ffff0e10"
        assert parts[2] == "ffff0e10"

    def test_extract_pieb_inf_custom_owner(self, tmp_path):
        runner = CliRunner()
        out = tmp_path / "out"
        runner.invoke(
            cli,
            [
                "extract",
                str(NETUTILS_ZIP_FILEPATH),
                "-d",
                str(out),
                "--meta-format",
                "inf-pieb",
                "--owner",
                "42",
            ],
        )
        inf = (out / "Free.inf").read_text().strip()
        assert inf.startswith("2a ")  # 42 = 0x2a

    def test_extract_no_inf(self, tmp_path):
        runner = CliRunner()
        out = tmp_path / "out"
        runner.invoke(
            cli,
            [
                "extract",
                str(NETUTILS_ZIP_FILEPATH),
                "-d",
                str(out),
                "--meta-format",
                "none",
            ],
        )
        assert (out / "Free").is_file()
        assert not (out / "Free.inf").exists()

    @requires_xattr
    def test_extract_xattr(self, tmp_path):
        runner = CliRunner()
        out = tmp_path / "out"
        result = runner.invoke(
            cli,
            [
                "extract",
                str(NETUTILS_ZIP_FILEPATH),
                "-d",
                str(out),
                "--meta-format",
                "xattr-pieb",
            ],
        )
        assert result.exit_code == 0
        assert get_xattr(out / "Free", "user.econet_load") == b"FFFF0E10"
        assert get_xattr(out / "Free", "user.econet_exec") == b"FFFF0E10"
        assert get_xattr(out / "Free", "user.econet_owner") == b"0000"

    def test_extract_verbose(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "extract",
                str(NETUTILS_ZIP_FILEPATH),
                "-d",
                str(tmp_path / "out"),
                "-v",
            ],
        )
        assert result.exit_code == 0
        assert "Free" in result.output
        assert "[sparkfs]" in result.output
        assert "type=" in result.output

    def test_extract_file_sizes_match(self, tmp_path):
        runner = CliRunner()
        out = tmp_path / "out"
        runner.invoke(cli, ["extract", str(NETUTILS_ZIP_FILEPATH), "-d", str(out)])
        with zipfile.ZipFile(NETUTILS_ZIP_FILEPATH) as zf:
            for info in zf.infolist():
                extracted = out / info.filename
                assert extracted.stat().st_size == info.file_size

    def test_list_command(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["list", str(NETUTILS_ZIP_FILEPATH)])
        assert result.exit_code == 0
        assert "Free" in result.output
        assert "FFFF0E10" in result.output
        assert "sparkfs" in result.output

    def test_info_command(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(NETUTILS_ZIP_FILEPATH)])
        assert result.exit_code == 0
        assert "Files:      12" in result.output
        assert "SparkFS:    12" in result.output
        assert "Filename:   0" in result.output
        assert "Plain:      0" in result.output


class TestNetUtilBZip:
    """Tests using the real NetUtilB.zip from MDFS."""

    def test_fixture_exists(self):
        assert NETUTILB_ZIP_FILEPATH.is_file()

    def test_all_entries_have_sparkfs(self):
        with zipfile.ZipFile(NETUTILB_ZIP_FILEPATH) as zf:
            for info in zf.infolist():
                meta = parse_sparkfs_extra(info.extra)
                assert meta is not None, f"{info.filename} missing SparkFS extra"

    def test_entry_count(self):
        with zipfile.ZipFile(NETUTILB_ZIP_FILEPATH) as zf:
            assert len(zf.infolist()) == 14

    def test_extract_and_list(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["list", str(NETUTILB_ZIP_FILEPATH)])
        assert result.exit_code == 0
        assert "sparkfs" in result.output


class TestSwehEconetSystemZip:
    """Tests using sweh_econet_system.zip (PiEconetBridge INFs, no SparkFS)."""

    def test_fixture_exists(self):
        assert SWEH_ZIP_FILEPATH.is_file()

    def test_no_sparkfs_fields(self):
        with zipfile.ZipFile(SWEH_ZIP_FILEPATH) as zf:
            for info in zf.infolist():
                meta = parse_sparkfs_extra(info.extra)
                assert meta is None

    def test_contains_bundled_inf_files(self):
        with zipfile.ZipFile(SWEH_ZIP_FILEPATH) as zf:
            inf_files = [i for i in zf.infolist() if i.filename.endswith(".inf")]
            assert len(inf_files) > 0

    def test_inf_files_are_pieb_format(self):
        """Bundled .inf files use PiEconetBridge format: owner load exec perm."""
        with zipfile.ZipFile(SWEH_ZIP_FILEPATH) as zf:
            for info in zf.infolist():
                if not info.filename.endswith(".inf"):
                    continue
                content = zf.read(info.filename).decode("ascii").strip()
                parts = content.split()
                # PiEconetBridge: owner load exec perm
                assert len(parts) >= 4, f"{info.filename}: {content!r}"
                # owner is short hex
                int(parts[0], 16)
                # load and exec are hex
                int(parts[1], 16)
                int(parts[2], 16)
                # perm is short hex
                int(parts[3], 16)

    def test_extract(self, tmp_path):
        runner = CliRunner()
        out = tmp_path / "out"
        result = runner.invoke(cli, ["extract", str(SWEH_ZIP_FILEPATH), "-d", str(out)])
        assert result.exit_code == 0
        assert (out / "Library").is_dir()

    def test_info_shows_no_sparkfs(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(SWEH_ZIP_FILEPATH)])
        assert result.exit_code == 0
        assert "SparkFS:    0" in result.output

    def test_entry_count(self):
        with zipfile.ZipFile(SWEH_ZIP_FILEPATH) as zf:
            assert len(zf.infolist()) == 140


class TestMasterZip:
    """Tests using MASTER.zip from mdfs.net (SparkFS, 344 files, 36 filetypes)."""

    def test_fixture_exists(self):
        assert MASTER_ZIP_FILEPATH.is_file()

    def test_all_entries_have_sparkfs(self):
        with zipfile.ZipFile(MASTER_ZIP_FILEPATH) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                meta = parse_sparkfs_extra(info.extra)
                assert meta is not None, f"{info.filename} missing SparkFS extra"

    def test_entry_count(self):
        with zipfile.ZipFile(MASTER_ZIP_FILEPATH) as zf:
            files = [i for i in zf.infolist() if not i.is_dir()]
            dirs = [i for i in zf.infolist() if i.is_dir()]
            assert len(files) == 344
            assert len(dirs) == 28

    def test_info_command(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(MASTER_ZIP_FILEPATH)])
        assert result.exit_code == 0
        assert "SparkFS:    344" in result.output
        assert "Plain:      0" in result.output

    def test_filetype_diversity(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(MASTER_ZIP_FILEPATH)])
        assert "Filetypes:  36 distinct" in result.output

    def test_extract(self, tmp_path):
        runner = CliRunner()
        out = tmp_path / "out"
        result = runner.invoke(
            cli, ["extract", str(MASTER_ZIP_FILEPATH), "-d", str(out)]
        )
        assert result.exit_code == 0
        # Spot-check some files exist
        extracted_files = list(out.rglob("*"))
        assert len([f for f in extracted_files if f.is_file()]) > 300


class TestTestdirUnixZip:
    """Tests using testdir-unix.zip from gerph/python-zipinfo-riscos.

    Contains 4 files with Unix filename encoding (,xxx suffixes), no SparkFS.
    """

    def test_fixture_exists(self):
        assert TESTDIR_UNIX_ZIP_FILEPATH.is_file()

    def test_no_sparkfs_on_files(self):
        with zipfile.ZipFile(TESTDIR_UNIX_ZIP_FILEPATH) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                meta = parse_sparkfs_extra(info.extra)
                assert meta is None, f"{info.filename} has unexpected SparkFS extra"

    def test_all_files_have_filename_encoding(self):
        with zipfile.ZipFile(TESTDIR_UNIX_ZIP_FILEPATH) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                _, filename_meta = parse_encoded_filename(info.filename.split("/")[-1])
                assert filename_meta is not None, f"{info.filename} has no encoding"

    def test_entry_count(self):
        with zipfile.ZipFile(TESTDIR_UNIX_ZIP_FILEPATH) as zf:
            files = [i for i in zf.infolist() if not i.is_dir()]
            assert len(files) == 4

    def test_info_command(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(TESTDIR_UNIX_ZIP_FILEPATH)])
        assert result.exit_code == 0
        assert "SparkFS:    0" in result.output
        assert "Filename:   4" in result.output

    def test_list_shows_filename_source(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["list", str(TESTDIR_UNIX_ZIP_FILEPATH)])
        assert result.exit_code == 0
        assert "filename" in result.output

    def test_filetypes(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(TESTDIR_UNIX_ZIP_FILEPATH)])
        assert "Filetypes:  4 distinct" in result.output
        assert "FFB:" in result.output
        assert "FFF:" in result.output
        assert "FFD:" in result.output
        assert "FF8:" in result.output

    def test_extract_strips_suffixes(self, tmp_path):
        runner = CliRunner()
        out = tmp_path / "out"
        result = runner.invoke(
            cli, ["extract", str(TESTDIR_UNIX_ZIP_FILEPATH), "-d", str(out)]
        )
        assert result.exit_code == 0
        testdir = out / "testdir"
        # Filenames should have ,xxx suffixes stripped
        assert (testdir / "text").is_file()
        assert (testdir / "swic").is_file()
        assert not (testdir / "text,fff").exists()
        assert not (testdir / "swic,ffb").exists()
        # INF files should be created
        assert (testdir / "text.inf").is_file()
        assert (testdir / "swic.inf").is_file()

    def test_extract_no_decode_preserves_suffixes(self, tmp_path):
        runner = CliRunner()
        out = tmp_path / "out"
        result = runner.invoke(
            cli,
            [
                "extract", "--no-decode-filenames",
                str(TESTDIR_UNIX_ZIP_FILEPATH), "-d", str(out),
            ],
        )
        assert result.exit_code == 0
        testdir = out / "testdir"
        assert (testdir / "text,fff").is_file()
        assert (testdir / "swic,ffb").is_file()


class TestTestdirRoZip:
    """Tests using testdir-ro.zip from gerph/python-zipinfo-riscos.

    Same content as testdir-unix.zip but with SparkFS extra fields instead
    of filename encoding. Useful for cross-checking metadata equivalence.
    """

    def test_fixture_exists(self):
        assert TESTDIR_RO_ZIP_FILEPATH.is_file()

    def test_all_entries_have_sparkfs(self):
        with zipfile.ZipFile(TESTDIR_RO_ZIP_FILEPATH) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                meta = parse_sparkfs_extra(info.extra)
                assert meta is not None, f"{info.filename} missing SparkFS extra"

    def test_entry_count(self):
        with zipfile.ZipFile(TESTDIR_RO_ZIP_FILEPATH) as zf:
            files = [i for i in zf.infolist() if not i.is_dir()]
            assert len(files) == 4

    def test_same_filetypes_as_unix_variant(self):
        """Both testdir-ro.zip and testdir-unix.zip should yield the same filetypes."""
        runner = CliRunner()
        ro_result = runner.invoke(cli, ["info", str(TESTDIR_RO_ZIP_FILEPATH)])
        unix_result = runner.invoke(cli, ["info", str(TESTDIR_UNIX_ZIP_FILEPATH)])
        # Both should have the same 4 filetypes
        for ft in ["FF8:", "FFB:", "FFD:", "FFF:"]:
            assert ft in ro_result.output
            assert ft in unix_result.output


# =========================================================================
# Extraction with synthetic ZIPs
# =========================================================================


class TestExtractMember:
    def test_directory_creation(self, tmp_path):
        zip_filepath = make_zip_file(tmp_path, [("subdir/", b"", None)])
        with zipfile.ZipFile(zip_filepath) as zf:
            info = zf.infolist()[0]
            extract_member(zf, info, tmp_path / "out")
        assert (tmp_path / "out" / "subdir").is_dir()

    def test_file_extraction(self, tmp_path):
        data = b"Hello, Acorn!"
        zip_filepath = make_zip_file(tmp_path, [("greeting", data, None)])
        with zipfile.ZipFile(zip_filepath) as zf:
            info = zf.infolist()[0]
            extract_member(zf, info, tmp_path / "out", meta_format=None)
        assert (tmp_path / "out" / "greeting").read_bytes() == data

    def test_sparkfs_trad_inf(self, tmp_path):
        extra = build_sparkfs_extra(0xFFFF0E10, 0x0000801F, 0x03)
        data = b"\x00" * 64
        zip_filepath = make_zip_file(tmp_path, [("PROG", data, extra)])
        with zipfile.ZipFile(zip_filepath) as zf:
            info = zf.infolist()[0]
            extract_member(
                zf, info, tmp_path / "out", meta_format=MetaFormat.INF_TRAD
            )
        inf = (tmp_path / "out" / "PROG.inf").read_text().strip()
        parts = inf.split()
        assert parts[0] == "PROG"
        assert parts[1] == "FFFF0E10"
        assert parts[2] == "0000801F"
        assert parts[3] == "00000040"  # 64 bytes
        assert parts[4] == "03"

    def test_sparkfs_pieb_inf(self, tmp_path):
        extra = build_sparkfs_extra(0xFFFF0E10, 0x0000801F, 0x03)
        data = b"\x00" * 64
        zip_filepath = make_zip_file(tmp_path, [("PROG", data, extra)])
        with zipfile.ZipFile(zip_filepath) as zf:
            info = zf.infolist()[0]
            extract_member(
                zf,
                info,
                tmp_path / "out",
                meta_format=MetaFormat.INF_PIEB,
                owner=7,
            )
        inf = (tmp_path / "out" / "PROG.inf").read_text().strip()
        parts = inf.split()
        assert parts[0] == "7"
        assert parts[1] == "ffff0e10"
        assert parts[2] == "801f"
        assert parts[3] == "3"

    @requires_xattr
    def test_sparkfs_xattr(self, tmp_path):
        extra = build_sparkfs_extra(0xFFFF0E10, 0x0000801F, 0x03)
        data = b"\x00" * 64
        zip_filepath = make_zip_file(tmp_path, [("PROG", data, extra)])
        with zipfile.ZipFile(zip_filepath) as zf:
            info = zf.infolist()[0]
            extract_member(
                zf,
                info,
                tmp_path / "out",
                meta_format=MetaFormat.XATTR_PIEB,
                owner=5,
            )
        prog_filepath = tmp_path / "out" / "PROG"
        assert get_xattr(prog_filepath, "user.econet_load") == b"FFFF0E10"
        assert get_xattr(prog_filepath, "user.econet_exec") == b"0000801F"
        assert get_xattr(prog_filepath, "user.econet_perm") == b"03"
        assert get_xattr(prog_filepath, "user.econet_owner") == b"0005"

    def test_encoded_filename_cleaned(self, tmp_path):
        data = b"\x01" * 32
        zip_filepath = make_zip_file(tmp_path, [("FILE,ffb", data, None)])
        with zipfile.ZipFile(zip_filepath) as zf:
            info = zf.infolist()[0]
            extract_member(zf, info, tmp_path / "out")
        assert (tmp_path / "out" / "FILE").is_file()
        assert not (tmp_path / "out" / "FILE,ffb").exists()

    def test_decode_disabled_preserves_name(self, tmp_path):
        data = b"\x01" * 32
        zip_filepath = make_zip_file(tmp_path, [("FILE,ffb", data, None)])
        with zipfile.ZipFile(zip_filepath) as zf:
            info = zf.infolist()[0]
            extract_member(
                zf, info, tmp_path / "out", decode_filenames=False, meta_format=None
            )
        assert (tmp_path / "out" / "FILE,ffb").is_file()
        assert not (tmp_path / "out" / "FILE").exists()

    def test_no_inf_for_plain_file(self, tmp_path):
        data = b"plain text"
        zip_filepath = make_zip_file(tmp_path, [("README", data, None)])
        with zipfile.ZipFile(zip_filepath) as zf:
            info = zf.infolist()[0]
            extract_member(zf, info, tmp_path / "out")
        assert (tmp_path / "out" / "README").is_file()
        assert not (tmp_path / "out" / "README.inf").exists()

    def test_nested_directory_created(self, tmp_path):
        extra = build_sparkfs_extra(0xFFFF0E10, 0xFFFF0E10, 0x03)
        data = b"\x00" * 8
        zip_filepath = make_zip_file(
            tmp_path, [("Library/Subdir/FILE", data, extra)]
        )
        with zipfile.ZipFile(zip_filepath) as zf:
            info = zf.infolist()[0]
            extract_member(zf, info, tmp_path / "out")
        assert (tmp_path / "out" / "Library" / "Subdir" / "FILE").is_file()

    def test_encoded_load_exec_inf(self, tmp_path):
        data = b"\x00" * 16
        zip_filepath = make_zip_file(
            tmp_path, [("PROG,ffff0e10,0000801f", data, None)]
        )
        with zipfile.ZipFile(zip_filepath) as zf:
            info = zf.infolist()[0]
            extract_member(zf, info, tmp_path / "out")
        assert (tmp_path / "out" / "PROG").is_file()
        inf = (tmp_path / "out" / "PROG.inf").read_text().strip()
        assert "FFFF0E10" in inf
        assert "0000801F" in inf


# =========================================================================
# xattr writing
# =========================================================================


@requires_xattr
class TestWriteEconetXattrs:
    def test_sets_all_four_attrs(self, tmp_path):
        filepath = tmp_path / "testfile"
        filepath.write_bytes(b"data")
        write_econet_xattrs(filepath, 0xFFFF0E10, 0x0000801F, 0x03, owner=0)
        assert get_xattr(filepath, "user.econet_load") == b"FFFF0E10"
        assert get_xattr(filepath, "user.econet_exec") == b"0000801F"
        assert get_xattr(filepath, "user.econet_perm") == b"03"
        assert get_xattr(filepath, "user.econet_owner") == b"0000"

    def test_owner_formatting(self, tmp_path):
        filepath = tmp_path / "testfile"
        filepath.write_bytes(b"data")
        write_econet_xattrs(filepath, 0, 0, 0, owner=255)
        assert get_xattr(filepath, "user.econet_owner") == b"00FF"

    def test_default_perm_when_attr_none(self, tmp_path):
        filepath = tmp_path / "testfile"
        filepath.write_bytes(b"data")
        write_econet_xattrs(filepath, 0, 0, attr=None)
        assert get_xattr(filepath, "user.econet_perm") == b"17"

    def test_zero_values(self, tmp_path):
        filepath = tmp_path / "testfile"
        filepath.write_bytes(b"data")
        write_econet_xattrs(filepath, 0, 0, 0, owner=0)
        assert get_xattr(filepath, "user.econet_load") == b"00000000"
        assert get_xattr(filepath, "user.econet_exec") == b"00000000"
        assert get_xattr(filepath, "user.econet_perm") == b"00"
        assert get_xattr(filepath, "user.econet_owner") == b"0000"

    def test_max_values(self, tmp_path):
        filepath = tmp_path / "testfile"
        filepath.write_bytes(b"data")
        write_econet_xattrs(filepath, 0xFFFFFFFF, 0xFFFFFFFF, 0xFF, owner=0xFFFF)
        assert get_xattr(filepath, "user.econet_load") == b"FFFFFFFF"
        assert get_xattr(filepath, "user.econet_exec") == b"FFFFFFFF"
        assert get_xattr(filepath, "user.econet_perm") == b"FF"
        assert get_xattr(filepath, "user.econet_owner") == b"FFFF"


# =========================================================================
# CLI commands
# =========================================================================


class TestCliExtract:
    def test_default_output_dir(self, tmp_path):
        zip_filepath = make_zip_file(
            tmp_path, [("FILE", b"data", None)], name="myarchive.zip"
        )
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["extract", str(zip_filepath)])
            assert result.exit_code == 0
            assert Path("myarchive/FILE").is_file()

    def test_custom_output_dir(self, tmp_path):
        zip_filepath = make_zip_file(tmp_path, [("FILE", b"data", None)])
        out = tmp_path / "custom"
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", str(zip_filepath), "-d", str(out)])
        assert result.exit_code == 0
        assert (out / "FILE").is_file()

    def test_invalid_zip(self, tmp_path):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"not a zip file")
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", str(bad)])
        assert result.exit_code != 0
        assert "not a valid ZIP file" in result.output

    def test_nonexistent_file(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "/nonexistent/file.zip"])
        assert result.exit_code != 0

    def test_verbose_flag(self, tmp_path):
        extra = build_sparkfs_extra(0xFFFF0E10, 0xFFFF0E10, 0x03)
        zip_filepath = make_zip_file(tmp_path, [("PROG", b"\x00" * 8, extra)])
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", str(zip_filepath), "-d", str(tmp_path / "out"), "-v"],
        )
        assert result.exit_code == 0
        assert "PROG" in result.output
        assert "[sparkfs]" in result.output

    def test_xattr_rejected_on_windows(self, tmp_path):
        zip_filepath = make_zip_file(tmp_path, [("FILE", b"data", None)])
        runner = CliRunner()
        with patch("oaknut_zip.api.sys") as mock_sys:
            mock_sys.platform = "win32"
            result = runner.invoke(
                cli,
                ["extract", "--meta-format", "xattr-pieb", str(zip_filepath), "-d", str(tmp_path / "out")],
            )
        assert result.exit_code != 0
        assert "not supported on Windows" in result.output


class TestCliList:
    def test_list_sparkfs(self, tmp_path):
        extra = build_sparkfs_extra(0xFFFF0E10, 0xFFFF0E10, 0x03)
        zip_filepath = make_zip_file(
            tmp_path, [("PROG", b"\x00" * 8, extra), ("README", b"text", None)]
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["list", str(zip_filepath)])
        assert result.exit_code == 0
        assert "PROG" in result.output
        assert "FFFF0E10" in result.output
        assert "sparkfs" in result.output
        assert "README" in result.output

    def test_list_filename_source(self, tmp_path):
        zip_filepath = make_zip_file(
            tmp_path, [("FILE,ffb", b"\x00" * 8, None)]
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["list", str(zip_filepath)])
        assert result.exit_code == 0
        assert "FILE" in result.output
        assert "filename" in result.output

    def test_list_directory(self, tmp_path):
        zip_filepath = make_zip_file(tmp_path, [("subdir/", b"", None)])
        runner = CliRunner()
        result = runner.invoke(cli, ["list", str(zip_filepath)])
        assert result.exit_code == 0
        assert "subdir" in result.output

    def test_list_invalid_zip(self, tmp_path):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"nope")
        runner = CliRunner()
        result = runner.invoke(cli, ["list", str(bad)])
        assert result.exit_code != 0


class TestCliInfo:
    def test_info_mixed(self, tmp_path):
        extra = build_sparkfs_extra(0xFFFF0E10, 0xFFFF0E10, 0x03)
        zip_filepath = make_zip_file(
            tmp_path,
            [
                ("PROG", b"\x00" * 8, extra),
                ("FILE,ffb", b"\x01" * 4, None),
                ("plain", b"text", None),
                ("dir/", b"", None),
            ],
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(zip_filepath)])
        assert result.exit_code == 0
        assert "Files:      3" in result.output
        assert "Dirs:       1" in result.output
        assert "SparkFS:    1" in result.output
        assert "Filename:   1" in result.output
        assert "Plain:      1" in result.output

    def test_info_filetypes(self, tmp_path):
        entries = []
        for ft, name in [(0xF0E, "CMD"), (0xF0E, "CMD2"), (0xFFB, "BASIC")]:
            load = 0xFFF00000 | (ft << 8)
            extra = build_sparkfs_extra(load, load, 0x03)
            entries.append((name, b"\x00" * 4, extra))
        zip_filepath = make_zip_file(tmp_path, entries)
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(zip_filepath)])
        assert "Filetypes:  2 distinct" in result.output
        assert "F0E: 2 files" in result.output
        assert "FFB: 1 files" in result.output


class TestCliVersion:
    def test_version(self):
        from oaknut_zip import __version__

        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output


# =========================================================================
# Bundled INF CLI tests
# =========================================================================


def _make_zip_with_inf(tmp_path, entries, name="test.zip"):
    """Create a ZIP with data files and optional companion .inf files.

    entries is a list of (filename, data, inf_content_or_None) tuples.
    """
    zip_filepath = tmp_path / name
    with zipfile.ZipFile(zip_filepath, "w") as zf:
        for filename, data, inf_content in entries:
            zf.writestr(filename, data)
            if inf_content is not None:
                zf.writestr(filename + ".inf", inf_content)
    return zip_filepath


class TestCliBundledInf:
    def test_extract_pieb_inf_creates_trad_inf(self, tmp_path):
        """Bundled PiEB .inf is consumed and rewritten as traditional INF."""
        zip_filepath = _make_zip_with_inf(
            tmp_path, [("FILE", b"\x00" * 8, "0 ffffdd00 ffffdd00 3")]
        )
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", str(zip_filepath), "-d", str(out)])
        assert result.exit_code == 0
        assert (out / "FILE").is_file()
        assert (out / "FILE.inf").is_file()
        inf = (out / "FILE.inf").read_text().strip()
        assert "FFFFDD00" in inf
        # The bundled PiEB .inf should NOT be extracted as a separate file
        # (it would conflict with the rewritten traditional .inf)

    @requires_xattr
    def test_extract_pieb_inf_as_xattr(self, tmp_path):
        """Bundled PiEB .inf is consumed and written as xattrs."""
        zip_filepath = _make_zip_with_inf(
            tmp_path, [("FILE", b"\x00" * 8, "0 ffffdd00 ffffdd00 3")]
        )
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", "--meta-format", "xattr-pieb", str(zip_filepath), "-d", str(out)],
        )
        assert result.exit_code == 0
        assert (out / "FILE").is_file()
        assert get_xattr(out / "FILE", "user.econet_load") == b"FFFFDD00"
        assert get_xattr(out / "FILE", "user.econet_exec") == b"FFFFDD00"
        # No .inf file should exist
        assert not (out / "FILE.inf").exists()

    def test_extract_none_preserves_inf(self, tmp_path):
        """With --meta-format none, bundled .inf files are extracted as-is."""
        zip_filepath = _make_zip_with_inf(
            tmp_path, [("FILE", b"\x00" * 8, "0 ffffdd00 ffffdd00 3")]
        )
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", "--meta-format", "none", str(zip_filepath), "-d", str(out)],
        )
        assert result.exit_code == 0
        assert (out / "FILE").is_file()
        assert (out / "FILE.inf").is_file()
        inf = (out / "FILE.inf").read_text().strip()
        assert inf == "0 ffffdd00 ffffdd00 3"

    def test_list_shows_pieb_inf_source(self, tmp_path):
        zip_filepath = _make_zip_with_inf(
            tmp_path, [("FILE", b"\x00" * 8, "0 ffffdd00 ffffdd00 3")]
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["list", str(zip_filepath)])
        assert result.exit_code == 0
        assert "FILE" in result.output
        assert "inf-pieb" in result.output
        # The .inf file itself should not appear in the listing
        assert "FILE.inf" not in result.output

    def test_list_shows_trad_inf_source(self, tmp_path):
        zip_filepath = _make_zip_with_inf(
            tmp_path,
            [("PROG", b"\x00" * 16, "PROG        FFFF0E10 FFFF0E10 00000010 03")],
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["list", str(zip_filepath)])
        assert result.exit_code == 0
        assert "PROG" in result.output
        assert "inf-trad" in result.output

    def test_info_counts_pieb_inf(self, tmp_path):
        zip_filepath = _make_zip_with_inf(
            tmp_path,
            [
                ("FILE1", b"\x00" * 8, "0 ffffdd00 ffffdd00 3"),
                ("FILE2", b"\x00" * 4, "0 fffff93a c7524201 33"),
                ("PLAIN", b"text", None),
            ],
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(zip_filepath)])
        assert result.exit_code == 0
        assert "Files:      3" in result.output
        assert "inf-pieb:   2" in result.output
        assert "Plain:      1" in result.output

    def test_info_counts_trad_inf(self, tmp_path):
        zip_filepath = _make_zip_with_inf(
            tmp_path,
            [("PROG", b"\x00" * 16, "PROG        FFFF0E10 FFFF0E10 00000010 03")],
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(zip_filepath)])
        assert result.exit_code == 0
        assert "inf-trad:   1" in result.output


class TestSwehBundledInf:
    """Tests that sweh_econet_system.zip PiEB INF files are consumed as metadata."""

    def test_info_shows_pieb_inf(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["info", str(SWEH_ZIP_FILEPATH)])
        assert result.exit_code == 0
        assert "inf-pieb:" in result.output
        # Should have PiEB-inf entries, not all plain
        pieb_line = [l for l in result.output.splitlines() if "inf-pieb:" in l][0]
        count = int(pieb_line.split(":")[1].strip().split()[0])
        assert count > 0

    def test_list_shows_pieb_inf_source(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["list", str(SWEH_ZIP_FILEPATH)])
        assert result.exit_code == 0
        assert "inf-pieb" in result.output

    @requires_xattr
    def test_extract_xattr_no_inf_files(self, tmp_path):
        """Extracting with xattr format should consume .inf files."""
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", "--meta-format", "xattr-pieb", str(SWEH_ZIP_FILEPATH), "-d", str(out)],
        )
        assert result.exit_code == 0
        # Check that at least one file has xattrs
        library_dirpath = out / "Library"
        if library_dirpath.is_dir():
            for filepath in library_dirpath.iterdir():
                if filepath.is_file() and not filepath.name.endswith(".inf"):
                    attrs = list_xattrs(filepath)
                    if attrs:
                        assert "user.econet_load" in attrs
                        break


# =========================================================================
# Filename encoding output format
# =========================================================================


class TestBuildFilenameSuffix:
    def test_filetype_stamped(self):
        meta = AcornMeta(load_addr=0xFFFFDD00, exec_addr=0xFFFFDD00, filetype=0xFDD)
        assert build_filename_suffix(meta) == ",fdd"

    def test_literal_addresses(self):
        meta = AcornMeta(load_addr=0x00001900, exec_addr=0x0000801F)
        assert build_filename_suffix(meta) == ",00001900,0000801f"

    def test_filetype_ffb(self):
        meta = AcornMeta(load_addr=0xFFFFB00, exec_addr=0, filetype=0xFFB)
        meta.load_addr = 0xFFFFFB00
        assert build_filename_suffix(meta) == ",ffb"


class TestCliFilenameFormat:
    def test_extract_sparkfs_as_filename(self, tmp_path):
        """SparkFS metadata is written as filename suffix."""
        extra = build_sparkfs_extra(0xFFFFDD00, 0xFFFFDD00, 0x03)
        zip_filepath = make_zip_file(tmp_path, [("FILE", b"\x00" * 8, extra)])
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", "--meta-format", "filename-riscos", str(zip_filepath), "-d", str(out)],
        )
        assert result.exit_code == 0
        assert (out / "FILE,fdd").is_file()
        assert not (out / "FILE").exists()
        assert not (out / "FILE.inf").exists()

    def test_extract_literal_load_exec(self, tmp_path):
        """Non-filetype-stamped files get ,llllllll,eeeeeeee suffix."""
        extra = build_sparkfs_extra(0x00001900, 0x0000801F, 0x03)
        zip_filepath = make_zip_file(tmp_path, [("PROG", b"\x00" * 8, extra)])
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", "--meta-format", "filename-riscos", str(zip_filepath), "-d", str(out)],
        )
        assert result.exit_code == 0
        assert (out / "PROG,00001900,0000801f").is_file()
        assert not (out / "PROG").exists()

    def test_no_double_encoding(self, tmp_path):
        """A file already named FILE,ffb should not become FILE,ffb,ffb."""
        extra = build_sparkfs_extra(0xFFFFFB00, 0xFFFFFB00, 0x03)
        zip_filepath = make_zip_file(
            tmp_path, [("FILE,ffb", b"\x00" * 8, extra)]
        )
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "extract", "--meta-format", "filename-riscos",
                "--no-decode-filenames",
                str(zip_filepath), "-d", str(out),
            ],
        )
        assert result.exit_code == 0
        assert (out / "FILE,ffb").is_file()
        assert not (out / "FILE,ffb,ffb").exists()

    def test_pieb_inf_to_filename(self, tmp_path):
        """Bundled PiEB INF metadata can be converted to filename encoding."""
        zip_filepath = _make_zip_with_inf(
            tmp_path, [("FILE", b"\x00" * 8, "0 ffffdd00 ffffdd00 3")]
        )
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", "--meta-format", "filename-riscos", str(zip_filepath), "-d", str(out)],
        )
        assert result.exit_code == 0
        assert (out / "FILE,fdd").is_file()
        assert not (out / "FILE.inf").exists()

    def test_plain_file_unchanged(self, tmp_path):
        """Files without metadata are not renamed."""
        zip_filepath = make_zip_file(tmp_path, [("README", b"text", None)])
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", "--meta-format", "filename-riscos", str(zip_filepath), "-d", str(out)],
        )
        assert result.exit_code == 0
        assert (out / "README").is_file()


# =========================================================================
# MOS filename encoding
# =========================================================================


class TestBuildMosFilenameSuffix:
    def test_short_addresses(self):
        meta = AcornMeta(load_addr=0x1900, exec_addr=0x801F)
        assert build_mos_filename_suffix(meta) == ",1900-801f"

    def test_full_width_addresses(self):
        meta = AcornMeta(load_addr=0xFFFF0E10, exec_addr=0xFFFF0E10)
        assert build_mos_filename_suffix(meta) == ",ffff0e10-ffff0e10"

    def test_zero_addresses(self):
        meta = AcornMeta(load_addr=0, exec_addr=0)
        assert build_mos_filename_suffix(meta) == ",0-0"

    def test_filetype_stamped(self):
        meta = AcornMeta(load_addr=0xFFFFDD00, exec_addr=0xFFFFDD00)
        assert build_mos_filename_suffix(meta) == ",ffffdd00-ffffdd00"


class TestCliMosFilenameFormat:
    def test_extract_sparkfs_as_mos_filename(self, tmp_path):
        """SparkFS metadata is written as MOS filename suffix."""
        extra = build_sparkfs_extra(0x00001900, 0x0000801F, 0x03)
        zip_filepath = make_zip_file(tmp_path, [("PROG", b"\x00" * 8, extra)])
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", "--meta-format", "filename-mos", str(zip_filepath), "-d", str(out)],
        )
        assert result.exit_code == 0
        assert (out / "PROG,1900-801f").is_file()
        assert not (out / "PROG").exists()
        assert not (out / "PROG.inf").exists()

    def test_extract_filetype_stamped(self, tmp_path):
        """Filetype-stamped files still get full load-exec in MOS format."""
        extra = build_sparkfs_extra(0xFFFFDD00, 0xFFFFDD00, 0x03)
        zip_filepath = make_zip_file(tmp_path, [("FILE", b"\x00" * 8, extra)])
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", "--meta-format", "filename-mos", str(zip_filepath), "-d", str(out)],
        )
        assert result.exit_code == 0
        assert (out / "FILE,ffffdd00-ffffdd00").is_file()

    def test_no_double_encoding_mos(self, tmp_path):
        """A file already carrying the correct MOS suffix is not renamed."""
        extra = build_sparkfs_extra(0x1900, 0x801F, 0x03)
        zip_filepath = make_zip_file(
            tmp_path, [("PROG,1900-801f", b"\x00" * 8, extra)]
        )
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "extract", "--meta-format", "filename-mos",
                "--no-decode-filenames",
                str(zip_filepath), "-d", str(out),
            ],
        )
        assert result.exit_code == 0
        assert (out / "PROG,1900-801f").is_file()

    def test_plain_file_unchanged(self, tmp_path):
        """Files without metadata are not renamed."""
        zip_filepath = make_zip_file(tmp_path, [("README", b"text", None)])
        out = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract", "--meta-format", "filename-mos", str(zip_filepath), "-d", str(out)],
        )
        assert result.exit_code == 0
        assert (out / "README").is_file()


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    def test_empty_zip(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        zip_filepath = tmp_path / "empty.zip"
        zip_filepath.write_bytes(buf.getvalue())
        runner = CliRunner()
        result = runner.invoke(
            cli, ["extract", str(zip_filepath), "-d", str(tmp_path / "out")]
        )
        assert result.exit_code == 0

    def test_empty_file_with_sparkfs(self, tmp_path):
        extra = build_sparkfs_extra(0xFFFF0E10, 0xFFFF0E10, 0x03)
        zip_filepath = make_zip_file(tmp_path, [("EMPTY", b"", extra)])
        runner = CliRunner()
        out = tmp_path / "out"
        result = runner.invoke(cli, ["extract", str(zip_filepath), "-d", str(out)])
        assert result.exit_code == 0
        assert (out / "EMPTY").stat().st_size == 0
        inf = (out / "EMPTY.inf").read_text().strip()
        assert "00000000" in inf  # zero length

    def test_multiple_files_same_dir(self, tmp_path):
        extra1 = build_sparkfs_extra(0xFFFF0E10, 0xFFFF0E10, 0x03)
        extra2 = build_sparkfs_extra(0xFFFF0900, 0xFFFF0900, 0x17)
        zip_filepath = make_zip_file(
            tmp_path,
            [
                ("dir/A", b"\x00" * 8, extra1),
                ("dir/B", b"\x01" * 16, extra2),
            ],
        )
        runner = CliRunner()
        out = tmp_path / "out"
        runner.invoke(cli, ["extract", str(zip_filepath), "-d", str(out)])
        assert (out / "dir" / "A").is_file()
        assert (out / "dir" / "B").is_file()
        assert (out / "dir" / "A.inf").is_file()
        assert (out / "dir" / "B.inf").is_file()

    def test_inf_extension_appended_not_replaced(self, tmp_path):
        extra = build_sparkfs_extra(0xFFFF0E10, 0xFFFF0E10, 0x03)
        zip_filepath = make_zip_file(tmp_path, [("file.dat", b"\x00" * 4, extra)])
        runner = CliRunner()
        out = tmp_path / "out"
        runner.invoke(cli, ["extract", str(zip_filepath), "-d", str(out)])
        # Should be file.dat.inf not file.inf
        assert (out / "file.dat.inf").is_file()
        assert not (out / "file.inf").exists()

    def test_three_digit_filetype_zero(self):
        clean, meta = parse_encoded_filename("FILE,000")
        assert clean == "FILE"
        assert meta.filetype == 0

    def test_load_exec_all_zeros(self):
        clean, meta = parse_encoded_filename("FILE,00000000,00000000")
        assert clean == "FILE"
        assert meta.load_addr == 0
        assert meta.exec_addr == 0

    def test_load_exec_all_f(self):
        clean, meta = parse_encoded_filename("FILE,ffffffff,ffffffff")
        assert clean == "FILE"
        assert meta.load_addr == 0xFFFFFFFF
        assert meta.exec_addr == 0xFFFFFFFF
