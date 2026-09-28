"""The typst-syntax project skill documents patterns; its example project must compile."""

from pathlib import Path

import typst

EXAMPLES = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "typst-syntax" / "examples"


def test_skill_examples_compile_without_warnings() -> None:
    compiler = typst.Compiler(str(EXAMPLES / "main.typ"), root=str(EXAMPLES))
    pages, warnings = compiler.compile_with_warnings(format="svg")
    assert isinstance(pages, list) and len(pages) >= 2
    assert [w.message for w in warnings] == []
