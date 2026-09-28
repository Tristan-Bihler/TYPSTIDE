"""Adapter around typst-py. Grows into the `Compiler` port implementation in Phase 1."""

import json
from functools import cache

import typst


@cache
def typst_version() -> str:
    """Version of the Typst compiler bundled in typst-py, as reported by Typst itself."""
    raw = typst.query(b"#metadata(str(sys.version)) <v>", "<v>", field="value", one=True)
    version = json.loads(raw)
    if not isinstance(version, str):
        raise TypeError(f"unexpected Typst version value: {version!r}")
    return version
