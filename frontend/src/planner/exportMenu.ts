// Export: a Typst figure (plans/<name>.typ, included into the document and regenerated on
// every save) or a PlantUML diagram (plans/<name>.puml).

import { ApiError, api } from "../api/client";
import type { PlanDocument, PlanExportKind, PlanExportResult } from "../api/types";
import { showContextMenu } from "../ui/contextMenu";
import { confirmAction, showMessage } from "../ui/dialog";
import { basename, el } from "../ui/dom";

export interface ExportContext {
  /** Flush pending changes first, so the export shows what is on screen. */
  flush(): Promise<void>;
  /** The .typ file the editor showed last (where the include line can go), if any. */
  targetFile(): string | null;
  /** Insert `line` at the cursor of `path` and show it; false if that is not possible. */
  insert(path: string, line: string): Promise<boolean>;
  notify(text: string): void;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function exportOnce(name: string, kind: PlanExportKind): Promise<PlanExportResult | null> {
  try {
    return await api.exportPlan(name, kind);
  } catch (error) {
    if (!(error instanceof ApiError && error.code === "exists")) throw error;
  }
  const file = `plans/${name}.${kind === "typst" ? "typ" : "puml"}`;
  const replace = await confirmAction("Replace file?", `${file} already exists and was not made by the planner. Replace it?`, "Replace", "danger");
  return replace ? api.exportPlan(name, kind, true) : null;
}

/** After the Typst export: the line to add, with Copy and (if possible) Insert. */
function includeDialog(result: PlanExportResult, line: string, ctx: ExportContext): void {
  const target = ctx.targetFile();
  const dialog = el("dialog", { class: "dialog include-dialog", "aria-labelledby": "include-title" });
  const code = el("code", {}, line);
  const copy = el("button", { type: "button", class: "button" }, "Copy");
  copy.addEventListener("click", () => {
    void navigator.clipboard.writeText(line).then(() => {
      copy.textContent = "Copied";
    });
  });
  const close = el("button", { type: "button", class: "button" }, "Close");
  close.addEventListener("click", () => dialog.close());
  const buttons = el("div", { class: "dialog-buttons" }, close, copy);
  if (target !== null) {
    const insert = el("button", { type: "button", class: "button primary" }, `Insert into ${basename(target)}`);
    insert.addEventListener("click", () => {
      dialog.close();
      void ctx.insert(target, line).then(async (ok) => {
        if (!ok) await showMessage("Could not insert the figure", `Open ${target} and paste the line instead.`);
      });
    });
    buttons.append(insert);
  }
  dialog.append(
    el("h2", { id: "include-title" }, `Saved ${result.path}`),
    el(
      "p",
      {},
      target === null
        ? "Put this line into your document where the plan should appear. The figure follows every change to the plan."
        : `Put this line into your document where the plan should appear; Insert adds it at the cursor in ${basename(target)}. The figure follows every change to the plan.`,
    ),
    el("pre", { class: "include-line" }, code),
    buttons,
  );
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
  (target === null ? copy : (buttons.lastElementChild as HTMLButtonElement)).focus();
}

export function showExportMenu(anchor: HTMLElement, doc: PlanDocument, ctx: ExportContext): void {
  const run = async (kind: PlanExportKind): Promise<void> => {
    try {
      await ctx.flush();
      const result = await exportOnce(doc.name, kind);
      if (result === null) return;
      if (kind === "typst" && result.include !== null) includeDialog(result, result.include, ctx);
      else ctx.notify(`Saved ${result.path}`);
    } catch (error) {
      await showMessage("Export failed", errorText(error));
    }
  };
  const rect = anchor.getBoundingClientRect();
  showContextMenu(rect.left, rect.bottom + 4, [
    { label: `Typst figure (plans/${doc.name}.typ)`, action: () => void run("typst") },
    { label: `PlantUML diagram (plans/${doc.name}.puml)`, action: () => void run("plantuml") },
  ]);
}
