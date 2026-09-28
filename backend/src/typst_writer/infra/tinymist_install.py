"""Download and verify Tinymist (Typst language server, used for autocomplete) into the
app's cache folder.

Tinymist ships as one program per platform. Nothing is downloaded without the user asking;
the file must match the SHA-256 pinned in config.toml and is moved into place in one step,
so a failed install never looks installed.

Run `python -m typst_writer.infra.tinymist_install` (or `python scripts/install_tinymist.py`)
to install ahead of time.
"""

import asyncio
import os
import platform
import stat
import sys
import tempfile
from pathlib import Path

import httpx

from typst_writer.config import TinymistConfig, load_config
from typst_writer.infra.app_dirs import cache_dir
from typst_writer.infra.tool_download import InstallError, InstallPhase, Progress, download

# Points at an existing Tinymist program instead of the cache (own installs, tests).
TINYMIST_ENV_VAR = "TYPST_WRITER_TINYMIST"
MAX_BYTES = 300_000_000
DOWNLOAD_MB = 70  # rough size, shown before asking


def platform_key(system: str = sys.platform, machine: str = platform.machine()) -> str | None:
    """The Tinymist release name for this computer, or None if there is no build for it."""
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
        machine.lower()
    )
    os_name = {"win32": "win32", "linux": "linux", "darwin": "darwin"}.get(system)
    if arch is None or os_name is None:
        return None
    return f"{os_name}-{arch}"


def program_name(key: str) -> str:
    return "tinymist.exe" if key.startswith("win32") else "tinymist"


def download_url(config: TinymistConfig, key: str) -> str:
    asset = key + (".exe" if key.startswith("win32") else "")
    return config.url.format(version=config.version, platform=asset)


def install_dir(config: TinymistConfig) -> Path:
    return cache_dir() / f"tinymist-{config.version}"


def find_installation(config: TinymistConfig) -> Path | None:
    """The Tinymist program, if installed."""
    if override := os.environ.get(TINYMIST_ENV_VAR):
        return Path(override) if Path(override).is_file() else None
    key = platform_key()
    if key is None:
        return None
    program = install_dir(config) / program_name(key)
    return program if program.is_file() else None


async def install(
    config: TinymistConfig, progress: Progress, client: httpx.AsyncClient | None = None
) -> Path:
    existing = find_installation(config)
    if existing is not None:
        return existing
    key = platform_key()
    if key is None:
        raise InstallError("Tinymist offers no download for this kind of computer.")
    expected = config.sha256.get(key)
    if not expected:
        raise InstallError(f"config.toml has no [tinymist.sha256] checksum for {key}.")
    target = install_dir(config)
    target.mkdir(parents=True, exist_ok=True)
    program = target / program_name(key)
    with tempfile.TemporaryDirectory(dir=target, prefix=".download-") as tmp:
        file = Path(tmp) / program.name
        url = download_url(config, key)
        await download(url, file, expected, progress, client, tool="Tinymist", max_bytes=MAX_BYTES)
        file.chmod(file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        file.replace(program)
    return program


def main() -> int:
    config = load_config().tinymist
    existing = find_installation(config)
    if existing is not None:
        print(f"Tinymist {config.version} is already installed: {existing}")
        return 0
    shown = -1

    def report(phase: InstallPhase, done: int, total: int | None) -> None:
        nonlocal shown
        if phase == "download" and total:
            percent = done * 100 // total
            if percent >= shown + 5:
                shown = percent
                print(f"Downloading Tinymist {config.version}: {percent} %", flush=True)

    try:
        program = asyncio.run(install(config, report))
    except InstallError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Installed Tinymist {config.version}: {program}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
