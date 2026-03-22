import { useState, useEffect, useRef, useCallback } from 'react';

const BASE_DELAY_MS  = 1000;
const MAX_DELAY_MS   = 30000;
const BACKOFF_FACTOR = 2;

export function useGatewayWS(token) {
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState(null);
  const wsRef       = useRef(null);
  const retryDelay  = useRef(BASE_DELAY_MS);
  const retryTimer  = useRef(null);
  const unmounted   = useRef(false);

  const connect = useCallback(() => {
    if (unmounted.current) return;

    const host = window.location.hostname;
    const url  = `ws://${host}:8765/ws`;
    const ws   = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmounted.current) { ws.close(); return; }
      setConnected(true);
      retryDelay.current = BASE_DELAY_MS;
      if (token) {
        ws.send(JSON.stringify({
          type:      'connect',
          timestamp: new Date().toISOString(),
          payload:   { token },
        }));
      }
    };

    ws.onmessage = (evt) => {
      if (unmounted.current) return;
      try {
        setLastMessage(JSON.parse(evt.data));
      } catch {
        setLastMessage({ raw: evt.data });
      }
    };

    ws.onclose = () => {
      if (unmounted.current) return;
      setConnected(false);
      wsRef.current = null;
      retryTimer.current = setTimeout(() => {
        retryDelay.current = Math.min(retryDelay.current * BACKOFF_FACTOR, MAX_DELAY_MS);
        connect();
      }, retryDelay.current);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [token]);

  const sendMessage = useCallback((msg) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
  }, []);

  useEffect(() => {
    unmounted.current = false;
    connect();
    return () => {
      unmounted.current = true;
      clearTimeout(retryTimer.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  return { connected, lastMessage, sendMessage };
}
