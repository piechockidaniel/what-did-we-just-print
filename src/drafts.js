const database = new Promise((resolve, reject) => {
  const request = indexedDB.open("print-production-drafts", 1);
  request.onupgradeneeded = () => request.result.createObjectStore("drafts");
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(request.error);
});
export async function loadDraft() {
  const db = await database;
  return new Promise((resolve, reject) => {
    const request = db
      .transaction("drafts")
      .objectStore("drafts")
      .get("intake");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
export async function saveDraft(draft) {
  const db = await database;
  return new Promise((resolve, reject) => {
    const tx = db.transaction("drafts", "readwrite");
    if (draft) tx.objectStore("drafts").put(draft, "intake");
    else tx.objectStore("drafts").delete("intake");
    tx.oncomplete = resolve;
    tx.onerror = tx.onabort = () =>
      reject(tx.error || new Error("Draft storage unavailable"));
  });
}
