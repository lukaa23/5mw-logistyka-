/* Logika zakładki Planimetria, wydzielona z komponentu, aby dało się ją testować.
 *
 * Przyczyna dawnego białego ekranu („Cannot read properties of undefined (reading 'title')"):
 * synchronizacja zerowała wybrany plan, ale adres blob poprzedniego PDF-a został w stanie,
 * a warunek renderowania sprawdzał tylko adres. Tutaj PDF jest renderowany wyłącznie wtedy,
 * gdy jednocześnie istnieje wybrany plan i gotowy zasób przypisany dokładnie do niego.
 */

export function parseDate(value) {
  if (value === null || value === undefined || value === "") return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatPlanDate(value, locale = "pl-PL") {
  const date = parseDate(value);
  if (!date) return "—";
  try { return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(date); } catch { return "—"; }
}

export function formatSize(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return "—";
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

/** Zamienia dowolną odpowiedź serwera na bezpieczną listę planów. Pomija rekordy bez identyfikatora. */
export function normalizePlans(input) {
  if (!Array.isArray(input)) return [];
  const result = [];
  const seen = new Set();
  for (const item of input) {
    if (!item || typeof item !== "object") continue;
    const id = item.id;
    if (id === null || id === undefined || id === "" || typeof id === "object") continue;
    if (seen.has(String(id))) continue;
    seen.add(String(id));
    const filename = typeof item.filename === "string" ? item.filename : "";
    const rawTitle = typeof item.title === "string" ? item.title.trim() : "";
    result.push({
      id,
      title: rawTitle || filename || `Plan ${id}`,
      filename: filename || `plan-${id}.pdf`,
      size: Number.isFinite(Number(item.size)) ? Number(item.size) : 0,
      uploaded_at: parseDate(item.uploaded_at) ? item.uploaded_at : null,
      uploaded_by: typeof item.uploaded_by === "string" && item.uploaded_by ? item.uploaded_by : "—",
      file_url: typeof item.file_url === "string" && item.file_url ? item.file_url : `/api/documents/${id}/file`,
      approved_source: Boolean(item.approved_source),
      deletable: Boolean(item.deletable) && !item.approved_source,
    });
  }
  return result;
}

/** Zachowuje wybór, jeśli plan nadal istnieje; w przeciwnym razie wybiera pierwszy albo nic. */
export function resolveSelection(plans, selectedId) {
  if (!Array.isArray(plans) || !plans.length) return null;
  if (selectedId !== null && selectedId !== undefined && plans.some(plan => String(plan.id) === String(selectedId))) return selectedId;
  return plans[0].id;
}

export function findPlan(plans, selectedId) {
  if (!Array.isArray(plans) || selectedId === null || selectedId === undefined) return undefined;
  return plans.find(plan => String(plan.id) === String(selectedId));
}

/** Klucz zasobu wiąże PDF z projektem, dokumentem i adresem pliku. */
export function resourceKey(projectId, plan) {
  if (!plan) return null;
  return `${projectId ?? "-"}|${plan.id}|${plan.file_url}`;
}

/** Jedyny warunek, po którym wolno wyrenderować ramkę z PDF-em. */
export function canRenderPdf(state, projectId, plan) {
  if (!plan || !state) return false;
  return state.status === "ready" && Boolean(state.url) && state.key === resourceKey(projectId, plan);
}

/** Strażnik nieaktualnych odpowiedzi: tylko ostatnie rozpoczęte żądanie jest „aktualne". */
export function createLatestGuard() {
  let counter = 0;
  return {
    begin() { counter += 1; return counter; },
    isCurrent(token) { return token === counter; },
    invalidate() { counter += 1; },
  };
}

const IDLE = Object.freeze({ status: "idle", key: null, url: null, error: null });

/**
 * Ładuje PDF jako blob. Zwalnia poprzedni adres, ignoruje spóźnione odpowiedzi
 * (zmiana projektu, zmiana planu, odmontowanie) i zamienia błędy w stan „error".
 */
export function createPdfLoader({ fetchBlob, createObjectURL, revokeObjectURL, onChange }) {
  const guard = createLatestGuard();
  let state = IDLE;
  const publish = next => { state = next; try { onChange?.(state); } catch { /* błąd widoku nie może przerwać ładowania */ } };
  const release = () => { if (state.url) { try { revokeObjectURL(state.url); } catch { /* adres mógł już zostać zwolniony */ } } };
  return {
    getState: () => state,
    async load(projectId, plan) {
      const token = guard.begin();
      release();
      if (!plan) { publish(IDLE); return; }
      const key = resourceKey(projectId, plan);
      publish({ status: "loading", key, url: null, error: null });
      let blob;
      try {
        blob = await fetchBlob(plan.file_url);
      } catch (error) {
        if (guard.isCurrent(token)) publish({ status: "error", key, url: null, error: error?.message || "Nie udało się pobrać dokumentu PDF" });
        return;
      }
      if (!guard.isCurrent(token)) return;
      if (!blob || typeof blob !== "object") { publish({ status: "error", key, url: null, error: "Serwer zwrócił pusty dokument" }); return; }
      let url;
      try { url = createObjectURL(blob); } catch (error) { publish({ status: "error", key, url: null, error: "Nie udało się przygotować podglądu PDF" }); return; }
      if (!guard.isCurrent(token)) { try { revokeObjectURL(url); } catch { /* nic do zwolnienia */ } return; }
      publish({ status: "ready", key, url, error: null });
    },
    dispose() {
      guard.invalidate();
      release();
      state = IDLE;
    },
  };
}

export const ZOOM_LEVELS = [50, 75, 100, 125, 150, 200, 300, 400];

export function nextZoom(current, direction) {
  const index = ZOOM_LEVELS.indexOf(current);
  const base = index === -1 ? ZOOM_LEVELS.indexOf(100) : index;
  const next = Math.min(ZOOM_LEVELS.length - 1, Math.max(0, base + (direction > 0 ? 1 : -1)));
  return ZOOM_LEVELS[next];
}

/** Fragment adresu rozumiany przez wbudowane przeglądarki PDF (Chrome, Edge, Firefox). */
export function pdfViewerHash(zoom) {
  return zoom === "fit" ? "#view=Fit&toolbar=1" : `#zoom=${Number(zoom) || 100}&toolbar=1`;
}
