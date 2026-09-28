// Applying accepted review changes to the editor (pure, unit-tested).

import type { EditorState, TransactionSpec } from "@codemirror/state";

import type { Suggestion } from "../api/types";

export interface ReviewedRange {
  path: string;
  from: number;
  to: number;
  text: string; // the selection as it was sent for review
}

/**
 * One transaction (one undo step) with the accepted changes, or a message explaining why
 * they cannot be applied: the text must still be exactly what was reviewed.
 */
export function applyAccepted(
  state: EditorState,
  activePath: string | null,
  reviewed: ReviewedRange,
  accepted: Suggestion[],
): TransactionSpec | string {
  if (activePath !== reviewed.path) return `Open ${reviewed.path} again to apply the changes.`;
  if (state.sliceDoc(reviewed.from, reviewed.to) !== reviewed.text) {
    return "The text changed while Claude was reviewing it. Select it and review again.";
  }
  for (const s of accepted) {
    if (state.sliceDoc(s.start, s.end) !== s.original) {
      return "A change no longer matches the text. Review the selection again.";
    }
  }
  const sorted = [...accepted].sort((a, b) => a.start - b.start);
  return {
    changes: sorted.map((s) => ({ from: s.start, to: s.end, insert: s.replacement })),
    userEvent: "input.review",
    scrollIntoView: true,
  };
}
