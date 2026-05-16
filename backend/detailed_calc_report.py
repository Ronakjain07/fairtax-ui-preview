#!/usr/bin/env python3
"""
Detailed calculation report - show all input and calculated values
"""

import sys
sys.path.insert(0, 'C:\\Users\\user\\Desktop\\fairtax\\backend')

from sheets_service import _sheet, _ws_call, HEADERS
from tax_engine import calculate
import json

def _to_num(x):
    if x is None or x == "":
        return 0.0
    try:
        return float(str(x).replace(',', '').replace('₹', ''))
    except:
        return 0.0

def main():
    print("="*100)
    print("DETAILED TAX CALCULATION REPORT")
    print("="*100)

    try:
        ws = _sheet("Submissions")
        all_values = _ws_call(ws, 'get_all_values')

        if len(all_values) <= 1:
            print("\n[ERROR] No submissions found in sheets")
            return

        headers = all_values[0]
        rows = all_values[1:]

        print(f"\nFound {len(rows)} submission(s)\n")

        for idx, row in enumerate(rows, start=2):
            row_dict = dict(zip(HEADERS, row + [""] * (len(HEADERS) - len(row))))

            submission_id = row_dict.get('submission_id', '')
            name = row_dict.get('name', '')
            pan = row_dict.get('pan', '')

            print("\n" + "="*100)
            print(f"SUBMISSION #{idx}: {name} ({pan})")
            print(f"ID: {submission_id}")
            print("="*100)

            # Prepare payload
            payload = {k: _to_num(v) if isinstance(v, str) else v for k, v in row_dict.items()}

            # Calculate
            calc = calculate(payload)

            # INPUT DATA
            print("\n[INPUT DATA]")
            input_fields = [
                'gross_salary', 'basic_salary', 'hra_received', 'monthly_rent',
                'home_loan_interest', 'home_loan_principal',
                'pf_employee', 'ulip_lic', 'school_fees',
                'medical_self', 'medical_parents', 'nps_self', 'nps_employer',
                'tds_paid'
            ]
            for field in input_fields:
                val = _to_num(row_dict.get(field, ''))
                if val > 0:
                    print(f"  {field:30s}: {val:12.2f}")

            # DEDUCTIONS
            print("\n[DEDUCTIONS (Section 80)]")
            deduction_fields = [
                ('sec_80c', 'Section 80C (limit: 150,000)'),
                ('sec_80ccd_1b', 'Section 80CCD(1B) (limit: 50,000)'),
                ('sec_80ccd_2', 'Section 80CCD(2)'),
                ('sec_80d', 'Section 80D'),
                ('sec_80e', 'Section 80E'),
                ('sec_80g', 'Section 80G'),
                ('deductions_total', 'TOTAL DEDUCTIONS'),
            ]
            for field, label in deduction_fields:
                stored = _to_num(row_dict.get(field, ''))
                calc_val = _to_num(calc.get(field, 0))
                match = "[OK]" if abs(stored - calc_val) < 1 else "[DIFF]"
                print(f"  {label:35s}: stored={stored:12.2f}, calc={calc_val:12.2f} {match}")

            # TAX CALCULATIONS - NEW REGIME
            print("\n[NEW REGIME]")
            print(f"  Gross Income:        {_to_num(calc.get('gross_salary', 0)):12.2f}")
            print(f"  Standard Deduction:  75,000.00")
            print(f"  Taxable Income:      {_to_num(calc.get('taxable_new', 0)):12.2f}")
            new_tax_fields = [
                ('total_tax_new', 'Total Tax (with 4% cess)'),
                ('refund_new', 'Refund/Due'),
            ]
            for field, label in new_tax_fields:
                stored = _to_num(row_dict.get(field, ''))
                calc_val = _to_num(calc.get(field, 0))
                match = "[OK]" if abs(stored - calc_val) < 1 else "[DIFF]"
                print(f"  {label:35s}: stored={stored:12.2f}, calc={calc_val:12.2f} {match}")

            # TAX CALCULATIONS - OLD REGIME VARIANTS
            print("\n[OLD REGIME - VARIANT A]")
            old_a_fields = [
                ('taxable_old_a', 'Taxable Income'),
                ('total_tax_old_a', 'Total Tax (with 4% cess)'),
                ('refund_old_a', 'Refund/Due'),
            ]
            for field, label in old_a_fields:
                stored = _to_num(row_dict.get(field, ''))
                calc_val = _to_num(calc.get(field, 0))
                match = "[OK]" if abs(stored - calc_val) < 1 else "[DIFF]"
                print(f"  {label:35s}: stored={stored:12.2f}, calc={calc_val:12.2f} {match}")

            print("\n[OLD REGIME - VARIANT B] (increased allowances)")
            old_b_fields = [
                ('taxable_old_b', 'Taxable Income'),
                ('total_tax_old_b', 'Total Tax (with 4% cess)'),
                ('refund_old_b', 'Refund/Due'),
            ]
            for field, label in old_b_fields:
                stored = _to_num(row_dict.get(field, ''))
                calc_val = _to_num(calc.get(field, 0))
                match = "[OK]" if abs(stored - calc_val) < 1 else "[DIFF]"
                print(f"  {label:35s}: stored={stored:12.2f}, calc={calc_val:12.2f} {match}")

            print("\n[OLD REGIME - VARIANT C] (max allowances)")
            old_c_fields = [
                ('taxable_old_c', 'Taxable Income'),
                ('total_tax_old_c', 'Total Tax (with 4% cess)'),
                ('refund_old_c', 'Refund/Due'),
            ]
            for field, label in old_c_fields:
                stored = _to_num(row_dict.get(field, ''))
                calc_val = _to_num(calc.get(field, 0))
                match = "[OK]" if abs(stored - calc_val) < 1 else "[DIFF]"
                print(f"  {label:35s}: stored={stored:12.2f}, calc={calc_val:12.2f} {match}")

            # VARIANT RECOMMENDATIONS
            print("\n[VARIANT RECOMMENDATIONS]")
            var_fields = [
                ('variant_a_refund', 'Variant A - Best Refund'),
                ('variant_a_regime', 'Variant A - Regime'),
                ('variant_b_refund', 'Variant B - Refund'),
                ('variant_c_refund', 'Variant C - Refund'),
            ]
            for field, label in var_fields:
                stored = str(row_dict.get(field, ''))
                calc_val = str(calc.get(field, ''))
                match = "[OK]" if stored == calc_val else "[DIFF]"
                print(f"  {label:35s}: stored={stored:20s}, calc={calc_val:20s} {match}")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
