"""
Quality Checker Service

Validates extraction quality and provides actionable warnings for users.
Ensures confidence thresholds and data quality standards.
"""

import logging

logger = logging.getLogger(__name__)

# Confidence thresholds
CONFIDENCE_THRESHOLDS = {
    'high_confidence': 0.85,      # >= 0.85: Good quality
    'medium_confidence': 0.65,    # 0.65-0.85: Review recommended
    'low_confidence': 0.40,       # 0.40-0.65: Manual correction likely needed
    'fail_threshold': 0.40,       # < 0.40: Likely requires reupload
}

# Quality levels
QUALITY_LEVELS = {
    'high': 0.85,
    'medium': 0.65,
    'low': 0.40,
}


def assess_extraction_quality(extraction_result, doc_type):
    """
    Assess quality of extraction and return quality score + warnings.

    Args:
        extraction_result: dict from document_processor with confidence/metadata
        doc_type: Document type (form16, payslip, etc.)

    Returns:
        {
            "quality_level": "high|medium|low|failed",
            "confidence_score": float,
            "warnings": [{"type": str, "severity": "error|warning|info", "message": str}],
            "user_action_required": bool,
            "actionable_feedback": str
        }
    """
    warnings = []
    confidence = extraction_result.get('confidence', 0)

    # Check overall confidence
    if confidence < CONFIDENCE_THRESHOLDS['fail_threshold']:
        return {
            "quality_level": "failed",
            "confidence_score": confidence,
            "warnings": [{
                "type": "low_confidence",
                "severity": "error",
                "message": f"Extraction confidence too low ({confidence:.0%}). Document may be unclear or not a {doc_type}. "
                          f"Please upload a clear, high-quality image."
            }],
            "user_action_required": True,
            "actionable_feedback": "Please upload a clearer image or try again with better lighting"
        }

    # Determine quality level
    if confidence >= CONFIDENCE_THRESHOLDS['high_confidence']:
        quality_level = "high"
    elif confidence >= CONFIDENCE_THRESHOLDS['medium_confidence']:
        quality_level = "medium"
    else:
        quality_level = "low"

    # Check extraction metadata
    metadata = extraction_result.get('metadata', {})

    # Check for high confidence fields
    low_conf_fields = metadata.get('fields_low_confidence', [])
    if low_conf_fields:
        warnings.append({
            "type": "low_confidence_fields",
            "severity": "warning" if quality_level != "low" else "error",
            "message": f"Low confidence on fields: {', '.join(low_conf_fields[:5])}. "
                      f"Please review and correct these values."
        })

    # Check validation errors
    validation_errors = metadata.get('validation_errors', [])
    if validation_errors:
        for error in validation_errors[:3]:  # Show first 3 errors
            error_reason = error.get('reason', 'Unknown error')
            warnings.append({
                "type": "validation_error",
                "severity": "warning",
                "message": error_reason
            })

    # Check validation warnings
    validation_warns = metadata.get('validation_warnings', [])
    if validation_warns:
        for warn in validation_warns[:2]:  # Show first 2 warnings
            warn_reason = warn.get('reason', 'Unknown warning')
            warnings.append({
                "type": "validation_warning",
                "severity": "info",
                "message": warn_reason
            })

    # Check for conflicts/duplicates
    conflicts = metadata.get('conflicts', [])
    if conflicts:
        warnings.append({
            "type": "data_conflicts",
            "severity": "warning",
            "message": f"Data conflicts detected in {len(conflicts)} field(s). "
                      f"System picked most likely value, but please verify."
        })

    duplicates = metadata.get('duplicates', [])
    if duplicates:
        warnings.append({
            "type": "duplicate_documents",
            "severity": "info",
            "message": f"Duplicate or similar data detected from {len(duplicates)} source(s). "
                      f"Data merged using highest confidence values."
        })

    # Check extraction quality from metadata
    extraction_quality = metadata.get('extraction_quality', 'unknown')
    if extraction_quality == 'low':
        warnings.append({
            "type": "low_extraction_quality",
            "severity": "warning",
            "message": "Document quality is low. Please ensure document is clear, well-lit, and properly scanned."
        })

    # Determine if user action is required
    user_action_required = any(w['severity'] == 'error' for w in warnings)

    # Generate actionable feedback
    actionable_feedback = _generate_feedback(quality_level, warnings, confidence)

    return {
        "quality_level": quality_level,
        "confidence_score": round(confidence, 2),
        "warnings": warnings,
        "user_action_required": user_action_required,
        "actionable_feedback": actionable_feedback
    }


def _generate_feedback(quality_level, warnings, confidence):
    """Generate user-friendly feedback message."""

    if quality_level == "high":
        return "✅ Extraction looks great! Review the extracted data and make any corrections as needed."

    elif quality_level == "medium":
        error_count = len([w for w in warnings if w['severity'] == 'error'])
        warn_count = len([w for w in warnings if w['severity'] == 'warning'])

        if error_count > 0:
            return (f"⚠️ Extraction has {error_count} error(s) that need attention. "
                   f"Please review and correct the marked fields.")
        else:
            return (f"✓ Extraction is okay ({confidence:.0%} confidence). "
                   f"Please review extracted values carefully as some fields may need correction.")

    else:  # low
        return (f"⚠️ Extraction confidence is low ({confidence:.0%}). "
               f"Please carefully review all extracted values and make corrections. "
               f"Consider re-uploading a clearer image if available.")


def validate_data_completeness(extracted_data, doc_type):
    """
    Check if extracted data has required fields for filing.

    Args:
        extracted_data: dict of extracted fields
        doc_type: Document type

    Returns:
        {
            "complete": bool,
            "missing_fields": [str],
            "optional_fields": [str],
            "feedback": str
        }
    """
    # Define required and optional fields per document type
    REQUIRED_FIELDS = {
        'form16': ['pan', 'assessment_year', 'gross_salary', 'basic_salary', 'tds_paid'],
        'payslip': ['employer_name', 'gross_salary', 'basic_salary'],
        'homeloan': ['home_loan_interest'],
        'school': ['school_fees'],
        'nps': ['nps_self'],
        'insurance': ['premium_amount'],
        'donation': ['donation_amount', 'donee_pan'],
    }

    OPTIONAL_FIELDS = {
        'form16': ['employer_name', 'hra_received', 'pf_employee', 'professional_tax'],
        'payslip': ['tds_paid', 'hra_received'],
    }

    required = REQUIRED_FIELDS.get(doc_type, [])
    optional = OPTIONAL_FIELDS.get(doc_type, [])

    # Check for missing required fields
    missing = []
    for field in required:
        value = extracted_data.get(field)
        # Consider 0, None, "" as missing
        if value is None or value == 0 or value == "" or (isinstance(value, str) and not value.strip()):
            missing.append(field)

    # Check optional fields
    present_optional = []
    for field in optional:
        value = extracted_data.get(field)
        if value is not None and value != 0 and value != "":
            present_optional.append(field)

    is_complete = len(missing) == 0

    feedback = ""
    if is_complete:
        feedback = "✅ All required data extracted successfully!"
    else:
        feedback = f"⚠️ Missing {len(missing)} required field(s): {', '.join(missing)}. " \
                  f"You can manually enter these values in the form."

    return {
        "complete": is_complete,
        "missing_fields": missing,
        "present_optional_fields": present_optional,
        "feedback": feedback
    }


def suggest_document_reupload(quality_result):
    """
    Determine if document should be re-uploaded.

    Args:
        quality_result: dict from assess_extraction_quality()

    Returns:
        {
            "should_reupload": bool,
            "reason": str,
            "suggestions": [str]
        }
    """
    confidence = quality_result['confidence_score']
    quality_level = quality_result['quality_level']
    warnings = quality_result['warnings']

    if quality_level == "failed":
        return {
            "should_reupload": True,
            "reason": "Extraction failed - confidence too low",
            "suggestions": [
                "Ensure the document is a valid " + quality_result.get('doc_type', 'tax') + " document",
                "Use a clear, high-resolution image",
                "Ensure proper lighting - avoid shadows and glare",
                "Keep the document straight and well-framed",
                "Try a PDF if you had images, or vice versa"
            ]
        }

    elif quality_level == "low":
        has_low_conf_fields = any(w['type'] == 'low_confidence_fields' for w in warnings)
        if has_low_conf_fields or confidence < 0.5:
            return {
                "should_reupload": True,
                "reason": "Multiple fields have low confidence",
                "suggestions": [
                    "Try uploading a different copy of the document",
                    "Improve image resolution and lighting",
                    "Ensure all text is clearly visible"
                ]
            }

    return {
        "should_reupload": False,
        "reason": "Extraction is acceptable",
        "suggestions": []
    }
