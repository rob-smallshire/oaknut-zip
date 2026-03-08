#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "click>=8.0",
# ]
# ///
"""
nutzip - Work with ZIP files containing Acorn computer metadata.

Handles Acorn/RISC OS-specific metadata stored in ZIP archives, preserving
load addresses, execution addresses, and file attributes that standard
unzip tools discard.

Supports two metadata sources within ZIP files:
  - SparkFS extra fields (header ID 0x4341, "ARC0" signature)
  - NFS filename encoding (,xxx filetype or ,llllllll,eeeeeeee load/exec)

Supports two output metadata formats:
  - Standard Acorn INF: filename load exec length [access]
  - PiEconetBridge INF: owner load exec perm [homeof]

References:
  - INF format: https://beebwiki.mdfs.net/INF_file_format
  - Extra field spec: https://libzip.org/specifications/extrafld.txt
  - RISC OS ZIP handling: https://github.com/gerph/python-zipinfo-riscos
  - PiEconetBridge: https://github.com/cr12925/PiEconetBridge
"""

from __future__ import annotations

import re
import struct
import sys
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import click


# SparkFS extra field constants
SPARKFS_HEADER_ID = 0x4341  # "AC" in little-endian
SPARKFS_SIGNATURE = b"ARC0"
SPARKFS_DATA_LENGTH = 20  # 4 sig + 4 load + 4 exec + 4 attr + 4 reserved

# NFS filename encoding patterns
# ,xxx = 3-hex-digit filetype
# ,llllllll,eeeeeeee = 8-hex-digit load and exec addresses
NFS_FILETYPE_RE = re.compile(r"^(.*),([0-9a-fA-F]{3})$")
NFS_LOADEXEC_RE = re.compile(r"^(.*),([0-9a-fA-F]{8}),([0-9a-fA-F]{8})$")

# BBC Micro to host filename character mapping
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


class InfFormat(str, Enum):
    """Supported .inf sidecar file formats."""

    ACORN = "acorn"
    PIBRIDGE = "pibridge"


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


# ---------------------------------------------------------------------------
# ZIP metadata parsing
# ---------------------------------------------------------------------------


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
        file,xxx              -> filetype xxx (3 hex digits)
        file,llllllll,eeeeeeee -> load/exec addresses (8 hex digits each)

    Returns the clean filename and any extracted metadata.
    """
    m = NFS_LOADEXEC_RE.match(filename)
    if m:
        clean = m.group(1)
        load_addr = int(m.group(2), 16)
        exec_addr = int(m.group(3), 16)
        meta = AcornMeta(load_addr=load_addr, exec_addr=exec_addr)
        meta.filetype = meta.infer_filetype()
        return clean, meta

    m = NFS_FILETYPE_RE.match(filename)
    if m:
        clean = m.group(1)
        filetype = int(m.group(2), 16)
        load_addr = 0xFFF00000 | (filetype << 8)
        meta = AcornMeta(load_addr=load_addr, exec_addr=0, filetype=filetype)
        return clean, meta

    return filename, None


def resolve_metadata(
    info: zipfile.ZipInfo,
    *,
    nfs_decode: bool = True,
) -> tuple[str, str, AcornMeta | None]:
    """Extract metadata and clean filename from a ZIP entry.

    Returns (original_filename, clean_filename, metadata).
    """
    original_filename = info.filename

    meta = parse_sparkfs_extra(info.extra)
    metadata_source = "sparkfs" if meta else None

    clean_filename, nfs_meta = parse_nfs_filename(original_filename)

    if nfs_decode and nfs_meta:
        if meta is None:
            meta = nfs_meta
            metadata_source = "nfs"
        output_filename = clean_filename
    else:
        output_filename = original_filename

    return metadata_source, output_filename, meta


# ---------------------------------------------------------------------------
# INF file formatting
# ---------------------------------------------------------------------------


def format_access(attr: int | None) -> str:
    """Format Acorn attributes as a hex string."""
    if attr is None:
        return ""
    return f"{attr:02X}"


def format_acorn_inf_line(
    filename: str,
    load_addr: int,
    exec_addr: int,
    length: int,
    attr: int | None = None,
) -> str:
    """Format a standard Acorn INF line.

    Format: filename load exec length [access]
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


def format_pibridge_inf_line(
    load_addr: int,
    exec_addr: int,
    attr: int | None = None,
    owner: int = 0,
) -> str:
    """Format a PiEconetBridge INF line.

    Format: owner load exec perm
    The PiEconetBridge uses: %hx %lx %lx %hx
    """
    perm = attr if attr is not None else 0x17  # default WR/R
    return f"{owner:x} {load_addr:x} {exec_addr:x} {perm:x}"


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def sanitise_extract_path(base_dirpath: Path, member_path: str) -> Path:
    """Sanitise a ZIP member path to prevent directory traversal."""
    parts = Path(member_path).parts
    safe_parts = [p for p in parts if p not in ("..", "/", "\\")]
    if not safe_parts:
        safe_parts = ["_"]
    result = base_dirpath.joinpath(*safe_parts)
    result.resolve().relative_to(base_dirpath.resolve())
    return result


def host_to_bbc_filename(name: str) -> str:
    """Convert host filesystem characters back to BBC equivalents."""
    return "".join(HOST_TO_BBC.get(c, c) for c in name)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def extract_member(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    output_dirpath: Path,
    *,
    verbose: bool = False,
    inf_format: InfFormat | None = InfFormat.ACORN,
    nfs_decode: bool = True,
    owner: int = 0,
) -> None:
    """Extract a single ZIP member, optionally writing .inf sidecar files."""

    if info.is_dir():
        dirpath = sanitise_extract_path(output_dirpath, info.filename)
        dirpath.mkdir(parents=True, exist_ok=True)
        if verbose:
            click.echo(f"  mkdir: {dirpath.relative_to(output_dirpath)}")
        return

    metadata_source, output_filename, meta = resolve_metadata(
        info, nfs_decode=nfs_decode
    )

    output_filepath = sanitise_extract_path(output_dirpath, output_filename)
    output_filepath.parent.mkdir(parents=True, exist_ok=True)

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
        click.echo(f"  extract: {rel}{type_info}")

    if inf_format is not None and meta and meta.has_metadata:
        leaf_name = output_filepath.name

        if inf_format == InfFormat.ACORN:
            inf_line = format_acorn_inf_line(
                filename=leaf_name,
                load_addr=meta.load_addr,
                exec_addr=meta.exec_addr,
                length=len(data),
                attr=meta.attr,
            )
        else:
            inf_line = format_pibridge_inf_line(
                load_addr=meta.load_addr,
                exec_addr=meta.exec_addr,
                attr=meta.attr,
                owner=owner,
            )

        inf_filepath = output_filepath.with_suffix(
            output_filepath.suffix + ".inf"
        )
        inf_filepath.write_text(inf_line + "\n", encoding="ascii")

        if verbose:
            inf_rel = inf_filepath.relative_to(output_dirpath)
            click.echo(f"     inf: {inf_rel}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version="0.1.0", prog_name="nutzip")
def cli() -> None:
    """Work with ZIP files containing Acorn computer metadata."""


@cli.command()
@click.argument("zipfile_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-d",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (default: ZIP filename without extension).",
)
@click.option("-v", "--verbose", is_flag=True, help="Show extraction progress.")
@click.option(
    "--inf-format",
    type=click.Choice(["acorn", "pibridge", "none"], case_sensitive=False),
    default="acorn",
    help="INF sidecar format: acorn (standard), pibridge (PiEconetBridge), or none.",
)
@click.option(
    "--no-nfs",
    is_flag=True,
    help="Do not decode NFS filename encoding (,xxx or ,load,exec suffixes).",
)
@click.option(
    "--owner",
    type=int,
    default=0,
    help="Econet owner ID for PiEconetBridge INF files (default: 0 = SYST).",
)
def extract(
    zipfile_path: Path,
    output_dir: Path | None,
    verbose: bool,
    inf_format: str,
    no_nfs: bool,
    owner: int,
) -> None:
    """Extract a ZIP file, preserving Acorn metadata as .inf sidecar files."""

    if not zipfile.is_zipfile(zipfile_path):
        raise click.ClickException(f"{zipfile_path} is not a valid ZIP file")

    if output_dir is None:
        output_dir = Path(zipfile_path.stem)

    resolved_inf_format: InfFormat | None
    if inf_format == "none":
        resolved_inf_format = None
    else:
        resolved_inf_format = InfFormat(inf_format)

    output_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        click.echo(f"Extracting {zipfile_path.name} -> {output_dir}")

    with zipfile.ZipFile(zipfile_path, "r") as zf:
        for info in zf.infolist():
            extract_member(
                zf,
                info,
                output_dir,
                verbose=verbose,
                inf_format=resolved_inf_format,
                nfs_decode=not no_nfs,
                owner=owner,
            )


@cli.command(name="list")
@click.argument("zipfile_path", type=click.Path(exists=True, path_type=Path))
def list_cmd(zipfile_path: Path) -> None:
    """List ZIP contents showing Acorn metadata."""

    if not zipfile.is_zipfile(zipfile_path):
        raise click.ClickException(f"{zipfile_path} is not a valid ZIP file")

    with zipfile.ZipFile(zipfile_path, "r") as zf:
        header = (
            f"{'Filename':<40} {'Load':>8} {'Exec':>8} {'Length':>8}"
            f" {'Attr':>4} {'Type':>4} {'Source':<7}"
        )
        click.echo(header)
        click.echo("-" * len(header))

        for info in zf.infolist():
            if info.is_dir():
                click.echo(f"{info.filename:<40} {'<dir>':>8}")
                continue

            metadata_source, clean_name, meta = resolve_metadata(info)

            if meta and meta.has_metadata:
                ft = meta.infer_filetype()
                ft_str = f"{ft:03X}" if ft is not None else ""
                attr_str = (
                    format_access(meta.attr) if meta.attr is not None else ""
                )
                source_str = metadata_source or ""
                click.echo(
                    f"{clean_name:<40} {meta.load_addr:08X}"
                    f" {meta.exec_addr:08X} {info.file_size:08X}"
                    f" {attr_str:>4} {ft_str:>4} {source_str:<7}"
                )
            else:
                click.echo(
                    f"{clean_name:<40} {'':>8} {'':>8}"
                    f" {info.file_size:08X} {'':>4} {'':>4}"
                )


@cli.command()
@click.argument("zipfile_path", type=click.Path(exists=True, path_type=Path))
def info(zipfile_path: Path) -> None:
    """Show summary of Acorn metadata in a ZIP file."""

    if not zipfile.is_zipfile(zipfile_path):
        raise click.ClickException(f"{zipfile_path} is not a valid ZIP file")

    with zipfile.ZipFile(zipfile_path, "r") as zf:
        total = 0
        dirs = 0
        sparkfs_count = 0
        nfs_count = 0
        plain_count = 0
        filetypes: dict[int, int] = {}

        for entry in zf.infolist():
            if entry.is_dir():
                dirs += 1
                continue

            total += 1
            metadata_source, _, meta = resolve_metadata(entry)

            if metadata_source == "sparkfs":
                sparkfs_count += 1
            elif metadata_source == "nfs":
                nfs_count += 1
            else:
                plain_count += 1

            if meta and meta.has_metadata:
                ft = meta.infer_filetype()
                if ft is not None:
                    filetypes[ft] = filetypes.get(ft, 0) + 1

        click.echo(f"Archive:    {zipfile_path.name}")
        click.echo(f"Files:      {total}")
        click.echo(f"Dirs:       {dirs}")
        click.echo(f"SparkFS:    {sparkfs_count} files with ARC0 extra fields")
        click.echo(f"NFS:        {nfs_count} files with NFS-encoded filenames")
        click.echo(f"Plain:      {plain_count} files without Acorn metadata")

        if filetypes:
            click.echo(f"Filetypes:  {len(filetypes)} distinct")
            for ft in sorted(filetypes):
                click.echo(f"  {ft:03X}: {filetypes[ft]} files")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
