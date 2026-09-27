"""Image evidence: EXIF/GPS from the file, plus reverse-image-search links.

No keyless reverse-image-search API exists, so OpenAtlas gives you one-click links
to the free web tools instead of pretending to search.
"""

from __future__ import annotations

import asyncio
import urllib.parse

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net


@source("image-exif", title="Photo metadata & GPS", filters=("images",),
        description="Camera, timestamps and GPS coordinates embedded in the image (local)",
        applies_to=("image",), timeout=30)
async def image_exif(t: Target, net: Net) -> SourceResult:
    from openatlas.tools.geolocation import _exif_gps
    from openatlas.tools.image_analysis import StaticImageExtractionEngine

    meta = await asyncio.to_thread(StaticImageExtractionEngine.extract_metadata, t.value)
    gps = await asyncio.to_thread(_exif_gps, t.value)
    res = SourceResult("image-exif", ok=meta.success, searched="embedded EXIF metadata")
    exif = (meta.content or {}).get("exif", {}) if meta.success else {}
    keep = {k: exif[k] for k in ("Make", "Model", "DateTimeOriginal", "Software") if k in exif}
    if keep:
        res.evidence.append(Evidence(
            source="image-exif", kind="info", title="Camera / software metadata present",
            snippet=", ".join(f"{k}: {v}" for k, v in keep.items()), confidence=0.8,
            verified=True, verification={"method": "read from file"}, data=keep))
    if gps:
        lat, lon = gps["latitude"], gps["longitude"]
        res.evidence.append(Evidence(
            source="image-exif", kind="record", title=f"GPS coordinates {lat}, {lon}",
            url=f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}",
            snippet="embedded in the photo's EXIF data", entity_type="location",
            entity_value=f"{lat},{lon}", confidence=0.85, verified=True,
            verification={"method": "read from file"}, data=gps))
    return res


@source("reverse-image", title="Reverse image search links", filters=("images",),
        description="One-click links to free reverse-image tools (Google Lens, Bing, Yandex, TinEye)",
        applies_to=("image",), timeout=5)
async def reverse_image(t: Target, net: Net) -> SourceResult:
    res = SourceResult("reverse-image", ok=True, searched="reverse image search links")
    if t.value.startswith(("http://", "https://")):
        q = urllib.parse.quote(t.value, safe="")
        links = {"Google Lens": f"https://lens.google.com/uploadbyurl?url={q}",
                 "Bing Visual Search": f"https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:{q}",
                 "Yandex Images": f"https://yandex.com/images/search?rpt=imageview&url={q}",
                 "TinEye": f"https://tineye.com/search?url={q}"}
    else:
        links = {"Google Lens": "https://lens.google.com/", "Bing Visual Search":
                 "https://www.bing.com/visualsearch", "Yandex Images": "https://yandex.com/images/",
                 "TinEye": "https://tineye.com/"}
    for name, url in links.items():
        res.evidence.append(Evidence(
            source="reverse-image", kind="link", title=f"Search this image on {name}", url=url,
            snippet="opens in your browser - upload the image there if it is a local file",
            confidence=0.0))
    return res
