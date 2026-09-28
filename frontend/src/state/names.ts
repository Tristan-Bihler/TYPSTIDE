// Client-side mirror of infra/paths.py name rules, for instant feedback in dialogs.
// The backend validates again; this only avoids a round trip.

const NAME_RE = /^[\p{L}\p{N}_\- .()+,]+$/u;
const RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$/i;

export function nameError(name: string, kind: "file" | "folder"): string | null {
  if (name.length === 0) return "Enter a name.";
  if (name.length > 120) return "Names can be at most 120 characters long.";
  if (name.startsWith(".") || name.endsWith(".")) return "Names cannot start or end with a dot.";
  if (!NAME_RE.test(name)) return "Use only letters, digits, spaces and - _ . ( ) + ,";
  if (RESERVED.test(name)) return `"${name}" is a reserved name on Windows.`;
  if (kind === "file" && !name.toLowerCase().endsWith(".typ")) return "File names must end with .typ.";
  return null;
}

/** Adds ".typ" when the user typed a bare name, so "kapitel-1" becomes "kapitel-1.typ". */
export function withTypExtension(name: string): string {
  return /\.[^.\s]+$/.test(name) ? name : `${name}.typ`;
}

/** Maps an old path to its new path after renaming `from` to `to` (file or folder). */
export function movedPath(path: string, from: string, to: string): string | null {
  if (path === from) return to;
  if (path.startsWith(`${from}/`)) return to + path.slice(from.length);
  return null;
}
