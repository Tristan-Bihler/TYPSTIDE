// WebSocket connection for live preview. Reconnects automatically.

import type { ClientMessage, ServerMessage } from "./types";

const SERVER_TYPES = new Set([
  "compile_status",
  "preview_pages",
  "problems",
  "workspace_changed",
  "suggestions",
  "checker_status",
]);

export function parseServerMessage(raw: string): ServerMessage | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value === "object" && value !== null && "type" in value) {
      const type = (value as { type: unknown }).type;
      if (typeof type === "string" && SERVER_TYPES.has(type)) return value as ServerMessage;
    }
  } catch {
    // ignore malformed frames
  }
  return null;
}

export interface LiveHandlers {
  onMessage(message: ServerMessage): void;
  /** Called after every (re)connect, e.g. to resend unsaved buffers. */
  onOpen(): void;
  onConnectionChange(connected: boolean): void;
}

export class LiveConnection {
  private socket: WebSocket | null = null;
  private retryMs = 500;

  constructor(private readonly handlers: LiveHandlers) {}

  connect(): void {
    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
    const socket = new WebSocket(url);
    this.socket = socket;
    socket.addEventListener("open", () => {
      this.retryMs = 500;
      this.handlers.onConnectionChange(true);
      this.handlers.onOpen();
    });
    socket.addEventListener("message", (event: MessageEvent<unknown>) => {
      if (typeof event.data !== "string") return;
      const message = parseServerMessage(event.data);
      if (message) this.handlers.onMessage(message);
    });
    socket.addEventListener("close", () => {
      this.handlers.onConnectionChange(false);
      window.setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = Math.min(this.retryMs * 2, 5000);
    });
  }

  send(message: ClientMessage): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }
}
