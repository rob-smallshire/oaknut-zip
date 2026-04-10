"""Click command-line interface for oaknut-zip."""

from __future__ import annotations

from pathlib import Path

import click

from oaknut_file import MetaFormat, format_access_text

from . import __version__
from .api import archive_info, extract_archive, list_archive
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


@click.group()
@click.version_option(version=__version__, prog_name="oaknut-zip")
def cli() -> None:
    """Work with ZIP files containing Acorn computer metadata."""


@cli.command()
@click.argument("zipfile_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-d",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (default: ZIP filename without extension).",
)
@click.option("-v", "--verbose", is_flag=True, help="Show extraction progress.")
@click.option(
    "--meta-format",
    type=click.Choice(
        ["inf-trad", "inf-pieb", "xattr-acorn", "xattr-pieb",
         "filename-riscos", "filename-mos", "none"],
        case_sensitive=False,
    ),
    default="inf-trad",
    help="Metadata format: inf-trad, inf-pieb, xattr-acorn, xattr-pieb, "
         "filename-riscos, filename-mos, or none.",
)
@click.option(
    "--no-decode-filenames",
    is_flag=True,
    help="Do not decode metadata from filename suffixes (,xxx or ,load,exec).",
)
@click.option(
    "--owner",
    type=int,
    default=0,
    help="Econet owner ID for inf-pieb and xattr-pieb outputs (default: 0 = SYST).",
)
def extract(
    zipfile_path: Path,
    output_dir: Path | None,
    verbose: bool,
    meta_format: str,
    no_decode_filenames: bool,
    owner: int,
) -> None:
    """Extract a ZIP file, preserving Acorn metadata."""

    if output_dir is None:
        output_dir = Path(zipfile_path.stem)

    resolved_meta_format: MetaFormat | None
    if meta_format == "none":
        resolved_meta_format = None
    else:
        resolved_meta_format = MetaFormat(meta_format)

    extract_archive(
        zipfile_path,
        output_dir,
        verbose=verbose,
        meta_format=resolved_meta_format,
        decode_filenames=not no_decode_filenames,
        owner=owner,
    )


def _tree_display_names(entries: list[dict]) -> list[str]:
    """Build tree-formatted display names for archive entries.

    Converts full paths into leaf names with Unicode box-drawing tree
    prefixes (├──, └──, │) based on the directory hierarchy.
    """
    paths = [e[FILENAME_KEY].rstrip("/") for e in entries]
    n = len(paths)
    names: list[str] = []

    for i in range(n):
        parts = paths[i].split("/")
        depth = len(parts) - 1
        leaf = parts[-1]

        if depth == 0:
            names.append(leaf)
            continue

        prefixes: list[str] = []
        for d in range(1, depth + 1):
            parent_path = "/".join(parts[:d])
            our_node = parts[d]
            parent_prefix = parent_path + "/"

            is_last = True
            for j in range(i + 1, n):
                pj = paths[j]
                if not pj.startswith(parent_prefix):
                    break
                pj_component = pj[len(parent_prefix):].split("/")[0]
                if pj_component != our_node:
                    is_last = False
                    break

            if d == depth:
                prefixes.append("└── " if is_last else "├── ")
            else:
                prefixes.append("    " if is_last else "│   ")

        names.append("".join(prefixes) + leaf)

    return names


@cli.command(name="list")
@click.argument("zipfile_path", type=click.Path(exists=True, path_type=Path))
def list_cmd(zipfile_path: Path) -> None:
    """List ZIP contents showing Acorn metadata."""
    from rich.console import Console
    from rich.table import Table

    entries = list_archive(zipfile_path)
    tree_names = _tree_display_names(entries)

    table = Table(title=zipfile_path.name)
    table.add_column("Filename", style="cyan", no_wrap=True)
    table.add_column("Load", justify="right", style="green", no_wrap=True)
    table.add_column("Exec", justify="right", style="green", no_wrap=True)
    table.add_column("Length", justify="right", no_wrap=True)
    table.add_column("Attr", justify="right", style="yellow", no_wrap=True)
    table.add_column("Type", justify="right", style="magenta", no_wrap=True)
    table.add_column("Source", style="dim", no_wrap=True)

    for entry, display_name in zip(entries, tree_names):
        if entry[IS_DIR_KEY]:
            if entry[LOAD_ADDR_KEY] is not None:
                ft = entry[FILETYPE_KEY]
                ft_str = f"{ft:03X}" if ft is not None else ""
                attr_str = format_access_text(entry[ATTR_KEY]) if entry[ATTR_KEY] is not None else ""
                table.add_row(
                    display_name,
                    f"{entry[LOAD_ADDR_KEY]:08X}",
                    f"{entry[EXEC_ADDR_KEY]:08X}",
                    "",
                    attr_str,
                    ft_str,
                    entry[SOURCE_KEY],
                )
            else:
                table.add_row(display_name, "", "", "", "", "", "")
            continue

        if entry[LOAD_ADDR_KEY] is not None:
            ft = entry[FILETYPE_KEY]
            ft_str = f"{ft:03X}" if ft is not None else ""
            attr_str = format_access_text(entry[ATTR_KEY]) if entry[ATTR_KEY] is not None else ""
            table.add_row(
                display_name,
                f"{entry[LOAD_ADDR_KEY]:08X}",
                f"{entry[EXEC_ADDR_KEY]:08X}",
                f"{entry[FILE_SIZE_KEY]:08X}",
                attr_str,
                ft_str,
                entry[SOURCE_KEY],
            )
        else:
            table.add_row(
                display_name,
                "",
                "",
                f"{entry[FILE_SIZE_KEY]:08X}",
                "",
                "",
                "",
            )

    Console().print(table)


@cli.command()
@click.argument("zipfile_path", type=click.Path(exists=True, path_type=Path))
def info(zipfile_path: Path) -> None:
    """Show summary of Acorn metadata in a ZIP file."""

    stats = archive_info(zipfile_path)

    click.echo(f"Archive:    {stats[FILENAME_KEY]}")
    click.echo(f"Files:      {stats[TOTAL_KEY]}")
    click.echo(f"Dirs:       {stats[DIRS_KEY]}")
    click.echo(f"SparkFS:    {stats[SPARKFS_COUNT_KEY]} files with ARC0 extra fields")
    click.echo(f"inf-trad:   {stats[INF_COUNT_KEY]} files with bundled traditional INF")
    click.echo(f"inf-pieb:   {stats[PIEB_INF_COUNT_KEY]} files with bundled PiEconetBridge INF")
    click.echo(f"Filename:   {stats[FILENAME_COUNT_KEY]} files with encoded filenames")
    click.echo(f"Plain:      {stats[PLAIN_COUNT_KEY]} files without Acorn metadata")

    filetypes = stats[FILETYPES_KEY]
    if filetypes:
        click.echo(f"Filetypes:  {len(filetypes)} distinct")
        for ft in sorted(filetypes):
            click.echo(f"  {ft:03X}: {filetypes[ft]} files")


def main() -> None:
    cli()
