// Suggestion layer: underlines findings (spelling/grammar in red, local AI in blue) and
// shows a card with the reason and the fixes on hover, or with Ctrl+. at the cursor.
// Each source's findings are replaced independently. Marks move with the text while
// typing; a mark whose text is edited disappears until the next check reports it again.

import { StateEffect, StateField, type ChangeDesc, type EditorState, type Extension } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  hoverTooltip,
  keymap,
  showTooltip,
  type DecorationSet,
  type Tooltip,
} from "@codemirror/view";

import type { Suggestion } from "../api/types";
import { el } from "../ui/dom";

export interface Mark {
  suggestion: Suggestion;
  from: number;
  to: number;
}

export interface SuggestionHandlers {
  /** Hide this finding (and the same word with the same rule) for the session. */
  ignore(suggestion: Suggestion): void;
  /** Accept the word in the spell check from now on. */
  addToDictionary(suggestion: Suggestion): void;
}

export const setSuggestions = StateEffect.define<{ source: Suggestion["source"]; suggestions: Suggestion[] }>();
const removeMatching = StateEffect.define<string>(); // ignoreKey
const openCard = StateEffect.define<number | null>(); // position, or null to close

/** Findings that are "the same" for Ignore: same source, rule and text. */
export function ignoreKey(suggestion: Suggestion): string {
  return `${suggestion.source}\u0000${suggestion.rule ?? suggestion.category}\u0000${suggestion.original}`;
}

/** Move marks through an edit; drop the ones whose text was changed. */
export function mapMarks(marks: readonly Mark[], changes: ChangeDesc): Mark[] {
  const kept: Mark[] = [];
  for (const mark of marks) {
    if (changes.touchesRange(mark.from, mark.to)) continue;
    const from = changes.mapPos(mark.from, 1);
    const to = changes.mapPos(mark.to, -1);
    if (from < to) kept.push({ ...mark, from, to });
  }
  return kept;
}

/** Marks for new findings; findings that do not fit the document are skipped. */
export function toMarks(suggestions: readonly Suggestion[], docLength: number): Mark[] {
  return suggestions
    .filter((s) => s.start >= 0 && s.start < s.end && s.end <= docLength)
    .map((s) => ({ suggestion: s, from: s.start, to: s.end }));
}

export function markAt(marks: readonly Mark[], pos: number): Mark | null {
  return marks.find((m) => m.from <= pos && pos <= m.to) ?? null;
}

const marksField = StateField.define<Mark[]>({
  create: () => [],
  update(marks, tr) {
    let next = tr.docChanged ? mapMarks(marks, tr.changes) : marks;
    for (const effect of tr.effects) {
      if (effect.is(setSuggestions)) {
        const { source, suggestions } = effect.value;
        const others = next.filter((m) => m.suggestion.source !== source);
        next = [...others, ...toMarks(suggestions, tr.state.doc.length)];
      }
      if (effect.is(removeMatching)) next = next.filter((m) => ignoreKey(m.suggestion) !== effect.value);
    }
    return next;
  },
  provide: (field) =>
    EditorView.decorations.from(field, (marks): DecorationSet =>
      Decoration.set(
        marks.map((m) =>
          Decoration.mark({
            class: `cm-suggestion cm-suggestion-${m.suggestion.source}`,
            attributes: { "data-suggestion": m.suggestion.id },
          }).range(m.from, m.to),
        ),
        true,
      ),
    ),
});

// The keyboard-opened card (Ctrl+.). Closed by any edit, cursor move or Escape.
const cardField = StateField.define<number | null>({
  create: () => null,
  update(pos, tr) {
    for (const effect of tr.effects) if (effect.is(openCard)) return effect.value;
    return tr.docChanged || tr.selection ? null : pos;
  },
});

function card(view: EditorView, mark: Mark, handlers: SuggestionHandlers): HTMLElement {
  const { suggestion } = mark;
  const close = (): void => view.dispatch({ effects: openCard.of(null) });
  const fixes = suggestion.fixes ?? [];
  const buttons = fixes.map((fix, i) => {
    const button = el(
      "button",
      { type: "button", class: `suggestion-fix${i === 0 ? " primary" : ""}`, title: `Replace with "${fix}"` },
      fix === "" ? "(remove)" : fix,
    );
    button.addEventListener("click", () => {
      const current = view.state.field(marksField).find((m) => m.suggestion.id === suggestion.id);
      if (current === undefined || view.state.sliceDoc(current.from, current.to) !== suggestion.original) return;
      view.dispatch({
        changes: { from: current.from, to: current.to, insert: fix },
        userEvent: "input.suggestion",
        effects: openCard.of(null),
      });
      view.focus();
    });
    return button;
  });
  const ignore = el("button", { type: "button", class: "suggestion-action" }, "Ignore");
  ignore.addEventListener("click", () => {
    handlers.ignore(suggestion);
    view.dispatch({ effects: [removeMatching.of(ignoreKey(suggestion)), openCard.of(null)] });
    view.focus();
  });
  const actions = el("div", { class: "suggestion-actions" }, ignore);
  if (suggestion.source === "rule" && suggestion.category === "spelling") {
    const add = el("button", { type: "button", class: "suggestion-action" }, "Add to dictionary");
    add.addEventListener("click", () => {
      handlers.addToDictionary(suggestion);
      view.dispatch({ effects: [removeMatching.of(ignoreKey(suggestion)), openCard.of(null)] });
      view.focus();
    });
    actions.append(add);
  }
  const dom = el(
    "div",
    { class: `suggestion-card ${suggestion.source}`, role: "dialog", "aria-label": "Suggestion" },
    el("p", { class: "suggestion-reason" }, suggestion.reason),
  );
  if (buttons.length > 0) dom.append(el("div", { class: "suggestion-fixes", role: "group", "aria-label": "Replace with" }, ...buttons));
  else dom.append(el("p", { class: "suggestion-none" }, "No replacement offered."));
  dom.append(actions);
  dom.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      close();
      view.focus();
    }
  });
  return dom;
}

function tooltipFor(state: EditorState, pos: number, handlers: SuggestionHandlers): Tooltip | null {
  const mark = markAt(state.field(marksField), pos);
  if (mark === null) return null;
  return {
    pos: mark.from,
    end: mark.to,
    above: true,
    create: (view) => ({ dom: card(view, mark, handlers) }),
  };
}

export function suggestionLayer(handlers: SuggestionHandlers): Extension {
  return [
    marksField,
    cardField,
    hoverTooltip((view, pos) => tooltipFor(view.state, pos, handlers), { hideOnChange: true }),
    showTooltip.compute([cardField, marksField], (state) => {
      const pos = state.field(cardField);
      return pos === null ? null : tooltipFor(state, pos, handlers);
    }),
    keymap.of([
      {
        key: "Mod-.",
        preventDefault: true,
        run: (view) => {
          const pos = view.state.selection.main.head;
          if (markAt(view.state.field(marksField), pos) === null) return false;
          view.dispatch({ effects: openCard.of(pos) });
          // Move focus into the card so its buttons can be reached with Tab.
          requestAnimationFrame(() => view.dom.querySelector<HTMLButtonElement>(".suggestion-card button")?.focus());
          return true;
        },
      },
      {
        key: "Escape",
        run: (view) => {
          if (view.state.field(cardField) === null) return false;
          view.dispatch({ effects: openCard.of(null) });
          return true;
        },
      },
    ]),
  ];
}

export function marksOf(state: EditorState): readonly Mark[] {
  return state.field(marksField, false) ?? [];
}
