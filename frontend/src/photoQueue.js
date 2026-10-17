/* Kolejka zdjęć offline. Zdjęcie trafia do pamięci telefonu (IndexedDB), gdy nie ma zasięgu,
 * i jest wysyłane automatycznie po powrocie połączenia. Logika jest niezależna od przeglądarki
 * (magazyn i funkcja wysyłki są wstrzykiwane), dzięki czemu można ją testować w Node. */

/** "keep" — spróbuj ponownie później; "drop" — błąd trwały (np. rząd usunięty), nie ma sensu ponawiać. */
export function classifyUploadError(error) {
  const status = error && error.status;
  if (status === undefined || status === null) return "keep"; // brak sieci
  if (status === 401 || status === 403 || status === 408 || status === 429 || status >= 500) return "keep";
  if (status >= 400) return "drop";
  return "keep";
}

/** Czy błąd uzasadnia zapisanie zdjęcia w kolejce zamiast pokazania komunikatu. */
export function shouldQueueAfterError(error) {
  const status = error && error.status;
  if (status === undefined || status === null) return true;
  return status === 401 || status === 408 || status === 429 || status >= 500;
}

export function createPhotoQueue({ store, send, onChange }) {
  let flushing = null;
  const announce = async () => { try { onChange?.(await store.count()); } catch { /* licznik jest pomocniczy */ } };
  return {
    async enqueue(item) {
      await store.put({ ...item, createdAt: item.createdAt ?? Date.now() });
      await announce();
      return item.id;
    },
    count: () => store.count(),
    /** Wysyła zaległe zdjęcia po kolei. Jednoczesne wywołania współdzielą jedno przejście. */
    flush() {
      if (flushing) return flushing;
      flushing = (async () => {
        const result = { sent: 0, dropped: 0, remaining: 0 };
        try {
          const items = (await store.getAll()).sort((a, b) => a.createdAt - b.createdAt);
          for (const item of items) {
            try {
              await send(item);
              await store.delete(item.id);
              result.sent += 1;
            } catch (error) {
              if (classifyUploadError(error) === "drop") { await store.delete(item.id); result.dropped += 1; continue; }
              break; // brak sieci lub błąd serwera — zachowaj resztę w kolejności
            }
          }
          result.remaining = await store.count();
        } finally {
          flushing = null;
          await announce();
        }
        return result;
      })();
      return flushing;
    },
  };
}

export function createMemoryStore() {
  const items = new Map();
  return {
    async put(item) { items.set(item.id, item); },
    async getAll() { return [...items.values()]; },
    async delete(id) { items.delete(id); },
    async count() { return items.size; },
  };
}

export function createIdbStore({ dbName = "asolar-photos", storeName = "photos" } = {}) {
  let opened = null;
  const open = () => opened ||= new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") { reject(new Error("Pamięć przeglądarki jest niedostępna")); return; }
    const request = indexedDB.open(dbName, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(storeName, { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => { opened = null; reject(request.error || new Error("Nie można otworzyć pamięci przeglądarki")); };
  });
  const run = async (mode, action) => {
    const db = await open();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, mode);
      const request = action(transaction.objectStore(storeName));
      transaction.oncomplete = () => resolve(request?.result);
      transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error("Błąd zapisu w pamięci przeglądarki"));
    });
  };
  return {
    put: item => run("readwrite", store => store.put(item)),
    getAll: () => run("readonly", store => store.getAll()),
    delete: id => run("readwrite", store => store.delete(id)),
    count: () => run("readonly", store => store.count()),
  };
}

/** Wspólna ścieżka dodawania zdjęcia: wyślij od razu albo zapisz w telefonie. */
export function createPhotoSubmitter({ queue, uploadNow, isOnline, compress, newId }) {
  return async function submitPhoto({ entityType, entityId, file }) {
    let prepared = file;
    try { prepared = (await compress(file)) || file; } catch { prepared = file; }
    const clientId = newId();
    const enqueue = () => queue.enqueue({ id: clientId, entityType, entityId, blob: prepared, filename: prepared.name || file.name || "zdjecie.jpg", mime: prepared.type || "image/jpeg" });
    if (!isOnline()) { await enqueue(); return { queued: true, id: clientId }; }
    try {
      const result = await uploadNow({ entityType, entityId, file: prepared, clientId });
      return { queued: false, result };
    } catch (error) {
      if (!shouldQueueAfterError(error)) throw error;
      await enqueue();
      return { queued: true, id: clientId };
    }
  };
}
