// Helpers for click-to-jump between the preview and the source.

const BLANK_LINE = /\n[ \t]*\n/g;

/** Start offset of the block (paragraph, or heading line) that contains `offset`. The
 * preview only follows the cursor when this changes, not on every keystroke. */
export function blockStart(text: string, offset: number): number {
  const before = text.slice(0, Math.min(Math.max(offset, 0), text.length));
  let start = 0;
  for (const match of before.matchAll(BLANK_LINE)) start = match.index + match[0].length;
  const lineStart = before.lastIndexOf("\n") + 1;
  if (/^[ \t]*=/.test(text.slice(lineStart))) return lineStart; // a heading is its own block
  // A heading line above the cursor in the same block ends the block there.
  const lines = text.slice(start, lineStart).split("\n");
  let position = start;
  for (const line of lines.slice(0, -1)) {
    position += line.length + 1;
    if (/^[ \t]*=/.test(line)) start = position;
  }
  return start;
}

/** Point (pt from the top of the page) for a click at `clientY` on a page drawn in `rect`. */
export function clickToPt(clientY: number, rect: { top: number; height: number }, pageHeightPt: number): number {
  if (rect.height <= 0) return 0;
  const fraction = Math.min(Math.max((clientY - rect.top) / rect.height, 0), 1);
  return fraction * pageHeightPt;
}
