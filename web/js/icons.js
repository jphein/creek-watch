// Hand-drawn inline SVG icons. They use currentColor plus a few fixed water
// tints so they read in both themes and in direct sunlight.

const svg = (body, vb = '0 0 48 48') =>
  `<svg viewBox="${vb}" aria-hidden="true" focusable="false" class="ico">${body}</svg>`;

const drop = (fill, extra = '') =>
  svg(
    `<path d="M24 5C24 5 10 21 10 30a14 14 0 0 0 28 0C38 21 24 5 24 5Z" fill="${fill}" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>${extra}`
  );

export const icon = {
  camera: svg(
    '<rect x="5" y="13" width="38" height="27" rx="5" fill="none" stroke="currentColor" stroke-width="3"/><path d="M16 13l3-5h10l3 5" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><circle cx="24" cy="26" r="7.5" fill="none" stroke="currentColor" stroke-width="3"/>'
  ),
  gallery: svg(
    '<rect x="6" y="8" width="36" height="32" rx="5" fill="none" stroke="currentColor" stroke-width="3"/><circle cx="17" cy="18" r="4" fill="currentColor"/><path d="M8 36l11-11 7 7 5-5 10 10" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/>'
  ),
  pin: svg(
    '<path d="M24 44s14-13 14-24a14 14 0 0 0-28 0c0 11 14 24 14 24Z" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><circle cx="24" cy="20" r="5" fill="currentColor"/>'
  ),
  check: svg('<path d="M10 25l9 9 19-20" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'),
  back: svg('<path d="M29 10L15 24l14 14" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'),
  next: svg('<path d="M19 10l14 14-14 14" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'),
  wifiOff: svg(
    '<path d="M6 18a26 26 0 0 1 36 0M12 25a17 17 0 0 1 24 0M18 32a8 8 0 0 1 12 0" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/><circle cx="24" cy="38" r="2.5" fill="currentColor"/><path d="M8 8l32 32" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/>'
  ),

  // water colour
  clear: drop('#e8f6fb', '<path d="M17 30a7 7 0 0 0 5 7" fill="none" stroke="#5aa9c9" stroke-width="2.5" stroke-linecap="round"/>'),
  cloudy: drop('#c9d3d6', '<circle cx="20" cy="31" r="2" fill="#7d8b8f"/><circle cx="28" cy="27" r="1.6" fill="#7d8b8f"/><circle cx="27" cy="35" r="1.8" fill="#7d8b8f"/>'),
  brown: drop('#9a6b3c'),
  green: drop('#5e9a3a'),
  other: drop('#b9a7d6', '<text x="24" y="36" text-anchor="middle" font-size="15" font-weight="700" fill="#2d2246" font-family="system-ui,sans-serif">?</text>'),

  // flow
  dry: svg(
    '<path d="M6 34h36" stroke="currentColor" stroke-width="3" stroke-linecap="round"/><path d="M12 34l4-6 3 4 5-8 4 6 3-3 5 7" fill="none" stroke="#b08a5a" stroke-width="3" stroke-linejoin="round"/><circle cx="36" cy="13" r="5" fill="#f2b33d"/>'
  ),
  low: svg('<path d="M6 32c6-3 12 3 18 0s12-3 18 0" fill="none" stroke="#3b8fb5" stroke-width="3.5" stroke-linecap="round"/>'),
  normal: svg(
    '<path d="M6 24c6-3 12 3 18 0s12-3 18 0M6 33c6-3 12 3 18 0s12-3 18 0" fill="none" stroke="#3b8fb5" stroke-width="3.5" stroke-linecap="round"/>'
  ),
  high: svg(
    '<path d="M6 16c6-3 12 3 18 0s12-3 18 0M6 25c6-3 12 3 18 0s12-3 18 0M6 34c6-3 12 3 18 0s12-3 18 0" fill="none" stroke="#2a74a0" stroke-width="3.5" stroke-linecap="round"/>'
  ),
  flood: svg(
    '<path d="M4 20c5-4 10 4 15 0s10-4 15 0 10 4 10 0M4 29c5-4 10 4 15 0s10-4 15 0 10 4 10 0M4 38c5-4 10 4 15 0s10-4 15 0 10 4 10 0" fill="none" stroke="#1d5f8a" stroke-width="4" stroke-linecap="round"/><path d="M24 4v9M20 9l4 4 4-4" fill="none" stroke="#c0392b" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
  ),

  // amounts (algae / trash)
  none: svg('<circle cx="24" cy="24" r="15" fill="none" stroke="currentColor" stroke-width="3"/><path d="M14 34L34 14" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'),
  algaeSome: svg(
    '<path d="M6 36c6-3 12 3 18 0s12-3 18 0" fill="none" stroke="#3b8fb5" stroke-width="3" stroke-linecap="round"/><path d="M18 34c-3-7 2-10 0-18M28 34c3-6-2-9 1-15" fill="none" stroke="#4f9a35" stroke-width="3.5" stroke-linecap="round"/>'
  ),
  algaeLots: svg(
    '<path d="M6 38c6-3 12 3 18 0s12-3 18 0" fill="none" stroke="#3b8fb5" stroke-width="3" stroke-linecap="round"/><path d="M10 36c-3-8 3-12 0-22M18 36c3-8-3-12 1-24M26 36c-3-7 3-11 0-20M34 36c3-8-3-12 1-22M40 36c-2-5 2-8 0-13" fill="none" stroke="#3f8a26" stroke-width="3.5" stroke-linecap="round"/>'
  ),
  trashSome: svg(
    '<path d="M17 18h14l-2 22H19Z" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><path d="M14 18h20M21 18v-4h6v4" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'
  ),
  trashLots: svg(
    '<path d="M7 20h11l-2 18H9ZM30 20h11l-2 18h-7Z" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><path d="M18 26h12l-2 16h-8Z" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><path d="M5 20h15M28 20h15M16 26h16" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'
  ),

  // odor
  noSmell: svg(
    '<path d="M24 8c-2 8-8 14-8 22a8 8 0 0 0 16 0" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/><path d="M10 38L38 10" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'
  ),
  earthy: svg('<path d="M8 36c4-10 12-14 16-14s12 4 16 14Z" fill="#8b6a43" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><path d="M24 22V8M24 14c-4 0-7-3-7-6 4 0 7 3 7 6Zm0-2c3 0 6-2 6-5-3 0-6 2-6 5Z" fill="#4f9a35" stroke="#4f9a35" stroke-width="2"/>'),
  sewage: svg(
    '<path d="M12 40h24M16 40V22h16v18" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><path d="M18 16c0-4 4-4 4-8M26 16c0-4 4-4 4-8" fill="none" stroke="#8a7a2a" stroke-width="3" stroke-linecap="round"/>'
  ),
  chemical: svg(
    '<path d="M19 6h10M21 6v12L10 38a3 3 0 0 0 3 4h22a3 3 0 0 0 3-4L27 18V6" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><path d="M14 32h20l3 6H11Z" fill="#9b59b6"/>'
  ),
  rotten: svg(
    '<circle cx="24" cy="28" r="12" fill="none" stroke="currentColor" stroke-width="3"/><path d="M18 26h.1M30 26h.1" stroke="currentColor" stroke-width="4" stroke-linecap="round"/><path d="M18 34c4-3 8-3 12 0" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/><path d="M16 12c0-3 3-3 3-6M24 12c0-3 3-3 3-6M32 12c0-3 3-3 3-6" fill="none" stroke="#7a8a2a" stroke-width="2.5" stroke-linecap="round"/>'
  ),
  otherSmell: svg('<circle cx="24" cy="24" r="16" fill="none" stroke="currentColor" stroke-width="3"/><text x="24" y="31" text-anchor="middle" font-size="20" font-weight="700" fill="currentColor" font-family="system-ui,sans-serif">?</text>'),

  fish: svg(
    '<path d="M6 24c6-8 16-10 24-6l10-6v24l-10-6c-8 4-18 2-24-6Z" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><circle cx="14" cy="23" r="2" fill="currentColor"/>'
  ),
  deadFish: svg(
    '<path d="M6 24c6-8 16-10 24-6l10-6v24l-10-6c-8 4-18 2-24-6Z" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><path d="M11 20l6 6M17 20l-6 6" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>'
  ),
  heron: svg(
    '<path d="M30 8a4 4 0 1 0 0 .1M30 12c-6 4-8 10-6 16h12c0-6-4-10-6-16Z" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><path d="M34 7l8-1M27 28l-3 14M31 28l1 14" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'
  ),

  // nav
  navReport: svg(
    '<path d="M24 6C24 6 12 20 12 28a12 12 0 0 0 24 0C36 20 24 6 24 6Z" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><path d="M24 22v12M18 28h12" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'
  ),
  navMap: svg(
    '<path d="M6 12l12-5 12 5 12-5v29l-12 5-12-5-12 5Z" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/><path d="M18 7v29M30 12v29" stroke="currentColor" stroke-width="3"/>'
  ),
  navDash: svg(
    '<path d="M8 34a16 16 0 1 1 32 0" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/><path d="M24 34l8-10" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/><circle cx="24" cy="34" r="3" fill="currentColor"/>'
  ),
  navAbout: svg(
    '<circle cx="24" cy="24" r="17" fill="none" stroke="currentColor" stroke-width="3"/><path d="M24 22v12" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/><circle cx="24" cy="15" r="2.5" fill="currentColor"/>'
  ),
};
