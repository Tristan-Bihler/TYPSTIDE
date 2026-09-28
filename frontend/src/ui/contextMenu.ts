// Right-click menu. Closes on selection, Escape, outside click or scroll.

import { el } from "./dom";

export interface MenuItem {
  label: string;
  action: () => void;
  danger?: boolean;
  /** Shown but not clickable; the text explains why (tooltip). */
  disabledReason?: string;
}

let current: HTMLElement | null = null;

function closeMenu(): void {
  current?.remove();
  current = null;
}

export function showContextMenu(x: number, y: number, items: (MenuItem | "separator")[]): void {
  closeMenu();
  const menu = el("div", { class: "context-menu", role: "menu" });
  for (const item of items) {
    if (item === "separator") {
      menu.append(el("div", { class: "context-separator", role: "separator" }));
      continue;
    }
    const button = el(
      "button",
      { type: "button", role: "menuitem", class: item.danger ? "danger" : "" },
      item.label,
    );
    if (item.disabledReason !== undefined) {
      button.disabled = true;
      button.title = item.disabledReason;
    }
    button.addEventListener("click", () => {
      closeMenu();
      item.action();
    });
    menu.append(button);
  }
  menu.addEventListener("keydown", (event) => {
    const buttons = [...menu.querySelectorAll("button")].filter((b) => !b.disabled);
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") closeMenu();
    if (event.key === "ArrowDown") buttons[(index + 1) % buttons.length]?.focus();
    if (event.key === "ArrowUp") buttons[(index - 1 + buttons.length) % buttons.length]?.focus();
    if (["Escape", "ArrowDown", "ArrowUp"].includes(event.key)) event.preventDefault();
  });
  document.body.append(menu);
  const { innerWidth, innerHeight } = window;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(x, innerWidth - rect.width - 4)}px`;
  menu.style.top = `${Math.min(y, innerHeight - rect.height - 4)}px`;
  current = menu;
  menu.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
}

document.addEventListener("pointerdown", (event) => {
  if (current && !current.contains(event.target as Node)) closeMenu();
});
window.addEventListener("blur", closeMenu);
window.addEventListener("resize", closeMenu);
