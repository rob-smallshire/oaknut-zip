"""Data models and constants for Acorn/RISC OS metadata.

Most types and constants are now provided by the shared ``oaknut_file``
package and re-exported here for backward compatibility.
"""

from __future__ import annotations

# Re-export shared types and constants from oaknut-file
from oaknut_file import (
    Access,
    AcornMeta,
    MetaFormat,
    SOURCE_DIR,
    SOURCE_FILENAME,
    SOURCE_INF_PIEB,
    SOURCE_INF_TRAD,
    SOURCE_SPARKFS,
)
from oaknut_file.filename_encoding import (
    SUFFIX_FILETYPE_RE,
    SUFFIX_LOADEXEC_RE,
    SUFFIX_MOS_LOADEXEC_RE,
)


# --- Backward-compatible attribute bit constants ---
# These shadow the Access enum values for code that still uses the
# ATTR_* names directly.
ATTR_OWNER_READ = int(Access.R)
ATTR_OWNER_WRITE = int(Access.W)
ATTR_LOCKED = int(Access.L)
ATTR_PUBLIC_READ = int(Access.PR)
ATTR_PUBLIC_WRITE = int(Access.PW)


# --- ZIP-specific constants (stay in oaknut-zip) ---

# SparkFS extra field constants
SPARKFS_HEADER_ID = 0x4341  # "AC" in little-endian
SPARKFS_SIGNATURE = b"ARC0"
SPARKFS_DATA_LENGTH = 20  # 4 sig + 4 load + 4 exec + 4 attr + 4 reserved


# --- oaknut-zip API dictionary keys ---
# Used by list_archive() and archive_info()

FILENAME_KEY = "filename"
IS_DIR_KEY = "is_dir"
FILE_SIZE_KEY = "file_size"
LOAD_ADDR_KEY = "load_addr"
EXEC_ADDR_KEY = "exec_addr"
ATTR_KEY = "attr"
FILETYPE_KEY = "filetype"
SOURCE_KEY = "source"

TOTAL_KEY = "total"
DIRS_KEY = "dirs"
SPARKFS_COUNT_KEY = "sparkfs_count"
INF_COUNT_KEY = "inf_count"
PIEB_INF_COUNT_KEY = "pieb_inf_count"
FILENAME_COUNT_KEY = "filename_count"
PLAIN_COUNT_KEY = "plain_count"
FILETYPES_KEY = "filetypes"
