// AI selector (bottom-right): two independent slots. Local AI = Ollama (Phase 5);
// Claude = the logged-in `claude` command, drives the on-demand review.

import { api } from "../api/client";
import type { AIOverview, AIStatus } from "../api/types";
import type { AppState, Store } from "../state/store";
import { showMessage } from "../ui/dialog";
import { el } from "../ui/dom";

function fill(select: HTMLSelectElement, status: AIStatus, selected: string | null): void {
  select.replaceChildren(el("option", { value: "" }, "None"));
  for (const model of status.models) select.append(el("option", { value: model }, model));
  select.disabled = !status.available || status.models.length === 0;
  select.value = status.available && selected !== null && status.models.includes(selected) ? selected : "";
  const reason = status.available ? "" : status.reason;
  select.title = reason;
  select.parentElement?.setAttribute("title", reason);
}

export function mountAiSelector(host: HTMLElement, store: Store<AppState>): void {
  const local = el("select", { class: "status-select", "aria-label": "Local AI" });
  const claude = el("select", { class: "status-select", "aria-label": "Claude" });
  host.append(
    el(
      "div",
      { class: "ai-selector", role: "group", "aria-label": "AI assistance" },
      el("label", { class: "ai-slot" }, el("span", {}, "Local AI"), local),
      el("label", { class: "ai-slot" }, el("span", {}, "Claude"), claude),
    ),
  );

  const load = async (refresh: boolean): Promise<void> => {
    try {
      store.set({ ai: await api.aiStatus(refresh) });
    } catch {
      // Backend not reachable yet; the status bar already says so.
    }
  };

  claude.addEventListener("change", () => {
    const settings = { local_model: store.get().ai?.settings.local_model ?? null, claude_model: claude.value || null };
    api
      .setAiSettings(settings)
      .then((ai: AIOverview) => store.set({ ai }))
      .catch(async (error: unknown) => {
        await showMessage("Could not select this model", error instanceof Error ? error.message : String(error));
        void load(true);
      });
  });
  // Re-check when the window gets focus again, e.g. after `claude auth login` in a terminal.
  window.addEventListener("focus", () => void load(true));

  store.subscribe((state, previous) => {
    if (state !== previous && state.ai === previous.ai) return;
    if (state.ai === null) {
      fill(local, { available: false, reason: "Checking…", models: [] }, null);
      fill(claude, { available: false, reason: "Checking…", models: [] }, null);
      return;
    }
    fill(local, state.ai.local, state.ai.settings.local_model);
    fill(claude, state.ai.claude, state.ai.settings.claude_model);
  });
  void load(false);
}
