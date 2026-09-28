"""Workspace guard: every file access goes through here.

Client paths are workspace-relative POSIX strings ("chapters/intro.typ"; "" is the root).
They are rejected if absolute, containing "..", a drive or a stream (":"), or if the
resolved target (after following symlinks) lies outside the workspace root.
"""

import re
from pathlib import Path, PurePosixPath
from typing import Literal

from typst_writer.domain.errors import InvalidNameError, PathOutsideWorkspaceError

MAX_NAME_LENGTH = 120
# Letters (incl. umlauts), digits, underscore, and a few safe punctuation characters.
_NAME_RE = re.compile(r"^[\w\- .()+,]+$")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

EntryKind = Literal["file", "folder"]


class WorkspaceGuard:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise NotADirectoryError(str(root))

    def resolve(self, rel: str) -> Path:
        """Map a client path to an absolute path inside the workspace, or raise."""
        normalized = rel.replace("\\", "/")
        pure = PurePosixPath(normalized)
        if (
            "\x00" in normalized
            or ":" in normalized
            or pure.is_absolute()
            or any(part == ".." for part in pure.parts)
        ):
            raise PathOutsideWorkspaceError(rel)
        candidate = (self.root / pure).resolve()
        if not candidate.is_relative_to(self.root):
            raise PathOutsideWorkspaceError(rel)
        return candidate

    def resolve_entry(self, rel: str) -> Path:
        """Like `resolve`, but a symlink as the last segment is returned as the link itself.

        Use for operations on the entry (rename, delete), not on the file it points to.
        """
        pure = PurePosixPath(rel.replace("\\", "/"))
        if pure.name in ("", ".", ".."):
            raise PathOutsideWorkspaceError(rel)
        self.resolve(rel)  # full validation, including where a symlink points
        return self.resolve(pure.parent.as_posix()) / pure.name

    def relative(self, path: Path) -> str:
        """Workspace-relative POSIX path of an absolute path inside the workspace."""
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise PathOutsideWorkspaceError(str(path))
        rel = resolved.relative_to(self.root).as_posix()
        return "" if rel == "." else rel


def validate_name(name: str, kind: EntryKind) -> str:
    """Validate a new file or folder name (a single path segment). New files must be .typ."""
    if not name or len(name) > MAX_NAME_LENGTH:
        raise InvalidNameError(f"Names must be 1 to {MAX_NAME_LENGTH} characters long.")
    if name != name.strip() or name.startswith(".") or name.endswith("."):
        raise InvalidNameError("Names cannot start with a dot or start or end with a space or dot.")
    if not _NAME_RE.fullmatch(name):
        raise InvalidNameError(
            'Use only letters, digits, spaces and - _ . ( ) + , in names (no / \\ : * ? " < > |).'
        )
    if name.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise InvalidNameError(f"'{name}' is a reserved name on Windows.")
    if kind == "file" and not name.lower().endswith(".typ"):
        raise InvalidNameError("New files must end with .typ.")
    return name


def validate_rename(old: Path, new_name: str) -> str:
    """Folders follow folder rules; files must keep their extension (a .typ stays .typ)."""
    if old.is_dir():
        return validate_name(new_name, "folder")
    validate_name(new_name, "folder")  # character rules only
    if PurePosixPath(new_name).suffix.lower() != old.suffix.lower():
        raise InvalidNameError(f"Renamed files must keep the '{old.suffix}' extension.")
    return new_name
