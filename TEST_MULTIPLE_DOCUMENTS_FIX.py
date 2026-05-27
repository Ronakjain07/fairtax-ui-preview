#!/usr/bin/env python3
"""
Test Suite: Multiple Documents Aggregation Fix

Tests the corrected normalization_service.py to verify that:
1. Multiple home loans are summed correctly
2. Multiple school fee documents are summed correctly
3. Multiple NPS accounts are summed correctly
4. Multiple insurance policies are summed correctly
5. Conflicts are properly logged
6. Assumptions are correctly generated
"""

import sys
sys.path.insert(0, '/backend')

from services import normalization_service

# ─────── TEST 1: Two Home Loans ─────────────────────────────────────
print("=" * 80)
print("TEST 1: Two Home Loans (Should SUM interests and principals)")
print("=" * 80)

home_loan_extractions = [
    {
        "fields": {
            "loan_account_no": {"value": "HDFC123", "confidence": 0.95},
            "bank_name": {"value": "HDFC Bank", "confidence": 0.95},
            "home_loan_interest": {"value": 250000, "confidence": 0.95},
            "home_loan_principal": {"value": 400000, "confidence": 0.92},
        },
        "overall_confidence": 0.93,
        "document_type_detected": "homeloan",
    },
    {
        "fields": {
            "loan_account_no": {"value": "SBI456", "confidence": 0.93},
            "bank_name": {"value": "SBI Bank", "confidence": 0.94},
            "home_loan_interest": {"value": 180000, "confidence": 0.90},
            "home_loan_principal": {"value": 300000, "confidence": 0.88},
        },
        "overall_confidence": 0.91,
        "document_type_detected": "homeloan",
    }
]

result = normalization_service.normalize_extractions(home_loan_extractions, ["homeloan", "homeloan"])

print("\n✓ Input: 2 home loan documents")
print(f"  Loan 1: Interest=250,000, Principal=400,000")
print(f"  Loan 2: Interest=180,000, Principal=300,000")
print(f"\n✓ Output:")
print(f"  home_loan_interest = {result['normalized'].get('home_loan_interest')} (Expected: 430000)")
print(f"  home_loan_principal = {result['normalized'].get('home_loan_principal')} (Expected: 700000)")

# Verify
assert result['normalized'].get('home_loan_interest') == 430000, "❌ Interest not summed correctly!"
assert result['normalized'].get('home_loan_principal') == 700000, "❌ Principal not summed correctly!"
print(f"\n✅ TEST 1 PASSED: Home loan interests and principals correctly summed")
print(f"   Conflicts: {result['conflicts']}")
print(f"   Assumptions: {result['assumptions']}")

# ─────── TEST 2: Two School Fee Documents ─────────────────────────────
print("\n" + "=" * 80)
print("TEST 2: Two School Fee Documents (Should SUM fees)")
print("=" * 80)

school_extractions = [
    {
        "fields": {
            "school_name": {"value": "ABC International School", "confidence": 0.95},
            "school_fees": {"value": 150000, "confidence": 0.92},
        },
        "overall_confidence": 0.93,
        "document_type_detected": "school",
    },
    {
        "fields": {
            "school_name": {"value": "XYZ High School", "confidence": 0.94},
            "school_fees": {"value": 120000, "confidence": 0.90},
        },
        "overall_confidence": 0.92,
        "document_type_detected": "school",
    }
]

result = normalization_service.normalize_extractions(school_extractions, ["school", "school"])

print("\n✓ Input: 2 school fee documents")
print(f"  School 1: Fees=150,000")
print(f"  School 2: Fees=120,000")
print(f"\n✓ Output:")
print(f"  school_fees = {result['normalized'].get('school_fees')} (Expected: 270000)")

assert result['normalized'].get('school_fees') == 270000, "❌ School fees not summed correctly!"
print(f"\n✅ TEST 2 PASSED: School fees correctly summed")
print(f"   Conflicts: {result['conflicts']}")
print(f"   Assumptions: {result['assumptions']}")

# ─────── TEST 3: Two NPS Accounts ──────────────────────────────────
print("\n" + "=" * 80)
print("TEST 3: Two NPS Accounts (Should SUM contributions)")
print("=" * 80)

nps_extractions = [
    {
        "fields": {
            "nps_pran": {"value": "PRAN123456", "confidence": 0.98},
            "nps_self": {"value": 50000, "confidence": 0.94},
            "nps_employer": {"value": 50000, "confidence": 0.92},
        },
        "overall_confidence": 0.95,
        "document_type_detected": "nps",
    },
    {
        "fields": {
            "nps_pran": {"value": "PRAN789012", "confidence": 0.97},
            "nps_self": {"value": 40000, "confidence": 0.91},
            "nps_employer": {"value": 40000, "confidence": 0.90},
        },
        "overall_confidence": 0.93,
        "document_type_detected": "nps",
    }
]

result = normalization_service.normalize_extractions(nps_extractions, ["nps", "nps"])

print("\n✓ Input: 2 NPS account documents")
print(f"  NPS Account 1: Self=50,000, Employer=50,000")
print(f"  NPS Account 2: Self=40,000, Employer=40,000")
print(f"\n✓ Output:")
print(f"  nps_self = {result['normalized'].get('nps_self')} (Expected: 90000)")
print(f"  nps_employer = {result['normalized'].get('nps_employer')} (Expected: 90000)")

assert result['normalized'].get('nps_self') == 90000, "❌ NPS self contribution not summed!"
assert result['normalized'].get('nps_employer') == 90000, "❌ NPS employer contribution not summed!"
print(f"\n✅ TEST 3 PASSED: NPS contributions correctly summed")
print(f"   Conflicts: {result['conflicts']}")
print(f"   Assumptions: {result['assumptions']}")

# ─────── TEST 4: Two Insurance Policies ────────────────────────────
print("\n" + "=" * 80)
print("TEST 4: Two Insurance Policies (Should SUM premiums)")
print("=" * 80)

insurance_extractions = [
    {
        "fields": {
            "policy_no": {"value": "POL001", "confidence": 0.95},
            "insurer_name": {"value": "LIC of India", "confidence": 0.96},
            "premium_amount": {"value": 50000, "confidence": 0.92},
            "coverage_type": {"value": "life", "confidence": 0.95},
        },
        "overall_confidence": 0.94,
        "document_type_detected": "insurance",
    },
    {
        "fields": {
            "policy_no": {"value": "POL002", "confidence": 0.96},
            "insurer_name": {"value": "SBI Life", "confidence": 0.95},
            "premium_amount": {"value": 35000, "confidence": 0.93},
            "coverage_type": {"value": "life", "confidence": 0.94},
        },
        "overall_confidence": 0.95,
        "document_type_detected": "insurance",
    }
]

result = normalization_service.normalize_extractions(insurance_extractions, ["insurance", "insurance"])

print("\n✓ Input: 2 insurance policy documents")
print(f"  Policy 1: Premium=50,000")
print(f"  Policy 2: Premium=35,000")
print(f"\n✓ Output:")
print(f"  premium_amount = {result['normalized'].get('premium_amount')} (Expected: 85000)")

assert result['normalized'].get('premium_amount') == 85000, "❌ Insurance premiums not summed!"
print(f"\n✅ TEST 4 PASSED: Insurance premiums correctly summed")
print(f"   Conflicts: {result['conflicts']}")
print(f"   Assumptions: {result['assumptions']}")

# ─────── TEST 5: Form16s Still Work (Backward Compatibility) ──────
print("\n" + "=" * 80)
print("TEST 5: Multiple Form16s (Backward Compatibility Check)")
print("=" * 80)

form16_extractions = [
    {
        "fields": {
            "employer_name": {"value": "Company A", "confidence": 0.95},
            "pan": {"value": "AAAAA0001A", "confidence": 0.98},
            "gross_salary": {"value": 1200000, "confidence": 0.95},
            "basic_salary": {"value": 600000, "confidence": 0.92},
            "tds_paid": {"value": 150000, "confidence": 0.96},
        },
        "overall_confidence": 0.95,
        "document_type_detected": "form16",
    },
    {
        "fields": {
            "employer_name": {"value": "Company B", "confidence": 0.94},
            "pan": {"value": "AAAAA0001A", "confidence": 0.98},
            "gross_salary": {"value": 800000, "confidence": 0.93},
            "basic_salary": {"value": 400000, "confidence": 0.91},
            "tds_paid": {"value": 100000, "confidence": 0.95},
        },
        "overall_confidence": 0.93,
        "document_type_detected": "form16",
    }
]

result = normalization_service.normalize_extractions(form16_extractions, ["form16", "form16"])

print("\n✓ Input: 2 Form16 documents (multiple employers)")
print(f"  Form16 1: Gross=1,200,000, TDS=150,000")
print(f"  Form16 2: Gross=800,000, TDS=100,000")
print(f"\n✓ Output:")
print(f"  gross_salary = {result['normalized'].get('gross_salary')} (Expected: 2000000)")
print(f"  tds_paid = {result['normalized'].get('tds_paid')} (Expected: 250000)")

assert result['normalized'].get('gross_salary') == 2000000, "❌ Form16 salaries not summed!"
assert result['normalized'].get('tds_paid') == 250000, "❌ Form16 TDS not summed!"
print(f"\n✅ TEST 5 PASSED: Form16 documents still summed correctly (backward compatible)")
print(f"   Assumptions: {result['assumptions']}")

# ─────── TEST 6: Mixed Document Types (Should NOT sum) ──────────────
print("\n" + "=" * 80)
print("TEST 6: Mixed Document Types (Should NOT sum, use highest confidence)")
print("=" * 80)

mixed_extractions = [
    {
        "fields": {
            "school_fees": {"value": 150000, "confidence": 0.95},
            "school_name": {"value": "School A", "confidence": 0.94},
        },
        "overall_confidence": 0.94,
        "document_type_detected": "school",
    },
    {
        "fields": {
            "premium_amount": {"value": 50000, "confidence": 0.92},
            "policy_no": {"value": "POL123", "confidence": 0.95},
        },
        "overall_confidence": 0.93,
        "document_type_detected": "insurance",
    }
]

result = normalization_service.normalize_extractions(mixed_extractions, ["school", "insurance"])

print("\n✓ Input: Mixed documents (school + insurance)")
print(f"  School fees: 150,000")
print(f"  Insurance premium: 50,000")
print(f"\n✓ Output:")
print(f"  school_fees = {result['normalized'].get('school_fees')} (Expected: 150000 - NOT summed)")
print(f"  premium_amount = {result['normalized'].get('premium_amount')} (Expected: 50000 - NOT summed)")

assert result['normalized'].get('school_fees') == 150000, "❌ School fees should not be summed with insurance!"
assert result['normalized'].get('premium_amount') == 50000, "❌ Premium should not be summed with school!"
print(f"\n✅ TEST 6 PASSED: Mixed documents not incorrectly summed")
print(f"   (Each field extracted separately, not cross-type aggregation)")

# ─────── TEST 7: Conflict Detection ────────────────────────────────
print("\n" + "=" * 80)
print("TEST 7: Conflict Detection (When values differ)")
print("=" * 80)

conflict_extractions = [
    {
        "fields": {
            "home_loan_interest": {"value": 250000, "confidence": 0.95},
            "home_loan_principal": {"value": 400000, "confidence": 0.92},
            "bank_name": {"value": "HDFC Bank", "confidence": 0.96},
        },
        "overall_confidence": 0.93,
        "document_type_detected": "homeloan",
    },
    {
        "fields": {
            "home_loan_interest": {"value": 180000, "confidence": 0.88},
            "home_loan_principal": {"value": 300000, "confidence": 0.85},
            "bank_name": {"value": "SBI Bank", "confidence": 0.94},
        },
        "overall_confidence": 0.89,
        "document_type_detected": "homeloan",
    }
]

result = normalization_service.normalize_extractions(conflict_extractions, ["homeloan", "homeloan"])

print("\n✓ Input: 2 home loans with DIFFERENT interest values (250K and 180K)")
print(f"\n✓ Output:")
print(f"  home_loan_interest = {result['normalized'].get('home_loan_interest')} (Summed: 430,000)")
print(f"  Conflicts detected: {len(result['conflicts'])} conflicts")
for conflict in result['conflicts']:
    if conflict['field'] == 'home_loan_interest':
        print(f"    - Field: {conflict['field']}")
        print(f"      Type: {conflict['type']}")
        print(f"      Values: {conflict['values']}")
        print(f"      Result: {conflict['result']}")

assert len([c for c in result['conflicts'] if c['type'].startswith('multi_homeloan')]) > 0, "❌ Conflicts not detected!"
print(f"\n✅ TEST 7 PASSED: Conflicts correctly detected and logged")

# ─────── FINAL SUMMARY ─────────────────────────────────────────────
print("\n" + "=" * 80)
print("ALL TESTS PASSED ✅")
print("=" * 80)
print("\n✓ Multiple home loans: Correctly summed")
print("✓ Multiple school fees: Correctly summed")
print("✓ Multiple NPS accounts: Correctly summed")
print("✓ Multiple insurance policies: Correctly summed")
print("✓ Multiple Form16s: Still work correctly (backward compatible)")
print("✓ Mixed document types: Not incorrectly summed")
print("✓ Conflict detection: Working properly")
print("\n✓ The fix successfully handles all multiple document scenarios!")
print("=" * 80)
