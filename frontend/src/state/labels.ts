// Label suggestions for the insert dialogs. Mirrors slugify/make_label in
// backend/src/typst_writer/domain/typst_text.py (the backend checks again on insert).

const TRANSLITERATE: Record<string, string> = { ä: "ae", ö: "oe", ü: "ue", ß: "ss" };

export const LABEL_RE = /^[\p{L}\p{N}][\p{L}\p{N}_.:-]*$/u;

export function slugify(text: string, maxLength = 40): string {
  const lowered = text.toLowerCase().replace(/[äöüß]/g, (c) => TRANSLITERATE[c] ?? c);
  const ascii = lowered.normalize("NFKD").replace(/[^\x00-\x7f]/g, "");
  return ascii
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, maxLength)
    .replace(/-+$/, "");
}

export function suggestLabel(prefix: string, text: string, existing: ReadonlySet<string>): string {
  const base = `${prefix}:${slugify(text) || prefix}`;
  let label = base;
  for (let n = 2; existing.has(label); n++) label = `${base}-${n}`;
  return label;
}

export function labelError(label: string, existing: ReadonlySet<string>): string | null {
  if (label === "") return null;
  if (!LABEL_RE.test(label)) return "Labels may contain letters, digits and _ - . : only.";
  if (existing.has(label)) return `The label <${label}> is already used.`;
  return null;
}
