/* Zmniejszanie zdjęć przed wysłaniem — mniej danych przez słaby zasięg i mniej miejsca na dysku laptopa. */

export function fitWithin(width, height, maxSide) {
  const longest = Math.max(width, height);
  if (!(longest > 0) || longest <= maxSide) return { width, height, scaled: false };
  const scale = maxSide / longest;
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)), scaled: true };
}

export async function compressImage(file, { maxSide = 1600, quality = 0.8, minBytes = 400_000 } = {}) {
  try {
    if (!file || !/^image\/(jpeg|png|webp)$/i.test(file.type || "")) return file;
    if (typeof createImageBitmap !== "function") return file;
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const target = fitWithin(bitmap.width, bitmap.height, maxSide);
    if (!target.scaled && file.size < minBytes) { bitmap.close?.(); return file; }
    const canvas = document.createElement("canvas");
    canvas.width = target.width; canvas.height = target.height;
    canvas.getContext("2d").drawImage(bitmap, 0, 0, target.width, target.height);
    bitmap.close?.();
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", quality));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], (file.name || "zdjecie").replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg", lastModified: Date.now() });
  } catch {
    return file; // w razie problemu wysyłamy oryginał
  }
}
