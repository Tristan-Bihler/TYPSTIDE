"""The open folder: file tree, file operations and which file is the main document."""

import os
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from typst_writer.domain.errors import (
    EntryExistsError,
    EntryNotFoundError,
    InvalidNameError,
    NotATextFileError,
    NoWorkspaceError,
    PathOutsideWorkspaceError,
)
from typst_writer.infra.paths import WorkspaceGuard, validate_name, validate_rename
from typst_writer.infra.state_store import StateStore, WorkspaceState

TEXT_EXTENSIONS = {".typ", ".bib", ".yml", ".yaml", ".csv", ".txt", ".toml", ".json", ".md"}
MAX_TEXT_BYTES = 5_000_000
MAX_TREE_ENTRIES = 5_000
DEFAULT_MAIN = "main.typ"


class TreeNode(BaseModel):
    name: str
    path: str
    kind: Literal["file", "folder"]
    children: list["TreeNode"] = []


class Tree(BaseModel):
    root: TreeNode
    truncated: bool


class WorkspaceInfo(BaseModel):
    root: str
    name: str
    main: str | None


class DirListing(BaseModel):
    path: str
    parent: str | None
    dirs: list[str]


def _visible(entry: os.DirEntry[str]) -> bool:
    return not entry.name.startswith(".")


def _sort_key(entry: os.DirEntry[str]) -> tuple[bool, str]:
    return (not entry.is_dir(), entry.name.casefold())


class WorkspaceService:
    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._guard: WorkspaceGuard | None = None
        self._main: str | None = None

    # --- workspace ---------------------------------------------------------------

    @property
    def guard(self) -> WorkspaceGuard:
        if self._guard is None:
            raise NoWorkspaceError()
        return self._guard

    def info(self) -> WorkspaceInfo | None:
        return self._info() if self._guard is not None else None

    def _info(self) -> WorkspaceInfo:
        root = self.guard.root
        return WorkspaceInfo(root=str(root), name=root.name, main=self._main)

    def open(self, path: str) -> WorkspaceInfo:
        folder = Path(path).expanduser()
        if not folder.is_absolute() or not folder.is_dir():
            raise EntryNotFoundError(path)
        self._guard = WorkspaceGuard(folder)
        state = self._store.load()
        key = str(self._guard.root)
        saved_main = state.workspaces.get(key, WorkspaceState()).main
        self._main = saved_main if saved_main and self._is_typ_file(saved_main) else None
        if self._main is None and self._is_typ_file(DEFAULT_MAIN):
            self._main = DEFAULT_MAIN
        state.last_workspace = key
        self._store.save(state)
        return self._info()

    def restore_last(self) -> None:
        last = self._store.load().last_workspace
        if last and Path(last).is_dir():
            self.open(last)

    def browse(self, path: str | None) -> DirListing:
        """List sub-folders of any local folder, for the 'Open folder' dialog."""
        folder = Path(path).expanduser() if path else Path.home()
        folder = folder.resolve()
        if not folder.is_dir():
            raise EntryNotFoundError(str(folder))
        try:
            with os.scandir(folder) as entries:
                dirs = sorted(
                    (e.name for e in entries if _visible(e) and e.is_dir()), key=str.casefold
                )
        except PermissionError:
            dirs = []
        parent = str(folder.parent) if folder.parent != folder else None
        return DirListing(path=str(folder), parent=parent, dirs=dirs)

    # --- main file ---------------------------------------------------------------

    @property
    def main(self) -> str | None:
        return self._main

    def _is_typ_file(self, rel: str) -> bool:
        try:
            path = self.guard.resolve(rel)
        except PathOutsideWorkspaceError:
            return False
        return path.is_file() and path.suffix.lower() == ".typ"

    def set_main(self, rel: str | None) -> WorkspaceInfo:
        if rel is not None and not self._is_typ_file(rel):
            raise InvalidNameError("Only an existing .typ file can be the main file.")
        self._main = rel
        state = self._store.load()
        state.workspaces[str(self.guard.root)] = WorkspaceState(main=rel)
        self._store.save(state)
        return self._info()

    # --- tree --------------------------------------------------------------------

    def tree(self) -> Tree:
        root = self.guard.root
        budget = [MAX_TREE_ENTRIES]

        def walk(folder: Path, rel: str) -> list[TreeNode]:
            nodes: list[TreeNode] = []
            try:
                with os.scandir(folder) as it:
                    entries = sorted((e for e in it if _visible(e)), key=_sort_key)
            except OSError:
                return nodes
            for entry in entries:
                if budget[0] <= 0:
                    break
                budget[0] -= 1
                path = Path(entry.path)
                if entry.is_symlink() and not path.resolve().is_relative_to(root):
                    continue
                child_rel = f"{rel}/{entry.name}" if rel else entry.name
                if entry.is_dir(follow_symlinks=False):
                    nodes.append(
                        TreeNode(
                            name=entry.name,
                            path=child_rel,
                            kind="folder",
                            children=walk(path, child_rel),
                        )
                    )
                elif entry.is_file():
                    nodes.append(TreeNode(name=entry.name, path=child_rel, kind="file"))
            return nodes

        children = walk(root, "")
        node = TreeNode(name=root.name, path="", kind="folder", children=children)
        return Tree(root=node, truncated=budget[0] <= 0)

    # --- files -------------------------------------------------------------------

    def _text_file(self, rel: str) -> Path:
        path = self.guard.resolve(rel)
        if not path.is_file():
            raise EntryNotFoundError(rel)
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            raise NotATextFileError(f"'{rel}' is not a text file this editor can open.")
        return path

    def read_text(self, rel: str) -> str:
        path = self._text_file(rel)
        if path.stat().st_size > MAX_TEXT_BYTES:
            raise NotATextFileError(f"'{rel}' is larger than {MAX_TEXT_BYTES // 1_000_000} MB.")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise NotATextFileError(f"'{rel}' is not UTF-8 text.") from e

    def write_text(self, rel: str, content: str) -> None:
        path = self._text_file(rel)
        data = content.encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            raise NotATextFileError(f"Files larger than {MAX_TEXT_BYTES // 1_000_000} MB.")
        tmp = path.with_name(f".{path.name}.saving")
        tmp.write_bytes(data)
        tmp.replace(path)  # atomic: a crash never leaves a half-written file

    def _folder(self, rel: str) -> Path:
        folder = self.guard.resolve(rel)
        if not folder.is_dir():
            raise EntryNotFoundError(rel)
        return folder

    def create_file(self, parent: str, name: str, overwrite: bool = False) -> str:
        target = self._folder(parent) / validate_name(name, "file")
        # is_symlink(): a broken link does not "exist", but writing to it would create
        # its target, possibly outside the folder. relative() refuses links leading out.
        if target.is_symlink() or target.exists():
            existing = self.guard.relative(target)
            if not (overwrite and target.is_file()):
                raise EntryExistsError(existing)
        target.write_text("", encoding="utf-8")
        return self.guard.relative(target)

    def create_folder(self, parent: str, name: str) -> str:
        target = self._folder(parent) / validate_name(name, "folder")
        if target.exists():
            raise EntryExistsError(self.guard.relative(target))
        target.mkdir()
        return self.guard.relative(target)

    def rename(self, rel: str, new_name: str, overwrite: bool = False) -> str:
        if rel in ("", "."):
            raise InvalidNameError("The open folder itself cannot be renamed here.")
        source = self.guard.resolve_entry(rel)
        if not source.exists():
            raise EntryNotFoundError(rel)
        target = source.parent / validate_rename(source, new_name)
        parent_rel = self.guard.relative(source.parent)
        new_rel = f"{parent_rel}/{target.name}" if parent_rel else target.name
        replaceable = overwrite and target.is_file() and source.is_file()
        if target.exists() and target != source and not replaceable:
            raise EntryExistsError(new_rel)
        source.replace(target)
        if self._main is not None and (self._main == rel or self._main.startswith(rel + "/")):
            self.set_main(new_rel + self._main[len(rel) :])
        return new_rel

    def delete(self, rel: str) -> None:
        if rel in ("", "."):
            raise InvalidNameError("The open folder itself cannot be deleted.")
        path = self.guard.resolve_entry(rel)
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            raise EntryNotFoundError(rel)
        if self._main is not None and (self._main == rel or self._main.startswith(rel + "/")):
            self.set_main(None)
