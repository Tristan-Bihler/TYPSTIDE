"""Safe building blocks for generated Typst code (rules: .claude/skills/typst-syntax)."""

import re
import unicodedata

# Characters with a meaning inside a content block [...]; "/" because "//" starts a comment.
_MARKUP_SPECIAL = frozenset("\\#$*_[]@<>`~/")
# Label names Typst accepts in <...> and @... (letters incl. umlauts, digits, _ - . :).
LABEL_RE = re.compile(r"^[^\W_][\w.:-]*$")
_TRANSLITERATE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


# At the start of a content block these begin a heading or list item: "= ", "- ", "+ ", "1. ".
_LEADING_MARKER = re.compile(r"^(?:[=+-]|\d+(?=\.))")


def escape_markup(text: str) -> str:
    """User text for a single-line content block: renders exactly as typed.

    Mid-text shorthands such as "--" (en dash) are left alone on purpose; they are
    typography, not structure.
    """
    single_line = " ".join(text.split())
    escaped = "".join("\\" + c if c in _MARKUP_SPECIAL else c for c in single_line)
    marker = _LEADING_MARKER.match(escaped)
    if marker is None:
        return escaped
    if marker.group(0)[0].isdigit():  # "1. Platz" -> "1\. Platz"
        return escaped[: marker.end()] + "\\" + escaped[marker.end() :]
    return "\\" + escaped


def escape_string(text: str) -> str:
    """User text for a Typst string literal "..."."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def is_label(name: str) -> bool:
    return LABEL_RE.fullmatch(name) is not None


def slugify(text: str, max_length: int = 40) -> str:
    """'Messwerte (Übersicht)' -> 'messwerte-uebersicht'."""
    lowered = text.lower().translate(_TRANSLITERATE)
    ascii_text = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug[:max_length].rstrip("-")


def make_label(prefix: str, text: str, existing: set[str]) -> str:
    """A new label like 'tab:messwerte', unique among `existing` ('tab:messwerte-2', …)."""
    base = f"{prefix}:{slugify(text) or prefix}"
    label, n = base, 2
    while label in existing:
        label, n = f"{base}-{n}", n + 1
    return label
