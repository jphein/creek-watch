#!/usr/bin/env bash
# Build responsive, EXIF-free web photo variants for Creek Watch.
# Usage: build-photos.sh <src-dir> <out-dir>
# <src-dir> holds full-size <slug>.jpg originals (>= 1600 px wide). To swap a photo,
# drop a new <slug>.jpg in, rerun, and update CREDITS.md. Output names never change,
# so the CSS and HTML need no edits.
set -euo pipefail
src=${1:?src dir}; out=${2:?out dir}; mkdir -p "$out"
# slug  aspect(w:h)  gravity  widths
# Heroes get 800 + 1600 (AVIF/WebP at 1600; JPEG fallback at 800 only, for very old
# browsers). Accents display under ~400 CSS px, so 800 covers 2x screens.
while read -r slug aspect grav widths; do
  [[ -z $slug || $slug == \#* ]] && continue
  f="$src/$slug.jpg"; [[ -f $f ]] || { echo "skip $slug (no $f)"; continue; }
  aw=${aspect%:*}; ah=${aspect#*:}
  for w in ${widths//,/ }; do
    h=$(( w * ah / aw ))
    base=(magick "$f" -auto-orient -strip -colorspace sRGB -resize "${w}x${h}^" -gravity "$grav" -extent "${w}x${h}")
    "${base[@]}" -quality 34 "$out/$slug-$w.avif"
    "${base[@]}" -quality 55 -define webp:method=6 "$out/$slug-$w.webp"
    if [[ $w == 800 ]]; then "${base[@]}" -quality 62 -sampling-factor 4:2:0 -interlace Plane "$out/$slug-$w.jpg"; fi
  done
  echo "built $slug ($aspect, $grav)"
done <<'LIST'
# Dashboard hero
canyon-purdon 2:1 center 800,1600
# About hero
bridgeport    2:1 center 800,1600
# Report step-1 backdrop
canyon-gold   2:1 center 800,1600
# About accents
high-water    3:2 center 800
newt          1:1 south  800
LIST
