// Phase 0 placeholder: proves frontend ↔ backend wiring. Replaced by the full layout in Phase 1.
import { getHealth } from "./api/client";

const status = document.querySelector<HTMLElement>("#status");

async function showHealth(target: HTMLElement): Promise<void> {
  try {
    const health = await getHealth();
    target.textContent = `Backend connected · Typst ${health.typst_version}`;
  } catch (error: unknown) {
    target.textContent = `Backend not reachable: ${error instanceof Error ? error.message : String(error)}`;
  }
}

if (status) {
  void showHealth(status);
}
