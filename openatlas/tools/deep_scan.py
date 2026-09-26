"""DeepScanEngine (dsE) - local OCR + face similarity/attributes.

OCR uses pytesseract (needs the ``tesseract`` binary). Face functions use DeepFace,
which is a heavy optional ``ml`` extra - all local, all free. Every path degrades
gracefully with a clear message when a dependency/binary is missing.
"""

from __future__ import annotations

from pathlib import Path

from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.logger import get_logger

log = get_logger("openatlas.tools.deepscan")


@ToolRegistry.register("dl-image-scans")
class DeepScanEngine(BaseTool):
    abbrev = "dsE"
    description = "Local deep-learning image scans (OCR, face similarity/attributes)."

    specs = {
        "OCR_analysis": ToolSpec(
            name="OCR_analysis",
            description="Extract text from an image using local OCR (pytesseract).",
            parameters={"image_path": {"type": "string", "required": True, "description": "Image path"}},
            backend="pytesseract (local)",
        ),
        "verify_similar_faces": ToolSpec(
            name="verify_similar_faces",
            description="Verify whether two local images contain the same person (DeepFace, ml extra).",
            parameters={
                "image_path_1": {"type": "string", "required": True, "description": "First image"},
                "image_path_2": {"type": "string", "required": True, "description": "Second image"},
            },
            backend="DeepFace (local, ml extra)",
        ),
        "face_attribute_analysis": ToolSpec(
            name="face_attribute_analysis",
            description="Estimate age/gender/emotion attributes from a local face image (ml extra).",
            parameters={"image_path": {"type": "string", "required": True, "description": "Image path"}},
            backend="DeepFace (local, ml extra)",
        ),
    }

    @staticmethod
    def OCR_analysis(image_path: str) -> ToolResult:
        if not Path(image_path).exists():
            return ToolResult.failure("OCR_analysis", f"file not found: {image_path}")
        try:
            import pytesseract
            from PIL import Image

            text = pytesseract.image_to_string(Image.open(image_path))
        except Exception as exc:
            return ToolResult.unavailable(
                "OCR_analysis", f"OCR backend unavailable ({exc}). Install pytesseract + tesseract."
            )
        return ToolResult(tool_name="OCR_analysis", content={"text": text}, success=True)

    @staticmethod
    def verify_similar_faces(image_path_1: str, image_path_2: str) -> ToolResult:
        for p in (image_path_1, image_path_2):
            if not Path(p).exists():
                return ToolResult.failure("verify_similar_faces", f"file not found: {p}")
        try:
            from deepface import DeepFace  # type: ignore

            res = DeepFace.verify(image_path_1, image_path_2, enforce_detection=False)
        except Exception as exc:
            return ToolResult.unavailable(
                "verify_similar_faces",
                f"DeepFace unavailable ({exc}). Install with `poetry install --with ml`.",
            )
        return ToolResult(
            tool_name="verify_similar_faces",
            content={"verified": res.get("verified"), "distance": res.get("distance"),
                     "threshold": res.get("threshold")}, success=True,
        )

    @staticmethod
    def face_attribute_analysis(image_path: str) -> ToolResult:
        if not Path(image_path).exists():
            return ToolResult.failure("face_attribute_analysis", f"file not found: {image_path}")
        try:
            from deepface import DeepFace  # type: ignore

            res = DeepFace.analyze(image_path, actions=["age", "gender", "emotion"],
                                   enforce_detection=False)
        except Exception as exc:
            return ToolResult.unavailable(
                "face_attribute_analysis",
                f"DeepFace unavailable ({exc}). Install with `poetry install --with ml`.",
            )
        return ToolResult(tool_name="face_attribute_analysis", content={"analysis": res}, success=True)
