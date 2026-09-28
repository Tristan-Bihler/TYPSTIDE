"""ParagraphCache: results of the local AI check per paragraph (in memory, LRU).

Key: sha256(paragraph + model + mode + language), as in CLAUDE.md. The value holds the
validated changes relative to the paragraph text, so a paragraph that moves within the
document keeps its entry and is never sent again.
"""

import hashlib
from collections import OrderedDict

from typst_writer.domain.review import ProposedChange


class ParagraphCache:
    def __init__(self, max_entries: int = 2000) -> None:
        self._max = max_entries
        self._entries: OrderedDict[str, list[ProposedChange]] = OrderedDict()

    @staticmethod
    def key(paragraph: str, model: str, mode: str, language: str) -> str:
        data = "\x00".join([paragraph, model, mode, language]).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def get(self, key: str) -> list[ProposedChange] | None:
        changes = self._entries.get(key)
        if changes is not None:
            self._entries.move_to_end(key)
        return changes

    def put(self, key: str, changes: list[ProposedChange]) -> None:
        self._entries[key] = changes
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)
