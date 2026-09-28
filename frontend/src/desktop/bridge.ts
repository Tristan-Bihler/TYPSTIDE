// The Windows app's bridge to Python (pywebview's `window.pywebview.api`, see
// backend/src/typst_writer/desktop.py DesktopApi). In a normal browser there is none and
// the app keeps its web dialogs.

interface PywebviewApi {
  pick_folder(start: string): Promise<string | null>;
  save_pdf(filename: string, data: string): Promise<string | null>;
  set_unsaved(unsaved: boolean): Promise<void>;
}

export interface DesktopHost extends EventTarget {
  pywebview?: { api?: Partial<PywebviewApi> };
}

export interface DesktopBridge {
  /** The native folder dialog; the chosen folder or null. */
  pickFolder(start: string | null): Promise<string | null>;
  /** The native Save dialog for a PDF; where it was saved, or null if cancelled. */
  savePdf(filename: string, pdf: Blob): Promise<string | null>;
  /** Whether closing the window should ask first. */
  setUnsaved(unsaved: boolean): void;
}

/** Base64 of the blob's bytes (chunked: large PDFs would overflow the argument list). */
export async function toBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function complete(api: Partial<PywebviewApi> | undefined): api is PywebviewApi {
  return (
    typeof api?.pick_folder === "function" &&
    typeof api.save_pdf === "function" &&
    typeof api.set_unsaved === "function"
  );
}

function bridge(api: PywebviewApi): DesktopBridge {
  return {
    pickFolder: (start) => api.pick_folder(start ?? ""),
    savePdf: async (filename, pdf) => api.save_pdf(filename, await toBase64(pdf)),
    setUnsaved: (unsaved) => {
      api.set_unsaved(unsaved).catch(() => {
        // The window is closing; nothing to do.
      });
    },
  };
}

/** Calls `ready` once pywebview's API is available (at once if it already is). */
export function onDesktopBridge(host: DesktopHost, ready: (bridge: DesktopBridge) => void): void {
  let done = false;
  const check = (): void => {
    const api = host.pywebview?.api;
    if (done || !complete(api)) return;
    done = true;
    ready(bridge(api));
  };
  check();
  host.addEventListener("pywebviewready", check);
}
