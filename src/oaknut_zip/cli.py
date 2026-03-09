"""Click command-line interface for oaknut-zip."""

from __future__ import annotations

from pathlib import Path

import click

from . import __version__
from .api import archive_info, extract_archive, list_archive
from .formatting import format_access
from .models import MetaFormat


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
    type=click.Choice(["inf-trad", "inf-pieb", "xattr", "filename-riscos", "filename-mos", "none"], case_sensitive=False),
    default="inf-trad",
    help="Metadata format: inf-trad, inf-pieb, xattr, filename-riscos, filename-mos, or none.",
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
    help="Econet owner ID for inf-pieb files (default: 0 = SYST).",
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


@cli.command(name="list")
@click.argument("zipfile_path", type=click.Path(exists=True, path_type=Path))
def list_cmd(zipfile_path: Path) -> None:
    """List ZIP contents showing Acorn metadata."""
    from rich.console import Console
    from rich.table import Table

    entries = list_archive(zipfile_path)

    table = Table(title=zipfile_path.name)
    table.add_column("Filename", style="cyan")
    table.add_column("Load", justify="right", style="green")
    table.add_column("Exec", justify="right", style="green")
    table.add_column("Length", justify="right")
    table.add_column("Attr", justify="right", style="yellow")
    table.add_column("Type", justify="right", style="magenta")
    table.add_column("Source", style="dim")

    for entry in entries:
        if entry["is_dir"]:
            table.add_row(entry["filename"], "", "", "", "", "", "dir")
            continue

        if entry["load_addr"] is not None:
            ft = entry["filetype"]
            ft_str = f"{ft:03X}" if ft is not None else ""
            attr_str = format_access(entry["attr"]) if entry["attr"] is not None else ""
            table.add_row(
                entry["filename"],
                f"{entry['load_addr']:08X}",
                f"{entry['exec_addr']:08X}",
                f"{entry['file_size']:08X}",
                attr_str,
                ft_str,
                entry["source"],
            )
        else:
            table.add_row(
                entry["filename"],
                "",
                "",
                f"{entry['file_size']:08X}",
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

    click.echo(f"Archive:    {stats['filename']}")
    click.echo(f"Files:      {stats['total']}")
    click.echo(f"Dirs:       {stats['dirs']}")
    click.echo(f"SparkFS:    {stats['sparkfs_count']} files with ARC0 extra fields")
    click.echo(f"inf-trad:   {stats['inf_count']} files with bundled traditional INF")
    click.echo(f"inf-pieb:   {stats['pieb_inf_count']} files with bundled PiEconetBridge INF")
    click.echo(f"Filename:   {stats['filename_count']} files with encoded filenames")
    click.echo(f"Plain:      {stats['plain_count']} files without Acorn metadata")

    filetypes = stats["filetypes"]
    if filetypes:
        click.echo(f"Filetypes:  {len(filetypes)} distinct")
        for ft in sorted(filetypes):
            click.echo(f"  {ft:03X}: {filetypes[ft]} files")


def main() -> None:
    cli()
