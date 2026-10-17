import { api } from "./api";
import { compressImage } from "./imageTools";
import { createIdbStore, createPhotoQueue, createPhotoSubmitter } from "./photoQueue";

const announce = count => window.dispatchEvent(new CustomEvent("asolar:photos", { detail: count }));

async function uploadNow({ entityType, entityId, file, clientId }) {
  const form = new FormData();
  form.append("file", file, file.name || "zdjecie.jpg");
  if (clientId) form.append("client_id", clientId);
  return api(`/api/${entityType}/${entityId}/photos`, { method: "POST", body: form });
}

const queue = createPhotoQueue({
  store: createIdbStore(),
  send: item => uploadNow({ entityType: item.entityType, entityId: item.entityId, file: item.blob, clientId: item.id }),
  onChange: announce,
});

const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

/** Dodaje zdjęcie: wysyła od razu albo zapisuje w telefonie do późniejszej wysyłki. */
export const submitPhoto = createPhotoSubmitter({ queue, uploadNow, isOnline: () => navigator.onLine, compress: compressImage, newId: uuid });
export const flushPhotos = () => (navigator.onLine ? queue.flush() : Promise.resolve({ sent: 0, dropped: 0, remaining: 0 }));
export const pendingPhotoCount = () => queue.count().catch(() => 0);
