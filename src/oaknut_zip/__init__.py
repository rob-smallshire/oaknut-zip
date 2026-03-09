"""oaknut-zip - Work with ZIP files containing Acorn computer metadata."""

__version__ = "0.1.0"

from .models import AcornMeta, MetaFormat
from .parsing import (
    build_inf_index,
    parse_encoded_filename,
    parse_inf_line,
    parse_sparkfs_extra,
    resolve_metadata,
)
from .formatting import (
    build_filename_suffix,
    build_mos_filename_suffix,
    format_access,
    format_pieb_inf_line,
    format_trad_inf_line,
    write_econet_xattrs,
)
from .api import (
    extract_member,
    sanitise_extract_path,
)

__all__ = [
    "AcornMeta",
    "MetaFormat",
    "build_filename_suffix",
    "build_inf_index",
    "build_mos_filename_suffix",
    "extract_member",
    "format_access",
    "format_pieb_inf_line",
    "format_trad_inf_line",
    "parse_encoded_filename",
    "parse_inf_line",
    "parse_sparkfs_extra",
    "resolve_metadata",
    "sanitise_extract_path",
    "write_econet_xattrs",
]
