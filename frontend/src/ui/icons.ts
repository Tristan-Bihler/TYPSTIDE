// 16 px stroke icons (trusted constants, inserted as SVG markup).

const svg = (body: string): string =>
  `<svg class="icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;

export const icons = {
  newFile: svg('<path d="M9 1.5H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5.5z"/><path d="M9 1.5v4h4M8 8v4M6 10h4"/>'),
  newFolder: svg('<path d="M1.5 4a1 1 0 0 1 1-1h3.5l1.5 1.5h6a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z"/><path d="M8 7v4M6 9h4"/>'),
  openFolder: svg('<path d="M1.5 12V4a1 1 0 0 1 1-1h3.5l1.5 1.5h5a1 1 0 0 1 1 1V7"/><path d="M1.5 12l2-5h11l-2 5.5h-10a1 1 0 0 1-1-.5z"/>'),
  save: svg('<path d="M2.5 2.5h9l2 2v9h-11z"/><path d="M5 2.5v3.5h5V2.5M5 13.5V9.5h6v4"/>'),
  exportPdf: svg('<path d="M8 1.5v8M5 6.5l3 3 3-3"/><path d="M2.5 10.5v3h11v-3"/>'),
  chevron: svg('<path d="M6 4l4 4-4 4"/>'),
  file: svg('<path d="M9 1.5H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5.5z"/><path d="M9 1.5v4h4"/>'),
  folder: svg('<path d="M1.5 4a1 1 0 0 1 1-1h3.5l1.5 1.5h6a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z"/>'),
  close: svg('<path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/>'),
  error: svg('<circle cx="8" cy="8" r="6"/><path d="M8 4.8v3.7M8 11v.2"/>'),
  warning: svg('<path d="M8 2l6.5 11.5h-13z"/><path d="M8 6.5v3M8 11.5v.2"/>'),
  spelling: svg('<path d="M3 9.5l2.5-6.5 2.5 6.5M3.9 7.3h3.2"/><path d="M1.5 13c1.1-1 2.1 1 3.2 0s2.1 1 3.2 0 2.1 1 3.2 0 2.1 1 3.4 0"/>'),
  localAi: svg('<path d="M8 2l1.4 3.6L13 7l-3.6 1.4L8 12l-1.4-3.6L3 7l3.6-1.4z"/><path d="M12.5 11.5l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6z"/>'),
  up: svg('<path d="M8 13V3M4 7l4-4 4 4"/>'),
};

export function iconNode(markup: string): Element {
  const template = document.createElement("template");
  template.innerHTML = markup;
  const node = template.content.firstElementChild;
  if (!node) throw new Error("invalid icon markup");
  return node;
}
