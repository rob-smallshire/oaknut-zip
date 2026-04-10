<p align="center">
  <img src="https://raw.githubusercontent.com/rob-smallshire/oaknut-zip/main/docs/oaknut-zip-logo.png" alt="oaknut-zip" width="300">
</p>

# oaknut-zip

[![PyPI version](https://img.shields.io/pypi/v/oaknut-zip)](https://pypi.org/project/oaknut-zip/)
[![CI](https://github.com/rob-smallshire/oaknut-zip/actions/workflows/tests.yml/badge.svg)](https://github.com/rob-smallshire/oaknut-zip/actions/workflows/tests.yml)
[![Python versions](https://img.shields.io/pypi/pyversions/oaknut-zip)](https://pypi.org/project/oaknut-zip/)
[![License: MIT](https://img.shields.io/pypi/l/oaknut-zip)](https://github.com/rob-smallshire/oaknut-zip/blob/main/LICENSE)

A Python tool for extracting ZIP files containing
[Acorn computer](https://en.wikipedia.org/wiki/Acorn_Computers) metadata.

Standard unzip tools silently discard the load addresses, execution addresses,
and file attributes that Acorn systems (BBC Micro, Master, RISC OS
machines) store in ZIP archives. oaknut-zip preserves this metadata, writing it out
in your choice of several output formats.

## The problem

When software for Acorn 8-bit and 32-bit systems is distributed as ZIP files,
the archives often contain platform-specific metadata embedded using mechanisms
that non-Acorn unzip tools ignore:

- **SparkFS extra fields** in the ZIP structure itself, carrying load/exec
  addresses and RISC OS file attributes.
- **Bundled INF sidecar files** inside the archive, in either Acorn
  or PiEconetBridge format.
- **Unix filename encoding**, where metadata is appended to filenames as comma-
  separated hex suffixes.

Extracting these archives with `unzip` or Python's `zipfile` module on Linux or
macOS produces the raw file data but loses all the Acorn metadata. For 6502 or
ARM executables, this means you no longer know where in memory a program should
be loaded or where execution should begin. For a PiEconetBridge fileserver, the
files become unserviceable without their attributes.

oaknut-zip reads all three metadata sources from the ZIP and writes them out in a
format your target system can consume.

## Prerequisites

oaknut-zip requires only [`uv`](https://docs.astral.sh/uv/). `uv` handles
Python installation, dependency resolution, and virtual environments
automatically --- you do not need to install anything else by hand.

### Installing uv

**macOS (Homebrew):**

```
brew install uv
```

**Linux / macOS (standalone installer):**

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**

```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

See the [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/)
for other methods including pip, pipx, Cargo, Conda, Winget, and Scoop.

## Installation

### Run without installing

```
uvx oaknut-zip <command> [options]
```

This always uses the latest published version, but has a small startup
overhead on each invocation.

### Persistent install

```
uv tool install oaknut-zip
```

Subsequently run as just `oaknut-zip`:

```
oaknut-zip <command> [options]
```

This is faster to invoke, but you need `uv tool upgrade oaknut-zip` to
pick up new versions.

## Usage

### Commands

```
$ oaknut-zip --help
Usage: oaknut-zip [OPTIONS] COMMAND [ARGS]...

  Work with ZIP files containing Acorn computer metadata.

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  extract  Extract a ZIP file, preserving Acorn metadata.
  info     Show summary of Acorn metadata in a ZIP file.
  list     List ZIP contents showing Acorn metadata.
```

## Inspecting an archive

### list --- tabular view of all entries

```
$ oaknut-zip list NetUtils.zip
                             NetUtils.zip                              
┏━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ Filename   ┃     Load ┃     Exec ┃   Length ┃ Attr ┃ Type ┃ Source  ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━━━━┩
│ Free       │ FFFF0E10 │ FFFF0E10 │ 000001E6 │ LR/R │  F0E │ sparkfs │
│ FSList     │ FFFF0900 │ FFFF0900 │ 00000200 │ LR/R │  F09 │ sparkfs │
│ PSList     │ FFFF0900 │ FFFF0900 │ 000001B5 │ LR/R │  F09 │ sparkfs │
│ Notify     │ FFFF0E23 │ FFFF0E23 │ 0000012A │ LR/R │  F0E │ sparkfs │
│ Remote     │ FFFF0E10 │ FFFF0E10 │ 000001ED │ LR/R │  F0E │ sparkfs │
│ Servers    │ FFFF0900 │ FFFF091A │ 000001CF │ LR/R │  F09 │ sparkfs │
│ SetStation │ FFFFDD00 │ FFFFDD00 │ 00000200 │ LR/R │  FDD │ sparkfs │
│ Stations   │ FFFF08D5 │ FFFF08E1 │ 0000022B │ WR/R │  F08 │ sparkfs │
│ SJMon      │ FFFF1B00 │ FFFF1B00 │ 00000D7E │  LR/ │  F1B │ sparkfs │
│ Users      │ FFFF0E23 │ FFFF0E23 │ 00000139 │ LR/R │  F0E │ sparkfs │
│ View       │ FFFF0900 │ FFFF0904 │ 000001FF │ LR/R │  F09 │ sparkfs │
│ ReadMe     │ FFFFFF52 │ 2FEEAFD0 │ 00000255 │  R/R │  FFF │ sparkfs │
└────────────┴──────────┴──────────┴──────────┴──────┴──────┴─────────┘
```

The **Source** column shows where the metadata was found (see the
[format identifier table](#extracting-an-archive) below). The **Type** column
shows the RISC OS filetype extracted from the load address (when the top
12 bits are `0xFFF`).

### info --- summary statistics

```
$ oaknut-zip info NetUtils.zip
Archive:    NetUtils.zip
Files:      12
Dirs:       0
SparkFS:    12 files with ARC0 extra fields
inf-trad:   0 files with bundled traditional INF
inf-pieb:   0 files with bundled PiEconetBridge INF
Filename:   0 files with encoded filenames
Plain:      0 files without Acorn metadata
Filetypes:  6 distinct
  F08: 1 files
  F09: 4 files
  F0E: 4 files
  F1B: 1 files
  FDD: 1 files
  FFF: 1 files
```

## Extracting an archive

```
$ oaknut-zip extract --help
Usage: oaknut-zip extract [OPTIONS] ZIPFILE_PATH

  Extract a ZIP file, preserving Acorn metadata.

Options:
  -d, --output-dir PATH           Output directory (default: ZIP filename
                                  without extension).
  -v, --verbose                   Show extraction progress.
  --meta-format [inf-trad|inf-pieb|xattr-acorn|xattr-pieb|filename-riscos|filename-mos|none]
                                  Metadata format: inf-trad, inf-pieb, xattr-
                                  acorn, xattr-pieb, filename-riscos,
                                  filename-mos, or none.
  --no-decode-filenames           Do not decode metadata from filename
                                  suffixes (,xxx or ,load,exec).
  --owner INTEGER                 Econet owner ID for inf-pieb and xattr-pieb
                                  outputs (default: 0 = SYST).
  --help                          Show this message and exit.
```

oaknut-zip uses a consistent `<mechanism>-<flavour>` naming scheme for format
identifiers. The same identifiers appear as metadata source labels in
the `list` and `info` commands, and as `--meta-format` choices for output:

| Identifier        | As input source                                                      | As output format (`--meta-format`)                          |
|-------------------|----------------------------------------------------------------------|-------------------------------------------------------------|
| `sparkfs`         | SparkFS/ARC0 extra fields in the ZIP structure                       | --- (not an output format)                                  |
| `inf-trad`        | Bundled traditional `.inf` sidecar files                             | Traditional INF sidecar files                               |
| `inf-pieb`        | Bundled PiEconetBridge `.inf` sidecar files                          | PiEconetBridge INF sidecar files                            |
| `filename`        | Metadata encoded in filenames (`,xxx`, `,load,exec`, `,load-exec`)  | --- (not an output format)                                  |
| `filename-riscos` | ---                                                                  | RISC OS filename encoding (`,xxx` or `,llllllll,eeeeeeee`) |
| `filename-mos`    | ---                                                                  | MOS filename encoding (`,load-exec`)                        |
| `xattr-acorn`     | ---                                                                  | Extended attributes (`user.acorn.*`)                        |
| `xattr-pieb`      | ---                                                                  | Extended attributes (`user.econet_*`, PiEconetBridge)       |
| `none`            | ---                                                                  | No metadata (raw extraction)                                |

### Format 1: Traditional INF (default)

```
oaknut-zip extract NetUtils.zip
```

Each extracted file gets a companion `.inf` sidecar file:

```
$ cat SetStation.inf
SetStation  FFFFDD00 FFFFDD00 00000200 5D

$ cat ReadMe.inf
ReadMe      FFFFFF52 2FEEAFD0 00000255 55
```

The fields are space-separated, with the filename left-padded to 11 characters:

```
filename    load     exec     length   [access]
```

| Field    | Format          | Description                                                                 |
|----------|-----------------|-----------------------------------------------------------------------------|
| filename | ASCII string    | Leaf filename, left-padded to 11 chars                                      |
| load     | 8-digit hex     | 32-bit load address; if top 12 bits = `FFF`, bits 8--19 encode the filetype |
| exec     | 8-digit hex     | 32-bit execution address (entry point for code)                             |
| length   | 8-digit hex     | File length in bytes                                                        |
| access   | 2-digit hex     | Acorn file attributes (optional; see attribute bits below)                  |

This is the standard format understood by BBC Micro emulators, disc image tools
(BBCIM, Disc Image Manager), and other retro-computing utilities.

### Format 2: PiEconetBridge INF

```
oaknut-zip extract --meta-format inf-pieb NetUtils.zip
```

Writes `.inf` sidecar files in the format used by
[PiEconetBridge](https://github.com/cr12925/PiEconetBridge):

```
$ cat SetStation.inf
0 ffffdd00 ffffdd00 5d

$ cat ReadMe.inf
0 ffffff52 2feeafd0 55
```

The fields, all lowercase hex:

```
owner load exec perm
```

| Field | Format       | Description                                            |
|-------|--------------|--------------------------------------------------------|
| owner | short hex    | Econet user ID (set with `--owner`, default 0 = SYST)  |
| load  | long hex     | 32-bit load address                                    |
| exec  | long hex     | 32-bit execution address                               |
| perm  | short hex    | File permissions byte                                  |

PiEconetBridge reads this format from `<filename>.inf` when extended attribute
support is unavailable on the host filesystem (e.g. FAT32). This is the format
produced by the `parse_acorn_zip.pl` utility bundled with PiEconetBridge.

### Format 3: Extended attributes (Acorn namespace)

```
oaknut-zip extract --meta-format xattr-acorn NetUtils.zip
```

Writes metadata directly into the filesystem's extended attributes using the
`user.acorn.*` namespace, with no sidecar files:

```
$ xattr -l SetStation
user.acorn.attr: 5D
user.acorn.exec: FFFFDD00
user.acorn.load: FFFFDD00

$ xattr -l ReadMe
user.acorn.attr: 55
user.acorn.exec: 2FEEAFD0
user.acorn.load: FFFFFF52
```

The attribute names and value formats:

| Attribute         | Format (sprintf) | Example      |
|-------------------|------------------|--------------|
| `user.acorn.load` | `%08X`           | `FFFFDD00`   |
| `user.acorn.exec` | `%08X`           | `FFFFDD00`   |
| `user.acorn.attr` | `%02X`           | `03`         |

This is the oaknut-file convention, free of the Econet/PiEconetBridge naming
legacy. The `user.acorn.attr` attribute is written only when attribute
information is available; there is no Econet owner field.

### Format 4: Extended attributes (PiEconetBridge namespace)

```
oaknut-zip extract --meta-format xattr-pieb NetUtils.zip
```

Writes metadata using the `user.econet_*` namespace defined by
[PiEconetBridge](https://github.com/cr12925/PiEconetBridge):

```
$ xattr -l SetStation
user.econet_exec: FFFFDD00
user.econet_load: FFFFDD00
user.econet_owner: 0000
user.econet_perm: 5D

$ xattr -l ReadMe
user.econet_exec: 2FEEAFD0
user.econet_load: FFFFFF52
user.econet_owner: 0000
user.econet_perm: 55
```

The attribute names and value formats match PiEconetBridge's C implementation
exactly:

| Attribute            | Format (sprintf) | Example      |
|----------------------|------------------|--------------|
| `user.econet_owner`  | `%04X`           | `0000`       |
| `user.econet_load`   | `%08X`           | `FFFFDD00`   |
| `user.econet_exec`   | `%08X`           | `FFFFDD00`   |
| `user.econet_perm`   | `%02X`           | `03`         |

This is the preferred format for PiEconetBridge when the host filesystem
supports extended attributes. PiEconetBridge reads xattrs in preference
to `.inf` files when both are present. Use `--owner` to set the Econet owner
ID (default 0 = SYST).

### Format 5: RISC OS filename encoding

```
oaknut-zip extract --meta-format filename-riscos NetUtils.zip
```

Encodes metadata directly into the output filenames using comma-separated hex
suffixes. No sidecar files are created. Filetype-stamped files get a `,xxx`
suffix (e.g. `FILE,fdd`); files with literal load/exec addresses get
`,llllllll,eeeeeeee` (e.g. `PROG,00001900,0000801f`).

This is the most portable format --- it requires no filesystem-specific
support and survives transfers between any systems. Files already carrying
the correct suffix are not double-encoded.

### Format 6: MOS filename encoding

```
oaknut-zip extract --meta-format filename-mos NetUtils.zip
```

Encodes metadata into output filenames using the `,load-exec` convention
documented in the [BeebWiki INF file format](https://beebwiki.mdfs.net/INF_file_format)
specification. This format uses a comma prefix with load and exec addresses
separated by a dash, with variable-width hex digits (no zero-padding):
`,1900-801f`.

This is the convention used by MOS and SparkFS when encoding addresses in
filenames. Unlike the RISC OS form (Format 4), it always encodes full
load/exec addresses and does not special-case filetype-stamped files.

### Format 7: No metadata

```
oaknut-zip extract --meta-format none NetUtils.zip
```

Extracts files only, discarding all Acorn metadata. Equivalent to a standard
`unzip`.

## Metadata sources in ZIP files

oaknut-zip reads Acorn metadata from three sources within ZIP archives. When
multiple sources are present for a given entry, they are used in priority order:
SparkFS extra fields, then bundled INF sidecar files, then filename encoding.

### SparkFS extra fields (ARC0)

ZIP archives created by [SparkFS](http://www.davidpilling.com/wiki/index.php/SparkFS),
SparkPlug, or RISC OS zip tools embed Acorn metadata as a ZIP extra field with
header ID `0x4341` ("AC") and an "ARC0" signature.

The extra field layout (all values little-endian), as defined in the
[Info-ZIP extra field specification](https://libzip.org/specifications/extrafld.txt)
by [David Pilling](http://www.davidpilling.com/wiki/index.php/SparkFS):

| Offset | Size    | Description                    |
|--------|---------|--------------------------------|
| 0      | 4 bytes | Signature `"ARC0"`             |
| 4      | 4 bytes | Load address (uint32)          |
| 8      | 4 bytes | Execution address (uint32)     |
| 12     | 4 bytes | File attributes (uint32)       |
| 16     | 4 bytes | Reserved (zero)                |

This is the most reliable metadata source, as it is embedded in the ZIP
structure itself and survives transfers between any systems.

#### A note on the 32-bit attributes field

Although the attributes field is stored as a 32-bit little-endian word,
the [Info-ZIP specification](https://libzip.org/specifications/extrafld.txt)
and [David Pilling's own SparkFS source](https://www.davidpilling.com/software/zipinfo.txt)
define meaning only for the low 8 bits --- the standard RISC OS access
byte (`R`, `W`, `L`, public `R`, public `W`, plus a couple of reserved
bits). Bits 8-31 have no documented semantics. Genuine RISC OS tooling
(SparkFS, SparkPlug) writes zero in the upper 24 bits, and archives
with host OS `13` (Acorn RISC OS) in the ZIP "version made by" field
are clean.

In the wild, however, some non-RISC-OS producers leave junk in the
upper 24 bits of the word --- stale memory, tool-private state, or
similar. The archives in `tests/fixtures/` sourced from
[MDFS](https://mdfs.net/) are in this shape: the access byte in bits
0-7 is correct and self-consistent across archives, but bits 8-31 are
effectively random. oaknut-zip masks the Attr field to its low 8 bits
when populating metadata, so the access byte written to `.inf`
sidecars and extended attributes is always a valid two-digit hex
value.

### Bundled INF sidecar files

Some ZIP archives include `.inf` sidecar files alongside the data files they
describe. oaknut-zip detects and parses these automatically, supporting both
flavours:

- **Traditional INF** (`filename load exec length [access]`) --- reported
  as source `inf-trad` in the list and info commands.
- **PiEconetBridge INF** (`owner load exec perm`) --- reported as source
  `inf-pieb`.

When extracting, bundled `.inf` files are consumed as a metadata source rather
than extracted as separate files. The metadata is then written in whatever
output format was requested (inf-trad, inf-pieb, xattr-acorn, xattr-pieb,
etc.). This allows, for example, converting a PiEconetBridge archive to
`user.acorn.*` extended attributes in a single step.

With `--meta-format none`, bundled `.inf` files are extracted as-is (no
metadata is consumed).

### Unix filename encoding

Because Unix filesystems have no way to store Acorn load/exec addresses
natively, a [convention](https://www.riscos.info/index.php/RISC_OS_Filename_Translation)
exists for encoding the RISC OS filetype into the filename itself as a
comma-separated hex suffix:

| Pattern                         | Example                    | Meaning                     |
|---------------------------------|----------------------------|-----------------------------|
| `filename,xxx`                  | `HELLO,ffb`                | RISC OS filetype `FFB`      |

oaknut-zip also supports two additional forms that encode full load and exec
addresses for files that are not filetype-stamped:

| Pattern                         | Example                    | Meaning                     |
|---------------------------------|----------------------------|-----------------------------|
| `filename,llllllll,eeeeeeee`    | `PROG,ffff0e10,0000801f`   | Load and exec addresses     |
| `filename,load-exec`            | `PROG,1900-801f`           | Load and exec (MOS/SparkFS) |

The first form is used by
[python-zipinfo-riscos](https://github.com/gerph/python-zipinfo-riscos)
and requires exactly 8 hex digits per address. The second form, documented
in the [BeebWiki INF file format](https://beebwiki.mdfs.net/INF_file_format)
specification, uses variable-width hex digits separated by a dash and is the
convention used by MOS and SparkFS.

oaknut-zip strips these suffixes from output filenames during extraction.
Use `--no-decode-filenames` to preserve the encoded filenames as-is.

## RISC OS filetype encoding

When the top 12 bits of a load address are `0xFFF`, the address does not
represent a literal memory location. Instead, bits 8--19 encode a
[RISC OS filetype](https://en.wikipedia.org/wiki/List_of_RISC_OS_filetypes):

```
Load address: FFFtttxx
                 ^^^
                 filetype (3 hex digits)
```

Example RISC OS filetypes:

| Type  | Name       | Description                               |
|-------|------------|-------------------------------------------|
| `FF9` | Sprite     | Sprite or saved screen                    |
| `FFA` | Module     | Relocatable module                        |
| `FFB` | BASIC      | Tokenised BASIC program                   |
| `FFC` | Utility    | Position independent code                 |
| `FFD` | Data       | Arbitrary data                            |
| `FFE` | Command    | Command (Exec) file                       |
| `FFF` | Text       | Plain ASCII text with LF newlines         |

## RISC OS file attribute bits

The attribute byte encodes access permissions following the RISC OS
convention (see RISC OS PRM volume 2, FileSwitch attributes):

| Bit | Mask   | Meaning          |
|-----|--------|------------------|
| 0   | `0x01` | Owner readable   |
| 1   | `0x02` | Owner writable   |
| 3   | `0x08` | Locked (L)       |
| 4   | `0x10` | Public readable  |
| 5   | `0x20` | Public writable  |

A file with attributes `0x03` is owner-readable and owner-writable (WR/).
A value of `0x15` adds public read access (R/R), which is the default
for files served by PiEconetBridge.

## Development

After cloning, install the pre-commit hooks:

```
uv run --group dev pre-commit install
```

### Running the tests

```
uv run --group test pytest tests/ -v
```

The test suite covers all parsing, formatting, and extraction logic,
including integration tests against six real-world ZIP fixtures:

- **NetUtils.zip** --- Econet utilities from [MDFS](https://mdfs.net/Apps/Networking/),
  with SparkFS/ARC0 extra fields. This is the archive that motivated the project.
- **NetUtilB.zip** --- A second Econet utilities pack, also with SparkFS metadata.
- **MASTER.zip** --- BBC Master utilities from
  [MDFS](https://mdfs.net/Mirror/Archive/SJ/MDFS/MASTER.zip), 344 files with
  SparkFS metadata and 36 distinct filetypes.
- **sweh_econet_system.zip** --- PiEconetBridge system files from
  [sweh](https://sweh.spuddy.org/tmp/econet-bridge/), containing bundled
  PiEconetBridge-format `.inf` sidecar files (no SparkFS extra fields).
- **testdir-unix.zip** --- Test archive from
  [python-zipinfo-riscos](https://github.com/gerph/python-zipinfo-riscos),
  with Unix filename encoding (`,xxx` suffixes).
- **testdir-ro.zip** --- The same content as testdir-unix.zip but with SparkFS
  extra fields instead of filename encoding.

## References

### Metadata format specifications

- [INF file format](https://beebwiki.mdfs.net/INF_file_format) ---
  BeebWiki specification for the Acorn `.inf` sidecar format.
- [ZIP extra field registry](https://libzip.org/specifications/extrafld.txt) ---
  Known ZIP extra field types, including the Acorn/SparkFS entry (`0x4341`).
- [RISC OS filetype](http://justsolve.archiveteam.org/wiki/RISC_OS_filetype) ---
  How RISC OS encodes filetypes in load addresses.
- [ZipToInf documentation](https://mdfs.net/Apps/Archivers/ZipTools/ZipToInf.txt) ---
  J.G.Harston's ZipToInf utility and INF format description.
- [RISC OS filename translation](https://www.riscos.info/index.php/RISC_OS_Filename_Translation) ---
  Documents the `,xxx` filetype suffix convention used on Unix filesystems.
- [INF file format](https://mdfs.net/Docs/Comp/BBC/FileFormat/INFfile) ---
  J.G.Harston's detailed INF file format specification.

### Tools and related projects

- [PiEconetBridge](https://github.com/cr12925/PiEconetBridge) ---
  Econet bridge for Raspberry Pi; defines the `user.econet_*` xattr convention
  and the alternative `.inf` format (`owner load exec perm`).
- [python-zipinfo-riscos](https://github.com/gerph/python-zipinfo-riscos) ---
  Python library for reading/writing RISC OS extra fields in ZIP archives;
  source of the `,llllllll,eeeeeeee` load/exec filename encoding convention.
- [ZipTools](https://mdfs.net/Apps/Archivers/ZipTools/) ---
  J.G.Harston's suite of Acorn-aware ZIP utilities including ZipToInf.
- [SparkFS](http://www.davidpilling.com/wiki/index.php/SparkFS) ---
  David Pilling's RISC OS filing system for ZIP/Arc/Spark archives;
  originator of the ARC0 extra field format.

### Forum discussion

- [Stardot forum thread](https://stardot.org.uk/forums/viewtopic.php?p=478751#p478751) ---
  Discussion of the metadata-loss problem that motivated this tool.
- [INF format discussion](https://www.stardot.org.uk/forums/viewtopic.php?t=31577) ---
  Community discussion on INF format variants and standardisation.
