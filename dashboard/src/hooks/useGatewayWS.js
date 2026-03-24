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
  const reqCounter  = useRef(0);
  const gatewayWS   = useRef(null);

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(cfg => { gatewayWS.current = cfg.gateway_ws; })
      .catch(() => {
        const host = window.location.hostname;
        gatewayWS.current = `ws://${host}:8765`;
      });
  }, []);

  const connect = useCallback(() => {
    if (unmounted.current) return;

    const url = gatewayWS.current || `ws://${window.location.hostname}:8765`;
    const ws  = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmounted.current) { ws.close(); return; }
      retryDelay.current = BASE_DELAY_MS;
      if (token) {
        ws.send(JSON.stringify({
          type:       'connect',
          timestamp:  new Date().toISOString(),
          payload:    { auth_token: token, user_id: 'dashboard-user', channel: 'dashboard' },
          request_id: `req-${++reqCounter.current}`,
        }));
      }
    };

    ws.onmessage = (evt) => {
      if (unmounted.current) return;
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'connected') setConnected(true);
        setLastMessage({ ...msg, _recv: new Date().toISOString() });
      } catch {
        setLastMessage({ type: 'raw', data: evt.data, _recv: new Date().toISOString() });
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

  const sendWire = useCallback((type, payload) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const msg = { type, timestamp: new Date().toISOString(), request_id: `req-${++reqCounter.current}` };
    if (payload && Object.keys(payload).length) msg.payload = payload;
    ws.send(JSON.stringify(msg));
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

  return { connected, lastMessage, sendMessage, sendWire };
}
