"""
Normalization Service - Data Aggregation & Conflict Resolution

Handles:
- Multi-page document merging
- Annual/monthly conversion
- Duplicate detection
- Conflict detection across multiple documents
- Deduction classification
"""

import hashlib
import json


def _compute_checksum(data, fields):
    """
    Compute checksum of key fields to detect duplicates.

    Args:
        data: Extraction result dict
        fields: List of field names to include in checksum

    Returns:
        Hex checksum string
    """
    values = []
    for field in fields:
        val = data.get(field)
        if val is not None:
            values.append(str(val))
    checksum_str = "|".join(values)
    return hashlib.md5(checksum_str.encode()).hexdigest()


def normalize_extractions(extractions_list, doc_types_list):
    """
    Normalize and aggregate multiple document extractions.

    Handles:
    - Multiple Form16s (sum gross salary, basic, etc.)
    - Multiple payslips (detect FY overlap, sum)
    - Annual/monthly conversion
    - Duplicate detection
    - Conflict detection
    - Deduction classification

    Args:
        extractions_list: List of extraction results
        doc_types_list: List of document types (corresponding to extractions)

    Returns:
        {
            "normalized": {field: value},
            "assumptions": [str],
            "extraction_confidence": float,
            "fields_high_confidence": [str],
            "fields_low_confidence": [str],
            "duplicates": [dict],
            "conflicts": [dict]
        }
    """
    if not extractions_list:
        return {
            "normalized": {},
            "assumptions": [],
            "extraction_confidence": 0,
            "fields_high_confidence": [],
            "fields_low_confidence": [],
            "duplicates": [],
            "conflicts": []
        }

    # Extract field data (handle both formats)
    extractions_data = []
    for ext in extractions_list:
        if "fields" in ext:
            # Vision extractor format
            fields = ext["fields"]
            flat = {}
            for k, v in fields.items():
                if isinstance(v, dict) and "value" in v:
                    flat[k] = v["value"]
                else:
                    flat[k] = v
            extractions_data.append({
                "data": flat,
                "fields": fields,
                "confidence": ext.get("overall_confidence", 0),
                "doc_type": ext.get("document_type_detected", doc_types_list[len(extractions_data)]) if len(extractions_data) < len(doc_types_list) else "unknown"
            })
        else:
            # Legacy format or flat dict
            extractions_data.append({
                "data": ext,
                "fields": {k: {"value": v, "confidence": 0.7} for k, v in ext.items()},
                "confidence": 0.7,
                "doc_type": doc_types_list[len(extractions_data)] if len(extractions_data) < len(doc_types_list) else "unknown"
            })

    # ─────── DUPLICATE DETECTION ──────────────────────
    duplicates = []
    seen_checksums = {}

    for i, ext_data in enumerate(extractions_data):
        # Checksum based on key fields
        key_fields = ["gross_salary", "basic_salary", "pan", "employer_name", "month", "year"]
        checksum = _compute_checksum(ext_data["data"], key_fields)

        if checksum in seen_checksums:
            duplicates.append({
                "index1": seen_checksums[checksum]["index"],
                "index2": i,
                "doc_type": ext_data["doc_type"],
                "checksum": checksum,
                "note": "Likely duplicate document"
            })
        else:
            seen_checksums[checksum] = {"index": i, "data": ext_data}

    # ─────── AGGREGATION & CONFLICT DETECTION ──────────
    normalized = {}
    conflicts = []
    all_confidences = []
    high_confidence_fields = []
    low_confidence_fields = []

    # Collect all fields across extractions
    all_field_keys = set()
    for ext_data in extractions_data:
        all_field_keys.update(ext_data["data"].keys())

    # Process each field
    for field_name in all_field_keys:
        field_values = []

        for ext_data in extractions_data:
            if field_name in ext_data["data"]:
                value = ext_data["data"][field_name]
                field_info = ext_data["fields"].get(field_name, {})
                confidence = field_info.get("confidence", 0.7) if isinstance(field_info, dict) else 0.7

                field_values.append({
                    "value": value,
                    "confidence": confidence,
                    "doc_type": ext_data["doc_type"]
                })

        if not field_values:
            normalized[field_name] = None
            continue

        # Single value: use it
        if len(field_values) == 1:
            normalized[field_name] = field_values[0]["value"]
            conf = field_values[0]["confidence"]
            all_confidences.append(conf)
            if conf >= 0.8:
                high_confidence_fields.append(field_name)
            elif conf < 0.6:
                low_confidence_fields.append(field_name)
            continue

        # Multiple values: consolidate
        numeric_values = []
        string_values = []

        for fv in field_values:
            val = fv["value"]
            if val is None:
                continue
            if isinstance(val, (int, float)):
                numeric_values.append(fv)
            else:
                string_values.append(fv)

        # For salary documents (multiple Form16s): sum numeric values
        if numeric_values and all(ext["doc_type"] == "form16" for ext in extractions_data):
            total = sum(fv["value"] for fv in numeric_values if isinstance(fv["value"], (int, float)))
            normalized[field_name] = int(total) if isinstance(total, float) and total.is_integer() else total

            # Log if different values (conflict)
            unique_vals = set(str(fv["value"]) for fv in numeric_values)
            if len(unique_vals) > 1:
                conflicts.append({
                    "field": field_name,
                    "type": "multi_form16_aggregate",
                    "values": [(fv["value"], fv["confidence"], fv["doc_type"]) for fv in numeric_values],
                    "result": "summed"
                })

            avg_conf = sum(fv["confidence"] for fv in numeric_values) / len(numeric_values)
            all_confidences.append(avg_conf)

        # For mixed numeric: use highest confidence
        elif numeric_values:
            best = max(numeric_values, key=lambda x: x["confidence"])
            normalized[field_name] = best["value"]

            # Conflict if values differ significantly
            if len(numeric_values) > 1:
                values = [fv["value"] for fv in numeric_values]
                if max(values) - min(values) > 0.1 * max(values):
                    conflicts.append({
                        "field": field_name,
                        "type": "numeric_divergence",
                        "values": [(fv["value"], fv["confidence"], fv["doc_type"]) for fv in numeric_values],
                        "chosen": best["value"],
                        "reason": f"Highest confidence ({best['confidence']})"
                    })

            all_confidences.append(best["confidence"])

        # For strings: use first non-empty
        elif string_values:
            normalized[field_name] = string_values[0]["value"]
            all_confidences.append(string_values[0]["confidence"])

            if len(string_values) > 1:
                unique_vals = set(str(sv["value"]) for sv in string_values)
                if len(unique_vals) > 1:
                    conflicts.append({
                        "field": field_name,
                        "type": "string_mismatch",
                        "values": [(sv["value"], sv["doc_type"]) for sv in string_values],
                        "chosen": string_values[0]["value"],
                        "reason": "First non-empty value selected"
                    })

    # ─────── ASSUMPTIONS ─────────────────────────────
    assumptions = []

    # Check for payslips (monthly amounts) that need annualization
    for ext_data in extractions_data:
        if ext_data["doc_type"] == "payslip":
            monthly_fields = {"gross_salary", "basic_salary", "hra_received", "special_allowance"}
            has_monthly = any(k in ext_data["data"] for k in monthly_fields)
            if has_monthly:
                assumptions.append("Payslip amounts are monthly; will be annualized (×12) in tax calculation")
                break

    # Multi-document aggregation
    if len(extractions_data) > 1:
        form16_count = sum(1 for e in extractions_data if e["doc_type"] == "form16")
        if form16_count > 1:
            assumptions.append(f"{form16_count} Form16 documents detected: numeric fields summed (multiple employers)")

    # ─────── FILTER SENSITIVE FIELDS ─────────────────
    # Exclude metadata fields from normalized output
    normalized = {k: v for k, v in normalized.items() if not k.startswith("_")}

    # Compute overall extraction confidence
    overall_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0

    return {
        "normalized": normalized,
        "assumptions": assumptions,
        "extraction_confidence": round(overall_confidence, 2),
        "fields_high_confidence": list(set(high_confidence_fields)),
        "fields_low_confidence": list(set(low_confidence_fields)),
        "duplicates": duplicates,
        "conflicts": conflicts
    }
