"""Output formatting for Acorn metadata.

Supports five output formats:
  - Traditional INF sidecar files
  - PiEconetBridge INF sidecar files
  - Extended attributes (user.econet_*)
  - RISC OS filename encoding (,xxx or ,llllllll,eeeeeeee)
  - MOS filename encoding (,load-exec)
"""

from __future__ import annotations

import os
from pathlib import Path

from .models import AcornMeta


def format_access(attr: int | None) -> str:
    """Format Acorn attributes as a hex string."""
    if attr is None:
        return ""
    return f"{attr:02X}"


def build_filename_suffix(meta: AcornMeta) -> str:
    """Build a RISC OS filename encoding suffix for Acorn metadata.

    Returns ',xxx' for filetype-stamped files, or
    ',llllllll,eeeeeeee' for files with literal load/exec addresses.
    """
    if meta.is_filetype_stamped:
        ft = meta.infer_filetype()
        return f",{ft:03x}"
    return f",{meta.load_addr:08x},{meta.exec_addr:08x}"


def build_mos_filename_suffix(meta: AcornMeta) -> str:
    """Build a MOS filename encoding suffix for Acorn metadata.

    Returns ',load-exec' with variable-width hex digits.
    """
    return f",{meta.load_addr:x}-{meta.exec_addr:x}"


def format_trad_inf_line(
    filename: str,
    load_addr: int,
    exec_addr: int,
    length: int,
    attr: int | None = None,
) -> str:
    """Format a traditional INF line.

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


def format_pieb_inf_line(
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


def _set_xattrs(filepath: Path, attrs: dict[str, str]) -> None:
    """Set extended attributes on a file.

    Uses os.setxattr on Linux, or the xattr package on macOS.
    """
    path_str = str(filepath)
    if hasattr(os, "setxattr"):
        for name, value in attrs.items():
            os.setxattr(path_str, name, value.encode("ascii"))
    else:
        import xattr

        x = xattr.xattr(path_str)
        for name, value in attrs.items():
            x.set(name, value.encode("ascii"))


def write_econet_xattrs(
    filepath: Path,
    load_addr: int,
    exec_addr: int,
    attr: int | None = None,
    owner: int = 0,
) -> None:
    """Write PiEconetBridge-compatible extended attributes to a file.

    Attributes written (uppercase hex strings matching PiEconetBridge's C sprintf):
        user.econet_owner  = %04X
        user.econet_load   = %08X
        user.econet_exec   = %08X
        user.econet_perm   = %02X
    """
    perm = attr if attr is not None else 0x17
    attrs = {
        "user.econet_owner": f"{owner:04X}",
        "user.econet_load": f"{load_addr:08X}",
        "user.econet_exec": f"{exec_addr:08X}",
        "user.econet_perm": f"{perm:02X}",
    }
    _set_xattrs(filepath, attrs)
