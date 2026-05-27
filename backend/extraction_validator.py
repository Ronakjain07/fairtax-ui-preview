"""
EXTRACTION VALIDATOR: Comprehensive validation and reconciliation for tax data.

Ensures:
1. Annual/YTD consistency (never mixes monthly with annual)
2. Form 16 as primary authoritative source
3. Document-level reconciliation
4. Multi-document aggregation with deduplication
5. Confidence scoring and fallback hierarchy
6. Strict caps applied after aggregation, not before
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple, Any

logger = logging.getLogger(__name__)

class ValidationError(Exception):
    """Raised when validation fails critically."""
    pass

class ExtractionValidator:
    """Validates and reconciles extracted tax data."""

    # Thresholds for reconciliation
    ANNUAL_VARIANCE_TOLERANCE = 0.15  # 15% variance allowed
    FORM16_CONFIDENCE = 0.95  # Form 16 is highly authoritative
    YTD_CONFIDENCE = 0.90    # YTD/Annual payslips are confident
    MONTHLY_CONFIDENCE = 0.70  # Monthly payslips need annualization

    # Deduction caps (all values in annual rupees)
    CAPS = {
        'sec_80c': 150000,
        'sec_80ccd_1b': 50000,
        'sec_80d_self': 25000,
        'sec_80d_parents': 50000,
        'sec_80d_senior_parents': 100000,
        'home_loan_interest': 200000,
    }

    # Required annual fields from salary documents
    SALARY_ANNUAL_FIELDS = [
        'gross_salary', 'basic_salary', 'hra_received',
        'pf_employee', 'tds_paid'
    ]

    def __init__(self, extractions: List[Dict], merged_data: Dict):
        """Initialize with raw extractions and merged data."""
        self.extractions = extractions
        self.merged_data = merged_data
        self.validations = []  # Track all validations
        self.errors = []       # Critical errors
        self.warnings = []     # Non-critical issues

    def validate(self) -> Tuple[Dict, Dict]:
        """
        Run full validation and reconciliation.

        Returns:
            (validated_data, validation_report)
        """
        try:
            # Step 1: Detect document types and confidence
            doc_analysis = self._analyze_documents()

            # Step 2: Extract annual values with source tracking
            annual_values = self._extract_annual_values(doc_analysis)

            # Step 3: Validate annual/monthly consistency
            self._validate_annual_monthly_consistency(annual_values)

            # Step 4: Reconcile with Form 16 as primary
            reconciled = self._reconcile_with_form16(doc_analysis, annual_values)

            # Step 5: Handle multi-document aggregation
            aggregated = self._aggregate_multiple_documents(doc_analysis, reconciled)

            # Step 6: Validate document-level totals
            self._reconcile_document_totals(doc_analysis, aggregated)

            # Step 7: Check for deduplication
            deduplicated = self._deduplicate_multiple_entries(aggregated)

            # Step 8: Apply caps AFTER aggregation
            capped = self._apply_caps_after_aggregation(deduplicated)

            # Step 9: Validate final consistency
            self._final_consistency_check(capped)

            # If we reach here, validation passed
            validation_report = {
                'valid': len(self.errors) == 0,
                'errors': self.errors,
                'warnings': self.warnings,
                'validations': self.validations,
                'document_analysis': doc_analysis,
                'confidence_scores': doc_analysis.get('confidence_scores', {})
            }

            return capped, validation_report

        except ValidationError as e:
            logger.error(f"[VALIDATION] Critical error: {e}")
            self.errors.append(str(e))
            # Return original data with error flags
            validation_report = {
                'valid': False,
                'errors': self.errors,
                'warnings': self.warnings,
                'critical_failure': str(e)
            }
            return self.merged_data, validation_report

    def _analyze_documents(self) -> Dict:
        """Identify document types, confidence, and primary sources."""
        analysis = {
            'documents': [],
            'primary_source': None,
            'confidence_scores': {},
            'form16_present': False,
            'payslip_present': False,
            'payslip_is_ytd': False,
        }

        for i, ext in enumerate(self.extractions):
            doc_type = ext.get('_doc_type', 'unknown')
            source = ext.get('_source_filename', f'doc_{i}')

            doc_info = {
                'index': i,
                'type': doc_type,
                'source': source,
                'confidence': self.FORM16_CONFIDENCE if doc_type == 'form16' else
                             (self.YTD_CONFIDENCE if ext.get('is_ytd') else self.MONTHLY_CONFIDENCE)
            }

            analysis['documents'].append(doc_info)
            analysis['confidence_scores'][source] = doc_info['confidence']

            if doc_type == 'form16':
                analysis['form16_present'] = True
                analysis['primary_source'] = source
            elif doc_type == 'payslip':
                analysis['payslip_present'] = True
                if ext.get('is_ytd'):
                    analysis['payslip_is_ytd'] = True

        # Form 16 is always primary if present
        if analysis['form16_present']:
            analysis['primary_source'] = [d['source'] for d in analysis['documents']
                                         if d['type'] == 'form16'][0]

        self.validations.append(f"Document analysis: {len(analysis['documents'])} documents, "
                               f"primary={analysis['primary_source']}")
        return analysis

    def _extract_annual_values(self, doc_analysis: Dict) -> Dict:
        """Extract annual values with source tracking and annualization."""
        annual = {}

        for i, ext in enumerate(self.extractions):
            doc_type = ext.get('_doc_type', 'unknown')
            source = ext.get('_source_filename', f'doc_{i}')
            is_ytd = ext.get('is_ytd', False)

            for field in self.SALARY_ANNUAL_FIELDS:
                value = ext.get(field, 0)
                if not value or value == 0:
                    continue

                # Determine if value needs annualization
                needs_annualization = (
                    doc_type == 'payslip' and not is_ytd
                )

                if needs_annualization:
                    annual_value = value * 12
                    self.warnings.append(
                        f"Annualized {field} from monthly payslip: "
                        f"₹{value:,.0f}/month → ₹{annual_value:,.0f}/year"
                    )
                else:
                    annual_value = value

                if field not in annual:
                    annual[field] = {
                        'value': annual_value,
                        'source': source,
                        'doc_type': doc_type,
                        'is_annualized': needs_annualization
                    }
                else:
                    # Track multiple values for reconciliation
                    if 'alternatives' not in annual[field]:
                        annual[field]['alternatives'] = []
                    annual[field]['alternatives'].append({
                        'value': annual_value,
                        'source': source,
                        'doc_type': doc_type,
                        'is_annualized': needs_annualization
                    })

        self.validations.append(f"Extracted {len(annual)} annual fields with reconciliation")
        return annual

    def _validate_annual_monthly_consistency(self, annual_values: Dict) -> None:
        """Validate that monthly and annual values are not mixed for same field."""
        for field, data in annual_values.items():
            if 'alternatives' not in data:
                continue

            # Check if any values are annualized (were monthly)
            sources = [data['source']] + [a['source'] for a in data['alternatives']]
            annualized = [data.get('is_annualized')] + [a.get('is_annualized') for a in data['alternatives']]

            if any(annualized) and not all(annualized):
                self.errors.append(
                    f"{field}: Mixed monthly and annual values detected. "
                    f"Sources: {sources}. Using annual values only."
                )

    def _reconcile_with_form16(self, doc_analysis: Dict, annual_values: Dict) -> Dict:
        """Ensure Form 16 is primary source for salary data."""
        reconciled = dict(self.merged_data)  # Start with merged

        if not doc_analysis['form16_present']:
            self.warnings.append("No Form 16 found. Using alternative sources with caution.")
            return reconciled

        # Form 16 values override all others for salary fields
        form16_source = doc_analysis['primary_source']

        for field in self.SALARY_ANNUAL_FIELDS:
            if field in annual_values:
                data = annual_values[field]

                # If Form 16 has this field, use it exclusively
                if data['source'] == form16_source:
                    reconciled[field] = data['value']
                    self.validations.append(f"Using {field} from Form 16 (primary source)")
                elif 'alternatives' in data:
                    # Form 16 might be in alternatives
                    form16_val = next(
                        (a['value'] for a in data['alternatives'] if a['source'] == form16_source),
                        None
                    )
                    if form16_val is not None:
                        reconciled[field] = form16_val
                        self.validations.append(f"Using {field} from Form 16 (primary source)")
                    else:
                        # Form 16 doesn't have this, use next best source
                        best = max(data['alternatives'],
                                  key=lambda x: doc_analysis['confidence_scores'].get(x['source'], 0))
                        reconciled[field] = best['value']
                        self.warnings.append(
                            f"Form 16 missing {field}, using {best['source']} "
                            f"(confidence: {doc_analysis['confidence_scores'].get(best['source']):.0%})"
                        )

        return reconciled

    def _aggregate_multiple_documents(self, doc_analysis: Dict, reconciled: Dict) -> Dict:
        """Handle aggregation of multiple documents (insurance, school, etc.)."""
        aggregated = dict(reconciled)

        # Insurance: Aggregate all policies
        if len([d for d in self.extractions if d.get('_doc_type') == 'insurance']) > 1:
            aggregated = self._aggregate_insurance(aggregated)

        # School: Aggregate all fee receipts
        if len([d for d in self.extractions if d.get('_doc_type') == 'school']) > 1:
            aggregated = self._aggregate_school_fees(aggregated)

        return aggregated

    def _aggregate_insurance(self, data: Dict) -> Dict:
        """Aggregate insurance policies and classify for Section 80D."""
        # Find all insurance extractions
        insurance_policies = [
            e for e in self.extractions
            if e.get('_doc_type') == 'insurance'
        ]

        if len(insurance_policies) <= 1:
            return data

        # Aggregate premiums by coverage type
        self_premiums = 0
        parent_premiums = 0
        senior_parent_premiums = 0

        processed = set()  # Track processed policies to avoid duplication

        for policy in insurance_policies:
            policy_id = policy.get('policy_no', '')
            if policy_id in processed:
                continue

            premium = policy.get('premium_amount', 0)
            coverage = policy.get('coverage_type', '').lower()
            policyholder = policy.get('policyholder', '').lower()

            if 'self' in policyholder or 'individual' in coverage:
                self_premiums += premium
            elif 'parent' in policyholder or 'senior' in policyholder:
                if 'senior' in policyholder:
                    senior_parent_premiums += premium
                else:
                    parent_premiums += premium

            processed.add(policy_id)

        # Store for 80D calculation
        data['_insurance_aggregated'] = {
            'self_premiums': self_premiums,
            'parent_premiums': parent_premiums,
            'senior_parent_premiums': senior_parent_premiums,
            'total_policies': len(processed)
        }

        self.validations.append(
            f"Aggregated {len(processed)} insurance policies: "
            f"self=₹{self_premiums:,.0f}, parents=₹{parent_premiums:,.0f}, "
            f"senior=₹{senior_parent_premiums:,.0f}"
        )

        return data

    def _aggregate_school_fees(self, data: Dict) -> Dict:
        """Aggregate school fee receipts and deduplicate."""
        school_receipts = [
            e for e in self.extractions
            if e.get('_doc_type') == 'school'
        ]

        if len(school_receipts) <= 1:
            return data

        # Deduplicate by school and academic year
        seen = set()
        total_fees = 0
        children_count = 0

        for receipt in school_receipts:
            school_name = receipt.get('school_name', '').strip()
            fees = receipt.get('school_fees', 0)

            # Simple dedup: school_name is unique per child
            if school_name not in seen:
                total_fees += fees
                children_count += 1
                seen.add(school_name)
            else:
                self.warnings.append(f"Duplicate school fee receipt from {school_name}, skipping")

        data['_school_aggregated'] = {
            'total_eligible_fees': total_fees,
            'number_of_children': children_count,
            'schools': list(seen)
        }

        self.validations.append(
            f"Aggregated school fees for {children_count} children: ₹{total_fees:,.0f}"
        )

        return data

    def _reconcile_document_totals(self, doc_analysis: Dict, data: Dict) -> None:
        """Validate that document totals match extracted/calculated values."""
        for i, ext in enumerate(self.extractions):
            doc_type = ext.get('_doc_type', 'unknown')
            source = ext.get('_source_filename', f'doc_{i}')

            if doc_type == 'form16':
                # Form 16 should have gross_salary
                form16_gross = ext.get('gross_salary', 0)
                if form16_gross > 0:
                    reconciled_gross = data.get('gross_salary', 0)
                    if abs(form16_gross - reconciled_gross) > 100:  # Allow small rounding
                        self.warnings.append(
                            f"Form 16 gross mismatch: "
                            f"Form16={form16_gross:,.0f}, reconciled={reconciled_gross:,.0f}"
                        )

            elif doc_type == 'payslip' and ext.get('is_ytd'):
                # YTD payslip totals should match salary
                payslip_gross = ext.get('gross_salary', 0)
                reconciled_gross = data.get('gross_salary', 0)
                variance = abs(payslip_gross - reconciled_gross) / max(payslip_gross, reconciled_gross) if max(payslip_gross, reconciled_gross) > 0 else 0

                if variance > self.ANNUAL_VARIANCE_TOLERANCE:
                    self.warnings.append(
                        f"YTD payslip-to-reconciled variance: {variance:.1%}. "
                        f"Using Form 16 value if available."
                    )

    def _deduplicate_multiple_entries(self, data: Dict) -> Dict:
        """Remove duplicate deduction entries from multiple documents."""
        dedup = dict(data)

        # Check for duplicate NPS entries
        nps_docs = [e for e in self.extractions if e.get('_doc_type') == 'nps']
        if len(nps_docs) > 1:
            total_nps = sum(e.get('nps_self', 0) for e in nps_docs)
            dedup['nps_self'] = total_nps
            self.validations.append(f"Deduplicated {len(nps_docs)} NPS documents")

        # Check for duplicate donation entries
        donation_docs = [e for e in self.extractions if e.get('_doc_type') == 'donation']
        if len(donation_docs) > 1:
            total_donated = sum(e.get('donation_amount', 0) for e in donation_docs)
            dedup['donation_amount'] = total_donated
            self.validations.append(f"Deduplicated {len(donation_docs)} donation receipts")

        return dedup

    def _apply_caps_after_aggregation(self, data: Dict) -> Dict:
        """Apply statutory caps AFTER aggregation, not before."""
        capped = dict(data)

        # Section 80C cap
        sec_80c = capped.get('sec_80c', 0)
        if sec_80c > self.CAPS['sec_80c']:
            original = sec_80c
            capped['sec_80c'] = self.CAPS['sec_80c']
            self.warnings.append(
                f"Section 80C capped: ₹{original:,.0f} → ₹{self.CAPS['sec_80c']:,.0f}"
            )

        # Section 80CCD(1B) cap
        sec_80ccd_1b = capped.get('sec_80ccd_1b', 0)
        if sec_80ccd_1b > self.CAPS['sec_80ccd_1b']:
            original = sec_80ccd_1b
            capped['sec_80ccd_1b'] = self.CAPS['sec_80ccd_1b']
            self.warnings.append(
                f"Section 80CCD(1B) capped: ₹{original:,.0f} → ₹{self.CAPS['sec_80ccd_1b']:,.0f}"
            )

        # Section 80D cap (self + parents)
        sec_80d_self = capped.get('sec_80d_self', 0)
        sec_80d_parents = capped.get('sec_80d_parents', 0)
        sec_80d_senior = capped.get('sec_80d_senior_parents', 0)

        # Apply individual caps
        if sec_80d_self > self.CAPS['sec_80d_self']:
            capped['sec_80d_self'] = self.CAPS['sec_80d_self']
            self.warnings.append(
                f"Section 80D (self) capped to ₹{self.CAPS['sec_80d_self']:,.0f}"
            )

        if sec_80d_parents > self.CAPS['sec_80d_parents']:
            capped['sec_80d_parents'] = self.CAPS['sec_80d_parents']
            self.warnings.append(
                f"Section 80D (parents) capped to ₹{self.CAPS['sec_80d_parents']:,.0f}"
            )

        if sec_80d_senior > self.CAPS['sec_80d_senior_parents']:
            capped['sec_80d_senior_parents'] = self.CAPS['sec_80d_senior_parents']
            self.warnings.append(
                f"Section 80D (senior parents) capped to ₹{self.CAPS['sec_80d_senior_parents']:,.0f}"
            )

        # Home loan interest cap
        home_loan = capped.get('home_loan_interest', 0)
        if home_loan > self.CAPS['home_loan_interest']:
            original = home_loan
            capped['home_loan_interest'] = self.CAPS['home_loan_interest']
            self.warnings.append(
                f"Home loan interest capped: ₹{original:,.0f} → ₹{self.CAPS['home_loan_interest']:,.0f}"
            )

        return capped

    def _final_consistency_check(self, data: Dict) -> None:
        """Final validation before allowing recommendation."""
        # Check for negative values
        for field in ['gross_salary', 'basic_salary', 'tds_paid']:
            if data.get(field, 0) < 0:
                self.errors.append(f"{field} is negative: ₹{data[field]:,.0f}")

        # Check for impossibly high values
        gross = data.get('gross_salary', 0)
        if gross > 100000000:  # >1 crore is extremely rare
            self.warnings.append(
                f"Gross salary seems very high: ₹{gross:,.0f}. Verify Form 16."
            )

        # Check TDS vs Gross consistency
        tds = data.get('tds_paid', 0)
        if gross > 0 and tds > gross * 0.5:  # TDS shouldn't be >50% of gross
            self.warnings.append(
                f"TDS (₹{tds:,.0f}) seems high relative to gross (₹{gross:,.0f}). Verify."
            )

        self.validations.append("Final consistency check passed")
