"""Windows native OCR wrapper using winsdk."""

from __future__ import annotations
import asyncio
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.graphics.imaging import BitmapDecoder
from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

async def _ocr_async(image_bytes: bytes) -> str:
    # Create random access stream
    stream = InMemoryRandomAccessStream()
    
    # Write bytes to stream
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(image_bytes)
    await writer.store_async()
    await writer.flush_async()
    
    # Decode bitmap
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    
    # Ensure BGRA8 pixel format and Premultiplied alpha format (strictly required by Windows OcrEngine)
    from winsdk.windows.graphics.imaging import BitmapPixelFormat, BitmapAlphaMode, SoftwareBitmap
    if bitmap.bitmap_pixel_format != BitmapPixelFormat.BGRA8 or bitmap.bitmap_alpha_mode == BitmapAlphaMode.STRAIGHT:
        bitmap = SoftwareBitmap.convert(bitmap, BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED)
        
    # Try to load English engine explicitly, otherwise fall back to user profile/available packages
    engine = None
    try:
        from winsdk.windows.globalization import Language
        if Language.is_well_formed("en-US"):
            engine = OcrEngine.try_create_from_language(Language("en-US"))
    except Exception:
        pass
        
    if not engine:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if not engine:
        available = OcrEngine.get_available_recognizer_languages()
        if available:
            engine = OcrEngine.try_create_from_language(available[0])
        else:
            raise RuntimeError("No OCR languages available on Windows.")
            
    result = await engine.recognize_async(bitmap)
    return result.text

def run_win_ocr(image_bytes: bytes) -> str:
    """Run Windows native OCR synchronously on bytes."""
    if not image_bytes:
        return ""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_ocr_async(image_bytes))
        finally:
            loop.close()
    except Exception as e:
        import traceback
        print(f"[win_ocr] Windows OCR failed: {e}")
        traceback.print_exc()
        return ""
