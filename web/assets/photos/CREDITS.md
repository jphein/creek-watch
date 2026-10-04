# Photo credits

Every photo in `web/assets/photos/` (and in the demo video and Devpost images) comes from
[Wikimedia Commons](https://commons.wikimedia.org/). Licences were checked on each file page
on 2026-10-03. Only public-domain, CC BY and CC BY-SA files are used, with no NC or ND.

**Edits:** every file was resized, re-encoded as AVIF/WebP/JPEG, and stripped of all metadata (EXIF, XMP, GPS).
Crops are noted per file. On the web, dark overlays are applied in CSS at display time, not baked in.
The video cards and stages and the Devpost images bake in a dark gradient, text and a photo credit (1920×1080 or 1500×1000 crop).
**Share-alike:** our edited versions of CC BY-SA files are released under the same licence
as the original (BY-SA 2.0 or 4.0). This covers only those image files: the Creek Watch code stays MIT.

| File (our name) | Used for | Original on Commons | Author | Licence | Changes |
|---|---|---|---|---|---|
| `canyon-purdon-*` | Creeks page banner; video §2 stage; Devpost map image | [South Yuba Recreation Area Purdon Crossing (52760437286).jpg](https://commons.wikimedia.org/wiki/File:South_Yuba_Recreation_Area_Purdon_Crossing_(52760437286).jpg) | U.S. Bureau of Land Management, California (blmcalifornia) | Public domain (PD-USGov-BLM) | 2:1 centre crop, resized |
| `canyon-gold-*` | Report page step-1 strip; video §3 and §7 stages; Devpost report image | [South Yuba Recreation Area (52257002433).jpg](https://commons.wikimedia.org/wiki/File:South_Yuba_Recreation_Area_(52257002433).jpg) | U.S. Bureau of Land Management, California | Public domain (PD-USGov-BLM) | 2:1 centre crop, resized, faded with a mask |
| `bridgeport-*` | About page hero; video §5 stage and closing card; Devpost thumbnail | [Bridgeport Covered Bridge (2025)-L1006838.jpg](https://commons.wikimedia.org/wiki/File:Bridgeport_Covered_Bridge_(2025)-L1006838.jpg) | Frank Schulenburg | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | 2:1 centre crop, resized, darkened by an overlay |
| `high-water-*` | About page (Limits); video §6 early-warning stage; Devpost early-warning image | [The old CA-49 bridge on the South Yuba River 2017.jpg](https://commons.wikimedia.org/wiki/File:The_old_CA-49_bridge_on_the_South_Yuba_River_2017.jpg) | Larry Miller | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0/) | 3:2 centre crop, resized |
| `newt-*` | About page (One Health) | [Sierra Newt, Taricha sierrae (8614529800).jpg](https://commons.wikimedia.org/wiki/File:Sierra_Newt,_Taricha_sierrae_(8614529800).jpg) | Larry Miller | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0/) | 1:1 bottom crop, resized |
| `rapids` (video and Devpost only) | Video title card and §8 water-tests stage; Devpost water-tests image | [South Yuba Recreation Area (53822635998).jpg](https://commons.wikimedia.org/wiki/File:South_Yuba_Recreation_Area_(53822635998).jpg) | U.S. Bureau of Land Management, California | Public domain (PD-USGov-BLM) | Resized, darkened, text added |
| `purdon-bridge` (video and Devpost only) | Video tracks card and §6 score stage; Devpost dashboard image | [South Yuba Recreation Area (53822389026).jpg](https://commons.wikimedia.org/wiki/File:South_Yuba_Recreation_Area_(53822389026).jpg) | U.S. Bureau of Land Management, California | Public domain (PD-USGov-BLM) | Resized, darkened, text added |
| `autumn-pool` (video and Devpost only) | Video §4 stage; Devpost about image | [South Yuba Recreation Area (52257005428).jpg](https://commons.wikimedia.org/wiki/File:South_Yuba_Recreation_Area_(52257005428).jpg) | U.S. Bureau of Land Management, California | Public domain (PD-USGov-BLM) | Resized, darkened, text added |

Public-domain files need no attribution. We credit them anyway.

## Swapping in your own photos

Every page and the CSS reference fixed names (`<slug>-800.avif|webp|jpg`, plus `<slug>-1600.avif|webp`
for the three heroes). To replace a photo:

1. Save the new original as `<slug>.jpg` in a source folder.
2. Run `web/assets/photos/build-photos.sh <src-dir> web/assets/photos`. It crops, resizes and strips metadata.
3. Update this table and the "Photo credits" list on the About page.

If it's your own photo, you choose the licence. Check that nobody in the frame can be identified.
