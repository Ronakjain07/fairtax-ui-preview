"""
AI-Powered ITR Document Extraction Service
Extracts financial and personal data from documents using Vision AI model
(Gemini) with structured extraction and validation.
"""

import base64
import json
from typing import Dict, List, Any, Optional
import io

from services import document_processor


# ═════════════════════════════════════════════════════════════════════════════
# AI-Based Extraction
# ═════════════════════════════════════════════════════════════════════════════

class AIDocumentExtractor:
    """Extracts ITR fields using Vision AI model (Gemini) with structured extraction."""

    def __init__(self):
        """Initialize Vision-based extractor."""
        pass

    def _build_response(self, result):
        """Build standardized response from extraction result, preserving all fields."""
        extracted_data = result["data"]

        # Nested structure for form16/payslip backward compatibility
        response_data = {
            'personal': {
                'pan': extracted_data.get('pan', ''),
                'name': extracted_data.get('employer_name', ''),
            },
            'income': {
                'gross_salary': extracted_data.get('gross_salary', 0),
                'basic_salary': extracted_data.get('basic_salary', 0),
                'hra_received': extracted_data.get('hra_received', 0),
                'tds_paid': extracted_data.get('tds_paid', 0),
                'pf_employee': extracted_data.get('pf_employee', 0),
                'pf_employer': extracted_data.get('pf_employer', 0),
                'professional_tax': extracted_data.get('professional_tax', 0),
                'lta': extracted_data.get('lta', 0),
                'special_allowance': extracted_data.get('special_allowance', 0),
                'car_lease_allowance': extracted_data.get('car_lease_allowance', 0),
                'uniform_allowance': extracted_data.get('uniform_allowance', 0),
                'gratuity': extracted_data.get('gratuity', 0),
                'leave_encashment': extracted_data.get('leave_encashment', 0),
            },
            'deductions': {
                'home_loan_interest': extracted_data.get('home_loan_interest', 0),
                'nps_self': extracted_data.get('nps_self', 0),
            },
        }

        # Include ALL raw extracted fields at the top level so frontend
        # can access doc-type-specific data (homeloan, insurance, school, etc.)
        for key, val in extracted_data.items():
            if key not in response_data:
                response_data[key] = val

        return {
            'success': True,
            'data': response_data,
            'errors': {},
            'raw_text': json.dumps(extracted_data)[:500],
            'confidence': result.get("confidence", 0),
            'metadata': result.get("metadata", {})
        }

    def extract_from_pdf(self, file_bytes: bytes, doc_type: str = "form16") -> Dict[str, Any]:
        """Extract ITR data from PDF using Vision model."""
        try:
            result = document_processor.process_documents(file_bytes, "application/pdf", doc_type=doc_type)

            if not result["success"]:
                return {
                    'success': False,
                    'data': {},
                    'errors': {'extraction': [result.get("error", "Vision extraction failed")]},
                    'raw_text': '',
                }

            return self._build_response(result)

        except Exception as e:
            error_msg = f"Vision extraction failed: {str(e)}"
            print(f"[ERROR] {error_msg}")
            return {
                'success': False,
                'data': {},
                'errors': {'extraction': [error_msg]},
                'raw_text': '',
            }

    def extract_from_image(self, file_bytes: bytes, doc_type: str = "form16") -> Dict[str, Any]:
        """Extract ITR data from image using Vision model."""
        try:
            result = document_processor.process_documents(file_bytes, "image/jpeg", doc_type=doc_type)

            if not result["success"]:
                return {
                    'success': False,
                    'data': {},
                    'errors': {'extraction': [result.get("error", "Vision extraction failed")]},
                    'raw_text': '',
                }

            return self._build_response(result)

        except Exception as e:
            error_msg = f"Vision extraction failed: {str(e)}"
            print(f"[ERROR] {error_msg}")
            return {
                'success': False,
                'data': {},
                'errors': {'extraction': [error_msg]},
                'raw_text': '',
            }


# ═════════════════════════════════════════════════════════════════════════════
# Main Document Processor (Simplified for AI)
# ═════════════════════════════════════════════════════════════════════════════

class ITRDocumentProcessor:
    """Main class for processing ITR documents using AI extraction.

    Parameters
    - use_ocr: optional bool to indicate OCR availability/preference. Kept
      for backwards compatibility with code that constructs the processor
      with `use_ocr=True`.
    """

    def __init__(self, use_ocr: bool = False):
        """Initialize document processor with AI extractor.

        The `use_ocr` flag is recorded on the instance for health checks and
        backwards compatibility. The processor will still attempt to create
        the AI extractor which uses the AI service. If OCR helpers are
        missing that's handled by the extractor itself.
        """
        self.use_ocr = bool(use_ocr)
        self.ai_extractor = None

        try:
            self.ai_extractor = AIDocumentExtractor()
            print("[OK] AI Document Extractor initialized successfully")
        except Exception as e:
            print(f"[WARNING] Failed to initialize AI Extractor: {e}")
            raise

    def process_pdf(self, file_bytes: bytes, doc_type: str = "form16") -> Dict[str, Any]:
        """
        Process PDF file and extract ITR data using Vision AI.

        Args:
            file_bytes: PDF file bytes
            doc_type: Document type (form16, payslip, homeloan, school, nps, insurance, donation)
        """
        if not self.ai_extractor:
            return {
                'success': False,
                'data': {},
                'errors': {'extraction': ['AI extractor not available']},
                'raw_text': '',
            }

        return self.ai_extractor.extract_from_pdf(file_bytes, doc_type=doc_type)

    def process_image(self, file_bytes: bytes, doc_type: str = "form16") -> Dict[str, Any]:
        """
        Process image file and extract ITR data using Vision AI.

        Args:
            file_bytes: Image file bytes
            doc_type: Document type (form16, payslip, homeloan, school, nps, insurance, donation)
        """
        if not self.ai_extractor:
            return {
                'success': False,
                'data': {},
                'errors': {'extraction': ['AI extractor not available']},
                'raw_text': '',
            }

        return self.ai_extractor.extract_from_image(file_bytes, doc_type=doc_type)

    def process_file(self, file_bytes: bytes, filename: str, doc_type: str = "form16") -> Dict[str, Any]:
        """
        Process any file type (PDF or image) with specified document type.

        Args:
            file_bytes: File content bytes
            filename: Original filename (used to determine file type)
            doc_type: Document type (form16, payslip, homeloan, school, nps, insurance, donation)
        """
        filename_lower = filename.lower()

        if filename_lower.endswith('.pdf'):
            return self.process_pdf(file_bytes, doc_type=doc_type)
        elif filename_lower.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff')):
            return self.process_image(file_bytes, doc_type=doc_type)
        else:
            return {
                'success': False,
                'data': {},
                'errors': {'general': [f'Unsupported file type: {filename}']},
                'raw_text': '',
            }


# ═════════════════════════════════════════════════════════════════════════════
# Special Document Type Extraction (Form 16, Payslip, Deductions, etc.)
# ═════════════════════════════════════════════════════════════════════════════

class SpecializedExtractor:
    """Extract specific document types (deductions, investments, etc.) using AI."""

    @staticmethod
    def extract_home_loan(file_bytes: bytes) -> Dict[str, Any]:
        """Extract Home Loan certificate data."""
        try:
            file_b64 = base64.b64encode(file_bytes).decode('utf-8')
            result = extract_document(file_b64, mime="application/pdf", doc_type="homeloan")
            if not result or not isinstance(result, dict):
                result = {}
            return {
                'success': bool(result and any(result.values())),
                'data': result,
                'errors': {} if (result and any(result.values())) else {'extraction': ['Could not extract home loan data']},
            }
        except Exception as e:
            return {
                'success': False,
                'data': {},
                'errors': {'extraction': [str(e)]},
            }

    @staticmethod
    def extract_insurance(file_bytes: bytes) -> Dict[str, Any]:
        """Extract Insurance policy data."""
        try:
            file_b64 = base64.b64encode(file_bytes).decode('utf-8')
            result = extract_document(file_b64, mime="application/pdf", doc_type="insurance")
            return {
                'success': bool(result),
                'data': result or {},
                'errors': {} if result else {'extraction': ['Could not extract insurance data']},
            }
        except Exception as e:
            return {
                'success': False,
                'data': {},
                'errors': {'extraction': [str(e)]},
            }

    @staticmethod
    def extract_nps(file_bytes: bytes) -> Dict[str, Any]:
        """Extract NPS statement data."""
        try:
            file_b64 = base64.b64encode(file_bytes).decode('utf-8')
            result = extract_document(file_b64, mime="application/pdf", doc_type="nps")
            return {
                'success': bool(result),
                'data': result or {},
                'errors': {} if result else {'extraction': ['Could not extract NPS data']},
            }
        except Exception as e:
            return {
                'success': False,
                'data': {},
                'errors': {'extraction': [str(e)]},
            }

    @staticmethod
    def extract_school_fees(file_bytes: bytes) -> Dict[str, Any]:
        """Extract School fees receipt data."""
        try:
            file_b64 = base64.b64encode(file_bytes).decode('utf-8')
            result = extract_document(file_b64, mime="application/pdf", doc_type="school")
            return {
                'success': bool(result),
                'data': result or {},
                'errors': {} if result else {'extraction': ['Could not extract school fees data']},
            }
        except Exception as e:
            return {
                'success': False,
                'data': {},
                'errors': {'extraction': [str(e)]},
            }

    @staticmethod
    def extract_donation(file_bytes: bytes) -> Dict[str, Any]:
        """Extract 80G Donation certificate data."""
        try:
            file_b64 = base64.b64encode(file_bytes).decode('utf-8')
            result = extract_document(file_b64, mime="application/pdf", doc_type="donation")
            return {
                'success': bool(result),
                'data': result or {},
                'errors': {} if result else {'extraction': ['Could not extract donation data']},
            }
        except Exception as e:
            return {
                'success': False,
                'data': {},
                'errors': {'extraction': [str(e)]},
            }
