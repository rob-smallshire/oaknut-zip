"""Parsing of Acorn metadata from ZIP entries.

Handles three metadata sources:
  - SparkFS extra fields (header ID 0x4341, "ARC0" signature)
  - Bundled INF sidecar files (traditional or PiEconetBridge format)
  - Unix filename encoding (,xxx filetype or ,llllllll,eeeeeeee load/exec)
"""

from __future__ import annotations

import struct
import zipfile

from .models import (
    SOURCE_FILENAME,
    SOURCE_INF_PIEB,
    SOURCE_INF_TRAD,
    SOURCE_SPARKFS,
    SPARKFS_DATA_LENGTH,
    SPARKFS_HEADER_ID,
    SPARKFS_SIGNATURE,
    SUFFIX_FILETYPE_RE,
    SUFFIX_LOADEXEC_RE,
    SUFFIX_MOS_LOADEXEC_RE,
    AcornMeta,
)


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


def parse_encoded_filename(filename: str) -> tuple[str, AcornMeta | None]:
    """Parse Unix-encoded metadata from a filename.

    Three forms:
        file,xxx                -> RISC OS filetype (3 hex digits)
        file,llllllll,eeeeeeee  -> load/exec addresses (8 hex digits each)
        file,load-exec          -> MOS load/exec addresses (1-8 hex digits, dash)

    Returns the clean filename and any extracted metadata.
    """
    m = SUFFIX_LOADEXEC_RE.match(filename)
    if m:
        clean = m.group(1)
        load_addr = int(m.group(2), 16)
        exec_addr = int(m.group(3), 16)
        meta = AcornMeta(load_addr=load_addr, exec_addr=exec_addr)
        meta.filetype = meta.infer_filetype()
        return clean, meta

    m = SUFFIX_MOS_LOADEXEC_RE.match(filename)
    if m:
        clean = m.group(1)
        load_addr = int(m.group(2), 16)
        exec_addr = int(m.group(3), 16)
        meta = AcornMeta(load_addr=load_addr, exec_addr=exec_addr)
        meta.filetype = meta.infer_filetype()
        return clean, meta

    m = SUFFIX_FILETYPE_RE.match(filename)
    if m:
        clean = m.group(1)
        filetype = int(m.group(2), 16)
        load_addr = 0xFFF00000 | (filetype << 8)
        meta = AcornMeta(load_addr=load_addr, exec_addr=0, filetype=filetype)
        return clean, meta

    return filename, None


def _is_hex(s: str) -> bool:
    """Check if a string consists entirely of hexadecimal digits."""
    return len(s) > 0 and all(c in "0123456789abcdefABCDEF" for c in s)


def parse_inf_line(line: str) -> tuple[str, AcornMeta] | None:
    """Parse an INF sidecar file line, detecting the flavour.

    Traditional INF:   filename load exec length [access]
    PiEconetBridge INF: owner load exec perm [homeof]

    Returns (source_label, metadata) where source_label is "inf-trad" for
    traditional or "inf-pieb" for PiEconetBridge.
    """
    parts = line.split()
    if len(parts) < 4:
        return None

    if not _is_hex(parts[0]):
        # First field contains non-hex chars, so it must be a traditional INF filename.
        # Traditional INF: filename load exec length [access]
        try:
            load_addr = int(parts[1], 16)
            exec_addr = int(parts[2], 16)
            # parts[3] is length (informational only)
            attr = int(parts[4], 16) if len(parts) >= 5 else None
            meta = AcornMeta(load_addr=load_addr, exec_addr=exec_addr, attr=attr)
            meta.filetype = meta.infer_filetype()
            return (SOURCE_INF_TRAD, meta)
        except (ValueError, IndexError):
            return None

    # All fields could be hex. Distinguish by field[3] width:
    # Traditional INF length field is always 8-digit hex; PiEB perm is short (1-2 digits).
    if len(parts[3]) == 8 and _is_hex(parts[3]):
        # Traditional INF with a hex-only filename
        try:
            load_addr = int(parts[1], 16)
            exec_addr = int(parts[2], 16)
            attr = int(parts[4], 16) if len(parts) >= 5 else None
            meta = AcornMeta(load_addr=load_addr, exec_addr=exec_addr, attr=attr)
            meta.filetype = meta.infer_filetype()
            return (SOURCE_INF_TRAD, meta)
        except (ValueError, IndexError):
            return None

    # PiEconetBridge INF: owner load exec perm
    try:
        load_addr = int(parts[1], 16)
        exec_addr = int(parts[2], 16)
        perm = int(parts[3], 16)
        meta = AcornMeta(load_addr=load_addr, exec_addr=exec_addr, attr=perm)
        meta.filetype = meta.infer_filetype()
        return (SOURCE_INF_PIEB, meta)
    except (ValueError, IndexError):
        return None


def build_inf_index(
    zf: zipfile.ZipFile,
) -> tuple[dict[str, tuple[str, AcornMeta]], set[str]]:
    """Scan a ZIP for bundled .inf files and parse their metadata.

    Returns (index, consumed) where:
      - index maps data filenames to (source_label, metadata)
      - consumed is the set of .inf ZIP member filenames that were parsed
    """
    names = {info.filename for info in zf.infolist()}
    index: dict[str, tuple[str, AcornMeta]] = {}
    consumed: set[str] = set()

    for info in zf.infolist():
        if info.is_dir():
            continue
        if not info.filename.lower().endswith(".inf"):
            continue

        data_filename = info.filename[:-4]
        if data_filename not in names:
            continue

        try:
            content = zf.read(info.filename).decode("ascii", errors="replace")
            line = content.strip().split("\n")[0].strip()
        except Exception:
            continue

        result = parse_inf_line(line)
        if result is not None:
            source_label, meta = result
            index[data_filename] = (source_label, meta)
            consumed.add(info.filename)

    return index, consumed


def resolve_metadata(
    info: zipfile.ZipInfo,
    *,
    decode_filenames: bool = True,
    inf_index: dict[str, tuple[str, AcornMeta]] | None = None,
) -> tuple[str | None, str, AcornMeta | None]:
    """Extract metadata and clean filename from a ZIP entry.

    Priority: SparkFS extra fields > bundled INF > filename encoding.

    Returns (source_label, clean_filename, metadata).
    """
    original_filename = info.filename

    meta = parse_sparkfs_extra(info.extra)
    metadata_source: str | None = SOURCE_SPARKFS if meta else None

    if meta is None and inf_index is not None:
        inf_entry = inf_index.get(original_filename)
        if inf_entry is not None:
            metadata_source, meta = inf_entry

    clean_filename, filename_meta = parse_encoded_filename(original_filename)

    if decode_filenames and filename_meta:
        if meta is None:
            meta = filename_meta
            metadata_source = SOURCE_FILENAME
        output_filename = clean_filename
    else:
        output_filename = original_filename

    return metadata_source, output_filename, meta
