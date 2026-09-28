from typst_writer.domain.paragraphs import paragraph_at, split_paragraphs
from typst_writer.domain.review import ProposedChange
from typst_writer.infra.cache import ParagraphCache

LONG = "Dieser Absatz ist lang genug, um vom lokalen Modell geprüft zu werden."
OTHER = "Auch der zweite Absatz enthält genügend Text für eine sinnvolle Prüfung."


def test_paragraphs_are_blank_line_separated_with_offsets() -> None:
    text = f"{LONG}\n\n  \n{OTHER}\nZweite Zeile desselben Absatzes.\n"
    paragraphs = split_paragraphs(text)
    assert [p.text for p in paragraphs] == [LONG, f"{OTHER}\nZweite Zeile desselben Absatzes."]
    for p in paragraphs:
        assert text[p.start : p.end] == p.text


def test_headings_code_math_figures_and_short_blocks_are_skipped() -> None:
    text = (
        "= Einleitung\n"
        f"{LONG}\n\n"
        "== Kurz\n\n"
        "Zu kurz.\n\n"
        "$ sum_(i=1)^n i = (n(n+1)) / 2 $\n\n"
        '#figure(\n  image("/b.svg"),\n  caption: [Kurz],\n) <fig:a>\n\n'
        "```python\ndef lange_funktion_mit_viel_code(): return 1\n```\n\n"
        '#set text(lang: "de", size: 11pt, font: "Linux Libertine")\n\n'
        f"{OTHER}"
    )
    assert [p.text for p in split_paragraphs(text)] == [LONG, OTHER]


def test_markup_inside_prose_does_not_count_but_stays_in_the_text() -> None:
    text = "Siehe @fig:aufbau und $E = m c^2$, kurz."
    assert split_paragraphs(text) == []
    longer = "Wie in @fig:aufbau gezeigt, wird die Messung sorgfältig durchgeführt."
    [paragraph] = split_paragraphs(longer)
    assert paragraph.text == longer


def test_paragraph_at_cursor() -> None:
    text = f"{LONG}\n\n{OTHER}"
    paragraphs = split_paragraphs(text)
    assert paragraph_at(paragraphs, 3) == paragraphs[0]
    assert paragraph_at(paragraphs, len(text)) == paragraphs[1]  # cursor at the very end
    assert paragraph_at(paragraphs, len(LONG) + 1) is None  # on the blank line


def test_emoji_and_crlf_keep_offsets_consistent() -> None:
    text = f"😀 {LONG}\r\n\r\n{OTHER}"
    paragraphs = split_paragraphs(text)
    assert [p.text for p in paragraphs] == [f"😀 {LONG}", OTHER]
    assert all(text[p.start : p.end] == p.text for p in paragraphs)


def _change(original: str) -> ProposedChange:
    return ProposedChange(original=original, replacement="x", reason="r", category="style")


def test_cache_key_depends_on_everything_and_lru_evicts_the_oldest() -> None:
    key = ParagraphCache.key
    base = key("Absatz", "qwen", "live", "de-DE")
    assert base == key("Absatz", "qwen", "live", "de-DE")
    assert (
        len(
            {
                base,
                key("Absatz.", "qwen", "live", "de-DE"),
                key("Absatz", "llama", "live", "de-DE"),
                key("Absatz", "qwen", "check", "de-DE"),
                key("Absatz", "qwen", "live", "en-US"),
            }
        )
        == 5
    )
    cache = ParagraphCache(max_entries=2)
    cache.put("a", [_change("a")])
    cache.put("b", [])
    assert cache.get("a") == [_change("a")]  # "a" is now the most recent
    cache.put("c", [])
    assert cache.get("b") is None
    assert cache.get("a") is not None
    assert cache.get("c") == []
    assert len(cache) == 2
