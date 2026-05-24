"""
Document Processing Orchestrator

Main entry point for the Vision-based extraction pipeline:
1. PDF → images conversion
2. PASS 1: Vision extraction with confidence scoring
3. Normalization & aggregation
4. Validation layer
5. Return normalized, validated data
"""

import io
import traceback
from services import file_handler, vision_extractor, normalization_service, validation_service
import logging

logger = logging.getLogger(__name__)

# Minimum average characters per page to consider a PDF "digital" (not scanned)
_TEXT_FAST_PATH_MIN_CHARS = 150

# Doc types where text fast-path is safe (well-structured tabular text in digital PDFs)
_TEXT_FAST_PATH_DOC_TYPES = {"payslip", "form16", "homeloan", "nps", "school", "insurance", "donation"}


def _try_text_extraction(file_bytes, doc_type):
    """
    Attempt fast-path text extraction for digital PDFs using pdfplumber.
    Returns a document_processor-compatible result dict, or None if text quality is too low.
    """
    try:
        import pdfplumber
        import ai_service

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages_text = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages_text.append(t)

            full_text = "\n\n".join(pages_text)
            num_pages = max(len(pages_text), 1)
            avg_chars = len(full_text.replace(" ", "").replace("\n", "")) / num_pages

            if avg_chars < _TEXT_FAST_PATH_MIN_CHARS:
                print(f"[DOC_PROCESSOR][TEXT_FAST] avg {avg_chars:.0f} chars/page — too low, falling back to Vision")
                return None

            print(f"[DOC_PROCESSOR][TEXT_FAST] Digital PDF detected ({avg_chars:.0f} chars/page). Using text extraction.")
            result = ai_service.extract_from_text(full_text, doc_type)

            if result.get("success"):
                return result
            else:
                print(f"[DOC_PROCESSOR][TEXT_FAST] Text extraction failed: {result.get('error')}. Falling back to Vision.")
                return None

    except Exception as e:
        print(f"[DOC_PROCESSOR][TEXT_FAST] pdfplumber error: {e}. Falling back to Vision.")
        return None


def process_documents(file_bytes, mime_type, doc_type):
    """
    Process document(s) through the Vision extraction pipeline.

    Pipeline:
    1. Convert PDF to images (if needed)
    2. PASS 1: Vision extraction with confidence scores
    3. Normalize: handle multi-page, annual/monthly, duplicates
    4. Validate: enforce business rules and deduction caps
    5. Return normalized, validated data

    Args:
        file_bytes: Raw document bytes (PDF or image)
        mime_type: MIME type (application/pdf, image/jpeg, image/png, etc.)
        doc_type: Document type (form16, payslip, homeloan, school, nps, insurance, donation)

    Returns:
        {
            "success": bool,
            "data": {normalized extracted fields},
            "confidence": float (0-1),
            "metadata": {
                "assumptions": [str],
                "duplicates": [dict],
                "conflicts": [dict],
                "pages_processed": int,
                "validation_warnings": [dict]
            },
            "error": str or None
        }

    Error behavior (Fail-Fast):
    - Invalid PDF/image → Error returned to user
    - Vision extraction failure → Error returned to user
    - Validation errors → Error returned to user
    - User uploads low-quality document → Error + feedback to user
    """
    try:
        # ─────── FAST PATH: Digital PDF via pdfplumber ───
        # For digital (non-scanned) PDFs, skip image conversion + Vision API entirely.
        # This is ~3-5× faster and more accurate for clean payslips / Form 16 PDFs.
        if "pdf" in (mime_type or "").lower() and doc_type in _TEXT_FAST_PATH_DOC_TYPES:
            fast_result = _try_text_extraction(file_bytes, doc_type)
            if fast_result:
                print(f"[DOCUMENT_PROCESSOR] Fast-path succeeded. Returning text-extracted result.")
                return fast_result

        # ─────── STEP 1: Convert File to Images ──────────
        try:
            print(f"[DOCUMENT_PROCESSOR] Converting {mime_type} to images...")
            images = file_handler.process_file(file_bytes, mime_type)
            print(f"[DOCUMENT_PROCESSOR] Successfully converted file to {len(images)} page(s)")

        except Exception as e:
            error_msg = f"File conversion failed: {str(e)}"
            print(f"[DOCUMENT_PROCESSOR] {error_msg}")
            logger.error(error_msg, exc_info=True)
            return {
                "success": False,
                "error": error_msg,
                "data": {},
                "confidence": 0,
                "metadata": {}
            }

        # ─────── STEP 2: PASS 1 - Vision Extraction ─────
        try:
            print(f"[DOCUMENT_PROCESSOR] Starting Vision extraction for {len(images)} page(s)...")
            extraction = vision_extractor.extract_pass1_vision(images, doc_type)

            print(f"[DOCUMENT_PROCESSOR] Vision extraction complete. "
                  f"Confidence: {extraction.get('overall_confidence', 0)}, "
                  f"Quality: {extraction.get('extraction_quality', 'unknown')}")

        except Exception as e:
            error_msg = f"Vision extraction failed: {str(e)}"
            print(f"[DOCUMENT_PROCESSOR] {error_msg}")
            logger.error(error_msg, exc_info=True)
            return {
                "success": False,
                "error": error_msg,
                "data": {},
                "confidence": 0,
                "metadata": {
                    "extraction_quality": "failed",
                    "pages_processed": len(images) if 'images' in locals() else 0
                }
            }

        # ─────── STEP 3: Normalize & Aggregate ─────────
        try:
            print(f"[DOCUMENT_PROCESSOR] Normalizing extracted data...")
            normalized_result = normalization_service.normalize_extractions(
                [extraction],
                [doc_type]
            )

            normalized_data = normalized_result.get("normalized", {})
            print(f"[DOCUMENT_PROCESSOR] Normalization complete. "
                  f"Confidence: {normalized_result.get('extraction_confidence', 0)}")

            if normalized_result.get("duplicates"):
                print(f"[DOCUMENT_PROCESSOR] Duplicates detected: {normalized_result['duplicates']}")

            if normalized_result.get("conflicts"):
                print(f"[DOCUMENT_PROCESSOR] Conflicts found: {len(normalized_result['conflicts'])} field(s)")

        except Exception as e:
            error_msg = f"Normalization failed: {str(e)}"
            print(f"[DOCUMENT_PROCESSOR] {error_msg}")
            traceback.print_exc()
            return {
                "success": False,
                "error": error_msg,
                "data": {},
                "confidence": 0,
                "metadata": {}
            }

        # ─────── STEP 4: Validate ──────────────────────
        # For extracted/OCR'd data, validation is informational only.
        # Errors here represent things the user should review/correct (bad PAN, salary mismatches)
        # but should NOT block extraction — the user can edit the fields manually after extraction.
        validation_result = {}
        try:
            print(f"[DOCUMENT_PROCESSOR] Validating extracted data...")
            validation_result = validation_service.validate_extraction(normalized_data)

            err_count = len(validation_result.get("errors", []))
            warn_count = len(validation_result.get("warnings", []))
            if err_count or warn_count:
                print(f"[DOCUMENT_PROCESSOR] Validation: {err_count} errors, {warn_count} warnings (non-blocking)")
            else:
                print(f"[DOCUMENT_PROCESSOR] Validation passed.")

        except Exception as e:
            print(f"[DOCUMENT_PROCESSOR] Validation error (non-blocking): {str(e)}")
            validation_result = {"errors": [], "warnings": [{"reason": str(e)}]}

        # ─────── STEP 5: Return Success ────────────────
        print(f"[DOCUMENT_PROCESSOR] Pipeline complete. Document processing successful.")

        return {
            "success": True,
            "data": normalized_data,
            "confidence": round(normalized_result.get("extraction_confidence", 0), 2),
            "metadata": {
                "assumptions": normalized_result.get("assumptions", []),
                "duplicates": normalized_result.get("duplicates", []),
                "conflicts": normalized_result.get("conflicts", []),
                "pages_processed": extraction.get("pages_processed", len(images)),
                "validation_errors": validation_result.get("errors", []),
                "validation_warnings": validation_result.get("warnings", []),
                "extraction_quality": extraction.get("extraction_quality", "medium"),
                "fields_high_confidence": normalized_result.get("fields_high_confidence", []),
                "fields_low_confidence": normalized_result.get("fields_low_confidence", [])
            },
            "error": None
        }

    except Exception as e:
        # Unexpected error
        error_msg = f"Document processing failed: {str(e)}"
        print(f"[DOCUMENT_PROCESSOR] UNEXPECTED ERROR: {error_msg}")
        traceback.print_exc()
        return {
            "success": False,
            "error": error_msg,
            "data": {},
            "confidence": 0,
            "metadata": {}
        }
