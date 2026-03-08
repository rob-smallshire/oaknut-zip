#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
nutzip - Extract ZIP files containing Acorn computer metadata.

Handles Acorn/RISC OS-specific metadata stored in ZIP archives, preserving
load addresses, execution addresses, and file attributes that standard
unzip tools discard. Outputs .inf sidecar files alongside extracted data.

Supports two metadata sources:
  - SparkFS extra fields (header ID 0x4341, "ARC0" signature)
  - NFS filename encoding (,xxx filetype or ,llllllll,eeeeeeee load/exec)

References:
  - INF format: https://beebwiki.mdfs.net/INF_file_format
  - Extra field spec: https://libzip.org/specifications/extrafld.txt
  - RISC OS ZIP handling: https://github.com/gerph/python-zipinfo-riscos
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path


# SparkFS extra field constants
SPARKFS_HEADER_ID = 0x4341  # "AC" in little-endian
SPARKFS_SIGNATURE = b"ARC0"
SPARKFS_DATA_LENGTH = 20  # 4 sig + 4 load + 4 exec + 4 attr + 4 reserved

# NFS filename encoding patterns
# ,xxx = 3-hex-digit filetype
# ,llllllll,eeeeeeee = 8-hex-digit load and exec addresses
NFS_FILETYPE_RE = re.compile(r"^(.*),([0-9a-fA-F]{3})$")
NFS_LOADEXEC_RE = re.compile(r"^(.*),([0-9a-fA-F]{8}),([0-9a-fA-F]{8})$")

# BBC Micro to host filename character mapping (for DFS-style names)
# BBC char -> host char
BBC_TO_HOST = {
    "#": "?",
    ".": "/",
    "$": "<",
    "^": ">",
    "&": "+",
    "@": "=",
    "%": ";",
}
HOST_TO_BBC = {v: k for k, v in BBC_TO_HOST.items()}

# Acorn attribute bits
ATTR_OWNER_WRITE = 0x01
ATTR_OWNER_READ = 0x02
ATTR_LOCKED = 0x08
ATTR_PUBLIC_WRITE = 0x10
ATTR_PUBLIC_READ = 0x20


@dataclass
class AcornMeta:
    """Acorn file metadata extracted from a ZIP entry."""

    load_addr: int | None = None
    exec_addr: int | None = None
    attr: int | None = None
    filetype: int | None = None

    @property
    def has_metadata(self) -> bool:
        return self.load_addr is not None

    @property
    def is_filetype_stamped(self) -> bool:
        """Check if load address encodes a RISC OS filetype."""
        if self.load_addr is None:
            return False
        return (self.load_addr & 0xFFF00000) == 0xFFF00000

    def infer_filetype(self) -> int | None:
        """Extract filetype from load address if present."""
        if self.is_filetype_stamped:
            return (self.load_addr >> 8) & 0xFFF
        return self.filetype


def parse_sparkfs_extra(extra: bytes) -> AcornMeta | None:
    """Parse SparkFS/ARC0 extra field data from a ZIP entry.

    The extra field format (after the standard 4-byte ZIP extra header):
        Offset  Size  Description
        0       4     Signature "ARC0"
        4       4     Load address (little-endian uint32)
        8       4     Exec address (little-endian uint32)
        12      4     Attributes (little-endian uint32)
        16      4     Reserved (zero)
    """
    offset = 0
    while offset + 4 <= len(extra):
        header_id, data_size = struct.unpack_from("<HH", extra, offset)
        offset += 4

        if offset + data_size > len(extra):
            break

        if header_id == SPARKFS_HEADER_ID and data_size >= SPARKFS_DATA_LENGTH:
            chunk = extra[offset : offset + SPARKFS_DATA_LENGTH]
            sig = chunk[0:4]
            if sig == SPARKFS_SIGNATURE:
                load_addr, exec_addr, attr, _reserved = struct.unpack_from(
                    "<IIII", chunk, 4
                )
                meta = AcornMeta(
                    load_addr=load_addr,
                    exec_addr=exec_addr,
                    attr=attr,
                )
                meta.filetype = meta.infer_filetype()
                return meta

        offset += data_size

    return None


def parse_nfs_filename(filename: str) -> tuple[str, AcornMeta | None]:
    """Parse NFS-encoded metadata from a filename.

    Two forms:
        file,xxx          -> filetype xxx (3 hex digits)
        file,llllllll,eeeeeeee -> load/exec addresses (8 hex digits each)

    Returns the clean filename and any extracted metadata.
    """
    # Try load/exec form first (more specific)
    m = NFS_LOADEXEC_RE.match(filename)
    if m:
        clean = m.group(1)
        load_addr = int(m.group(2), 16)
        exec_addr = int(m.group(3), 16)
        meta = AcornMeta(load_addr=load_addr, exec_addr=exec_addr)
        meta.filetype = meta.infer_filetype()
        return clean, meta

    # Try filetype form
    m = NFS_FILETYPE_RE.match(filename)
    if m:
        clean = m.group(1)
        filetype = int(m.group(2), 16)
        # Encode filetype into a synthetic load address
        load_addr = 0xFFF00000 | (filetype << 8)
        meta = AcornMeta(load_addr=load_addr, exec_addr=0, filetype=filetype)
        return clean, meta

    return filename, None


def format_access(attr: int | None) -> str:
    """Format Acorn attributes as a hex string or DFS-style letter code."""
    if attr is None:
        return ""
    # Use simple hex representation
    return f"{attr:02X}"


def format_inf_line(
    filename: str,
    load_addr: int,
    exec_addr: int,
    length: int,
    attr: int | None = None,
) -> str:
    """Format a single INF file line.

    Standard format: filename load exec length [access]
    Filename left-padded to 11 chars, all values in uppercase hex.
    """
    name_field = filename.ljust(11)
    parts = [
        name_field,
        f"{load_addr:08X}",
        f"{exec_addr:08X}",
        f"{length:08X}",
    ]
    if attr is not None:
        parts.append(format_access(attr))
    return " ".join(parts)


def host_to_bbc_filename(name: str) -> str:
    """Convert host filesystem characters back to BBC equivalents."""
    return "".join(HOST_TO_BBC.get(c, c) for c in name)


def sanitise_extract_path(base_dirpath: Path, member_path: str) -> Path:
    """Sanitise a ZIP member path to prevent directory traversal."""
    # Remove leading slashes and .. components
    parts = Path(member_path).parts
    safe_parts = [p for p in parts if p not in ("..", "/", "\\")]
    if not safe_parts:
        safe_parts = ["_"]
    result = base_dirpath.joinpath(*safe_parts)
    # Verify the result is under base_dirpath
    result.resolve().relative_to(base_dirpath.resolve())
    return result


def extract_member(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    output_dirpath: Path,
    *,
    verbose: bool = False,
    write_inf: bool = True,
    nfs_decode: bool = True,
) -> None:
    """Extract a single ZIP member, preserving Acorn metadata as .inf files."""

    original_filename = info.filename

    # Skip directory entries (but create them)
    if info.is_dir():
        dirpath = sanitise_extract_path(output_dirpath, original_filename)
        dirpath.mkdir(parents=True, exist_ok=True)
        if verbose:
            print(f"  mkdir: {dirpath.relative_to(output_dirpath)}")
        return

    # 1. Try SparkFS extra field first
    meta = parse_sparkfs_extra(info.extra)
    metadata_source = "sparkfs" if meta else None

    # 2. Parse NFS encoding from filename
    clean_filename, nfs_meta = parse_nfs_filename(original_filename)

    if nfs_decode and nfs_meta:
        # Use NFS metadata if no SparkFS, or merge
        if meta is None:
            meta = nfs_meta
            metadata_source = "nfs"
        # Use clean filename (without NFS suffix) for output
        output_filename = clean_filename
    else:
        output_filename = original_filename

    # Determine output path
    output_filepath = sanitise_extract_path(output_dirpath, output_filename)
    output_filepath.parent.mkdir(parents=True, exist_ok=True)

    # Extract the file data
    data = zf.read(info.filename)
    output_filepath.write_bytes(data)

    if verbose:
        rel = output_filepath.relative_to(output_dirpath)
        type_info = ""
        if meta and meta.has_metadata:
            type_info = f" [{metadata_source}]"
            ft = meta.infer_filetype()
            if ft is not None:
                type_info += f" type={ft:03X}"
        print(f"  extract: {rel}{type_info}")

    # Write .inf sidecar file
    if write_inf and meta and meta.has_metadata:
        # Use the leaf filename for the INF content
        leaf_name = output_filepath.name
        inf_line = format_inf_line(
            filename=leaf_name,
            load_addr=meta.load_addr,
            exec_addr=meta.exec_addr,
            length=len(data),
            attr=meta.attr,
        )
        inf_filepath = output_filepath.with_suffix(
            output_filepath.suffix + ".inf"
        )
        inf_filepath.write_text(inf_line + "\n", encoding="ascii")

        if verbose:
            inf_rel = inf_filepath.relative_to(output_dirpath)
            print(f"     inf: {inf_rel}")


def extract_zip(
    zip_filepath: Path,
    output_dirpath: Path,
    *,
    verbose: bool = False,
    write_inf: bool = True,
    nfs_decode: bool = True,
    list_only: bool = False,
) -> None:
    """Extract a ZIP file, preserving Acorn metadata."""

    with zipfile.ZipFile(zip_filepath, "r") as zf:
        if list_only:
            list_contents(zf)
            return

        output_dirpath.mkdir(parents=True, exist_ok=True)

        if verbose:
            print(f"Extracting {zip_filepath.name} -> {output_dirpath}")

        for info in zf.infolist():
            extract_member(
                zf,
                info,
                output_dirpath,
                verbose=verbose,
                write_inf=write_inf,
                nfs_decode=nfs_decode,
            )


def list_contents(zf: zipfile.ZipFile) -> None:
    """List ZIP contents showing Acorn metadata."""

    print(
        f"{'Filename':<40} {'Load':>8} {'Exec':>8} {'Length':>8}"
        f" {'Attr':>4} {'Type':>4} {'Source':<7}"
    )
    print("-" * 85)

    for info in zf.infolist():
        if info.is_dir():
            print(f"{info.filename:<40} {'<dir>':>8}")
            continue

        meta = parse_sparkfs_extra(info.extra)
        source = "spark" if meta else ""

        clean_name, nfs_meta = parse_nfs_filename(info.filename)
        display_name = clean_name if nfs_meta else info.filename

        if meta is None and nfs_meta:
            meta = nfs_meta
            source = "nfs"

        if meta and meta.has_metadata:
            ft = meta.infer_filetype()
            ft_str = f"{ft:03X}" if ft is not None else ""
            attr_str = format_access(meta.attr) if meta.attr is not None else ""
            print(
                f"{display_name:<40} {meta.load_addr:08X} {meta.exec_addr:08X}"
                f" {info.file_size:08X} {attr_str:>4} {ft_str:>4} {source:<7}"
            )
        else:
            print(
                f"{display_name:<40} {'':>8} {'':>8}"
                f" {info.file_size:08X} {'':>4} {'':>4}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="nutzip",
        description=(
            "Extract ZIP files containing Acorn computer metadata. "
            "Preserves load/exec addresses and file attributes as .inf sidecar files."
        ),
    )
    parser.add_argument(
        "zipfile",
        type=Path,
        help="Path to the ZIP file to extract",
    )
    parser.add_argument(
        "-d",
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: ZIP filename without extension)",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List contents with Acorn metadata instead of extracting",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed extraction progress",
    )
    parser.add_argument(
        "--no-inf",
        action="store_true",
        help="Do not write .inf sidecar files",
    )
    parser.add_argument(
        "--no-nfs",
        action="store_true",
        help="Do not decode NFS filename encoding (,xxx or ,load,exec suffixes)",
    )

    args = parser.parse_args()

    zip_filepath: Path = args.zipfile
    if not zip_filepath.is_file():
        print(f"Error: {zip_filepath} not found", file=sys.stderr)
        return 1

    if not zipfile.is_zipfile(zip_filepath):
        print(f"Error: {zip_filepath} is not a valid ZIP file", file=sys.stderr)
        return 1

    output_dirpath = args.output_dir
    if output_dirpath is None:
        output_dirpath = Path(zip_filepath.stem)

    try:
        extract_zip(
            zip_filepath,
            output_dirpath,
            verbose=args.verbose,
            write_inf=not args.no_inf,
            nfs_decode=not args.no_nfs,
            list_only=args.list,
        )
    except (zipfile.BadZipFile, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
