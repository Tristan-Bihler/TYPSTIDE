"""Converting between LSP positions, Python string indices and UTF-16 offsets.

LSP positions are (line, UTF-16 code unit in that line); the browser editor counts UTF-16
code units from the start of the document; Python counts code points.
"""

from bisect import bisect_right

from typst_writer.domain.review import utf16_len


class TextPositions:
    def __init__(self, text: str) -> None:
        self.text = text
        self._line_starts = [0]
        self._line_starts.extend(i + 1 for i, c in enumerate(text) if c == "\n")
        self._bmp_only = utf16_len(text) == len(text)  # then UTF-16 offset == index

    def index(self, line: int, character: int) -> int:
        """Python index of an LSP position (clamped to the text)."""
        if line < 0:
            return 0
        if line >= len(self._line_starts):
            return len(self.text)
        start = self._line_starts[line]
        end = (
            self._line_starts[line + 1] - 1 if line + 1 < len(self._line_starts) else len(self.text)
        )
        units = 0
        for i in range(start, end):
            if units >= character:
                return i
            units += 2 if ord(self.text[i]) > 0xFFFF else 1
        return end

    def utf16_offset(self, index: int) -> int:
        """UTF-16 offset from the document start of a Python index."""
        return index if self._bmp_only else utf16_len(self.text[:index])

    def index_of_utf16(self, offset: int) -> int:
        """Python index of a UTF-16 document offset (clamped to the text)."""
        if self._bmp_only:
            return max(0, min(offset, len(self.text)))
        units = 0
        for i, c in enumerate(self.text):
            if units >= offset:
                return i
            units += 2 if ord(c) > 0xFFFF else 1
        return len(self.text)

    def line_column(self, index: int) -> tuple[int, int]:
        """1-based line and column (in characters) of a Python index."""
        line = bisect_right(self._line_starts, index) - 1
        return line + 1, index - self._line_starts[line] + 1
