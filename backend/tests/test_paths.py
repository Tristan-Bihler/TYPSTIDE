import os
from pathlib import Path

import pytest

from typst_writer.domain.errors import InvalidNameError, PathOutsideWorkspaceError
from typst_writer.infra.paths import WorkspaceGuard, validate_name, validate_rename


@pytest.fixture
def guard(tmp_path: Path) -> WorkspaceGuard:
    root = tmp_path / "ws"
    (root / "chapters").mkdir(parents=True)
    (root / "main.typ").write_text("= Hi", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    return WorkspaceGuard(root)


@pytest.mark.parametrize("rel", ["", "main.typ", "chapters", "chapters/new.typ", "chapters\\x.typ"])
def test_resolves_paths_inside_workspace(guard: WorkspaceGuard, rel: str) -> None:
    assert guard.resolve(rel).is_relative_to(guard.root)


@pytest.mark.parametrize(
    "rel",
    [
        "../secret.txt",
        "chapters/../../secret.txt",
        "..\\secret.txt",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "C:secret.txt",
        "main.typ:stream",
        "main.typ\x00.png",
    ],
)
def test_rejects_traversal(guard: WorkspaceGuard, rel: str) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        guard.resolve(rel)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra privileges on Windows")
def test_rejects_symlink_escaping_workspace(guard: WorkspaceGuard) -> None:
    (guard.root / "link.txt").symlink_to(guard.root.parent / "secret.txt")
    (guard.root / "linkdir").symlink_to(guard.root.parent)
    with pytest.raises(PathOutsideWorkspaceError):
        guard.resolve("link.txt")
    with pytest.raises(PathOutsideWorkspaceError):
        guard.resolve("linkdir/secret.txt")


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra privileges on Windows")
def test_allows_symlink_inside_workspace(guard: WorkspaceGuard) -> None:
    (guard.root / "alias.typ").symlink_to(guard.root / "main.typ")
    assert guard.resolve("alias.typ") == guard.root / "main.typ"


def test_relative(guard: WorkspaceGuard) -> None:
    assert guard.relative(guard.root / "chapters" / "a.typ") == "chapters/a.typ"
    assert guard.relative(guard.root) == ""
    with pytest.raises(PathOutsideWorkspaceError):
        guard.relative(guard.root.parent / "secret.txt")


@pytest.mark.parametrize("name", ["main.typ", "01-Einleitung.typ", "Übung (1).typ", "a b.TYP"])
def test_valid_file_names(name: str) -> None:
    assert validate_name(name, "file") == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "notes.txt",
        "noext",
        ".hidden.typ",
        "a/b.typ",
        "a\\b.typ",
        "..",
        "what?.typ",
        "x:y.typ",
        " lead.typ",
        "trail.typ ",
        "CON.typ",
        "lpt1.typ",
        "a" * 200 + ".typ",
    ],
)
def test_invalid_file_names(name: str) -> None:
    with pytest.raises(InvalidNameError):
        validate_name(name, "file")


def test_folder_names_do_not_need_extension() -> None:
    assert validate_name("chapters", "folder") == "chapters"
    with pytest.raises(InvalidNameError):
        validate_name("a/b", "folder")


def test_rename_keeps_extension(guard: WorkspaceGuard) -> None:
    main = guard.root / "main.typ"
    assert validate_rename(main, "thesis.typ") == "thesis.typ"
    with pytest.raises(InvalidNameError):
        validate_rename(main, "thesis.txt")
    assert validate_rename(guard.root / "chapters", "kapitel") == "kapitel"
