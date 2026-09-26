"""StaticImageExtractionEngine (siE) - image metadata + binary/firmware analysis.

* ``extract_metadata`` - EXIF (via Pillow) plus C2PA provenance if the ``c2pa`` lib
  is installed.
* ``scan_firmware`` / ``extract_firmware`` / ``extract_strings`` - local binary
  analysis. A pure-Python magic-signature scanner is the default so it works
  everywhere; an optional Rust/binwalk backend (see openatlas/rust) is used when
  available for deeper carving.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.logger import get_logger

log = get_logger("openatlas.tools.image")

# A small set of well-known file magic signatures for the pure-Python scanner.
_SIGNATURES = {
    b"\x1f\x8b\x08": "gzip compressed data",
    b"BZh": "bzip2 compressed data",
    b"\x50\x4b\x03\x04": "zip archive",
    b"\x89PNG\r\n\x1a\n": "PNG image",
    b"\xff\xd8\xff": "JPEG image",
    b"\x7fELF": "ELF executable",
    b"hsqs": "squashfs filesystem",
    b"UBI#": "UBI image",
    b"\xd0\xcf\x11\xe0": "MS Office/OLE",
    b"%PDF": "PDF document",
    b"\x27\x05\x19\x56": "uImage (u-boot) header",
}


def _read(path: str) -> bytes:
    return Path(path).read_bytes()


@ToolRegistry.register("image-metadata")
class StaticImageExtractionEngine(BaseTool):
    abbrev = "siE"
    description = "Metadata + binary/firmware analysis on images and files (local)."

    specs = {
        "extract_metadata": ToolSpec(
            name="extract_metadata",
            description="Extract EXIF/basic metadata (and C2PA provenance if present) from an image.",
            parameters={"image_path": {"type": "string", "required": True, "description": "Image path"}},
            backend="Pillow + c2pa (local)",
        ),
        "scan_firmware": ToolSpec(
            name="scan_firmware",
            description="Scan a file/image for embedded firmware signatures (binwalk-style).",
            parameters={"image_path": {"type": "string", "required": True, "description": "File path"}},
            backend="local signature scan / rust binwalk",
        ),
        "extract_firmware": ToolSpec(
            name="extract_firmware",
            description="Extract a byte range from a binary/image by offset.",
            parameters={
                "input_path": {"type": "string", "required": True, "description": "File path"},
                "skip": {"type": "integer", "required": False, "description": "Blocks to skip"},
                "count": {"type": "integer", "required": False, "description": "Blocks to read"},
                "output_file_name": {"type": "string", "required": False, "description": "Output name"},
                "block_size": {"type": "integer", "required": False, "description": "Block size bytes"},
            },
            backend="local",
        ),
        "extract_strings": ToolSpec(
            name="extract_strings",
            description="Extract readable ASCII/UTF-16LE strings from a binary or image file.",
            parameters={
                "input_path": {"type": "string", "required": True, "description": "File path"},
                "min_length": {"type": "integer", "required": False, "description": "Min length"},
            },
            backend="local",
        ),
    }

    @staticmethod
    def extract_metadata(image_path: str) -> ToolResult:
        if not Path(image_path).exists():
            return ToolResult.failure("extract_metadata", f"file not found: {image_path}")
        meta: Dict[str, Any] = {"basic": {}, "exif": {}, "c2pa": None}
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS

            with Image.open(image_path) as img:
                meta["basic"] = {"format": img.format, "mode": img.mode, "size": list(img.size)}
                exif = getattr(img, "_getexif", lambda: None)()
                if exif:
                    meta["exif"] = {TAGS.get(k, str(k)): str(v) for k, v in exif.items()}
        except Exception as exc:
            log.debug("EXIF extraction failed: %s", exc)
            meta["basic"]["error"] = str(exc)
        try:
            import c2pa  # type: ignore

            meta["c2pa"] = c2pa.read_file(image_path, None)  # type: ignore[attr-defined]
        except Exception:
            meta["c2pa"] = None  # c2pa optional
        return ToolResult(tool_name="extract_metadata", content=meta, success=True)

    @staticmethod
    def scan_firmware(image_path: str) -> ToolResult:
        if not Path(image_path).exists():
            return ToolResult.failure("scan_firmware", f"file not found: {image_path}")
        # Prefer the optional Rust/binwalk backend if present.
        try:
            from openatlas.rust import binwalk_bindings  # type: ignore

            return ToolResult(tool_name="scan_firmware",
                              content=binwalk_bindings.scan(image_path), success=True,
                              metadata={"backend": "rust-binwalk"})
        except Exception:
            pass
        data = _read(image_path)
        hits: List[Dict[str, Any]] = []
        for sig, desc in _SIGNATURES.items():
            start = 0
            while True:
                idx = data.find(sig, start)
                if idx == -1:
                    break
                hits.append({"offset": idx, "signature": desc})
                start = idx + 1
                if len(hits) > 1000:  # safety cap
                    break
        return ToolResult(tool_name="scan_firmware",
                          content={"file": image_path, "size": len(data), "signatures": hits},
                          success=True, metadata={"backend": "python-signature-scan"})

    @staticmethod
    def extract_firmware(input_path: str, skip: int = 0, count: int = 0,
                         output_file_name: str = "extracted.bin", block_size: int = 1) -> ToolResult:
        if not Path(input_path).exists():
            return ToolResult.failure("extract_firmware", f"file not found: {input_path}")
        data = _read(input_path)
        start = skip * block_size
        end = start + count * block_size if count else len(data)
        chunk = data[start:end]
        out = Path(output_file_name)
        try:
            out.write_bytes(chunk)
        except OSError as exc:
            return ToolResult.failure("extract_firmware", f"write failed: {exc}")
        return ToolResult(tool_name="extract_firmware",
                          content={"bytes_written": len(chunk), "output_file": str(out)}, success=True)

    @staticmethod
    def extract_strings(input_path: str, min_length: int = 4) -> ToolResult:
        if not Path(input_path).exists():
            return ToolResult.failure("extract_strings", f"file not found: {input_path}")
        data = _read(input_path)
        results: List[Dict[str, Any]] = []
        cur = bytearray()
        start_off = 0
        for i, b in enumerate(data):
            if 32 <= b < 127:
                if not cur:
                    start_off = i
                cur.append(b)
            else:
                if len(cur) >= min_length:
                    results.append({"offset": start_off, "string": cur.decode("ascii", "ignore")})
                cur = bytearray()
        if len(cur) >= min_length:
            results.append({"offset": start_off, "string": cur.decode("ascii", "ignore")})
        return ToolResult(tool_name="extract_strings",
                          content={"file": input_path, "count": len(results),
                                   "strings": results[:5000]}, success=True)
