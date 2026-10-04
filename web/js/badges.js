// Cleanup badges: no accounts. Everything lives in this browser's localStorage, wrapped so the
// app works when storage is blocked (private mode, full quota): you just don't keep badges.
import { esc } from './ui.js';

const KEY = 'cw-badges';
const EMPTY = () => ({ cleanups: 0, bags: 0, earned: {} });

export const BADGES = [
  { id: 'helper', name: 'Creek Helper', rule: 'your first cleanup', earned: (s) => s.cleanups >= 1,
    progress: (s) => `${Math.min(s.cleanups, 1)} of 1 cleanup` },
  { id: 'steward', name: 'Creek Steward', rule: '5 cleanups', earned: (s) => s.cleanups >= 5,
    progress: (s) => `${Math.min(s.cleanups, 5)} of 5 cleanups` },
  { id: 'hero', name: 'Trash Hero', rule: '10 bags of trash', earned: (s) => s.bags >= 10,
    progress: (s) => `${Math.min(s.bags, 10)} of 10 bags` },
];

export function loadStats() {
  try {
    const s = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (!s || typeof s !== 'object') return EMPTY();
    return { cleanups: Math.max(0, s.cleanups | 0), bags: Math.max(0, s.bags | 0), earned: s.earned && typeof s.earned === 'object' ? s.earned : {} };
  } catch { return EMPTY(); }
}

/** Count one cleanup (with optional bags). Returns {stats, newly: [badge], saved}. */
export function recordCleanup(bags = 0) {
  const s = loadStats();
  const before = new Set(BADGES.filter((b) => b.earned(s)).map((b) => b.id));
  s.cleanups += 1;
  s.bags += Math.max(0, Math.min(20, bags | 0));
  const now = new Date().toISOString();
  const newly = BADGES.filter((b) => b.earned(s) && !before.has(b.id));
  for (const b of newly) s.earned[b.id] = s.earned[b.id] || now;
  let saved = true;
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { saved = false; }
  return { stats: s, newly, saved };
}

// Medallions in the Yuba palette (river teal, moss, canyon gold). Each has its own glyph and the
// name is always written next to it, so colour is never the only cue.
const ART = {
  helper: { c1: '#2b7d8c', c2: '#11505d', glyph:
    '<path d="M22 46V30c0-2 3-2 3 0v-9c0-2 3-2 3 0v-3c0-2 3-2 3 0v3c0-2 3-2 3 0v9c0-2 3-2 3 0v4l1 6c1 6-3 12-10 12h-1c-5 0-7-3-7-6Z" fill="#fff"/>' },
  steward: { c1: '#3b7a4b', c2: '#2c4a32', glyph:
    '<path d="M32 15c10 4 13 13 10 22-3 8-10 12-10 12s-7-4-10-12c-3-9 0-18 10-22Z" fill="#fff"/><path d="M32 22v24M32 30l-5-4M32 36l5-4" stroke="#2c4a32" stroke-width="2.5" stroke-linecap="round"/>' },
  hero: { c1: '#c8952f', c2: '#8a5a1c', glyph:
    '<path d="M22 26h20l-2 22H24Z" fill="#fff"/><path d="M27 26c0-6 10-6 10 0" fill="none" stroke="#fff" stroke-width="3"/><path d="M32 31l2 4 4.5.5-3.3 3 1 4.5-4.2-2.3-4.2 2.3 1-4.5-3.3-3 4.5-.5Z" fill="#8a5a1c"/>' },
};

export function badgeSVG(id, { size = 64, locked = false } = {}) {
  const b = BADGES.find((x) => x.id === id);
  const a = ART[id];
  const gid = `bg-${id}-${Math.random().toString(36).slice(2, 7)}`;
  return `<svg class="badge-art${locked ? ' locked' : ''}" width="${size}" height="${size}" viewBox="0 0 64 64" role="img"
    aria-label="${esc(b.name)} badge${locked ? ' (not earned yet)' : ''}">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${a.c1}"/><stop offset="1" stop-color="${a.c2}"/></linearGradient></defs>
    <circle cx="32" cy="32" r="29" fill="url(#${gid})" stroke="#fff" stroke-width="3"/>
    <circle cx="32" cy="32" r="24" fill="none" stroke="#fff" stroke-opacity=".35" stroke-width="1.5" stroke-dasharray="3 3"/>
    ${a.glyph}
  </svg>`;
}

export function badgesStripHTML(stats = loadStats(), { heading = 'Your badges' } = {}) {
  return `<section class="badge-strip" aria-label="${esc(heading)}">
    <h3>${esc(heading)}</h3>
    <ul>${BADGES.map((b) => {
      const got = b.earned(stats);
      return `<li class="${got ? 'got' : 'locked'}">${badgeSVG(b.id, { size: 56, locked: !got })}
        <span class="b-name">${esc(b.name)}</span>
        <span class="b-rule">${got ? 'Earned ✓' : `Locked · ${esc(b.progress(stats))}`}</span></li>`;
    }).join('')}</ul>
    <p class="b-note">${stats.cleanups ? `You’ve logged ${stats.cleanups} cleanup${stats.cleanups === 1 ? '' : 's'}${stats.bags ? ` and ${stats.bags} bag${stats.bags === 1 ? '' : 's'}` : ''}. ` : ''}Badges live on this phone only: no account, nothing sent. Clearing your browser data removes them.</p>
  </section>`;
}
