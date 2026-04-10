"""Public API for extracting ZIP files with Acorn metadata."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import click

from .formatting import (
    build_filename_suffix,
    build_mos_filename_suffix,
    format_pieb_inf_line,
    format_trad_inf_line,
    write_econet_xattrs,
)
from oaknut_file import write_acorn_xattrs
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
    SOURCE_DIR,
    SOURCE_FILENAME,
    SOURCE_INF_PIEB,
    SOURCE_INF_TRAD,
    SOURCE_KEY,
    SOURCE_SPARKFS,
    SPARKFS_COUNT_KEY,
    TOTAL_KEY,
    AcornMeta,
    MetaFormat,
)
from .parsing import build_inf_index, resolve_metadata


def sanitise_extract_path(base_dirpath: Path, member_path: str) -> Path:
    """Sanitise a ZIP member path to prevent directory traversal.

    Strips ``..``, ``/``, and ``\\`` components from the member path and
    resolves the result relative to *base_dirpath*.

    Args:
        base_dirpath: The root directory that all extracted paths must
            fall within.
        member_path: The raw path from the ZIP entry.

    Returns:
        A safe path under *base_dirpath*.

    Raises:
        ValueError: If the resolved path escapes *base_dirpath*.
    """
    parts = Path(member_path).parts
    safe_parts = [p for p in parts if p not in ("..", "/", "\\")]
    if not safe_parts:
        safe_parts = ["_"]
    result = base_dirpath.joinpath(*safe_parts)
    result.resolve().relative_to(base_dirpath.resolve())
    return result


def extract_member(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    output_dirpath: Path,
    *,
    verbose: bool = False,
    meta_format: MetaFormat | None = MetaFormat.INF_TRAD,
    decode_filenames: bool = True,
    owner: int = 0,
    inf_index: dict[str, tuple[str, AcornMeta]] | None = None,
) -> None:
    """Extract a single ZIP member, optionally writing metadata.

    Writes the member's data to *output_dirpath* and, when Acorn metadata
    is available, writes it in the requested *meta_format*.

    Args:
        zf: An open ZipFile to read from.
        info: The ZipInfo entry to extract.
        output_dirpath: Directory to extract into.
        verbose: Print extraction progress to stdout.
        meta_format: Output metadata format, or ``None`` to skip metadata.
        decode_filenames: Strip encoded metadata suffixes from filenames.
        owner: Econet owner ID for inf-pieb and xattr formats.
        inf_index: Pre-built index of bundled ``.inf`` metadata, as
            returned by :func:`~oaknut_zip.parsing.build_inf_index`.
    """

    if info.is_dir():
        dirpath = sanitise_extract_path(output_dirpath, info.filename)
        dirpath.mkdir(parents=True, exist_ok=True)
        if verbose:
            click.echo(f"  mkdir: {dirpath.relative_to(output_dirpath)}")
        return

    metadata_source, output_filename, meta = resolve_metadata(
        info, decode_filenames=decode_filenames, inf_index=inf_index
    )

    output_filepath = sanitise_extract_path(output_dirpath, output_filename)
    output_filepath.parent.mkdir(parents=True, exist_ok=True)

    data = zf.read(info.filename)
    output_filepath.write_bytes(data)

    if verbose:
        rel = output_filepath.relative_to(output_dirpath)
        type_info = ""
        if meta and meta.has_metadata:
            type_info = f" [{metadata_source}]"
            ft = meta.infer_filetype()
            if ft is not None:
                type_info += f" type={ft:03X}"
        click.echo(f"  extract: {rel}{type_info}")

    if meta_format is None or not (meta and meta.has_metadata):
        return

    if meta_format == MetaFormat.XATTR_PIEB:
        write_econet_xattrs(
            output_filepath,
            load_addr=meta.load_addr,
            exec_addr=meta.exec_addr,
            attr=meta.attr,
            owner=owner,
        )
        if verbose:
            rel = output_filepath.relative_to(output_dirpath)
            click.echo(f"    xattr-pieb: {rel}")
    elif meta_format == MetaFormat.XATTR_ACORN:
        write_acorn_xattrs(
            output_filepath,
            load_addr=meta.load_addr,
            exec_addr=meta.exec_addr,
            attr=meta.attr,
        )
        if verbose:
            rel = output_filepath.relative_to(output_dirpath)
            click.echo(f"    xattr-acorn: {rel}")
    elif meta_format in (MetaFormat.FILENAME_RISCOS, MetaFormat.FILENAME_MOS):
        if meta_format == MetaFormat.FILENAME_MOS:
            suffix = build_mos_filename_suffix(meta)
        else:
            suffix = build_filename_suffix(meta)
        if not output_filepath.name.endswith(suffix):
            encoded_filepath = output_filepath.with_name(
                output_filepath.name + suffix
            )
            output_filepath.rename(encoded_filepath)
            if verbose:
                rel = encoded_filepath.relative_to(output_dirpath)
                click.echo(f"    renamed: {rel}")
    else:
        leaf_name = output_filepath.name

        if meta_format == MetaFormat.INF_TRAD:
            inf_line = format_trad_inf_line(
                filename=leaf_name,
                load_addr=meta.load_addr,
                exec_addr=meta.exec_addr,
                length=len(data),
                attr=meta.attr,
            )
        else:
            inf_line = format_pieb_inf_line(
                load_addr=meta.load_addr,
                exec_addr=meta.exec_addr,
                attr=meta.attr,
                owner=owner,
            )

        inf_filepath = output_filepath.with_suffix(
            output_filepath.suffix + ".inf"
        )
        inf_filepath.write_text(inf_line + "\n", encoding="ascii")

        if verbose:
            inf_rel = inf_filepath.relative_to(output_dirpath)
            click.echo(f"     inf: {inf_rel}")


def extract_archive(
    zipfile_path: Path,
    output_dirpath: Path,
    *,
    verbose: bool = False,
    meta_format: MetaFormat | None = MetaFormat.INF_TRAD,
    decode_filenames: bool = True,
    owner: int = 0,
) -> None:
    """Extract a ZIP file, preserving Acorn metadata.

    Args:
        zipfile_path: Path to the ZIP file.
        output_dirpath: Directory to extract into.
        verbose: Print extraction progress.
        meta_format: Output metadata format, or None for raw extraction.
        decode_filenames: Decode metadata from filename suffixes.
        owner: Econet owner ID for inf-pieb and xattr formats.

    Raises:
        click.ClickException: If the file is not a valid ZIP or xattr is
            requested on Windows.
    """
    if not zipfile.is_zipfile(zipfile_path):
        raise click.ClickException(f"{zipfile_path} is not a valid ZIP file")

    if meta_format in (MetaFormat.XATTR_ACORN, MetaFormat.XATTR_PIEB) and sys.platform == "win32":
        raise click.ClickException(
            "Extended attributes are not supported on Windows. "
            "Use --meta-format inf-trad, inf-pieb, or filename-riscos instead."
        )

    output_dirpath.mkdir(parents=True, exist_ok=True)

    if verbose:
        click.echo(f"Extracting {zipfile_path.name} -> {output_dirpath}")

    with zipfile.ZipFile(zipfile_path, "r") as zf:
        if meta_format is not None:
            inf_index, consumed_inf_filenames = build_inf_index(zf)
        else:
            inf_index, consumed_inf_filenames = None, set()

        for info in zf.infolist():
            if info.filename in consumed_inf_filenames:
                if verbose:
                    click.echo(f"  skip: {info.filename} (metadata consumed)")
                continue
            extract_member(
                zf,
                info,
                output_dirpath,
                verbose=verbose,
                meta_format=meta_format,
                decode_filenames=decode_filenames,
                owner=owner,
                inf_index=inf_index,
            )


def list_archive(
    zipfile_path: Path,
) -> list[dict]:
    """List ZIP contents with resolved Acorn metadata.

    Args:
        zipfile_path: Path to the ZIP file.

    Returns:
        A list of dicts, one per entry (excluding consumed ``.inf``
        sidecars), with keys: ``filename``, ``is_dir``, ``file_size``,
        ``load_addr``, ``exec_addr``, ``attr``, ``filetype``, ``source``.

    Raises:
        click.ClickException: If the file is not a valid ZIP.
    """
    if not zipfile.is_zipfile(zipfile_path):
        raise click.ClickException(f"{zipfile_path} is not a valid ZIP file")

    entries = []
    with zipfile.ZipFile(zipfile_path, "r") as zf:
        inf_index, consumed_inf_filenames = build_inf_index(zf)

        for info in zf.infolist():
            if info.filename in consumed_inf_filenames:
                continue
            if info.is_dir():
                entry = {
                    FILENAME_KEY: info.filename,
                    IS_DIR_KEY: True,
                    LOAD_ADDR_KEY: None,
                    EXEC_ADDR_KEY: None,
                    FILE_SIZE_KEY: 0,
                    ATTR_KEY: None,
                    FILETYPE_KEY: None,
                    SOURCE_KEY: SOURCE_DIR,
                }
                inf_entry = inf_index.get(info.filename)
                if inf_entry is not None:
                    source_label, meta = inf_entry
                    entry[SOURCE_KEY] = source_label
                    entry[LOAD_ADDR_KEY] = meta.load_addr
                    entry[EXEC_ADDR_KEY] = meta.exec_addr
                    entry[ATTR_KEY] = meta.attr
                    entry[FILETYPE_KEY] = meta.infer_filetype()
                entries.append(entry)
                continue

            metadata_source, clean_name, meta = resolve_metadata(
                info, inf_index=inf_index
            )

            entry = {
                FILENAME_KEY: clean_name,
                IS_DIR_KEY: False,
                FILE_SIZE_KEY: info.file_size,
                LOAD_ADDR_KEY: None,
                EXEC_ADDR_KEY: None,
                ATTR_KEY: None,
                FILETYPE_KEY: None,
                SOURCE_KEY: metadata_source or "",
            }
            if meta and meta.has_metadata:
                entry[LOAD_ADDR_KEY] = meta.load_addr
                entry[EXEC_ADDR_KEY] = meta.exec_addr
                entry[ATTR_KEY] = meta.attr
                entry[FILETYPE_KEY] = meta.infer_filetype()

            entries.append(entry)

    return entries


def archive_info(
    zipfile_path: Path,
) -> dict:
    """Return summary statistics of Acorn metadata in a ZIP file.

    Args:
        zipfile_path: Path to the ZIP file.

    Returns:
        A dict with keys: ``filename``, ``total``, ``dirs``,
        ``sparkfs_count``, ``inf_count``, ``pieb_inf_count``,
        ``filename_count``, ``plain_count``, ``filetypes`` (a dict
        mapping filetype ints to counts).

    Raises:
        click.ClickException: If the file is not a valid ZIP.
    """
    if not zipfile.is_zipfile(zipfile_path):
        raise click.ClickException(f"{zipfile_path} is not a valid ZIP file")

    with zipfile.ZipFile(zipfile_path, "r") as zf:
        inf_index, consumed_inf_filenames = build_inf_index(zf)

        total = 0
        dirs = 0
        sparkfs_count = 0
        inf_count = 0
        pieb_inf_count = 0
        filename_count = 0
        plain_count = 0
        filetypes: dict[int, int] = {}

        for entry in zf.infolist():
            if entry.filename in consumed_inf_filenames:
                continue
            if entry.is_dir():
                dirs += 1
                continue

            total += 1
            metadata_source, _, meta = resolve_metadata(
                entry, inf_index=inf_index
            )

            if metadata_source == SOURCE_SPARKFS:
                sparkfs_count += 1
            elif metadata_source == SOURCE_INF_TRAD:
                inf_count += 1
            elif metadata_source == SOURCE_INF_PIEB:
                pieb_inf_count += 1
            elif metadata_source == SOURCE_FILENAME:
                filename_count += 1
            else:
                plain_count += 1

            if meta and meta.has_metadata:
                ft = meta.infer_filetype()
                if ft is not None:
                    filetypes[ft] = filetypes.get(ft, 0) + 1

    return {
        FILENAME_KEY: zipfile_path.name,
        TOTAL_KEY: total,
        DIRS_KEY: dirs,
        SPARKFS_COUNT_KEY: sparkfs_count,
        INF_COUNT_KEY: inf_count,
        PIEB_INF_COUNT_KEY: pieb_inf_count,
        FILENAME_COUNT_KEY: filename_count,
        PLAIN_COUNT_KEY: plain_count,
        FILETYPES_KEY: filetypes,
    }
