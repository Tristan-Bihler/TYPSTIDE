// AI selector (bottom-right). Phase 1: both slots fixed to "None"; Phase 3 wires up
// the settings service, Ollama models and Claude models.

import { el } from "../ui/dom";

function slot(label: string, reason: string): HTMLElement {
  const select = el("select", { class: "status-select", disabled: "", title: reason, "aria-label": label });
  select.append(el("option", { value: "" }, "None"));
  return el("label", { class: "ai-slot", title: reason }, el("span", {}, label), select);
}

export function mountAiSelector(host: HTMLElement): void {
  const reason = "AI assistance is not set up yet. The editor works fully without it.";
  host.append(
    el("div", { class: "ai-selector", role: "group", "aria-label": "AI assistance" }, slot("Local AI", reason), slot("Claude", reason)),
  );
}
