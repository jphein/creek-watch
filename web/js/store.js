// Tiny IndexedDB wrapper: keeps the draft photo across reloads and holds the
// offline outbox. Every call fails soft — the app must work without storage.

import './idb-schema.js';

const { NAME, VERSION, upgrade } = self.CW_IDB;
let dbp;
function db() {
  if (!dbp) {
    dbp = new Promise((resolve, reject) => {
      const req = indexedDB.open(NAME, VERSION);
      req.onupgradeneeded = () => upgrade(req.result);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  return dbp;
}

async function tx(store, mode, fn) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const t = d.transaction(store, mode);
    const r = fn(t.objectStore(store));
    t.oncomplete = () => resolve(r && 'result' in r ? r.result : undefined);
    t.onerror = () => reject(t.error);
  });
}

export async function kvGet(key) {
  try { return await tx('kv', 'readonly', (s) => s.get(key)); } catch { return undefined; }
}
export async function kvSet(key, val) {
  try { await tx('kv', 'readwrite', (s) => s.put(val, key)); } catch { /* soft */ }
}
export async function kvDel(key) {
  try { await tx('kv', 'readwrite', (s) => s.delete(key)); } catch { /* soft */ }
}

export async function outboxAdd(item) {
  try { await tx('outbox', 'readwrite', (s) => s.add(item)); return true; } catch { return false; }
}
export async function outboxAll() {
  try { return (await tx('outbox', 'readonly', (s) => s.getAll())) || []; } catch { return []; }
}
export async function outboxDel(key) {
  try { await tx('outbox', 'readwrite', (s) => s.delete(key)); } catch { /* soft */ }
}

// Draft fields (not the photo) live in localStorage for instant restore.
export function draftLoad() {
  try { return JSON.parse(localStorage.getItem('cw-draft') || 'null'); } catch { return null; }
}
export function draftSave(d) {
  try { localStorage.setItem('cw-draft', JSON.stringify(d)); } catch { /* soft */ }
}
export function draftClear() {
  try { localStorage.removeItem('cw-draft'); } catch { /* soft */ }
}
