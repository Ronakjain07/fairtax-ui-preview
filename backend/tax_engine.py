"""
FairTax — Tax engine for FY 2025-26 (AY 2026-27)
Clean, single-source-of-truth implementation
"""

# ================= HELPERS =================

def _num(x):
    if x is None or x == "":
        return 0.0
    try:
        return float(str(x).replace(',', ''))
    except:
        return 0.0

import tax_config


# ================= TAX SLABS =================

def slab_tax_old(taxable):
    """Compute old-regime tax (pre-cess) using centralized config.
    Returns tax before cess (i.e., the value callers should multiply by
    (1 + CESS_RATE) to get total tax).
    """
    return compute_tax_before_cess(taxable, 'OLD')


def slab_tax_new(taxable):
    """Compute new-regime tax (pre-cess) using centralized config."""
    return compute_tax_before_cess(taxable, 'NEW')


def compute_tax_before_cess(taxable, regime):
    """Centralized tax computation (pre-cess) applying slabs and rebate.

    - Uses tax_config.SLABS[regime]
    - Applies rebate as per tax_config.REBATE[regime] (if present)
    - Applies a marginal-relief style cap consistent with prior behavior
      (keeps legacy marginal relief calculation to avoid surprise changes).
    """
    try:
        slabs = tax_config.SLABS.get(regime)
    except Exception:
        slabs = None

    if not slabs:
        return 0.0

    raw = _compute_slabs(taxable, slabs)

    # Apply rebate if configured
    rebate_cfg = tax_config.REBATE.get(regime, {}) if hasattr(tax_config, 'REBATE') else {}
    threshold = rebate_cfg.get('threshold')
    cap = rebate_cfg.get('cap', 0)

    tax = raw
    if threshold is not None and taxable <= threshold:
        tax = 0.0  # FIXED: Section 87A rebate eliminates tax completely, not subtract cap
    elif threshold is not None:
        # Legacy marginal relief behaviour preserved: ensure tax not exceed
        # taxable - threshold. This mimics existing logic in older engine.
        if tax > (taxable - threshold):
            tax = taxable - threshold

    return float(tax)


def _compute_slabs(taxable, slabs):
    """Compute tax by slab rates without applying rebates or marginal relief.
    This helper is used to expose intermediate values for debugging/clarity.
    """
    tax = 0.0
    remaining = float(taxable)
    for limit, rate in slabs:
        chunk = min(remaining, limit)
        tax += chunk * rate
        remaining -= chunk
        if remaining <= 0:
            break
    return tax


def _apply_surcharge_and_cess(tax_before_cess, total_income):
    """Apply surcharge (based on tax_config.SURCHARGE_BANDS) and cess.

    Returns a dict with keys: surcharge_rate, surcharge_amount,
    tax_after_surcharge, cess_amount, total_tax
    """
    try:
        rate = 0.0
        for th, r in tax_config.SURCHARGE_BANDS:
            try:
                if total_income >= th:  # FIXED: Changed > to >= (taxpayers at exact threshold should get surcharge)
                    rate = r
            except Exception:
                continue
    except Exception:
        rate = 0.0

    surcharge_amount = round(tax_before_cess * rate, 2)
    tax_after_surcharge = tax_before_cess + surcharge_amount
    cess_amount = round(tax_after_surcharge * tax_config.CESS_RATE, 2)
    total_tax = round(tax_after_surcharge + cess_amount, 2)

    return {
        'surcharge_rate': rate,
        'surcharge_amount': surcharge_amount,
        'tax_after_surcharge': round(tax_after_surcharge, 2),
        'cess_amount': cess_amount,
        'total_tax': total_tax,
    }


# ================= HRA =================

def calculate_hra_exemption(basic, hra_received, rent_paid, is_metro):
    basic = _num(basic)
    hra_received = _num(hra_received)
    rent_paid = _num(rent_paid)

    if rent_paid <= 0.10 * basic:
        return 0

    percent = 0.5 if is_metro else 0.4

    return max(
        0,
        min(
            hra_received,
            percent * basic,
            rent_paid - 0.10 * basic
        )
    )


# ================= VARIANT CONSTANTS =================

VARIANT_B = {"lta": 65000, "sec10_14_ii": 28000, "sec10_14_i": 98000}
VARIANT_C = {"lta": 95000, "sec10_14_ii": 76000, "sec10_14_i": 228000}


# ================= CORE OLD REGIME =================

def _compute_old_regime(
    gross,
    other_income,
    sec10_total,
    home_loan_interest,
    std_deduction,
    pt,
    deductions_total,
    tds
):
    gti = gross + other_income - sec10_total - home_loan_interest - std_deduction - pt
    taxable = max(0, gti - deductions_total)

    tax = slab_tax_old(taxable)
    # Apply surcharge and cess based on total income (gti)
    s_info = _apply_surcharge_and_cess(tax, gti)
    total_tax = s_info['total_tax']

    refund = round(tds - total_tax, 2)

    return {
        "gti": round(gti, 2),
        "taxable": round(taxable, 2),
        "tax": round(tax, 2),
        "surcharge_rate": s_info['surcharge_rate'],
        "surcharge_amount": s_info['surcharge_amount'],
        "tax_after_surcharge": s_info['tax_after_surcharge'],
        "cess_amount": s_info['cess_amount'],
        "total_tax": total_tax,
        "refund": refund,
    }


# ================= MAIN FUNCTION =================

def calculate(payload):
    g = lambda k, d=0: _num(payload.get(k, d))

    is_metro = str(payload.get("city_type", "")).lower() == "metro"

    # ===== BASIC INPUTS =====
    gross = g("gross_salary")
    basic = g("basic_salary")
    hra_received = g("hra_received")

    # FIXED: Handle rent correctly — detect if it's already annual or monthly
    # Priority: use monthly_rent if provided, fallback to rent_paid
    monthly_rent = g("monthly_rent") or 0
    rent_paid_field = g("rent_paid") or 0

    # If rent_paid_field > 1 lakh, assume it's annual; otherwise multiply by 12
    if rent_paid_field > 0 and monthly_rent == 0:
        # Use rent_paid_field: if it looks like annual (>100k), use as-is; otherwise multiply by 12
        if rent_paid_field > 100000:
            rent_paid = rent_paid_field  # Already annual
        else:
            rent_paid = rent_paid_field * 12  # Multiply monthly by 12
    else:
        # Use monthly_rent and multiply by 12
        rent_paid = monthly_rent * 12

    tds = g("tds_paid") or g("tds_deducted")

    # House property: 30% standard deduction under Section 24(a)
    rental_annual = g("rental_income_monthly") * 12
    rental_taxable = round(rental_annual * 0.70, 2) if rental_annual > 0 else 0

    other_income = (
        rental_taxable
        + g("fno_pl")
        + g("securities_income")
        + g("business_income")
        + g("other_income_misc")
        + g("fd_interest")
        + g("dividend")
        + g("refund_interest")
    )

    # ===== HRA =====
    hra_exempt = calculate_hra_exemption(
        basic, hra_received, rent_paid, is_metro
    )

    # ===== SECTION 10 =====
    lta = g("lta")
    sec10_14_i = g("car_lease_allowance")
    sec10_14_ii = g("uniform_allowance")

    home_loan_interest_raw = g("home_loan_interest")
    home_loan_interest = min(home_loan_interest_raw, 200000)

    # ===== STANDARD =====
    std_old = tax_config.STANDARD_DEDUCTION.get('OLD', 50000)
    std_new = tax_config.STANDARD_DEDUCTION.get('NEW', 75000)
    pt = g("professional_tax")

    # ===== DEDUCTIONS =====
    sec_80c = min(
        g("pf_employee")
        + g("ulip_lic")
        + g("school_fees")
        + g("home_loan_principal"),
        150000,
    )

    sec_80ccd_1b = min(g("nps_self"), 50000)
    sec_80ccd_2 = min(g("nps_employer"), 0.10 * basic)
    sec_80ccd_2_new = min(g("nps_employer"), 0.14 * basic)

    parents_senior = str(payload.get("parents_senior", "")).lower() in (
        "1", "true", "yes"
    )

    sec_80d = min(g("medical_self"), 25000) + min(
        g("medical_parents"),
        50000 if parents_senior else 25000,
    )

    # Additional deductions available from form/frontend
    sec_80e = g("sec_80e")  # Education loan interest (no upper limit)
    sec_80g = g("sec_80g")  # Donations (80G) - treated as a deduction here (AI may refine)
    # 80TTA savings bank interest deduction (cap ₹10,000)
    savings_interest = min(g("savings_interest"), 10000)
    # 80DB - Medical treatment of specified disease (cap ₹100,000)
    sec_80db = min(g("sec_80db", 0), 100000)

    deductions_total = (
        sec_80c + sec_80ccd_1b + sec_80ccd_2 + sec_80d + sec_80e + sec_80g + savings_interest + sec_80db
    )

    # ===== OLD REGIME (ACTUAL) =====
    sec10_total = hra_exempt + lta + sec10_14_i + sec10_14_ii

    old_a = _compute_old_regime(
        gross,
        other_income,
        sec10_total,
        home_loan_interest,
        std_old,
        pt,
        deductions_total,
        tds,
    )

    # ===== NEW REGIME =====
    gti_new = gross + other_income - std_new

    taxable_new = max(0, gti_new - sec_80ccd_2_new)

    tax_new = slab_tax_new(taxable_new)
    s_info_new = _apply_surcharge_and_cess(tax_new, gti_new)
    total_tax_new = s_info_new['total_tax']

    refund_new = round(tds - total_tax_new, 2)

    # ===== VARIANT A =====
    variant_a_refund = max(old_a["refund"], refund_new)
    variant_a_regime = "OLD" if old_a["refund"] >= refund_new else "NEW"

    # ===== VARIANT B =====
    sec10_b = (
        hra_exempt
        + VARIANT_B["lta"]
        + VARIANT_B["sec10_14_i"]
        + VARIANT_B["sec10_14_ii"]
    )

    old_b = _compute_old_regime(
        gross,
        other_income,
        sec10_b,
        home_loan_interest,
        std_old,
        pt,
        deductions_total,
        tds,
    )

    # ===== VARIANT C =====
    sec10_c = (
        hra_exempt
        + VARIANT_C["lta"]
        + VARIANT_C["sec10_14_i"]
        + VARIANT_C["sec10_14_ii"]
    )

    old_c = _compute_old_regime(
        gross,
        other_income,
        sec10_c,
        home_loan_interest,
        std_old,
        pt,
        deductions_total,
        tds,
    )

    # ===== INTERMEDIATE RAW TAXES (pre-rebate) FOR DEBUG/EXPLAINABILITY =====
    old_slabs = tax_config.SLABS.get('OLD')
    new_slabs = tax_config.SLABS.get('NEW')

    old_a_raw = _compute_slabs(old_a["taxable"], old_slabs)
    old_b_raw = _compute_slabs(old_b["taxable"], old_slabs)
    old_c_raw = _compute_slabs(old_c["taxable"], old_slabs)
    new_raw = _compute_slabs(taxable_new, new_slabs)

    # ===== FINAL OUTPUT =====
    return {
        # Basic
        "gross_salary": round(gross, 2),
        "basic_salary": round(basic, 2),
        "hra_received": round(hra_received, 2),
        "hra_exempt_actual": round(hra_exempt, 2),
        "tds_paid": round(tds, 2),

        # Allowed capped values
        "home_loan_interest_allowed": round(home_loan_interest, 2),

        # Deductions
        "sec_80c": round(sec_80c, 2),
        "sec_80d": round(sec_80d, 2),
        "sec_80db": round(sec_80db, 2),
        "sec_80e": round(sec_80e, 2),
        "sec_80g": round(sec_80g, 2),
        "savings_interest": round(savings_interest, 2),
        "sec_80ccd_1b": round(sec_80ccd_1b, 2),
        "sec_80ccd_2": round(sec_80ccd_2, 2),
        "deductions_total": round(deductions_total, 2),

        # New Regime
        "taxable_new": round(taxable_new, 2),
        "new_tax_raw": round(new_raw, 2),
        "new_tax_before_cess": round(tax_new, 2),
        "total_tax_new": total_tax_new,
        "refund_new": refund_new,
        "new_surcharge_rate": s_info_new.get('surcharge_rate', 0.0),
        "new_surcharge_amount": s_info_new.get('surcharge_amount', 0.0),
        "new_tax_after_surcharge": s_info_new.get('tax_after_surcharge', 0.0),
        "new_cess_amount": s_info_new.get('cess_amount', 0.0),

        # Old A
        "taxable_old_a": old_a["taxable"],
        "old_tax_raw_a": round(old_a_raw, 2),
        "old_tax_before_cess_a": old_a["tax"],
        "total_tax_old_a": old_a["total_tax"],
        "refund_old_a": old_a["refund"],
        "old_surcharge_rate_a": old_a.get('surcharge_rate', 0.0),
        "old_surcharge_amount_a": old_a.get('surcharge_amount', 0.0),
        "old_tax_after_surcharge_a": old_a.get('tax_after_surcharge', 0.0),
        "old_cess_amount_a": old_a.get('cess_amount', 0.0),

        # Old B
        "taxable_old_b": old_b["taxable"],
        "old_tax_raw_b": round(old_b_raw, 2),
        "old_tax_before_cess_b": old_b["tax"],
        "total_tax_old_b": old_b["total_tax"],
        "refund_old_b": old_b["refund"],
        "old_surcharge_rate_b": old_b.get('surcharge_rate', 0.0),
        "old_surcharge_amount_b": old_b.get('surcharge_amount', 0.0),
        "old_tax_after_surcharge_b": old_b.get('tax_after_surcharge', 0.0),
        "old_cess_amount_b": old_b.get('cess_amount', 0.0),

        # Old C
        "taxable_old_c": old_c["taxable"],
        "old_tax_raw_c": round(old_c_raw, 2),
        "old_tax_before_cess_c": old_c["tax"],
        "total_tax_old_c": old_c["total_tax"],
        "refund_old_c": old_c["refund"],
        "old_surcharge_rate_c": old_c.get('surcharge_rate', 0.0),
        "old_surcharge_amount_c": old_c.get('surcharge_amount', 0.0),
        "old_tax_after_surcharge_c": old_c.get('tax_after_surcharge', 0.0),
        "old_cess_amount_c": old_c.get('cess_amount', 0.0),

        # Variants
        "variant_a_refund": variant_a_refund,
        "variant_a_regime": variant_a_regime,
        "variant_b_refund": old_b["refund"],
        "variant_c_refund": old_c["refund"],

        # Status
        "approval_status": "PENDING",
    }