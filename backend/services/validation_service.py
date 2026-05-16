"""
Validation Service - Data Quality & Business Rule Enforcement

Validates extracted financial data against:
- Field ranges and types
- Business logic (e.g., HRA ≤ 50% of basic)
- Tax deduction caps (80C ≤ 150K, etc.)
- Sanity checks
"""

import re


def _is_valid_pan(pan):
    """Validate PAN format (XXXXX9999X)."""
    if not pan:
        return False
    return bool(re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]$', str(pan).strip().upper()))


def validate_extraction(normalized_data):
    """
    Validate extracted data against business rules and deduction caps.

    Args:
        normalized_data: Normalized extraction result dict

    Returns:
        {
            "valid": True/False,
            "errors": [
                {"field": str, "reason": str, "value": any}
            ],
            "warnings": [
                {"field": str, "reason": str, "value": any}
            ]
        }
    """
    errors = []
    warnings = []

    if not normalized_data:
        return {"valid": False, "errors": [{"reason": "No data to validate"}], "warnings": []}

    # Helper: get numeric value safely
    def get_num(key, default=0):
        val = normalized_data.get(key, default)
        try:
            return float(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    # ─────── FIELD VALIDATION ──────────────────────────

    # PAN format — extracted PAN is often misread by OCR; treat as warning so user can correct it
    pan = normalized_data.get("pan")
    if pan and not _is_valid_pan(pan):
        warnings.append({
            "field": "pan",
            "reason": "Invalid PAN format (expected XXXXX9999X) — please verify",
            "value": pan
        })

    # ─────── MONETARY FIELD RANGES ──────────────────────

    gross = get_num("gross_salary")
    basic = get_num("basic_salary")
    hra = get_num("hra_received")
    tds = get_num("tds_paid")

    # No negative values
    for field in ["gross_salary", "basic_salary", "hra_received", "lta", "special_allowance",
                   "pf_employee", "pf_employer", "tds_paid", "professional_tax"]:
        val = get_num(field)
        if val < 0:
            errors.append({
                "field": field,
                "reason": "Cannot be negative",
                "value": val
            })

    # Basic <= Gross — OCR can misread amounts; treat as warning so user can correct
    if basic > 0 and gross > 0 and basic > gross:
        warnings.append({
            "field": "basic_salary",
            "reason": f"Basic ({int(basic)}) exceeds gross ({int(gross)}) — verify amounts",
            "value": basic
        })

    # HRA <= 50% of basic
    if hra > 0 and basic > 0:
        hra_max = basic * 0.5
        if hra > hra_max:
            warnings.append({
                "field": "hra_received",
                "reason": f"HRA ({int(hra)}) exceeds 50% of basic ({int(hra_max)}); only capped amount is tax-exempt",
                "value": hra
            })

    # TDS <= Gross — OCR can misread amounts; treat as warning so user can correct
    if tds > 0 and gross > 0 and tds > gross:
        warnings.append({
            "field": "tds_paid",
            "reason": f"TDS ({int(tds)}) exceeds gross salary ({int(gross)}) — verify amounts",
            "value": tds
        })

    # HRA > 0 but basic = 0 (warning)
    if hra > 0 and basic == 0:
        warnings.append({
            "field": "hra_received",
            "reason": "HRA present but basic salary not found; HRA exemption calculation may be affected",
            "value": hra
        })

    # ─────── HOME LOAN VALIDATION ──────────────────────

    home_loan_interest = get_num("home_loan_interest")
    home_loan_principal = get_num("home_loan_principal")

    if home_loan_interest > 200000:
        warnings.append({
            "field": "home_loan_interest",
            "reason": f"Home loan interest ({int(home_loan_interest)}) exceeds ₹200K cap; only ₹200K allowed under Section 24",
            "value": home_loan_interest
        })

    if home_loan_principal < 0 or home_loan_interest < 0:
        errors.append({
            "field": "home_loan",
            "reason": "Home loan interest and principal cannot be negative",
            "value": {"interest": home_loan_interest, "principal": home_loan_principal}
        })

    # ─────── SECTION 80D (INSURANCE) VALIDATION ──────

    # Section 80D: ₹25K (self) + ₹50K (parents if senior) or ₹25K (parents if non-senior)
    # Actual capping happens in tax engine; here we just warn if unrealistic
    ulip_lic = get_num("ulip_lic") or get_num("premium_amount", 0)
    if ulip_lic > 500000:
        warnings.append({
            "field": "insurance_premium",
            "reason": f"Insurance premium ({int(ulip_lic)}) is unusually high; verify this is annual amount",
            "value": ulip_lic
        })

    # ─────── SECTION 80C VALIDATION ──────────────────

    # 80C cap: ₹150K total (PF + ULIP + school fees + home loan principal)
    school_fees = get_num("school_fees")
    nps_self = get_num("nps_self")
    pf_emp = get_num("pf_employee")

    total_80c_inputs = pf_emp + ulip_lic + school_fees + home_loan_principal + nps_self
    if total_80c_inputs > 300000:  # Warning threshold (double the cap)
        warnings.append({
            "field": "section_80c",
            "reason": f"Total 80C inputs ({int(total_80c_inputs)}) exceed ₹150K cap; verify all amounts",
            "value": total_80c_inputs
        })

    # ─────── SCHOOL FEES VALIDATION ────────────────────

    if school_fees > 1000000:
        warnings.append({
            "field": "school_fees",
            "reason": f"School fees ({int(school_fees)}) is very high; verify annual amount",
            "value": school_fees
        })

    if school_fees < 0:
        errors.append({
            "field": "school_fees",
            "reason": "School fees cannot be negative",
            "value": school_fees
        })

    # ─────── DONATION (80G) VALIDATION ────────────────

    donation = normalized_data.get("donation_amount") or normalized_data.get("sec_80g", 0)
    donation_pan = normalized_data.get("donee_pan")

    if donation and donation > 0 and not _is_valid_pan(donation_pan):
        warnings.append({
            "field": "donation",
            "reason": "80G donation requires valid donee PAN; current PAN is invalid",
            "value": {"amount": donation, "pan": donation_pan}
        })

    if donation < 0:
        errors.append({
            "field": "sec_80g",
            "reason": "Donation amount cannot be negative",
            "value": donation
        })

    # ─────── ASSESSMENT YEAR ───────────────────────────

    ay = normalized_data.get("assessment_year")
    if ay and not re.match(r'^\d{4}-\d{2}$', str(ay)):
        warnings.append({
            "field": "assessment_year",
            "reason": f"Assessment year format unexpected: {ay} (expected YYYY-YY)",
            "value": ay
        })

    # ─────── OVERALL VALIDATION ────────────────────────

    valid = len(errors) == 0

    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings
    }
