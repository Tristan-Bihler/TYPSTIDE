import hashlib
import io
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest

from typst_writer.config import LtexConfig, load_config
from typst_writer.infra import ltex_install
from typst_writer.infra.ltex_install import (
    LTEX_DIR_ENV_VAR,
    LtexInstallError,
    archive_url,
    extract,
    find_installation,
    install,
    platform_key,
)

pytestmark = pytest.mark.anyio


def test_platform_keys() -> None:
    assert platform_key("win32", "AMD64") == "windows-x64"
    assert platform_key("linux", "x86_64") == "linux-x64"
    assert platform_key("darwin", "arm64") == "mac-aarch64"
    assert platform_key("darwin", "x86_64") == "mac-x64"
    assert platform_key("win32", "ARM64") is None
    assert platform_key("freebsd", "amd64") is None


def test_config_pins_a_checksum_for_every_platform() -> None:
    config = load_config().ltex
    assert set(config.sha256) == {"windows-x64", "linux-x64", "mac-aarch64", "mac-x64"}
    assert all(len(v) == 64 for v in config.sha256.values())
    windows = f"/{config.version}/ltex-ls-plus-{config.version}-windows-x64.zip"
    assert archive_url(config, "windows-x64").endswith(windows)
    assert archive_url(config, "linux-x64").endswith("-linux-x64.tar.gz")


def _tar(files: dict[str, bytes], links: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
        for name, target in (links or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)
    return buffer.getvalue()


def _zip(files: dict[str, bytes], symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
        if symlink is not None:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "/etc/passwd")
    return buffer.getvalue()


JAVA = "java.exe" if sys.platform == "win32" else "java"
GOOD_FILES = {
    "ltex-ls-plus-9.9.9/lib/ltex.jar": b"jar",
    f"ltex-ls-plus-9.9.9/jdk-21.0.10+7/bin/{JAVA}": b"#!/bin/sh\n",
}


def _config(archive: bytes, key: str) -> LtexConfig:
    return LtexConfig(
        version="9.9.9",
        url="https://example.test/{version}/ltex-{platform}.{extension}",
        sha256={key: hashlib.sha256(archive).hexdigest()},
    )


def _client(archive: bytes, requests: list[str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, content=archive)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _archive_for_this_platform(files: dict[str, bytes]) -> tuple[bytes, str]:
    key = platform_key()
    assert key is not None
    return (_zip(files) if key.startswith("windows") else _tar(files)), key


async def test_install_downloads_verifies_and_unpacks(isolated_app_home: Path) -> None:
    archive, key = _archive_for_this_platform(GOOD_FILES)
    config = _config(archive, key)
    requests: list[str] = []
    phases: set[str] = set()
    async with _client(archive, requests) as client:
        installation = await install(config, lambda phase, *_: phases.add(phase), client)
    assert requests == [archive_url(config, key)]
    assert phases == {"download", "unpack"}
    assert installation.home == isolated_app_home / "cache" / "ltex-ls-plus-9.9.9"
    assert installation.command()[0] == str(installation.java)
    assert installation.command()[-1] == ltex_install.MAIN_CLASS
    assert find_installation(config) == installation
    leftovers = [p.name for p in installation.home.parent.iterdir() if p.name.startswith(".ltex")]
    assert leftovers == []


async def test_existing_installation_is_not_downloaded_again(isolated_app_home: Path) -> None:
    archive, key = _archive_for_this_platform(GOOD_FILES)
    config = _config(archive, key)
    requests: list[str] = []
    async with _client(archive, requests) as client:
        await install(config, lambda *_: None, client)
        await install(config, lambda *_: None, client)
    assert len(requests) == 1


async def test_checksum_mismatch_installs_nothing(isolated_app_home: Path) -> None:
    archive, key = _archive_for_this_platform(GOOD_FILES)
    config = _config(archive, key).model_copy(update={"sha256": {key: "0" * 64}})
    async with _client(archive, []) as client:
        with pytest.raises(LtexInstallError, match="checksum"):
            await install(config, lambda *_: None, client)
    assert find_installation(config) is None
    assert list((isolated_app_home / "cache").iterdir()) == []


async def test_failed_download_installs_nothing(isolated_app_home: Path) -> None:
    archive, key = _archive_for_this_platform(GOOD_FILES)
    config = _config(archive, key)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b"blocked")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(LtexInstallError, match="Downloading LTeX\\+ failed"):
            await install(config, lambda *_: None, client)
    assert find_installation(config) is None


async def test_archive_without_java_is_rejected(isolated_app_home: Path) -> None:
    archive, key = _archive_for_this_platform({"ltex-ls-plus-9.9.9/lib/ltex.jar": b"jar"})
    config = _config(archive, key)
    async with _client(archive, []) as client:
        with pytest.raises(LtexInstallError, match="expected folder"):
            await install(config, lambda *_: None, client)
    assert find_installation(config) is None


def test_env_override_points_at_an_existing_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "my-ltex"
    (home / "lib").mkdir(parents=True)
    java = home / "jdk-21" / "bin" / JAVA
    java.parent.mkdir(parents=True)
    java.write_text("")
    monkeypatch.setenv(LTEX_DIR_ENV_VAR, str(home))
    found = find_installation(LtexConfig())
    assert found is not None and found.java == java


@pytest.mark.parametrize(
    "archive",
    [
        _tar({"../evil.txt": b"x"}),
        _tar({"ok/file": b"x"}, links={"ok/link": "/etc/passwd"}),
        _tar({"ok/file": b"x"}, links={"ok/link": "../../outside"}),
    ],
    ids=["tar-dotdot", "tar-absolute-link", "tar-escaping-link"],
)
def test_unsafe_tar_entries_are_refused(tmp_path: Path, archive: bytes) -> None:
    path = tmp_path / "a.tar.gz"
    path.write_bytes(archive)
    with pytest.raises(LtexInstallError):
        extract(path, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_absolute_tar_entries_stay_inside_the_target(tmp_path: Path) -> None:
    path = tmp_path / "a.tar.gz"
    path.write_bytes(_tar({str(tmp_path / "evil.txt"): b"x"}))
    extract(path, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()
    assert (tmp_path / "out" / str(tmp_path / "evil.txt").lstrip("/")).is_file()


@pytest.mark.parametrize(
    ("files", "symlink"),
    [
        ({"../evil.txt": b"x"}, None),
        ({"/abs/evil.txt": b"x"}, None),
        ({"C:/evil.txt": b"x"}, None),
        ({"ok\\..\\..\\evil.txt": b"x"}, None),
        ({"ok/file": b"x"}, "ok/link"),
    ],
    ids=["zip-dotdot", "zip-absolute", "zip-drive", "zip-backslash-dotdot", "zip-symlink"],
)
def test_unsafe_zip_entries_are_refused(
    tmp_path: Path, files: dict[str, bytes], symlink: str | None
) -> None:
    path = tmp_path / "a.zip"
    path.write_bytes(_zip(files, symlink))
    with pytest.raises(LtexInstallError, match="unsafe entry"):
        extract(path, tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []
