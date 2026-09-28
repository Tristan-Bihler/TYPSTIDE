// Findings as entries for the problems panel (pure, unit-tested).

import type { Problem, Suggestion } from "../api/types";

/** Problems for `suggestions` in `content` (offsets are UTF-16, like JS string indices). */
export function suggestionProblems(path: string, content: string, suggestions: readonly Suggestion[]): Problem[] {
  const lineStarts = [0];
  for (let i = content.indexOf("\n"); i !== -1; i = content.indexOf("\n", i + 1)) lineStarts.push(i + 1);
  return suggestions.map((s) => {
    let line = 0;
    while (line + 1 < lineStarts.length && (lineStarts[line + 1] ?? Infinity) <= s.start) line++;
    const fix = s.fixes?.[0];
    const message = fix === undefined || fix === s.original ? s.reason : `${s.reason} (${s.original} → ${fix})`;
    return {
      file: path,
      line: line + 1,
      column: s.start - (lineStarts[line] ?? 0) + 1,
      severity: s.source === "rule" ? "grammar" : "ai",
      message,
      source: s.source === "rule" ? "ltex" : s.source === "local_ai" ? "local AI" : "Claude",
    };
  });
}
