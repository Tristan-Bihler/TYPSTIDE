import { describe, expect, it } from "vitest";

import { onDesktopBridge, toBase64, type DesktopBridge, type DesktopHost } from "./bridge";

function fakeApi(calls: unknown[][]) {
  return {
    pick_folder: (start: string) => (calls.push(["pick_folder", start]), Promise.resolve("C:/Arbeit")),
    save_pdf: (name: string, data: string) => (calls.push(["save_pdf", name, data]), Promise.resolve("C:/x.pdf")),
    set_unsaved: (value: boolean) => (calls.push(["set_unsaved", value]), Promise.resolve()),
  };
}

describe("onDesktopBridge", () => {
  it("stays silent in a normal browser", () => {
    const host: DesktopHost = new EventTarget();
    let found: DesktopBridge | null = null;
    onDesktopBridge(host, (b) => (found = b));
    host.dispatchEvent(new Event("pywebviewready"));
    expect(found).toBeNull();
  });

  it("finds the API at once or when pywebview says it is ready, only once", async () => {
    const calls: unknown[][] = [];
    const host: DesktopHost = new EventTarget();
    const found: DesktopBridge[] = [];
    onDesktopBridge(host, (b) => found.push(b));
    host.pywebview = { api: { pick_folder: fakeApi(calls).pick_folder } }; // not complete yet
    host.dispatchEvent(new Event("pywebviewready"));
    expect(found).toHaveLength(0);
    host.pywebview = { api: fakeApi(calls) };
    host.dispatchEvent(new Event("pywebviewready"));
    host.dispatchEvent(new Event("pywebviewready"));
    expect(found).toHaveLength(1);

    const bridge = found[0]!;
    expect(await bridge.pickFolder(null)).toBe("C:/Arbeit");
    expect(await bridge.savePdf("a.pdf", new Blob(["%PDF-1.7"]))).toBe("C:/x.pdf");
    bridge.setUnsaved(true);
    expect(calls).toEqual([
      ["pick_folder", ""],
      ["save_pdf", "a.pdf", btoa("%PDF-1.7")],
      ["set_unsaved", true],
    ]);

    const again: DesktopBridge[] = [];
    onDesktopBridge(host, (b) => again.push(b)); // already there: immediately
    expect(again).toHaveLength(1);
  });
});

describe("toBase64", () => {
  it("encodes large binary data", async () => {
    const bytes = new Uint8Array(100_000).map((_, i) => i % 256);
    const encoded = await toBase64(new Blob([bytes]));
    const decoded = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
    expect(decoded).toEqual(bytes);
  });
});
