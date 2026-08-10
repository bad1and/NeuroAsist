export type AvatarEnvelope = {
  protocol_version: 1 | 2;
  type: string;
  message_id: string;
  timestamp: string;
  session_id: string;
  payload: Record<string, unknown>;
};

type AvatarProtocolClientOptions = {
  url: string;
  onMessage: (message: AvatarEnvelope) => void;
  onConnectionChange?: (connected: boolean) => void;
};

/** A small browser counterpart to Unity's AvatarWebSocketClient. */
export class AvatarProtocolClient {
  private socket: WebSocket | null = null;
  private stopped = false;
  private reconnectTimer: number | null = null;
  private reconnectAttempt = 0;

  constructor(private readonly options: AvatarProtocolClientOptions) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.socket?.close(1000, "avatar host unmounted");
    this.socket = null;
    this.options.onConnectionChange?.(false);
  }

  send(type: string, payload: Record<string, unknown>, replyTo?: string): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    const message = this.createEnvelope(type, payload);
    if (replyTo) message.payload.reply_to = replyTo;
    this.socket.send(JSON.stringify(message));
  }

  private connect(): void {
    if (this.stopped) return;
    const socket = new WebSocket(this.options.url);
    this.socket = socket;
    socket.onopen = () => {
      if (this.socket !== socket) return;
      this.reconnectAttempt = 0;
      this.options.onConnectionChange?.(true);
      this.send("avatar.hello", {
        client_name: "iris-threejs",
        client_version: "0.8.0",
        supported_protocol_versions: [1, 2],
        platform: "webview",
      });
    };
    socket.onmessage = (event) => {
      if (typeof event.data !== "string") return;
      try {
        const message = JSON.parse(event.data) as AvatarEnvelope;
        if (!message?.type || !message?.payload || !message?.message_id) return;
        this.options.onMessage(message);
      } catch {
        // One malformed frame must not disconnect a healthy renderer.
      }
    };
    socket.onclose = () => {
      if (this.socket === socket) this.socket = null;
      this.options.onConnectionChange?.(false);
      this.scheduleReconnect();
    };
    socket.onerror = () => socket.close();
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.reconnectTimer !== null) return;
    const delay = Math.min(5_000, 500 * 2 ** this.reconnectAttempt++);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private createEnvelope(type: string, payload: Record<string, unknown>): AvatarEnvelope {
    return {
      protocol_version: 2,
      type,
      message_id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
      session_id: "default",
      payload,
    };
  }
}
