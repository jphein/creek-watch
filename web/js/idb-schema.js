// Single source of truth for the IndexedDB schema. Classic-script compatible on purpose:
// the service worker loads it with importScripts(), the page imports it as a side-effect module.
// Both then read self.CW_IDB, so the SW can never create an empty v1 database without the
// stores the report outbox needs.
self.CW_IDB = {
  NAME: 'creekwatch',
  VERSION: 1,
  upgrade(db) {
    if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv');
    if (!db.objectStoreNames.contains('outbox')) db.createObjectStore('outbox', { keyPath: 'key', autoIncrement: true });
  },
};
