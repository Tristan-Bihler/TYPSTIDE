// Rendered main document, page by page. Pages are shown as <img> with SVG blob URLs, so
// nothing inside a page (links, scripts) can run in the app. Only changed pages are swapped.

import type { PageUpdate } from "../api/types";
import type { AppState, Store } from "../state/store";
import { el, storage } from "../ui/dom";

const PT_TO_PX = 96 / 72;
const ZOOM_KEY = "preview.zoom";
const ZOOM_STEPS = [0.5, 0.67, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3];

interface Page {
  hash: string;
  url: string;
  widthPx: number;
  heightPx: number;
  node: HTMLElement;
  img: HTMLImageElement;
}

/** Page size in CSS pixels from the SVG's width/height attributes (given in pt). */
export function svgSize(svg: string): { width: number; height: number } {
  const head = svg.slice(0, 400);
  const width = /width="([\d.]+)pt"/.exec(head)?.[1];
  const height = /height="([\d.]+)pt"/.exec(head)?.[1];
  return {
    width: width === undefined ? 794 : Number(width) * PT_TO_PX,
    height: height === undefined ? 1123 : Number(height) * PT_TO_PX,
  };
}

export class PreviewPane {
  private pages: Page[] = [];
  private zoom: number | "fit";
  private readonly desk: HTMLElement;
  private readonly pagesHost: HTMLElement;
  private readonly message: HTMLElement;
  private readonly banner: HTMLElement;
  private readonly zoomLabel: HTMLElement;

  constructor(host: HTMLElement, store: Store<AppState>) {
    const stored = storage.get(ZOOM_KEY);
    this.zoom = stored === null || stored === "fit" || !Number(stored) ? "fit" : Number(stored);

    const zoomOut = el("button", { type: "button", class: "tool icon-only", title: "Zoom out", "aria-label": "Zoom out" }, "−");
    const zoomIn = el("button", { type: "button", class: "tool icon-only", title: "Zoom in", "aria-label": "Zoom in" }, "+");
    const fit = el("button", { type: "button", class: "tool", title: "Fit page width to the panel" }, "Fit width");
    this.zoomLabel = el("span", { class: "zoom-label", "aria-live": "polite" });
    zoomOut.addEventListener("click", () => this.step(-1));
    zoomIn.addEventListener("click", () => this.step(1));
    fit.addEventListener("click", () => this.setZoom("fit"));

    this.banner = el("div", { class: "preview-banner", role: "status", hidden: "" });
    this.message = el("div", { class: "preview-message" });
    this.pagesHost = el("div", { class: "pages" });
    this.desk = el("div", { class: "desk" }, this.banner, this.message, this.pagesHost);
    host.append(el("div", { class: "preview-toolbar" }, zoomOut, this.zoomLabel, zoomIn, fit), this.desk);

    new ResizeObserver(() => {
      if (this.zoom === "fit") this.layout();
    }).observe(this.desk);
    this.layout();

    store.subscribe((state) => this.renderState(state));
  }

  apply(updates: PageUpdate[]): void {
    updates.forEach((update, index) => {
      const existing = this.pages[index];
      // null: unchanged. The server forgets its page hashes whenever the client clears
      // the preview, so an unchanged page is always one we still have.
      if (update.svg === null) return;
      const url = URL.createObjectURL(new Blob([update.svg], { type: "image/svg+xml" }));
      const size = svgSize(update.svg);
      if (existing) {
        const oldUrl = existing.url;
        existing.img.addEventListener("load", () => URL.revokeObjectURL(oldUrl), { once: true });
        existing.img.src = url;
        Object.assign(existing, { hash: update.hash, url, widthPx: size.width, heightPx: size.height });
      } else {
        const img = el("img", { alt: `Page ${index + 1}`, draggable: "false" });
        img.src = url;
        const node = el("div", { class: "page" }, img);
        this.pagesHost.append(node);
        this.pages.push({ hash: update.hash, url, widthPx: size.width, heightPx: size.height, node, img });
      }
    });
    for (const page of this.pages.splice(updates.length)) {
      URL.revokeObjectURL(page.url);
      page.node.remove();
    }
    this.layout();
  }

  clear(): void {
    this.apply([]);
  }

  private renderState(state: AppState): void {
    const { compile } = state;
    const errors = state.problems.filter((p) => p.severity === "error").length;
    const stale = compile.state === "error" && this.pages.length > 0;
    this.desk.classList.toggle("stale", stale);
    this.banner.hidden = !stale;
    this.banner.textContent = stale
      ? `Showing the last version that compiled. Fix ${errors === 1 ? "the error" : `the ${errors} errors`} under Problems to update it.`
      : "";

    let text = "";
    if (compile.state === "no_workspace") text = "Open a folder to see its main document here.";
    else if (compile.state === "no_main") {
      text = "There is no main file yet. Right-click a .typ file on the left and choose Set as main file.";
    } else if (this.pages.length === 0 && compile.state === "error") {
      text = "The document has errors, so there is nothing to show yet. See Problems on the left.";
    } else if (this.pages.length === 0) text = "Rendering…";
    this.message.textContent = text;
    this.message.hidden = text === "";
    if (compile.state === "no_workspace" || compile.state === "no_main") this.clear();
  }

  private step(direction: 1 | -1): void {
    const current = this.effectiveZoom();
    const next =
      direction > 0
        ? ZOOM_STEPS.find((z) => z > current + 0.001)
        : [...ZOOM_STEPS].reverse().find((z) => z < current - 0.001);
    this.setZoom(next ?? current);
  }

  private setZoom(zoom: number | "fit"): void {
    this.zoom = zoom;
    storage.set(ZOOM_KEY, String(zoom));
    this.layout();
  }

  private effectiveZoom(): number {
    if (this.zoom !== "fit") return this.zoom;
    const widest = Math.max(...this.pages.map((p) => p.widthPx), 794);
    const available = this.desk.clientWidth - 48;
    return available > 0 ? available / widest : 1;
  }

  private layout(): void {
    const zoom = this.effectiveZoom();
    for (const page of this.pages) {
      page.node.style.width = `${Math.round(page.widthPx * zoom)}px`;
      page.node.style.height = `${Math.round(page.heightPx * zoom)}px`;
    }
    this.zoomLabel.textContent = `${Math.round(zoom * 100)} %`;
  }
}
