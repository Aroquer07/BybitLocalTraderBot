import { useEffect, useState } from "react";
import { api, ApiError, type AuthMe, type BotStatus } from "@/api/client";

export function useBotStatus(pollMs = 5000) {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [auth, setAuth] = useState<AuthMe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [accessDenied, setAccessDenied] = useState(false);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [statusData, authData] = await Promise.all([api.status(), api.authMe()]);
        if (active) {
          setStatus(statusData);
          setAuth(authData);
          setError(null);
          setAccessDenied(false);
        }
      } catch (e) {
        if (!active) return;
        if (e instanceof ApiError && e.status === 403) {
          setAccessDenied(true);
          setError(e.detail);
          return;
        }
        setError(e instanceof Error ? e.message : "Failed to load status");
      }
    };
    load();
    const id = setInterval(load, pollMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [pollMs]);

  return { status, auth, error, accessDenied };
}

export function useSSE(onUpdate: (status: BotStatus) => void) {
  useEffect(() => {
    const source = new EventSource("/api/events");
    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.status) onUpdate(data.status);
      } catch {
        /* ignore malformed */
      }
    };
    return () => source.close();
  }, [onUpdate]);
}
