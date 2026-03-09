"""Data models and constants for Acorn/RISC OS metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


# SparkFS extra field constants
SPARKFS_HEADER_ID = 0x4341  # "AC" in little-endian
SPARKFS_SIGNATURE = b"ARC0"
SPARKFS_DATA_LENGTH = 20  # 4 sig + 4 load + 4 exec + 4 attr + 4 reserved

# Unix filename encoding patterns
# ,xxx = 3-hex-digit RISC OS filetype
# ,llllllll,eeeeeeee = 8-hex-digit load and exec addresses (python-zipinfo-riscos)
# ,load-exec = 1-to-8-hex-digit load and exec with dash separator (MOS/SparkFS)
SUFFIX_FILETYPE_RE = re.compile(r"^(.*),([0-9a-fA-F]{3})$")
SUFFIX_LOADEXEC_RE = re.compile(r"^(.*),([0-9a-fA-F]{8}),([0-9a-fA-F]{8})$")
SUFFIX_MOS_LOADEXEC_RE = re.compile(r"^(.*),([0-9a-fA-F]{1,8})-([0-9a-fA-F]{1,8})$")

# Acorn attribute bits
ATTR_OWNER_WRITE = 0x01
ATTR_OWNER_READ = 0x02
ATTR_LOCKED = 0x08
ATTR_PUBLIC_WRITE = 0x10
ATTR_PUBLIC_READ = 0x20


class MetaFormat(str, Enum):
    """Supported output metadata formats."""

    INF_TRAD = "inf-trad"
    INF_PIEB = "inf-pieb"
    XATTR = "xattr"
    FILENAME_RISCOS = "filename-riscos"
    FILENAME_MOS = "filename-mos"


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
