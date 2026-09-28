"""Download, verify and unpack LTeX+ (with its bundled Java) into the app's cache folder.

Nothing is downloaded without the user asking for it. The archive must match the SHA-256
pinned in config.toml before it is unpacked, extraction refuses entries that would land
outside the target folder, and the finished folder is moved into place in one step, so a
cancelled or failed install never looks installed.

Run `python -m typst_writer.infra.ltex_install` (or `python scripts/install_ltex.py`) to
install ahead of time, e.g. before going offline.
"""

import asyncio
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import httpx

from typst_writer.config import LtexConfig, load_config
from typst_writer.infra.app_dirs import cache_dir
from typst_writer.infra.tool_download import InstallError, InstallPhase, Progress, download

# Points at an existing LTeX+ folder instead of the cache (own installs, shared test install).
LTEX_DIR_ENV_VAR = "TYPST_WRITER_LTEX_DIR"
MAIN_CLASS = "org.bsplines.ltexls.LtexLanguageServerLauncher"
MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_UNPACKED_BYTES = 3_000_000_000
DOWNLOAD_MB = 320  # rough size of every platform's archive, shown before asking


def platform_key(system: str = sys.platform, machine: str = platform.machine()) -> str | None:
    """The LTeX+ release name for this computer, or None if there is no build for it."""
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "aarch64", "aarch64": "aarch64"}.get(
        machine.lower()
    )
    os_name = {"win32": "windows", "linux": "linux", "darwin": "mac"}.get(system)
    if arch is None or os_name is None or (os_name == "windows" and arch != "x64"):
        return None
    return f"{os_name}-{arch}"


def archive_extension(key: str) -> str:
    return "zip" if key.startswith("windows") else "tar.gz"


def archive_url(config: LtexConfig, key: str) -> str:
    return config.url.format(version=config.version, platform=key, extension=archive_extension(key))


@dataclass(frozen=True)
class LtexInstallation:
    home: Path
    java: Path

    def command(self) -> list[str]:
        """Start the language server with the bundled Java directly: fixed arguments, no
        shell (the release's bin scripts would need one on Windows)."""
        return [
            str(self.java),
            "-classpath",
            str(self.home / "lib" / "*"),
            "-Dapp.name=ltex-ls-plus",
            f"-Dapp.home={self.home}",
            f"-Dbasedir={self.home}",
            MAIN_CLASS,
        ]


def find_java(home: Path) -> Path | None:
    exe = "java.exe" if sys.platform == "win32" else "java"
    for jdk in sorted(home.glob("jdk-*")):
        for candidate in (jdk / "bin" / exe, jdk / "Contents" / "Home" / "bin" / exe):
            if candidate.is_file():
                return candidate
    return None


def install_dir(config: LtexConfig) -> Path:
    if override := os.environ.get(LTEX_DIR_ENV_VAR):
        return Path(override)
    return cache_dir() / f"ltex-ls-plus-{config.version}"


def find_installation(config: LtexConfig) -> LtexInstallation | None:
    home = install_dir(config)
    java = find_java(home) if (home / "lib").is_dir() else None
    return None if java is None else LtexInstallation(home, java)


async def install(
    config: LtexConfig,
    progress: Progress,
    client: httpx.AsyncClient | None = None,
) -> LtexInstallation:
    existing = find_installation(config)
    if existing is not None:
        return existing
    key = platform_key()
    if key is None:
        raise InstallError("LTeX+ offers no download for this kind of computer.")
    expected = config.sha256.get(key)
    if not expected:
        raise InstallError(f"config.toml has no [ltex.sha256] checksum for {key}.")
    target = install_dir(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".ltex-install-") as tmp:
        archive = Path(tmp) / f"ltex.{archive_extension(key)}"
        url = archive_url(config, key)
        await download(
            url, archive, expected, progress, client, tool="LTeX+", max_bytes=MAX_ARCHIVE_BYTES
        )
        progress("unpack", 0, None)
        unpacked = Path(tmp) / "unpacked"
        await asyncio.to_thread(extract, archive, unpacked)
        folders = [p for p in unpacked.iterdir() if p.is_dir()]
        if len(folders) != 1 or find_java(folders[0]) is None:
            raise InstallError("The LTeX+ archive does not contain the expected folder.")
        if target.exists():
            shutil.rmtree(target)  # an incomplete folder from someone else; not an install
        folders[0].replace(target)
    installation = find_installation(config)
    if installation is None:
        raise InstallError("LTeX+ was unpacked but cannot be found.")
    return installation


def extract(archive: Path, dest: Path) -> None:
    """Unpack a .zip or .tar.gz, refusing anything that would land outside `dest`."""
    dest.mkdir(parents=True)
    try:
        if archive.name.endswith(".zip"):
            _extract_zip(archive, dest)
        else:
            with tarfile.open(archive, "r:gz") as tar:
                if sum(m.size for m in tar.getmembers()) > MAX_UNPACKED_BYTES:
                    raise InstallError("The LTeX+ archive is unexpectedly large.")
                tar.extractall(dest, filter="data")
    except (tarfile.TarError, zipfile.BadZipFile, OSError) as exc:
        raise InstallError(f"Unpacking LTeX+ failed: {exc}") from exc


def _extract_zip(archive: Path, dest: Path) -> None:
    root = dest.resolve()
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
            raise InstallError("The LTeX+ archive is unexpectedly large.")
        for info in infos:
            name = PurePosixPath(info.filename.replace("\\", "/"))
            unsafe = (
                name.is_absolute()
                or ".." in name.parts
                or (name.parts and ":" in name.parts[0])
                or stat.S_ISLNK(info.external_attr >> 16)
                or not (root / name).resolve().is_relative_to(root)
            )
            if unsafe:
                raise InstallError(f"The LTeX+ archive has an unsafe entry: {info.filename}")
        z.extractall(root)  # noqa: S202 - every entry was checked above


def main() -> int:
    config = load_config().ltex
    existing = find_installation(config)
    if existing is not None:
        print(f"LTeX+ {config.version} is already installed in {existing.home}")
        return 0
    shown = -1

    def report(phase: InstallPhase, done: int, total: int | None) -> None:
        nonlocal shown
        if phase == "unpack":
            print("Unpacking…", flush=True)
        elif total:
            percent = done * 100 // total
            if percent >= shown + 5:
                shown = percent
                print(f"Downloading LTeX+ {config.version}: {percent} %", flush=True)

    try:
        installation = asyncio.run(install(config, report))
    except InstallError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Installed LTeX+ {config.version} in {installation.home}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
