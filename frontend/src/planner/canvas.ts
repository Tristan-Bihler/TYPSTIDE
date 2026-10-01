// The plan as boxes and arrows (Cytoscape.js). Drag boxes, zoom with the wheel, pan by
// dragging the background. A click selects a step; Shift-click one step, then another,
// to make the second depend on the first (again to remove it).

import cytoscape, { type Core, type EventObject, type NodeSingular, type StylesheetJson } from "cytoscape";

import type { Plan } from "../api/types";
import { toElements } from "./model";

export interface CanvasCallbacks {
  onSelect(id: string | null): void;
  /** After a drag ends: the positions of every step. */
  onMoved(positions: Map<string, { x: number; y: number }>): void;
  /** Shift-click on `from`, then on `to`: toggle "`to` depends on `from`". */
  onLink(from: string, to: string): void;
}

const GRID = 24; // canvas pixels between the background dots
const FIT_PADDING = 48;
const MAX_FIT_ZOOM = 1.2;
const MIN_READABLE_ZOOM = 0.55;

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888888";
}

function stylesheet(): StylesheetJson {
  const font = token("--font-ui");
  return [
    {
      selector: "node",
      style: {
        shape: "round-rectangle",
        width: 184,
        height: 58,
        "corner-radius": "6px",
        "background-color": token("--paper"),
        "border-width": 1,
        "border-color": token("--rule"),
        label: "data(label)",
        "text-wrap": "ellipsis",
        "text-max-width": "164px",
        "text-valign": "center",
        "text-halign": "center",
        "font-family": font,
        "font-size": 13,
        color: token("--ink"),
        "overlay-opacity": 0,
        "underlay-opacity": 0,
        "underlay-color": token("--accent"),
        "underlay-padding": 5,
        "underlay-shape": "round-rectangle",
      },
    },
    {
      selector: 'node[status = "doing"]',
      style: { "border-width": 2, "border-color": token("--accent"), "font-weight": 600 },
    },
    {
      selector: 'node[status = "done"]',
      style: { "background-color": token("--chrome"), color: token("--pencil") },
    },
    { selector: "node:selected", style: { "underlay-opacity": 0.2 } },
    {
      selector: "node.link-source",
      style: { "border-style": "dashed", "border-width": 2, "border-color": token("--accent") },
    },
    {
      selector: "edge",
      style: {
        width: 1.4,
        "curve-style": "bezier",
        "line-color": token("--pencil"),
        "target-arrow-shape": "triangle",
        "target-arrow-color": token("--pencil"),
        "arrow-scale": 0.9,
        "overlay-opacity": 0,
      },
    },
    { selector: "edge.related", style: { "line-color": token("--accent"), "target-arrow-color": token("--accent"), width: 2 } },
  ];
}

export class PlanCanvas {
  private readonly cy: Core;
  private linkFrom: string | null = null;
  private fitted = false;

  constructor(
    private readonly host: HTMLElement,
    private readonly callbacks: CanvasCallbacks,
  ) {
    this.cy = cytoscape({
      container: host,
      style: stylesheet(),
      boxSelectionEnabled: false,
      selectionType: "single",
      minZoom: 0.2,
      maxZoom: 2.5,
    });
    this.cy.on("tap", "node", (event: EventObject) => this.tapNode(event));
    this.cy.on("tap", (event: EventObject) => {
      if (event.target !== this.cy) return;
      this.setLinkFrom(null);
      this.callbacks.onSelect(null);
    });
    this.cy.on("dragfree", "node", () => {
      const positions = new Map<string, { x: number; y: number }>();
      this.cy.nodes().forEach((node) => {
        positions.set(node.id(), { ...node.position() });
      });
      this.callbacks.onMoved(positions);
    });
    this.cy.on("viewport", () => this.moveGrid());
    this.moveGrid();
  }

  private tapNode(event: EventObject): void {
    const node = event.target as NodeSingular;
    const shift = (event.originalEvent as MouseEvent | undefined)?.shiftKey === true;
    if (!shift) {
      this.setLinkFrom(null);
      this.callbacks.onSelect(node.id());
      return;
    }
    if (this.linkFrom === null) {
      this.setLinkFrom(node.id());
    } else if (this.linkFrom === node.id()) {
      this.setLinkFrom(null);
    } else {
      const from = this.linkFrom;
      this.setLinkFrom(null);
      this.callbacks.onLink(from, node.id());
    }
  }

  private setLinkFrom(id: string | null): void {
    this.cy.nodes(".link-source").removeClass("link-source");
    this.linkFrom = id;
    if (id !== null) this.cy.getElementById(id).addClass("link-source");
    this.host.classList.toggle("linking", id !== null);
  }

  /** The dot grid moves and scales with the plan, like paper under the boxes. */
  private moveGrid(): void {
    const zoom = this.cy.zoom();
    const pan = this.cy.pan();
    this.host.style.backgroundSize = `${GRID * zoom}px ${GRID * zoom}px`;
    this.host.style.backgroundPosition = `${pan.x}px ${pan.y}px`;
  }

  /** Show `plan`, keeping zoom, pan and anything being dragged. */
  render(plan: Plan, selected: string | null): void {
    const { nodes, edges } = toElements(plan);
    const wanted = new Set([...nodes.map((n) => n.data.id), ...edges.map((e) => e.data.id)]);
    this.cy.batch(() => {
      this.cy.elements().forEach((element) => {
        if (!wanted.has(element.id())) element.remove();
      });
      for (const node of nodes) {
        const existing = this.cy.getElementById(node.data.id);
        if (existing.empty()) {
          this.cy.add({ group: "nodes", ...node });
        } else {
          existing.data(node.data);
          if (!existing.grabbed()) existing.position(node.position);
        }
      }
      for (const edge of edges) {
        if (this.cy.getElementById(edge.data.id).empty()) this.cy.add({ group: "edges", ...edge });
      }
    });
    if (this.linkFrom !== null && !wanted.has(this.linkFrom)) this.setLinkFrom(null);
    this.select(selected);
    if (!this.fitted && nodes.length > 0) {
      this.fit();
      this.fitted = true;
    }
  }

  select(id: string | null): void {
    this.cy.batch(() => {
      this.cy.elements(":selected").unselect();
      this.cy.edges(".related").removeClass("related");
      if (id === null) return;
      const node = this.cy.getElementById(id);
      node.select();
      node.connectedEdges().addClass("related");
    });
  }

  /** Bring a step into view (a new step, or one chosen in the Next list): show the whole
   * plan if it still fits legibly, else centre the step. */
  reveal(id: string): void {
    const node = this.cy.getElementById(id);
    if (node.empty()) return;
    const box = node.renderedBoundingBox();
    const inside = box.x1 >= 0 && box.y1 >= 0 && box.x2 <= this.cy.width() && box.y2 <= this.cy.height();
    if (inside) return;
    const whole = this.fitView();
    if (whole.zoom >= MIN_READABLE_ZOOM) this.cy.animate(whole, { duration: 200 });
    else this.cy.animate({ center: { eles: node } }, { duration: 200 });
  }

  /** Zoom and pan that show every step (never closer than 120 %). */
  private fitView(): { zoom: number; pan: { x: number; y: number } } {
    const box = this.cy.elements().boundingBox();
    const width = this.cy.width();
    const height = this.cy.height();
    const zoom = Math.min(MAX_FIT_ZOOM, (width - 2 * FIT_PADDING) / Math.max(box.w, 1), (height - 2 * FIT_PADDING) / Math.max(box.h, 1));
    return { zoom, pan: { x: width / 2 - zoom * (box.x1 + box.w / 2), y: height / 2 - zoom * (box.y1 + box.h / 2) } };
  }

  fit(): void {
    this.cy.resize();
    if (this.cy.elements().empty()) return;
    this.cy.viewport(this.fitView());
    this.moveGrid();
  }

  /** The visible centre in plan coordinates (where new steps without a neighbour go). */
  center(): { x: number; y: number } {
    const extent = this.cy.extent();
    return { x: (extent.x1 + extent.x2) / 2, y: (extent.y1 + extent.y2) / 2 };
  }

  zoomBy(factor: number): void {
    const level = Math.min(2.5, Math.max(0.2, this.cy.zoom() * factor));
    this.cy.zoom({ level, renderedPosition: { x: this.cy.width() / 2, y: this.cy.height() / 2 } });
  }

  /** Re-read the colour tokens (theme changed). */
  restyle(): void {
    this.cy.style(stylesheet());
  }

  resize(): void {
    this.cy.resize();
  }

  destroy(): void {
    this.cy.destroy();
  }
}
