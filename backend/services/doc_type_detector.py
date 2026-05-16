"""
Document Type Detector

Auto-detects document type from filename, content, or visual features.
Helps when doc_type is not explicitly provided.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Keywords to detect document types
DOC_TYPE_KEYWORDS = {
    'form16': ['form 16', 'form16', 'itr', 'tax', '16a', 'salary certificate', 'employer'],
    'payslip': ['payslip', 'salary slip', 'pay slip', 'monthly', 'gross salary', 'deduction'],
    'homeloan': ['home loan', 'homeloan', 'interest certificate', 'principal', 'loan statement', 'iic'],
    'school': ['school', 'tuition', 'fees', 'education', 'college', 'university', 'receipt'],
    'nps': ['nps', 'national pension', 'pension statement', 'pran', 'contribution'],
    'insurance': ['insurance', 'premium', 'policy', 'lic', 'ulip', 'health', 'mediclaim', 'coverage'],
    'donation': ['donation', '80g', 'receipt', 'donee', 'charitable', 'trust'],
}

VALID_DOC_TYPES = ['form16', 'payslip', 'homeloan', 'school', 'nps', 'insurance', 'donation']


def detect_from_filename(filename):
    """
    Detect document type from filename.

    Args:
        filename: str, e.g. "payslip_may_2024.pdf"

    Returns:
        str: Detected doc_type or None
    """
    if not filename:
        return None

    filename_lower = filename.lower()

    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in filename_lower:
                logger.info(f"[DOC_TYPE_DETECTOR] Detected '{doc_type}' from filename: {filename}")
                return doc_type

    return None


def detect_from_content_hints(extracted_fields):
    """
    Detect document type from extracted fields.

    Args:
        extracted_fields: dict of extracted fields

    Returns:
        str: Detected doc_type or None
    """
    if not extracted_fields:
        return None

    field_names = set(extracted_fields.keys())

    # Form16-specific fields
    if {'assessment_year', 'tds_paid', 'pf_employer'}.issubset(field_names):
        logger.info("[DOC_TYPE_DETECTOR] Detected 'form16' from extracted fields")
        return 'form16'

    # Payslip-specific fields
    if {'month', 'year', 'gross_salary', 'basic_salary'}.intersection(field_names):
        if 'month' in field_names:  # Month is payslip-specific
            logger.info("[DOC_TYPE_DETECTOR] Detected 'payslip' from extracted fields")
            return 'payslip'

    # Home loan-specific fields
    if {'loan_account_no', 'bank_name', 'home_loan_interest'}.intersection(field_names):
        logger.info("[DOC_TYPE_DETECTOR] Detected 'homeloan' from extracted fields")
        return 'homeloan'

    # School-specific fields
    if {'school_fees', 'school_name'}.intersection(field_names):
        logger.info("[DOC_TYPE_DETECTOR] Detected 'school' from extracted fields")
        return 'school'

    # NPS-specific fields
    if {'nps_self', 'nps_pran'}.intersection(field_names):
        logger.info("[DOC_TYPE_DETECTOR] Detected 'nps' from extracted fields")
        return 'nps'

    # Insurance-specific fields
    if {'policy_no', 'premium_amount', 'coverage_type'}.intersection(field_names):
        logger.info("[DOC_TYPE_DETECTOR] Detected 'insurance' from extracted fields")
        return 'insurance'

    # Donation-specific fields
    if {'donation_amount', 'donee_pan'}.intersection(field_names):
        logger.info("[DOC_TYPE_DETECTOR] Detected 'donation' from extracted fields")
        return 'donation'

    return None


def resolve_doc_type(provided_type, filename=None, extracted_fields=None):
    """
    Resolve final document type using multiple detection methods.

    Args:
        provided_type: str, explicitly provided doc_type (may be "form16" default)
        filename: str, filename to check
        extracted_fields: dict, extracted fields for content-based detection

    Returns:
        str: Final resolved doc_type
    """
    # If explicit type provided and valid, use it
    if provided_type and provided_type in VALID_DOC_TYPES and provided_type != 'form16':
        return provided_type

    # Try filename detection
    if filename:
        detected = detect_from_filename(filename)
        if detected:
            return detected

    # Try content detection
    if extracted_fields:
        detected = detect_from_content_hints(extracted_fields)
        if detected:
            return detected

    # Fallback to provided type (likely form16)
    logger.info(f"[DOC_TYPE_DETECTOR] Using default/provided type: {provided_type}")
    return provided_type


def suggest_correct_doc_type(provided_type, filename, extracted_fields):
    """
    Suggest if a different doc_type should have been used.

    Args:
        provided_type: str, provided doc_type
        filename: str, filename
        extracted_fields: dict, extracted fields

    Returns:
        {
            "should_retry": bool,
            "suggested_type": str or None,
            "reason": str
        }
    """
    # Don't suggest retry if it's already correct
    if provided_type != 'form16':
        return {
            "should_retry": False,
            "suggested_type": None,
            "reason": "Document type was explicitly provided"
        }

    # Check if we detected a different type
    detected_from_filename = detect_from_filename(filename) if filename else None
    detected_from_content = detect_from_content_hints(extracted_fields) if extracted_fields else None

    # Prefer content detection over filename
    suggested = detected_from_content or detected_from_filename

    if suggested and suggested != provided_type:
        return {
            "should_retry": True,
            "suggested_type": suggested,
            "reason": f"Document appears to be {suggested}, not {provided_type}. "
                     f"Re-upload with doc_type='{suggested}' for better extraction."
        }

    return {
        "should_retry": False,
        "suggested_type": None,
        "reason": "No alternative document type detected"
    }
