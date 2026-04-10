"""oaknut-zip - Work with ZIP files containing Acorn computer metadata."""

__version__ = "1.0.0"

from .api import (
    archive_info,
    extract_archive,
    extract_member,
    list_archive,
    sanitise_extract_path,
)
from .models import (
    ATTR_KEY,
    DIRS_KEY,
    EXEC_ADDR_KEY,
    FILE_SIZE_KEY,
    FILENAME_COUNT_KEY,
    FILENAME_KEY,
    FILETYPE_KEY,
    FILETYPES_KEY,
    INF_COUNT_KEY,
    IS_DIR_KEY,
    LOAD_ADDR_KEY,
    PIEB_INF_COUNT_KEY,
    PLAIN_COUNT_KEY,
    SOURCE_KEY,
    SPARKFS_COUNT_KEY,
    TOTAL_KEY,
)
from .parsing import (
    build_inf_index,
    parse_sparkfs_extra,
    resolve_metadata,
)

__all__ = [
    "ATTR_KEY",
    "DIRS_KEY",
    "EXEC_ADDR_KEY",
    "FILE_SIZE_KEY",
    "FILENAME_COUNT_KEY",
    "FILENAME_KEY",
    "FILETYPE_KEY",
    "FILETYPES_KEY",
    "INF_COUNT_KEY",
    "IS_DIR_KEY",
    "LOAD_ADDR_KEY",
    "PIEB_INF_COUNT_KEY",
    "PLAIN_COUNT_KEY",
    "SOURCE_KEY",
    "SPARKFS_COUNT_KEY",
    "TOTAL_KEY",
    "archive_info",
    "build_inf_index",
    "extract_archive",
    "extract_member",
    "list_archive",
    "parse_sparkfs_extra",
    "resolve_metadata",
    "sanitise_extract_path",
]
