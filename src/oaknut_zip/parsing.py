"""Parsing of Acorn metadata from ZIP entries.

Handles three metadata sources:
  - SparkFS extra fields (header ID 0x4341, "ARC0" signature) — ZIP-specific
  - Bundled INF sidecar files (traditional or PiEconetBridge format)
  - Unix filename encoding (,xxx filetype or ,llllllll,eeeeeeee load/exec)

Generic INF and filename parsing is delegated to oaknut-file; only the
ZIP-specific glue (SparkFS extra field parsing, scanning the ZIP for
.inf members, and the priority resolution) lives here.
"""

from __future__ import annotations

import struct
import zipfile

from oaknut_file import (
    AcornMeta,
    parse_encoded_filename,
    parse_inf_line,
)
from oaknut_file import SOURCE_FILENAME, SOURCE_SPARKFS

from .models import (
    SPARKFS_DATA_LENGTH,
    SPARKFS_HEADER_ID,
    SPARKFS_SIGNATURE,
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

    The Info-ZIP / David Pilling SparkFS specification defines only
    bits 0-7 of the Attributes field (the standard RISC OS access
    byte: R, W, L, PR, PW). Bits 8-31 have no documented meaning.
    In practice, archives produced by genuine RISC OS tooling write
    zero in the upper 24 bits, but some non-RISC-OS producers leave
    junk there. We mask to the low 8 bits so the stored attribute
    matches the Access enum semantics used throughout oaknut-file.
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
                    attr=attr & 0xFF,
                )
                meta.filetype = meta.infer_filetype()
                return meta

        offset += data_size

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
        dir_filename = data_filename + "/"
        if data_filename not in names and dir_filename not in names:
            continue

        try:
            content = zf.read(info.filename).decode("ascii", errors="replace")
            line = content.strip().split("\n")[0].strip()
        except Exception:
            continue

        result = parse_inf_line(line)
        if result is not None:
            source_label, meta = result
            key = dir_filename if dir_filename in names else data_filename
            index[key] = (source_label, meta)
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
