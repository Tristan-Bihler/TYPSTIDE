"""Compiles the workspace's main file, including unsaved edits in any open file."""

import asyncio
import hashlib
from collections.abc import Mapping
from pathlib import Path

from typst_writer.domain.errors import NoMainFileError
from typst_writer.domain.models import CompileResult
from typst_writer.infra.shadow import ShadowWorkspace
from typst_writer.ports.compiler import Compiler


class CompileService:
    def __init__(self, compiler: Compiler, cache_root: Path) -> None:
        self._compiler = compiler
        self._cache_root = cache_root
        self._shadows: dict[Path, ShadowWorkspace] = {}
        self._lock = asyncio.Lock()

    def _shadow_for(self, root: Path) -> ShadowWorkspace:
        root = root.resolve()
        if root not in self._shadows:
            digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
            self._shadows[root] = ShadowWorkspace(root, self._cache_root / "shadow" / digest)
        return self._shadows[root]

    async def _prepare(
        self, root: Path, main: str, overlays: Mapping[str, str]
    ) -> tuple[Path, Path]:
        """Sync the mirror; return (main file, project root) inside the mirror."""
        shadow = self._shadow_for(root)
        await asyncio.to_thread(shadow.sync, overlays)
        main_path = shadow.shadow / main
        if not main_path.is_file():
            raise NoMainFileError()
        return main_path, shadow.shadow

    async def preview(self, root: Path, main: str, overlays: Mapping[str, str]) -> CompileResult:
        async with self._lock:
            main_path, shadow_root = await self._prepare(root, main, overlays)
            return await self._compiler.to_svg_pages(main_path, shadow_root)

    async def export_pdf(self, root: Path, main: str, overlays: Mapping[str, str]) -> bytes:
        async with self._lock:
            main_path, shadow_root = await self._prepare(root, main, overlays)
            return await self._compiler.to_pdf(main_path, shadow_root)
