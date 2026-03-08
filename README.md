# nutzip

A standalone Python script for extracting ZIP files containing
[Acorn computer](https://en.wikipedia.org/wiki/Acorn_Computers) metadata.

Standard unzip tools silently discard the load addresses, execution addresses,
and file attributes that Acorn systems (BBC Micro, Master, Archimedes, RISC OS
machines) store in ZIP archives. nutzip preserves this metadata, writing it out
in your choice of three formats.

## The problem

When software for Acorn 8-bit and 32-bit systems is distributed as ZIP files,
the archives often contain platform-specific metadata embedded using mechanisms
that non-Acorn unzip tools ignore:

- **SparkFS extra fields** in the ZIP structure itself, carrying load/exec
  addresses and RISC OS file attributes.
- **NFS filename encoding**, where metadata is appended to filenames as comma-
  separated hex suffixes.

Extracting these archives with `unzip` or Python's `zipfile` module on Linux or
macOS produces the raw file data but loses all the Acorn metadata. For 6502 or
ARM executables, this means you no longer know where in memory a program should
be loaded or where execution should begin. For a PiEconetBridge fileserver, the
files become unserviceable without their attributes.

nutzip reads both metadata sources from the ZIP and writes them out in a format
your target system can consume.

## Prerequisites

nutzip requires only [`uv`](https://docs.astral.sh/uv/) and a Python 3.10+
installation. `uv` handles dependency resolution and virtual environments
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

Once `uv` is available on your PATH, nutzip is ready to run. The first
invocation will fetch the required Python packages (`click`, `rich`, and
`xattr`) into an isolated cache; subsequent runs start instantly.

## Usage

nutzip is a single-file [PEP 723](https://peps.python.org/pep-0723/) script
with an embedded dependency table. Run it directly:

```
./nutzip.py <command> [options]
```

Or explicitly via uv:

```
uv run nutzip.py <command> [options]
```

### Commands

```
$ ./nutzip.py --help
Usage: nutzip.py [OPTIONS] COMMAND [ARGS]...

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
$ ./nutzip.py list NetUtils.zip
                               NetUtils.zip                                
┏━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ Filename   ┃     Load ┃     Exec ┃   Length ┃     Attr ┃ Type ┃ Source  ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━╇━━━━━━━━━┩
│ Free       │ FFFF0E10 │ FFFF0E10 │ 000001E6 │  C18325D │  F0E │ sparkfs │
│ FSList     │ FFFF0900 │ FFFF0900 │ 00000200 │ 1415365D │  F09 │ sparkfs │
│ PSList     │ FFFF0900 │ FFFF0900 │ 000001B5 │  B861C5D │  F09 │ sparkfs │
│ Notify     │ FFFF0E23 │ FFFF0E23 │ 0000012A │  C6B1E5D │  F0E │ sparkfs │
│ Remote     │ FFFF0E10 │ FFFF0E10 │ 000001ED │ 1347085D │  F0E │ sparkfs │
│ Servers    │ FFFF0900 │ FFFF091A │ 000001CF │ 17162C5D │  F09 │ sparkfs │
│ SetStation │ FFFFDD00 │ FFFFDD00 │ 00000200 │ 1761575D │  FDD │ sparkfs │
│ Stations   │ FFFF08D5 │ FFFF08E1 │ 0000022B │ 13615A57 │  F08 │ sparkfs │
│ SJMon      │ FFFF1B00 │ FFFF1B00 │ 00000D7E │   F6040D │  F1B │ sparkfs │
│ Users      │ FFFF0E23 │ FFFF0E23 │ 00000139 │   15355D │  F0E │ sparkfs │
│ View       │ FFFF0900 │ FFFF0904 │ 000001FF │ 135A115D │  F09 │ sparkfs │
│ ReadMe     │ FFFFFF52 │ 2FEEAFD0 │ 00000255 │  BEB2A55 │  FFF │ sparkfs │
└────────────┴──────────┴──────────┴──────────┴──────────┴──────┴─────────┘
```

The **Source** column shows where the metadata was found: `sparkfs` for
SparkFS/ARC0 extra fields, or `nfs` for NFS-encoded filenames. The **Type**
column shows the RISC OS filetype extracted from the load address (when the top
12 bits are `0xFFF`).

### info --- summary statistics

```
$ ./nutzip.py info NetUtils.zip
Archive:    NetUtils.zip
Files:      12
Dirs:       0
SparkFS:    12 files with ARC0 extra fields
NFS:        0 files with NFS-encoded filenames
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
$ ./nutzip.py extract --help
Usage: nutzip.py extract [OPTIONS] ZIPFILE_PATH

  Extract a ZIP file, preserving Acorn metadata.

Options:
  -d, --output-dir PATH           Output directory (default: ZIP filename
                                  without extension).
  -v, --verbose                   Show extraction progress.
  --meta-format [acorn|pibridge|xattr|none]
                                  Metadata format: acorn INF (standard),
                                  pibridge INF, xattr (extended attributes),
                                  or none.
  --no-nfs                        Do not decode NFS filename encoding (,xxx or
                                  ,load,exec suffixes).
  --owner INTEGER                 Econet owner ID for PiEconetBridge INF files
                                  (default: 0 = SYST).
  --help                          Show this message and exit.
```

nutzip supports three output metadata formats, selected with `--meta-format`.

### Format 1: Standard Acorn INF (default)

```
./nutzip.py extract NetUtils.zip
```

Each extracted file gets a companion `.inf` sidecar file:

```
$ cat SetStation.inf
SetStation  FFFFDD00 FFFFDD00 00000200 1761575D

$ cat ReadMe.inf
ReadMe      FFFFFF52 2FEEAFD0 00000255 BEB2A55
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
./nutzip.py extract --meta-format pibridge NetUtils.zip
```

Writes `.inf` sidecar files in the format used by
[PiEconetBridge](https://github.com/cr12925/PiEconetBridge):

```
$ cat SetStation.inf
0 ffffdd00 ffffdd00 1761575d

$ cat ReadMe.inf
0 ffffff52 2feeafd0 beb2a55
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

### Format 3: Extended attributes (xattr)

```
./nutzip.py extract --meta-format xattr NetUtils.zip
```

Writes metadata directly into the filesystem's extended attributes, with no
sidecar files:

```
$ xattr -l SetStation
user.econet_exec: FFFFDD00
user.econet_load: FFFFDD00
user.econet_owner: 0000
user.econet_perm: 1761575D

$ xattr -l ReadMe
user.econet_exec: 2FEEAFD0
user.econet_load: FFFFFF52
user.econet_owner: 0000
user.econet_perm: BEB2A55
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
supports extended attributes (ext4, XFS, HFS+, APFS). PiEconetBridge reads
xattrs in preference to `.inf` files when both are present.

### Format 4: No metadata

```
./nutzip.py extract --meta-format none NetUtils.zip
```

Extracts files only, discarding all Acorn metadata. Equivalent to a standard
`unzip`.

## Metadata sources in ZIP files

nutzip reads Acorn metadata from two sources within ZIP archives. When both are
present for a given entry, SparkFS extra fields take priority.

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

### Unix filename encoding

Because Unix filesystems have no way to store Acorn load/exec addresses
natively, a convention exists for encoding this metadata into the filename
itself using comma-separated hex suffixes:

| Pattern                         | Example                    | Meaning                     |
|---------------------------------|----------------------------|-----------------------------|
| `filename,xxx`                  | `HELLO,ffb`                | RISC OS filetype `FFB`      |
| `filename,llllllll,eeeeeeee`    | `PROG,ffff0e10,0000801f`   | Load and exec addresses     |

nutzip strips these suffixes from output filenames during extraction.
Use `--no-nfs` to preserve the encoded filenames as-is.

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
| `F08` | ViewPS     | View word processor                       |
| `F09` | WiniUtil   | BBC Winchester utility                    |
| `F0E` | EconetUt   | BBC Econet utility                        |
| `F1B` | 65Host     | Usually a BASIC program                   |
| `FDD` | MasterUt   | BBC Master utilities                      |
| `FF9` | Sprite     | Sprite or saved screen                    |
| `FFA` | Module     | Relocatable module                        |
| `FFB` | BASIC      | Tokenised BASIC program                   |
| `FFC` | Utility    | Position independent code                 |
| `FFD` | Data       | Arbitrary data                            |
| `FFE` | Command    | Command (Exec) file                       |
| `FFF` | Text       | Plain ASCII text with LF newlines         |

## Acorn file attribute bits

The attribute byte encodes access permissions in the Acorn filing system
convention:

| Bit | Mask   | Meaning          |
|-----|--------|------------------|
| 0   | `0x01` | Owner writable   |
| 1   | `0x02` | Owner readable   |
| 3   | `0x08` | Locked (DFS `L`) |
| 4   | `0x10` | Public writable  |
| 5   | `0x20` | Public readable  |

A file with attributes `0x03` is owner-readable and owner-writable (WR).
A value of `0x17` adds public read access (WR/R), which is the default
for files served by PiEconetBridge.

## Running the tests

```
uv run --with pytest --with xattr pytest tests/ -v
```

The test suite covers all parsing, formatting, and extraction logic,
including integration tests against three real-world ZIP fixtures:

- **NetUtils.zip** --- Econet utilities from [MDFS](https://mdfs.net/Apps/Networking/),
  with SparkFS/ARC0 extra fields. This is the archive that motivated the project.
- **NetUtilB.zip** --- A second Econet utilities pack, also with SparkFS metadata.
- **sweh_econet_system.zip** --- PiEconetBridge system files from
  [sweh](https://sweh.spuddy.org/tmp/econet-bridge/), containing bundled
  PiEconetBridge-format `.inf` sidecar files (no SparkFS extra fields).

## References

### Metadata format specifications

- [INF file format](https://beebwiki.mdfs.net/INF_file_format) ---
  BeebWiki specification for the standard Acorn `.inf` sidecar format.
- [ZIP extra field registry](https://libzip.org/specifications/extrafld.txt) ---
  Known ZIP extra field types, including the Acorn/SparkFS entry (`0x4341`).
- [RISC OS filetype](http://justsolve.archiveteam.org/wiki/RISC_OS_filetype) ---
  How RISC OS encodes filetypes in load addresses.
- [ZipToInf documentation](https://mdfs.net/Apps/Archivers/ZipTools/ZipToInf.txt) ---
  J.G.Harston's ZipToInf utility and INF format description.

### Tools and related projects

- [PiEconetBridge](https://github.com/cr12925/PiEconetBridge) ---
  Econet bridge for Raspberry Pi; defines the `user.econet_*` xattr convention
  and the alternative `.inf` format (`owner load exec perm`).
- [python-zipinfo-riscos](https://github.com/gerph/python-zipinfo-riscos) ---
  Python library for reading/writing RISC OS extra fields in ZIP archives.
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
