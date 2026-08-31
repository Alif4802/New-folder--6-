"""
Windows Media OCR Smoke Test Diagnostic

- Optional manual Windows OCR environment diagnostic.
- Not run by pytest (kept outside the automated test suite).
- Not required for normal application startup.
- Makes no database mutations or network requests.
- Validates host Windows Media OCR runtime, language pack availability, and bounding-box extraction on synthetic image bytes.
"""

import asyncio
import io
import sys
from pathlib import Path

# Add backend root directory to sys.path so app packages resolve
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from PIL import Image, ImageDraw
from app.services.ocr.winocr_provider import WinOCRProvider


async def run_smoke_test():
    print("=== WINDOWS MEDIA OCR ENVIRONMENT SMOKE TEST ===")
    provider = WinOCRProvider(language="en-US")
    is_avail = provider.is_available()
    print(f"WinOCR Available on Host: {is_avail}")
    print(f"Language Used: {provider.language}")

    if not is_avail:
        print("RESULT: WinOCR is not available on this host.")
        return False

    # Create a synthetic image with distinct text
    img = Image.new("RGB", (600, 150), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((30, 30), "NATIONAL CURRICULUM AND TEXTBOOK BOARD", fill="black")
    draw.text((30, 65), "English for Today Class 9", fill="black")
    draw.text((30, 100), "Unit 1 : Father of the Nation", fill="black")

    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    png_bytes = img_bytes.getvalue()

    result = await provider.extract_page(
        image_bytes=png_bytes,
        target_width_pt=595.0,
        target_height_pt=150.0,
    )

    print(f"OCR Execution Success: {result.is_successful}")
    print(f"Extracted Text:\n---\n{result.text}\n---")
    print(f"Extracted Words Count: {len(result.words)}")
    if result.words:
        print(f"Sample Word 0: text='{result.words[0].text}', box=({result.words[0].x0}, {result.words[0].y0}, {result.words[0].x1}, {result.words[0].y1}), confidence={result.words[0].confidence}")

    success = result.is_successful and len(result.words) >= 5
    print(f"RESULT: {'PASSED' if success else 'FAILED'}")
    return success


if __name__ == "__main__":
    asyncio.run(run_smoke_test())
