"""Output formatting for Acorn metadata.

This module is now a thin re-export shim over ``oaknut_file``.
All formatting functions are provided by the shared package.
"""

from __future__ import annotations

from oaknut_file import (
    build_filename_suffix,
    build_mos_filename_suffix,
    format_access_hex,
    format_access_text,
    format_pieb_inf_line,
    format_trad_inf_line,
    write_econet_xattrs,
)
from oaknut_file.xattr import _set_xattrs


# Backward-compatible alias: the old name was format_access
format_access = format_access_hex


__all__ = [
    "_set_xattrs",
    "build_filename_suffix",
    "build_mos_filename_suffix",
    "format_access",
    "format_access_hex",
    "format_access_text",
    "format_pieb_inf_line",
    "format_trad_inf_line",
    "write_econet_xattrs",
]
