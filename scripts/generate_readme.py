#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "jinja2>=3.0",
#     "xattr>=1.0",
# ]
# ///
"""Generate README.md by running nutzip commands and rendering a Jinja2 template.

Ensures that all command output examples in the README are up-to-date with
the actual behaviour of nutzip.py.

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
NUTZIP_FILEPATH = REPO_DIRPATH / "nutzip.py"
TEMPLATE_DIRPATH = REPO_DIRPATH / "scripts"
TEMPLATE_FILENAME = "README.md.j2"
OUTPUT_FILEPATH = REPO_DIRPATH / "README.md"
FIXTURE_ZIP_FILEPATH = REPO_DIRPATH / "tests" / "fixtures" / "NetUtils.zip"

EXAMPLE_INF_FILES = ["SetStation", "ReadMe"]
EXAMPLE_XATTR_FILES = ["SetStation", "ReadMe"]


def run_nutzip(*args: str) -> str:
    """Run nutzip.py via uv and return stripped stdout."""
    uv = shutil.which("uv")
    if uv is None:
        print("ERROR: uv not found on PATH", file=sys.stderr)
        sys.exit(1)
    result = subprocess.run(
        [uv, "run", str(NUTZIP_FILEPATH), *args],
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


def collect_acorn_inf_examples(extract_dirpath: Path) -> str:
    """Read .inf files and format them as cat-style examples."""
    lines = []
    for name in EXAMPLE_INF_FILES:
        inf_filepath = extract_dirpath / f"{name}.inf"
        content = inf_filepath.read_text().rstrip()
        lines.append(f"$ cat {name}.inf")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip()


def collect_pibridge_inf_examples(extract_dirpath: Path) -> str:
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

    help_output = run_nutzip("--help")
    extract_help_output = run_nutzip("extract", "--help")
    list_output = run_nutzip("list", fixture)
    info_output = run_nutzip("info", fixture)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Acorn INF extraction
        acorn_dirpath = tmp / "acorn"
        run_nutzip("extract", fixture, "-d", str(acorn_dirpath))
        acorn_inf_examples = collect_acorn_inf_examples(acorn_dirpath)

        # PiEconetBridge INF extraction
        pibridge_dirpath = tmp / "pibridge"
        run_nutzip(
            "extract", "--meta-format", "pibridge", fixture,
            "-d", str(pibridge_dirpath),
        )
        pibridge_inf_examples = collect_pibridge_inf_examples(pibridge_dirpath)

        # xattr extraction
        xattr_dirpath = tmp / "xattr"
        run_nutzip(
            "extract", "--meta-format", "xattr", fixture,
            "-d", str(xattr_dirpath),
        )
        xattr_examples = collect_xattr_examples(xattr_dirpath)

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
        acorn_inf_examples=acorn_inf_examples,
        pibridge_inf_examples=pibridge_inf_examples,
        xattr_examples=xattr_examples,
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
                "Regenerate with: ./scripts/generate_readme.py",
                file=sys.stderr,
            )
            return 1

    OUTPUT_FILEPATH.write_text(rendered)
    print(f"Wrote {OUTPUT_FILEPATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
