import json
from pathlib import Path

try:
    import pytesseract
    from PIL import Image
    _TESSERACT_AVAILABLE = True
except ImportError:
    _TESSERACT_AVAILABLE = False


def run_ocr(index_path: str) -> None:
    """
    Annotate each frame entry in index.json with OCR text.
    Mutates index.json in place. No-ops if Tesseract is not installed.
    """
    if not _TESSERACT_AVAILABLE:
        return

    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    for entry in index:
        try:
            text = pytesseract.image_to_string(Image.open(entry["path"])).strip()
            if len(text) >= 10:
                entry["ocr_text"] = text
        except Exception:
            pass  # corrupt frame or Tesseract crash — skip silently
    Path(index_path).write_text(json.dumps(index, indent=2), encoding="utf-8")
