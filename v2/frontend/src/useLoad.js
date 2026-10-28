import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Ładuje dane i ignoruje spóźnione odpowiedzi: po przełączeniu budowy wynik zapytania
 * o poprzednią budowę nigdy nie trafia na ekran nowej (lekcja z błędu Planimetrii w v1).
 */
export function useLoad(fetcher, deps) {
  const [state, setState] = useState({ data: null, error: "", loading: true });
  const seq = useRef(0);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const reload = useCallback(async () => {
    const current = ++seq.current;
    setState(previous => ({ ...previous, loading: true, error: "" }));
    try {
      const data = await fetcher();
      if (mounted.current && current === seq.current) setState({ data, error: "", loading: false });
    } catch (error) {
      if (mounted.current && current === seq.current) setState(previous => ({ ...previous, error: error.message || "Błąd wczytywania", loading: false }));
    }
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setState({ data: null, error: "", loading: true }); // nowe parametry = nie pokazujemy starych danych
    reload();
  }, [reload]);

  return { ...state, reload };
}
