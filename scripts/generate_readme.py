#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "jinja2>=3.0",
#     "xattr>=1.0",
# ]
# ///
"""Generate README.md by running oaknut-zip commands and rendering a Jinja2 template.

Ensures that all command output examples in the README are up-to-date with
the actual behaviour of the oaknut-zip package.

Usage:
    ./scripts/generate_readme.py              # write to README.md
    ./scripts/generate_readme.py --check      # check README.md is up-to-date
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import xattr as xattr_mod
from jinja2 import Environment, FileSystemLoader

REPO_DIRPATH = Path(__file__).resolve().parent.parent
TEMPLATE_DIRPATH = REPO_DIRPATH / "scripts"
TEMPLATE_FILENAME = "README.md.j2"
OUTPUT_FILEPATH = REPO_DIRPATH / "README.md"
FIXTURE_ZIP_FILEPATH = REPO_DIRPATH / "tests" / "fixtures" / "NetUtils.zip"

EXAMPLE_INF_FILES = ["SetStation", "ReadMe"]
EXAMPLE_XATTR_FILES = ["SetStation", "ReadMe"]


def run_oaknut_zip(*args: str) -> str:
    """Run oaknut_zip.py via uv and return stripped stdout."""
    uv = shutil.which("uv")
    if uv is None:
        print("ERROR: uv not found on PATH", file=sys.stderr)
        sys.exit(1)
    result = subprocess.run(
        [uv, "run", "--project", str(REPO_DIRPATH), "oaknut-zip", *args],
        capture_output=True,
        text=True,
        check=True,
        env={
            **__import__("os").environ,
            # Disable rich colour/markup so we get plain text for the table
            "NO_COLOR": "1",
        },
    )
    return result.stdout.rstrip()


def run_shell(cmd: str) -> str:
    """Run a shell command and return stripped stdout."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, check=True,
    )
    return result.stdout.rstrip()


def collect_trad_inf_examples(extract_dirpath: Path) -> str:
    """Read .inf files and format them as cat-style examples."""
    lines = []
    for name in EXAMPLE_INF_FILES:
        inf_filepath = extract_dirpath / f"{name}.inf"
        content = inf_filepath.read_text().rstrip()
        lines.append(f"$ cat {name}.inf")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip()


def collect_pieb_inf_examples(extract_dirpath: Path) -> str:
    lines = []
    for name in EXAMPLE_INF_FILES:
        inf_filepath = extract_dirpath / f"{name}.inf"
        content = inf_filepath.read_text().rstrip()
        lines.append(f"$ cat {name}.inf")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip()


def collect_xattr_examples(extract_dirpath: Path) -> str:
    lines = []
    for name in EXAMPLE_XATTR_FILES:
        filepath = extract_dirpath / name
        x = xattr_mod.xattr(str(filepath))
        lines.append(f"$ xattr -l {name}")
        for attr_name in sorted(x.list()):
            value = x.get(attr_name).decode("ascii")
            lines.append(f"{attr_name}: {value}")
        lines.append("")
    return "\n".join(lines).rstrip()


def generate() -> str:
    """Run all commands and render the README template."""
    fixture = str(FIXTURE_ZIP_FILEPATH)

    help_output = run_oaknut_zip("--help")
    extract_help_output = run_oaknut_zip("extract", "--help")
    list_output = run_oaknut_zip("list", fixture)
    info_output = run_oaknut_zip("info", fixture)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Traditional INF extraction
        trad_dirpath = tmp / "trad"
        run_oaknut_zip("extract", fixture, "-d", str(trad_dirpath))
        trad_inf_examples = collect_trad_inf_examples(trad_dirpath)

        # PiEconetBridge INF extraction
        pieb_dirpath = tmp / "pieb"
        run_oaknut_zip(
            "extract", "--meta-format", "inf-pieb", fixture,
            "-d", str(pieb_dirpath),
        )
        pieb_inf_examples = collect_pieb_inf_examples(pieb_dirpath)

        # xattr extraction (PiEconetBridge namespace)
        xattr_pieb_dirpath = tmp / "xattr-pieb"
        run_oaknut_zip(
            "extract", "--meta-format", "xattr-pieb", fixture,
            "-d", str(xattr_pieb_dirpath),
        )
        xattr_pieb_examples = collect_xattr_examples(xattr_pieb_dirpath)

        # xattr extraction (Acorn namespace)
        xattr_acorn_dirpath = tmp / "xattr-acorn"
        run_oaknut_zip(
            "extract", "--meta-format", "xattr-acorn", fixture,
            "-d", str(xattr_acorn_dirpath),
        )
        xattr_acorn_examples = collect_xattr_examples(xattr_acorn_dirpath)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIRPATH)),
        keep_trailing_newline=True,
    )
    template = env.get_template(TEMPLATE_FILENAME)

    return template.render(
        help_output=help_output,
        extract_help_output=extract_help_output,
        list_output=list_output,
        info_output=info_output,
        trad_inf_examples=trad_inf_examples,
        pieb_inf_examples=pieb_inf_examples,
        xattr_pieb_examples=xattr_pieb_examples,
        xattr_acorn_examples=xattr_acorn_examples,
    )


def main() -> int:
    check_mode = "--check" in sys.argv

    rendered = generate()

    if check_mode:
        if not OUTPUT_FILEPATH.is_file():
            print(f"ERROR: {OUTPUT_FILEPATH} does not exist", file=sys.stderr)
            return 1
        current = OUTPUT_FILEPATH.read_text()
        if current == rendered:
            print("README.md is up-to-date.")
            return 0
        else:
            print(
                "ERROR: README.md is out of date. "
                "Regenerate with: uv run scripts/generate_readme.py",
                file=sys.stderr,
            )
            return 1

    OUTPUT_FILEPATH.write_text(rendered)
    print(f"Wrote {OUTPUT_FILEPATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
