// App shell: top bar, three resizable columns (left split in two), status bar.

import { el, storage } from "../ui/dom";

export interface Shell {
  topbar: HTMLElement;
  files: HTMLElement;
  problems: HTMLElement;
  editor: HTMLElement;
  preview: HTMLElement;
  statusbar: HTMLElement;
}

interface SplitSpec {
  handle: HTMLElement;
  host: HTMLElement;
  cssVar: string;
  axis: "x" | "y";
  /** +1 when dragging right/down grows the panel, -1 when it shrinks it. */
  direction: 1 | -1;
  min: number;
  max: () => number;
  initial: number;
}

function makeSplitter(spec: SplitSpec): void {
  const key = `layout${spec.cssVar}`;
  const stored = Number(storage.get(key));
  let size = Number.isFinite(stored) && stored > 0 ? stored : spec.initial;
  const apply = (value: number): void => {
    size = Math.round(Math.max(spec.min, Math.min(spec.max(), value)));
    spec.host.style.setProperty(spec.cssVar, `${size}px`);
    spec.handle.setAttribute("aria-valuenow", String(size));
  };
  apply(size);

  spec.handle.addEventListener("pointerdown", (down: PointerEvent) => {
    down.preventDefault();
    spec.handle.setPointerCapture(down.pointerId);
    const start = spec.axis === "x" ? down.clientX : down.clientY;
    const startSize = size;
    spec.handle.classList.add("dragging");
    const move = (event: PointerEvent): void => {
      const now = spec.axis === "x" ? event.clientX : event.clientY;
      apply(startSize + spec.direction * (now - start));
    };
    const up = (): void => {
      spec.handle.classList.remove("dragging");
      spec.handle.removeEventListener("pointermove", move);
      storage.set(key, String(size));
    };
    spec.handle.addEventListener("pointermove", move);
    spec.handle.addEventListener("pointerup", up, { once: true });
    spec.handle.addEventListener("pointercancel", up, { once: true });
  });

  spec.handle.addEventListener("keydown", (event: KeyboardEvent) => {
    const grow = spec.axis === "x" ? ["ArrowRight", "ArrowLeft"] : ["ArrowDown", "ArrowUp"];
    const step = event.key === grow[0] ? 16 : event.key === grow[1] ? -16 : 0;
    if (step !== 0) {
      event.preventDefault();
      apply(size + spec.direction * step);
      storage.set(key, String(size));
    }
  });
}

function handle(orientation: "vertical" | "horizontal", label: string): HTMLElement {
  return el("div", {
    class: `splitter ${orientation}`,
    role: "separator",
    tabindex: "0",
    "aria-orientation": orientation,
    "aria-label": label,
  });
}

export function buildShell(root: HTMLElement): Shell {
  const topbar = el("header", { class: "topbar" });
  const files = el("section", { class: "files", "aria-label": "Files" });
  const problems = el("section", { class: "problems", "aria-label": "Problems" });
  const sidebarSplit = handle("horizontal", "Resize problems panel");
  const sidebar = el("aside", { class: "sidebar" }, files, sidebarSplit, problems);
  const leftSplit = handle("vertical", "Resize file panel");
  const editor = el("main", { class: "editor-area" });
  const rightSplit = handle("vertical", "Resize preview");
  const preview = el("section", { class: "preview", "aria-label": "Rendered document" });
  const workbench = el("div", { class: "workbench" }, sidebar, leftSplit, editor, rightSplit, preview);
  const statusbar = el("footer", { class: "statusbar" });
  root.append(topbar, workbench, statusbar);

  makeSplitter({
    handle: leftSplit, host: workbench, cssVar: "--left-width", axis: "x", direction: 1,
    min: 160, max: () => workbench.clientWidth * 0.4, initial: 240,
  });
  makeSplitter({
    handle: rightSplit, host: workbench, cssVar: "--right-width", axis: "x", direction: -1,
    min: 280, max: () => workbench.clientWidth * 0.65, initial: Math.round(window.innerWidth * 0.42),
  });
  makeSplitter({
    handle: sidebarSplit, host: sidebar, cssVar: "--problems-height", axis: "y", direction: -1,
    min: 80, max: () => sidebar.clientHeight - 120, initial: 220,
  });
  return { topbar, files, problems, editor, preview, statusbar };
}
