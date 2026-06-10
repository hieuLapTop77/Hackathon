import { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE_URL } from "../config";

export function useApi(endpoint, options = {}, { immediate = true } = {}) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(immediate);
  const [error, setError]     = useState(null);
  const abortRef = useRef(null);

  const fetch_ = useCallback(async (body) => {
    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${endpoint}`, {
        method:  body ? "POST" : "GET",
        headers: body ? { "Content-Type": "application/json" } : {},
        body:    body ? JSON.stringify(body) : undefined,
        signal:  controller.signal,
        ...options,
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const json = await res.json();
      if (!controller.signal.aborted) setData(json);
    } catch (e) {
      if (e.name !== "AbortError" && !controller.signal.aborted) {
        setError(e.message);
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [endpoint]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (immediate) fetch_();
    return () => { if (abortRef.current) abortRef.current.abort(); };
  }, [fetch_, immediate]);

  return { data, loading, error, refetch: fetch_ };
}

export { API_BASE_URL as API };
