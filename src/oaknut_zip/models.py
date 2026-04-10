"""ZIP-specific constants and dict keys for oaknut-zip.

Metadata types, access enums, source labels, and filename-encoding
helpers live in ``oaknut_file``. This module keeps only the pieces
that are specific to the ZIP layer: SparkFS extra-field constants
and the dict keys used by :func:`~oaknut_zip.api.list_archive` and
:func:`~oaknut_zip.api.archive_info`.
"""

from __future__ import annotations


# --- SparkFS extra field constants ---

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
