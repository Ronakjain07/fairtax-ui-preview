"""
PDF to Image Conversion Service

Converts PDF documents to a list of JPEG images (one per page)
for Vision model processing.
"""

import io
from PIL import Image


def convert_pdf_to_images(pdf_bytes, dpi=300):
    """
    Convert PDF to list of JPEG image bytes (one per page).

    Args:
        pdf_bytes: Raw PDF file bytes
        dpi: Resolution for conversion (default 300 for clarity)

    Returns:
        List[bytes] of JPEG images, one per page

    Raises:
        Exception: If PDF is invalid or conversion fails
    """
    try:
        # Try pdf2image first (requires Poppler on PATH for Windows)
        try:
            from pdf2image import convert_from_bytes
            images = convert_from_bytes(pdf_bytes, dpi=dpi)
        except Exception:
            images = None

        # If pdf2image failed (often because poppler isn't installed), try PyMuPDF (fitz)
        if not images:
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                images = []
                for page in doc:
                    pix = page.get_pixmap(dpi=dpi)
                    img_bytes = pix.tobytes("jpeg")
                    from PIL import Image
                    img = Image.open(io.BytesIO(img_bytes))
                    images.append(img)
                doc.close()
            except Exception:
                images = None

        # As a last resort, raise an informative error
        if not images:
            raise EnvironmentError(
                "pdf2image/Poppler not available and PyMuPDF fallback failed. "
                "Install poppler (and ensure pdftoppm is on PATH) or install PyMuPDF."
            )

        # Convert PIL Images to JPEG bytes
        jpeg_images = []
        for img in images:
            # Convert RGBA to RGB if needed (for JPEG compatibility)
            if img.mode in ("RGBA", "LA", "P"):
                rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                img = rgb_img

            # Convert to JPEG bytes
            img_bytes_io = io.BytesIO()
            img.save(img_bytes_io, format="JPEG", quality=95)
            jpeg_images.append(img_bytes_io.getvalue())

        if not jpeg_images:
            raise ValueError("No pages extracted from PDF")

        print(f"[PDF_PROCESSOR] Converted {len(jpeg_images)} pages from PDF at {dpi} DPI")
        return jpeg_images

    except Exception as e:
        print(f"[PDF_PROCESSOR] Error converting PDF: {str(e)}")
        raise
