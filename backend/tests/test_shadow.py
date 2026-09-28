import os
from pathlib import Path

import pytest

from typst_writer.infra.shadow import ShadowWorkspace


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "chapters").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("x", encoding="utf-8")
    (root / "main.typ").write_text('#include "chapters/one.typ"', encoding="utf-8")
    (root / "chapters" / "one.typ").write_text("saved", encoding="utf-8")
    return root


@pytest.fixture
def shadow(workspace: Path, tmp_path: Path) -> ShadowWorkspace:
    return ShadowWorkspace(workspace, tmp_path / "shadow")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mirrors_files_and_skips_hidden(shadow: ShadowWorkspace) -> None:
    shadow.sync({})
    assert read(shadow.shadow / "chapters" / "one.typ") == "saved"
    assert not (shadow.shadow / ".git").exists()


def test_overlay_never_modifies_the_workspace(shadow: ShadowWorkspace, workspace: Path) -> None:
    shadow.sync({})  # mirror now holds hard links to the real files
    shadow.sync({"chapters/one.typ": "unsaved"})
    assert read(shadow.shadow / "chapters" / "one.typ") == "unsaved"
    assert read(workspace / "chapters" / "one.typ") == "saved"


def test_dropping_overlay_restores_disk_content(shadow: ShadowWorkspace) -> None:
    shadow.sync({"chapters/one.typ": "unsaved"})
    shadow.sync({})
    assert read(shadow.shadow / "chapters" / "one.typ") == "saved"


def test_picks_up_saved_changes_and_deletions(shadow: ShadowWorkspace, workspace: Path) -> None:
    shadow.sync({})
    (workspace / "chapters" / "one.typ").unlink()
    (workspace / "chapters" / "one.typ").write_text("new version", encoding="utf-8")
    (workspace / "main.typ").unlink()
    shadow.sync({})
    assert read(shadow.shadow / "chapters" / "one.typ") == "new version"
    assert not (shadow.shadow / "main.typ").exists()


def test_overlay_for_deleted_file_is_ignored(shadow: ShadowWorkspace) -> None:
    shadow.sync({"gone.typ": "x"})
    assert not (shadow.shadow / "gone.typ").exists()


def test_falls_back_to_copies(
    shadow: ShadowWorkspace, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(_src: object, _dst: object) -> None:
        raise OSError("cross-device link")

    monkeypatch.setattr(os, "link", no_links)
    shadow.sync({})
    mirrored = shadow.shadow / "chapters" / "one.typ"
    assert read(mirrored) == "saved"
    assert not mirrored.samefile(workspace / "chapters" / "one.typ")

    source = workspace / "chapters" / "one.typ"
    source.write_text("edited!", encoding="utf-8")
    os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 10**9))
    shadow.sync({})
    assert read(mirrored) == "edited!"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra privileges on Windows")
def test_skips_symlinks_leaving_the_workspace(
    shadow: ShadowWorkspace, workspace: Path, tmp_path: Path
) -> None:
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    (workspace / "leak.txt").symlink_to(tmp_path / "secret.txt")
    shadow.sync({})
    assert not (shadow.shadow / "leak.txt").exists()
