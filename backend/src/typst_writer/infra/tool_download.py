"""Verified downloads of the optional language tools (LTeX+, Tinymist).

Nothing is downloaded without the user asking for it. A download is streamed to a file,
limited in size, and must match the SHA-256 pinned in config.toml; otherwise the file is
deleted and nothing is installed.
"""

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import httpx

InstallPhase = Literal["download", "unpack"]
Progress = Callable[[InstallPhase, int, int | None], None]  # phase, bytes done, total


class InstallError(Exception):
    """Installing a tool failed; the message is meant for the user."""


async def download(
    url: str,
    dest: Path,
    sha256: str,
    progress: Progress,
    client: httpx.AsyncClient | None = None,
    *,
    tool: str,
    max_bytes: int,
) -> None:
    own = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0))
    digest = hashlib.sha256()
    try:
        async with http.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            length = response.headers.get("content-length")
            total = int(length) if length and length.isdigit() else None
            if total is not None and total > max_bytes:
                raise InstallError(f"The {tool} download is unexpectedly large.")
            done = 0
            with dest.open("wb") as f:
                async for chunk in response.aiter_bytes(1 << 20):
                    done += len(chunk)
                    if done > max_bytes:
                        raise InstallError(f"The {tool} download is unexpectedly large.")
                    digest.update(chunk)
                    f.write(chunk)
                    progress("download", done, total)
    except httpx.HTTPError as exc:
        raise InstallError(f"Downloading {tool} failed: {exc}") from exc
    finally:
        if own:
            await http.aclose()
    if digest.hexdigest() != sha256.lower():
        dest.unlink(missing_ok=True)
        raise InstallError(
            f"The {tool} download does not match its checksum; nothing was installed."
        )
