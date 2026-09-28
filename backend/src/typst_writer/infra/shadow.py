"""Mirror of a workspace in which unsaved editor buffers replace their files on disk.

Typst reads every file from disk, so to render the *main* document with unsaved edits
in any chapter, we compile from this mirror. Unchanged files are hard links (or copies
when hard links are impossible, e.g. across drives); edited files are written out.
The workspace itself is never written to.
"""

import os
import shutil
from collections.abc import Mapping
from pathlib import Path


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def _same_content_marker(src: os.stat_result, dst: os.stat_result) -> bool:
    """A hard link to the same file, or a copy made by copy2 that is still current."""
    if (src.st_ino, src.st_dev) == (dst.st_ino, dst.st_dev):
        return True
    return src.st_size == dst.st_size and src.st_mtime_ns == dst.st_mtime_ns


class ShadowWorkspace:
    def __init__(self, source: Path, shadow: Path) -> None:
        self.source = source.resolve()
        self.shadow = shadow
        self._written: dict[str, str] = {}  # overlay text currently in the mirror, by rel path

    def sync(self, overlays: Mapping[str, str]) -> None:
        """Bring the mirror up to date. `overlays` maps workspace-relative paths to text."""
        self.shadow.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(self.source, followlinks=False):
            dirnames[:] = [d for d in dirnames if not _is_hidden(d)]
            for name in filenames:
                if _is_hidden(name):
                    continue
                src = Path(dirpath) / name
                if src.is_symlink() and not src.resolve().is_relative_to(self.source):
                    continue  # never expose files outside the workspace
                rel = src.relative_to(self.source).as_posix()
                seen.add(rel)
                dst = self.shadow / rel
                if rel in overlays:
                    self._write_overlay(rel, dst, overlays[rel])
                else:
                    self._written.pop(rel, None)
                    self._link(src, dst)
        self._remove_stale(seen)

    def _write_overlay(self, rel: str, dst: Path, text: str) -> None:
        if self._written.get(rel) == text and dst.exists():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Unlink first: dst may be a hard link to the real file, which must stay untouched.
        dst.unlink(missing_ok=True)
        dst.write_text(text, encoding="utf-8", newline="")
        self._written[rel] = text

    def _link(self, src: Path, dst: Path) -> None:
        src_stat = src.stat()
        try:
            if _same_content_marker(src_stat, dst.stat()):
                return
        except FileNotFoundError:
            pass
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.unlink(missing_ok=True)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)

    def _remove_stale(self, seen: set[str]) -> None:
        for dirpath, _dirnames, filenames in os.walk(self.shadow, topdown=False):
            for name in filenames:
                path = Path(dirpath) / name
                if path.relative_to(self.shadow).as_posix() not in seen:
                    path.unlink()
            if Path(dirpath) != self.shadow and not any(Path(dirpath).iterdir()):
                Path(dirpath).rmdir()
        for rel in list(self._written):
            if rel not in seen:
                del self._written[rel]
