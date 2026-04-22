import { useEffect, useRef, useCallback } from "react";

export function useWebSocket(
  channel: string,
  onMessage: (data: unknown) => void,
  enabled = true
) {
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const connect = useCallback(() => {
    if (!enabled) return;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/${channel}`);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        onMessageRef.current(JSON.parse(ev.data));
      } catch {
        onMessageRef.current(ev.data);
      }
    };
    ws.onclose = () => {
      setTimeout(connect, 3000);  // auto-reconnect
    };
  }, [channel, enabled]);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);
}
