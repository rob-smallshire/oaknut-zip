# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

oaknut-zip is a Python 3.10+ CLI tool and library for extracting ZIP files containing Acorn/RISC OS computer metadata. It preserves load addresses, execution addresses, file attributes, and filetypes that standard unzip tools discard.

## Commands

```bash
# Run the tool
uv run oaknut-zip <command> [options]

# Run all tests
uv run --group test pytest tests/ -v

# Run a single test class or test
uv run --group test pytest tests/test_oaknut_zip.py::TestAcornMeta -v
uv run --group test pytest tests/test_oaknut_zip.py::TestAcornMeta::test_filetype_from_load_addr -v

# Regenerate README from template
uv run scripts/generate_readme.py

# Check README is up-to-date (used in CI)
uv run scripts/generate_readme.py --check
```

## Architecture

Package source is in `src/oaknut_zip/` with this module layout:

- `models.py` — `AcornMeta` dataclass, `MetaFormat` enum, constants (SparkFS header, regex patterns, attribute bits)
- `parsing.py` — Input parsing: SparkFS extra fields, INF sidecar files, filename encoding, `resolve_metadata()`, `build_inf_index()`
- `formatting.py` — Output formatting: INF lines, filename suffixes, xattr writing
- `api.py` — High-level operations: `extract_archive()`, `list_archive()`, `archive_info()`, plus `extract_member()` and `sanitise_extract_path()`
- `cli.py` — Click CLI (`extract`, `list`, `info` subcommands) delegating to `api.py`. Rich is used for table output.
- `__init__.py` — Version and public API re-exports

Tests are in `tests/test_oaknut_zip.py` with real-world ZIP fixtures in `tests/fixtures/`.

### Metadata Sources (priority order)

1. **SparkFS extra fields** — ZIP extra field header ID `0x4341`, signature `ARC0`. Most reliable; embedded in ZIP structure.
2. **Bundled INF sidecar files** — `.inf` files inside the ZIP. Two flavours: traditional (`filename load exec length [access]`) and PiEconetBridge (`owner load exec perm [homeof]`).
3. **Unix filename encoding** — Suffixes like `,xxx` (filetype), `,llllllll,eeeeeeee` (load/exec), or `,load-exec` (MOS style).

When multiple sources exist, higher-priority sources win via `resolve_metadata()`.

### Key encoding detail

A RISC OS filetype is encoded in the load address when the top 12 bits equal `0xFFF`. Bits 8-19 then contain the 3-digit hex filetype.

## Testing

Tests use pytest with Click's `CliRunner` for CLI tests. Integration tests use real-world ZIP fixtures. xattr tests are platform-aware (skipped on non-macOS). CI runs on Ubuntu, macOS, and Windows via GitHub Actions.

## Releasing

Uses `bump-my-version` to update `__version__` in `src/oaknut_zip/__init__.py`, commit, and tag. Pushing the tag triggers the publish workflow.

```bash
uv run --group dev bump-my-version bump patch   # 0.1.0 → 0.1.1
uv run --group dev bump-my-version bump minor   # 0.1.0 → 0.2.0
uv run --group dev bump-my-version bump major   # 0.1.0 → 1.0.0
git push && git push --tags
```
