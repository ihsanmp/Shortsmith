"use client";

/**
 * Upload langsung dari browser ke object storage.
 *
 * Byte video tidak pernah menyentuh serverless function — API route hanya
 * menerbitkan URL bertanda tangan, lalu browser PUT langsung ke storage.
 * XMLHttpRequest dipakai (bukan fetch) semata karena hanya ia yang memberi
 * progress upload; tanpa itu upload video besar terasa menggantung.
 */
export type UploadHasil = { key: string; namaFile: string; ukuranBytes: number };

export async function uploadFile(
  file: File,
  prefix: "raw" | "sample" | "music",
  onProgress?: (persen: number) => void,
): Promise<UploadHasil> {
  const res = await fetch("/api/upload-token", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      contentType: file.type || "application/octet-stream",
      prefix,
      ukuranBytes: file.size,
    }),
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Gagal mendapatkan izin upload: ${detail}`);
  }
  const { key, uploadUrl } = (await res.json()) as { key: string; uploadUrl: string };

  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", uploadUrl, true);
    xhr.setRequestHeader("content-type", file.type || "application/octet-stream");

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`Upload ditolak storage (HTTP ${xhr.status})`));
    xhr.onerror = () => reject(new Error("Koneksi terputus saat upload."));
    xhr.send(file);
  });

  return { key, namaFile: file.name, ukuranBytes: file.size };
}
