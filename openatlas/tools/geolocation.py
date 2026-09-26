"""ImageGeolocationEngine (igE) - EXIF GPS + local vision LLM + OSM reverse geocode.

Replaces Picarta (paid) and VertexAI (paid):
* EXIF GPS is read locally with Pillow.
* Reverse geocoding uses Nominatim (OSM, keyless; we honour its <=1 req/s policy).
* LLM inference uses a *local* Ollama vision model; if Ollama is unreachable the
  call degrades gracefully.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from openatlas.config import Config
from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.llm import ollama_client
from openatlas.logger import get_logger
from openatlas.utils.http import api_get_json, scrape_get

log = get_logger("openatlas.tools.geo")


def _dms_to_deg(dms, ref) -> Optional[float]:
    try:
        d, m, s = [float(x[0]) / float(x[1]) if isinstance(x, tuple) else float(x) for x in dms]
        val = d + m / 60 + s / 3600
        if ref in ("S", "W"):
            val = -val
        return round(val, 6)
    except Exception:
        return None


def _exif_gps(image_path: str) -> Optional[Dict[str, float]]:
    try:
        from PIL import Image
        from PIL.ExifTags import GPSTAGS, TAGS

        with Image.open(image_path) as img:
            exif = getattr(img, "_getexif", lambda: None)()
        if not exif:
            return None
        gps_ifd = None
        for k, v in exif.items():
            if TAGS.get(k) == "GPSInfo":
                gps_ifd = {GPSTAGS.get(kk, kk): vv for kk, vv in v.items()}
        if not gps_ifd:
            return None
        lat = _dms_to_deg(gps_ifd.get("GPSLatitude"), gps_ifd.get("GPSLatitudeRef"))
        lon = _dms_to_deg(gps_ifd.get("GPSLongitude"), gps_ifd.get("GPSLongitudeRef"))
        if lat is None or lon is None:
            return None
        return {"latitude": lat, "longitude": lon}
    except Exception as exc:
        log.debug("EXIF GPS read failed: %s", exc)
        return None


def _reverse_geocode(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    time.sleep(1.0)  # honour Nominatim usage policy
    data = api_get_json(
        Config.services.nominatim_reverse,
        params={"lat": lat, "lon": lon, "format": "jsonv2"},
    )
    if not data:
        return None
    return {"display_name": data.get("display_name"), "address": data.get("address")}


@ToolRegistry.register("image-geolocation")
class ImageGeolocationEngine(BaseTool):
    abbrev = "igE"
    description = "Geolocate images using EXIF GPS, local vision LLM, and OSM reverse-geocode."

    specs = {
        "geolocate_local_image": ToolSpec(
            name="geolocate_local_image",
            description="Geolocate a local image from EXIF GPS + reverse geocoding.",
            parameters={
                "image_path": {"type": "string", "required": True, "description": "Local image path"},
                "top_k": {"type": "integer", "required": False, "description": "Candidates"},
            },
            backend="EXIF + Nominatim", network=True,
        ),
        "geolocate_online_image": ToolSpec(
            name="geolocate_online_image",
            description="Download a public image URL (robots-gated) and geolocate it from EXIF.",
            parameters={
                "image_url": {"type": "string", "required": True, "description": "Image URL"},
                "top_k": {"type": "integer", "required": False, "description": "Candidates"},
            },
            backend="EXIF + Nominatim", network=True, scrapes_web=True,
        ),
        "geolocate_using_LLMs": ToolSpec(
            name="geolocate_using_LLMs",
            description="Infer likely location by reasoning over the image with a local vision LLM.",
            parameters={
                "image_path": {"type": "string", "required": True, "description": "Image path"},
                "prompt": {"type": "string", "required": False, "description": "Guiding context"},
            },
            backend="Ollama vision (local)", needs_llm=True,
        ),
        "combined_llm_deeplearning_analysis": ToolSpec(
            name="combined_llm_deeplearning_analysis",
            description="Merge EXIF/geocode results with local vision-LLM inference.",
            parameters={
                "image_path": {"type": "string", "required": True, "description": "Local image path"},
                "top_k": {"type": "integer", "required": False, "description": "Candidates"},
            },
            backend="EXIF + Nominatim + Ollama", network=True, needs_llm=True,
        ),
    }

    @staticmethod
    def geolocate_local_image(image_path: str, top_k: int = 10) -> ToolResult:
        if not Path(image_path).exists():
            return ToolResult.failure("geolocate_local_image", f"file not found: {image_path}")
        gps = _exif_gps(image_path)
        if not gps:
            return ToolResult(tool_name="geolocate_local_image",
                              content={"image": image_path, "gps": None,
                                       "note": "no EXIF GPS; try geolocate_using_LLMs"}, success=True)
        place = _reverse_geocode(gps["latitude"], gps["longitude"])
        return ToolResult(tool_name="geolocate_local_image",
                          content={"image": image_path, "gps": gps, "place": place}, success=True)

    @staticmethod
    def geolocate_online_image(image_url: str, top_k: int = 10) -> ToolResult:
        resp = scrape_get(image_url)
        if resp is None or resp.status_code != 200:
            return ToolResult.failure("geolocate_online_image", "robots-disallowed or download failed")
        tmp = Path(Config.files.output_dir)
        tmp.mkdir(parents=True, exist_ok=True)
        local = tmp / "online_image.bin"
        local.write_bytes(resp.content)
        return ImageGeolocationEngine.geolocate_local_image(str(local), top_k=top_k)

    @staticmethod
    def geolocate_using_LLMs(image_path: str, prompt: str = "") -> ToolResult:
        if not Path(image_path).exists():
            return ToolResult.failure("geolocate_using_LLMs", f"file not found: {image_path}")
        if not ollama_client.available():
            return ToolResult.unavailable(
                "geolocate_using_LLMs",
                f"Ollama vision backend unreachable at {Config.llm.host}. Run `ollama serve` and "
                f"pull a vision model (e.g. `ollama pull llava`).",
            )
        q = ("You are a geolocation analyst. From visual cues (signage, architecture, vegetation, "
             "license plates, language) infer the most likely country, region and city. Give your "
             "reasoning and a confidence 0-1. " + (f"Context: {prompt}" if prompt else ""))
        answer = ollama_client.vision(q, image_path)
        if answer is None:
            return ToolResult.unavailable("geolocate_using_LLMs", "vision inference returned nothing")
        return ToolResult(tool_name="geolocate_using_LLMs",
                          content={"image": image_path, "inference": answer}, success=True,
                          metadata={"backend": "ollama-vision"})

    @staticmethod
    def combined_llm_deeplearning_analysis(image_path: str, top_k: int = 10) -> ToolResult:
        exif = ImageGeolocationEngine.geolocate_local_image(image_path, top_k=top_k)
        llm = ImageGeolocationEngine.geolocate_using_LLMs(image_path)
        ok = exif.success or llm.success
        return ToolResult(
            tool_name="combined_llm_deeplearning_analysis",
            content={"exif_geocode": exif.content, "llm": llm.content},
            success=ok,
            error=None if ok else (exif.error or llm.error or "both analyses failed"),
        )
