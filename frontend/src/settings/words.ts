// Settings → Words: the words the spelling check accepts in the open project, per language.
// (Later also the terms an AI must keep as written.)

import { api } from "../api/client";
import type { GrammarSettings } from "../api/types";
import type { AppState, Language, Store } from "../state/store";
import { el } from "../ui/dom";
import { iconNode, icons } from "../ui/icons";

const LANGUAGES: { value: Language; label: string }[] = [
  { value: "de-DE", label: "German" },
  { value: "en-US", label: "English" },
];

/** Same rule as the backend: one word, no spaces, at most 100 characters. */
export function wordError(word: string, existing: readonly string[]): string | null {
  if (word === "") return "Type a word first.";
  if (/\s/.test(word)) return "One word at a time (no spaces).";
  if (word.length > 100) return "Words can have at most 100 characters.";
  if (existing.includes(word)) return `"${word}" is already in the list.`;
  return null;
}

export function wordsSection(store: Store<AppState>): HTMLElement {
  const section = el("section", { class: "settings-section words-section" }, el("h3", {}, "Words in this project"));
  const workspace = store.get().workspace;
  if (workspace === null) {
    section.append(el("p", { class: "setting-hint" }, "Open a folder to manage the words its spelling check accepts."));
    return section;
  }
  section.append(
    el(
      "p",
      { class: "setting-hint" },
      `The spelling check accepts these words in ${workspace.name}. Add terms from your field, names and abbreviations.`,
    ),
  );

  let language: Language = store.get().language;
  let dictionary: GrammarSettings["dictionary"] = {};
  const words = (): string[] => dictionary[language] ?? [];

  const tabs = el("div", { class: "segmented", role: "radiogroup", "aria-label": "Language of the word list" });
  for (const { value, label } of LANGUAGES) {
    const input = el("input", { type: "radio", name: "words-language", value });
    input.checked = value === language;
    input.addEventListener("change", () => {
      language = value;
      render();
    });
    tabs.append(el("label", { class: "segment" }, input, el("span", {}, label)));
  }

  const filter = el("input", { type: "search", class: "text-input words-filter", placeholder: "Search", "aria-label": "Search the word list" });
  const newWord = el("input", { type: "text", class: "text-input", placeholder: "New word", "aria-label": "New word", maxlength: "100" });
  const add = el("button", { type: "submit", class: "button" }, "Add");
  const error = el("p", { class: "dialog-error", role: "alert" });
  const form = el("form", { class: "words-add" }, newWord, add);
  const count = el("span", { class: "setting-status" });
  const list = el("ul", { class: "words-list", "aria-label": "Accepted words" });

  const apply = (overview: { settings: GrammarSettings }): void => {
    dictionary = overview.settings.dictionary;
    render();
  };

  const render = (): void => {
    const all = words();
    const query = filter.value.trim().toLocaleLowerCase();
    const shown = query === "" ? all : all.filter((w) => w.toLocaleLowerCase().includes(query));
    count.textContent = all.length === 1 ? "1 word" : `${all.length} words`;
    list.replaceChildren();
    if (all.length === 0) {
      list.append(el("li", { class: "words-empty" }, "No words yet. Add one above, or choose Add to dictionary on an underlined word."));
      return;
    }
    if (shown.length === 0) {
      list.append(el("li", { class: "words-empty" }, `No word contains "${filter.value.trim()}".`));
      return;
    }
    for (const word of shown) {
      const remove = el("button", { type: "button", class: "word-remove", title: `Remove "${word}"`, "aria-label": `Remove ${word}` }, iconNode(icons.close));
      remove.addEventListener("click", () => {
        api.removeFromDictionary(language, word).then(apply).catch((e: unknown) => {
          error.textContent = e instanceof Error ? e.message : String(e);
        });
      });
      list.append(el("li", { class: "word" }, el("span", {}, word), remove));
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const word = newWord.value.trim();
    const problem = wordError(word, words());
    error.textContent = problem ?? "";
    if (problem !== null) return;
    api
      .addToDictionary(language, word)
      .then((overview) => {
        newWord.value = "";
        apply(overview);
      })
      .catch((e: unknown) => {
        error.textContent = e instanceof Error ? e.message : String(e);
      });
  });
  filter.addEventListener("input", render);

  section.append(
    el("div", { class: "words-toolbar" }, tabs, count),
    form,
    error,
    filter,
    list,
  );
  api
    .grammar()
    .then(apply)
    .catch(() => {
      error.textContent = "Could not load the word list.";
    });
  render();
  return section;
}
