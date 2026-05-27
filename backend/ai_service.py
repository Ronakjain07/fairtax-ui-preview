import requests
import json
import base64
import re
from config import Config
import tax_engine
import tax_config
from decimal import Decimal, ROUND_HALF_UP

EXTRACTION_PROMPT = """You are a tax document extractor. Extract ONLY factual values from the document.
Return ONLY valid JSON with these exact keys (use 0 if not found, strings for names):
{
  "name": "",
  "employer_name": "",
  "pan": "",
  "assessment_year": "",
  "gross_salary": 0,
  "basic_salary": 0,
  "hra_received": 0,
  "lta": 0,
  "special_allowance": 0,
  "car_lease_allowance": 0,
  "uniform_allowance": 0,
  "pf_employee": 0,
  "pf_employer": 0,
  "tds_paid": 0,
  "professional_tax": 0,
  "gratuity": 0,
  "leave_encashment": 0,
  "section_17_1": 0,
  "section_17_2": 0,
  "section_17_3": 0
}

CRITICAL RULES:
• Never invent values. Use 0 only if genuinely not found.
• All monetary values MUST be ANNUAL amounts (convert monthly by ×12 and note in assumptions).
• Do NOT guess or estimate. Extract only what you see.
• Numbers: plain integers (no commas, no currency symbols)."""

# Dedicated prompt for payslip text extraction (fast-path via pdfplumber)
PAYSLIP_TEXT_EXTRACTION_PROMPT = """You are an expert Indian payslip extractor. Extract salary data from the payslip text below.
Return ONLY valid JSON with these exact keys (use 0 if not found):
{
  "name": "",
  "employer_name": "",
  "pan": "",
  "gross_salary": 0,
  "basic_salary": 0,
  "hra_received": 0,
  "lta": 0,
  "special_allowance": 0,
  "car_lease_allowance": 0,
  "uniform_allowance": 0,
  "pf_employee": 0,
  "pf_employer": 0,
  "tds_paid": 0,
  "professional_tax": 0,
  "gratuity": 0,
  "leave_encashment": 0,
  "is_ytd": false,
  "assumptions": []
}

━━━ STEP 1: DETECT FORMAT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FORMAT A — MONTHLY PAYSLIP: single month, one "Amount" column.
  → Extract monthly figures. Set is_ytd=false. All values are monthly; multiply by 12 for annual.

FORMAT B — YTD/ANNUAL PAYSLIP: multiple month columns OR "Grand Total"/"YTD"/"Cumulative" column.
  → Extract ONLY from "Grand Total" / "YTD" / "Annual Total" / rightmost totals column.
  → DO NOT use individual month columns. Set is_ytd=true. Values are already annual (do NOT multiply by 12).

━━━ STEP 2: HRA — SUM ALL VARIANTS ━━━━━━━━━━━━━━━━━━━━━━━━━━
hra_received = SUM of ALL rows containing "HRA" in their label:
  HRA + NON-FBP HRA + BASIC HRA + METRO HRA + any other "...HRA..." row.
Add them all. Record each component in assumptions[].

━━━ STEP 3: TDS — INCOME TAX ROW ONLY ━━━━━━━━━━━━━━━━━━━━━━━
tds_paid = value from "INCOME TAX" or "TAX DEDUCTED AT SOURCE" or "TDS" row ONLY.
⚠ NEVER use "TOTAL DEDUCTION" or "TOTAL DEDUCTIONS" — that is the sum of all deductions.

━━━ STEP 4: PF & PROFESSIONAL TAX ━━━━━━━━━━━━━━━━━━━━━━━━━━━
pf_employee: "EMPLOYEE PF" / "PF EMPLOYEE" / "EPF EMPLOYEE" / "PF CONTRIBUTION"
pf_employer: "EMPLOYER PF" / "PF EMPLOYER" / "EPF EMPLOYER"
professional_tax: "PROFESSIONAL TAX" / "PROF TAX" / "PT"

CRITICAL RULES:
• Return plain integers only (no commas, no ₹ symbols).
• Never invent values. Use 0 only if genuinely not found.
• Record every assumption and conversion in the assumptions array."""

INVESTMENT_PROMPTS = {
    "homeloan": """You are a tax document extractor. Extract from Home Loan Interest Certificate / Statement.
Return ONLY valid JSON (use 0 if not found):
{
  "home_loan_interest": 0,
  "home_loan_principal": 0,
  "loan_account_no": "",
  "bank_name": "",
  "loan_outstanding": 0
}

CRITICAL RULES:
• Extract ANNUAL figures only (convert monthly by ×12).
• Never invent values.
• If interest and principal both appear, extract both (don't guess which applies).
• Numbers: plain integers (no commas, no currency symbols).""",

    "school": """You are a tax document extractor. Extract from School / Tuition Fee receipt.
Return ONLY valid JSON (use 0 if not found):
{
  "school_fees": 0,
  "school_name": ""
}

CRITICAL RULES:
• Extract ANNUAL total fees (if monthly is given, multiply by 12 and add "×12" to name if ambiguous).
• Never invent values.
• Numbers: plain integers (no commas, no currency symbols).""",

    "nps": """You are a tax document extractor. Extract from NPS (National Pension System) Statement.
Return ONLY valid JSON (use 0 if not found):
{
  "nps_self": 0,
  "nps_employer": 0,
  "nps_pran": ""
}

CRITICAL RULES:
• Extract ANNUAL contribution amounts.
• Distinguish self vs employer contributions clearly.
• If contributions vary by month, extract only the most recent full-year total or annotate ambiguity.
• Numbers: plain integers (no commas, no currency symbols).""",

    "insurance": """You are a tax document extractor. Extract from Insurance document (LIC / ULIP / Health Insurance).
Return ONLY valid JSON (use 0 if not found):
{
  "policy_no": "",
  "insurer_name": "",
  "premium_amount": 0,
  "sum_assured": 0,
  "coverage_type": "life or health"
}

CRITICAL RULES:
• Extract ANNUAL premium amount (convert monthly by ×12 if needed).
• Identify coverage_type as "life" (LIC, ULIP → Section 80C), "health" (mediclaim → Section 80D), or "both".
• Never invent values.
• Numbers: plain integers (no commas, no currency symbols).""",

    "donation": """You are a tax document extractor. Extract from Donation receipt / 80G certificate.
Return ONLY valid JSON (use 0 if not found):
{
  "donation_amount": 0,
  "organization_name": "",
  "donee_pan": "",
  "receipt_number": ""
}

CRITICAL RULES:
• Extract only 80G-eligible donations.
• Verify donee PAN is present (Section 80G requires valid PAN).
• Never invent values or PAN.
• Numbers: plain integers (no commas, no currency symbols).""",
}


def _call_openai(messages, max_tokens=2000):
    headers = {
        "Authorization": f"Bearer {Config.OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": Config.OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.0,  # FIXED: Changed from 0.1 to 0.0 for deterministic extraction
        "max_tokens": max_tokens,
    }
    r = requests.post(Config.OPENAI_URL, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse_json(text):
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def _regex_fallback(text, doc_type):
    """Regex fallback extraction when AI returns empty."""
    result = {}
    t = text.replace(',', '').replace('Rs.', '').replace('INR', '')

    if doc_type == 'homeloan':
        m = re.search(r'interest[^\d]*(\d{4,})', t, re.I)
        if m: result['home_loan_interest'] = int(m.group(1))
        m = re.search(r'principal[^\d]*(\d{4,})', t, re.I)
        if m: result['home_loan_principal'] = int(m.group(1))
        m = re.search(r'(?:bank|lender|nbfc)[^\n]*?([A-Za-z ]{3,30})', t, re.I)
        if m: result['bank_name'] = m.group(1).strip()

    elif doc_type == 'nps':
        m = re.search(r'PRAN[^\d]*(\d{12})', t, re.I)
        if m: result['nps_pran'] = m.group(1)
        m = re.search(r'(?:employee|subscriber)\s+contribution[^\d]*(\d{4,})', t, re.I)
        if m: result['nps_self'] = int(m.group(1))
        m = re.search(r'employer\s+contribution[^\d]*(\d{4,})', t, re.I)
        if m: result['nps_employer'] = int(m.group(1))

    elif doc_type == 'school':
        m = re.search(r'(?:total\s+)?fee[s]?[^\d]*(\d{3,})', t, re.I)
        if m: result['school_fees'] = int(m.group(1))

    elif doc_type == 'insurance':
        m = re.search(r'premium[^\d]*(\d{3,})', t, re.I)
        if m: result['premium_amount'] = int(m.group(1))
        m = re.search(r'(?:policy\s+no|policy\s+number)[^\w]*([A-Z0-9\-]{6,})', t, re.I)
        if m: result['policy_no'] = m.group(1)

    elif doc_type == 'donation':
        m = re.search(r'(?:amount|donation|gift)[^\d]*(\d{3,})', t, re.I)
        if m: result['donation_amount'] = int(m.group(1))
        m = re.search(r'PAN[^\w]*([A-Z]{5}[0-9]{4}[A-Z])', t, re.I)
        if m: result['donee_pan'] = m.group(1)

    if result:
        print(f"[EXTRACT][{doc_type}] regex fallback found: {result}")
    return result


def _sum_all_hra_from_text(text):
    """
    Deterministic HRA extraction for payslips.

    Handles two payslip structures safely:

    STRUCTURE A — separate components (sum them):
        HRA           1,96,875
        NON-FBP HRA   7,41,563
        → return 9,38,438

    STRUCTURE B — total + breakdown (use total, don't double-count):
        TOTAL HRA     9,38,438   ← summary row
        FBP HRA       1,96,875
        NON-FBP HRA   7,41,563
        → return 9,38,438 (from summary row only)

    Returns the correct hra_received value, or None to leave it to the AI.
    """
    if not text:
        return None

    clean = text.replace(',', '').replace('₹', '').replace('Rs.', '').replace('INR', '')
    lines = clean.split('\n')

    summary_rows = []   # lines with "TOTAL HRA" / "HRA TOTAL" / "GROSS HRA"
    component_rows = [] # lines with plain "HRA" / "NON-FBP HRA" / "BASIC HRA"

    # Keywords that indicate a summary/total row — skip these when summing components
    TOTAL_KEYWORDS = re.compile(r'\b(total|grand|subtotal|gross|net|aggregate)\b', re.I)

    for line in lines:
        if not re.search(r'\bHRA\b', line, re.I):
            continue
        # Skip non-data lines
        if re.search(r'(calculation|exemption|header|description|component|allowance\s+type)', line, re.I):
            continue

        numbers = [int(m) for m in re.findall(r'\d{4,}', line)]
        if not numbers:
            continue

        # Rightmost large number = Grand Total / YTD column
        grand_total = numbers[-1]
        if grand_total <= 0:
            continue

        if TOTAL_KEYWORDS.search(line):
            summary_rows.append(grand_total)
            print(f"[HRA_SUM] Summary row: '{line.strip()[:60]}' = {grand_total}")
        else:
            component_rows.append(grand_total)
            print(f"[HRA_SUM] Component row: '{line.strip()[:60]}' = {grand_total}")

    # STRUCTURE B: a summary row exists — use it directly (no double-counting)
    if summary_rows:
        result = max(summary_rows)  # use the largest summary value
        print(f"[HRA_SUM] Using summary row value: {result}")
        return result

    # STRUCTURE A: only component rows — sum them if there are 2+
    if len(component_rows) >= 2:
        # Safety check: if one value equals the sum of others, it's itself a total
        total = sum(component_rows)
        for v in component_rows:
            rest = [x for x in component_rows if x != v]
            if rest and sum(rest) == v:
                print(f"[HRA_SUM] Detected hidden total row ({v}), using it directly")
                return v
        print(f"[HRA_SUM] Summing components {component_rows} = {total}")
        return total

    return None  # 0 or 1 row — leave to AI


def _preprocess_ocr_text(text):
    """Normalize OCR text before sending to AI:
    - Remove duplicate lines
    - Normalize whitespace
    - Fix common OCR errors (0 vs O, l vs 1)
    """
    if not text:
        return ''

    lines = text.split('\n')
    seen_lines = set()
    normalized = []

    for line in lines:
        # Normalize whitespace
        line = ' '.join(line.split())
        # Skip duplicates
        if line and line not in seen_lines:
            seen_lines.add(line)
            normalized.append(line)

    return '\n'.join(normalized)


def _parse_int_like(s):
    if s is None:
        return 0
    try:
        s = str(s)
        s = s.replace('₹', '').replace('Rs.', '').replace('INR', '').replace(',', '').strip()
        # take first numeric group
        m = re.search(r'-?\d+', s)
        if m:
            return int(m.group(0))
        return 0
    except Exception:
        return 0


def deterministic_extract(text, doc_type="form16"):
    """Deterministic extraction using regex/heuristics. Returns (result_dict, meta).

    result contains the same keys as the AI extractor (numbers as ints, strings as str).
    meta contains per-field confidence and source.
    """
    result = {}
    meta = {"fields": {}, "assumptions": []}

    if not text:
        return {}, meta

    # Quick path for investment doc types that already have regex fallback
    if doc_type in ('homeloan', 'nps', 'school', 'insurance', 'donation'):
        rf = _regex_fallback(text, doc_type)
        for k, v in (rf or {}).items():
            result[k] = v
            meta['fields'][k] = {'confidence': 0.9, 'source': 'regex'}
        return result, meta

    t = text
    t_clean = t.replace(',', '').replace('Rs.', '').replace('INR', '').replace('₹', '')

    def find_number_by_labels(labels):
        for lab in labels:
            # try label: number
            m = re.search(fr'{lab}\s*[:\-]?\s*([\d\.,₹₹ ]{{1,30}})', t, re.I)
            if m:
                val = _parse_int_like(m.group(1))
                if val:
                    return val, f"label:{lab}", m.group(1)
        # fallback: search lines containing label and pick first number in line
        lines = t.split('\n')
        for i, line in enumerate(lines):
            for lab in labels:
                if re.search(lab, line, re.I):
                    m2 = re.search(r'([\d\.,₹₹ ]{3,30})', line)
                    if m2:
                        val = _parse_int_like(m2.group(1))
                        if val:
                            return val, f"line:{lab}", m2.group(1)
                    # try next line
                    if i + 1 < len(lines):
                        next_line = lines[i+1]
                        m3 = re.search(r'([\d\.,₹₹ ]{3,30})', next_line)
                        if m3:
                            val = _parse_int_like(m3.group(1))
                            if val:
                                return val, f"nextline:{lab}", m3.group(1)
        return None, None, None

    def find_text_label(labels):
        lines = t.split('\n')
        for i, line in enumerate(lines):
            for lab in labels:
                if re.search(lab, line, re.I):
                    parts = re.split(fr'{lab}\s*[:\-]?\s*', line, flags=re.I)
                    if len(parts) >= 2 and parts[1].strip():
                        val = parts[1].strip()
                        return val, f'label:{lab}'
                    # try next line
                    if i + 1 < len(lines):
                        nxt = lines[i+1].strip()
                        if nxt:
                            return nxt, f'nextline:{lab}'
        # heuristic fallback: first long text line that looks like a name/company
        for line in lines:
            s = line.strip()
            if s and len(s) < 120 and len(re.findall(r'\d', s)) == 0 and len(s.split()) >= 2:
                if not re.search(r'(form\s*16|income tax|tds|pan|assessment year)', s, re.I):
                    return s, 'heuristic'
        return '', 'none'

    # field labels map
    labels_map = {
        'gross_salary': [r'gross salary', r'gross total', r'total gross', r'total earnings', r'gross pay', r'gross income', r'total remuneration'],
        'basic_salary': [r'basic salary', r'\bbasic\b', r'basic pay'],
        'hra_received': [r'hra received', r'house rent allowance', r'\bhra\b'],
        'lta': [r'leave travel allowance', r'\blta\b', r'leave travel'],
        'special_allowance': [r'special allowance', r'special pay'],
        'car_lease_allowance': [r'car lease allowance', r'car allowance', r'car lease'],
        'uniform_allowance': [r'uniform allowance', r'\buniform\b'],
        'pf_employee': [r'employee pf', r'pf employee', r'provident fund employee', r'pf \(employee\)'],
        'pf_employer': [r'employer pf', r'pf employer', r'provident fund employer', r'pf \(employer\)'],
        'tds_paid': [r'tds deducted', r'tds paid', r'tax deducted at source', r'\btds\b'],
        'professional_tax': [r'professional tax', r'prof tax', r'\bpt\b'],
        'gratuity': [r'gratuity'],
        'leave_encashment': [r'leave encashment', r'encashment'],
        'section_17_1': [r'section 17\(1\)', r'section 17 1', r'section 17-1'],
        'section_17_2': [r'section 17\(2\)', r'section 17 2', r'section 17-2'],
        'section_17_3': [r'section 17\(3\)', r'section 17 3', r'section 17-3'],
    }

    # textual fields
    # PAN
    m_pan = re.search(r'\b([A-Z]{5}[0-9]{4}[A-Z])\b', t)
    if m_pan:
        result['pan'] = m_pan.group(1)
        meta['fields']['pan'] = {'confidence': 0.95, 'source': 'regex', 'match': m_pan.group(0)}

    # assessment year
    m_ay = re.search(r'(?:Assessment Year|Assessment Year[:\s]|AY[:\s]|A\.Y\.|A Y)\s*[:\-]?\s*([0-9]{4}-[0-9]{2,4})', t, re.I)
    if not m_ay:
        m_ay = re.search(r'\b([0-9]{4}-[0-9]{2})\b', t)
    if m_ay:
        result['assessment_year'] = m_ay.group(1)
        meta['fields']['assessment_year'] = {'confidence': 0.85, 'source': 'regex', 'match': m_ay.group(1)}

    emp_name, src = find_text_label(['employer name', 'name of employer', 'employer', 'employer/organisation', 'employer/organization'])
    if emp_name:
        result['employer_name'] = emp_name.strip()
        meta['fields']['employer_name'] = {'confidence': 0.8, 'source': src}

    # numeric fields
    for field, labs in labels_map.items():
        val, why, raw = find_number_by_labels(labs)
        if val is not None:
            result[field] = val
            conf = 0.9 if why and why.startswith('label:') else 0.75 if why else 0.6
            meta['fields'][field] = {'confidence': conf, 'source': why or 'heuristic', 'raw': raw}
        else:
            result[field] = 0
            meta['fields'][field] = {'confidence': 0.0, 'source': 'none'}

    # post-processing: normalize keys expected by LLM path
    # ensure gross_salary exists
    if 'gross_salary' not in result:
        result['gross_salary'] = 0

    result['_extraction_meta'] = meta
    return result, meta


def extract_document(file_b64, mime, doc_type="form16"):
    try:
        try:
            from ocr_service import extract_text_from_image, extract_text_from_pdf
        except Exception as ie:
            print(f'[EXTRACT] ocr_service import failed: {ie}')
            return {}

        file_bytes = base64.b64decode(file_b64)

        if "pdf" in mime:
            text = extract_text_from_pdf(file_bytes)
        else:
            text = extract_text_from_image(file_bytes)

        # Safety check: ensure text is not None
        if text is None:
            text = ''

        # ✅ Preprocess OCR text to normalize and deduplicate
        text = _preprocess_ocr_text(text)
        print(f"[EXTRACT][{doc_type}] OCR text length: {len(text)} chars")

        # If EXTRACTION_USE_AI is disabled, use deterministic regex/heuristic extraction
        if not getattr(Config, 'EXTRACTION_USE_AI', True):
            result, meta = deterministic_extract(text, doc_type)
            # fallback to existing regex fallback for any missing keys
            if (not result or all((v == 0 or v == "") for v in result.values())) and text:
                result = _regex_fallback(text, doc_type)
            # include metadata if available
            try:
                if isinstance(result, dict) and meta:
                    result.setdefault('_extraction_meta', meta)
            except Exception:
                pass
        else:
            prompt = INVESTMENT_PROMPTS.get(doc_type, EXTRACTION_PROMPT)
            messages = [{"role": "user", "content": f"{prompt}\n\nDOCUMENT TEXT:\n{text}"}]

            raw = _call_openai(messages)
            result = _parse_json(raw)

            if not result and text:
                result = _regex_fallback(text, doc_type)

        print(f"[EXTRACT][{doc_type}] final result: {result}")
        return result

    except Exception as e:
        print(f"[EXTRACT][{doc_type}] error: {e}")
        return {}


def extract_from_text(text, doc_type="payslip"):
    """
    Fast-path extraction from pre-extracted plain text (e.g. pdfplumber output).
    Skips OCR entirely — for use when the PDF is digital (not scanned).

    Returns dict in document_processor-compatible format:
    {
        "success": bool,
        "data": {flat field dict},
        "confidence": float,
        "metadata": {"assumptions": [...], "duplicates": [], "conflicts": [],
                      "pages_processed": 1, "validation_errors": [], "validation_warnings": [],
                      "extraction_quality": "high", "extraction_method": "text"}
    }
    """
    try:
        text = _preprocess_ocr_text(text)
        if not text or len(text.strip()) < 50:
            return {"success": False, "error": "Insufficient text for extraction"}

        # Pick the right prompt
        if doc_type == "payslip":
            prompt = PAYSLIP_TEXT_EXTRACTION_PROMPT
        else:
            prompt = INVESTMENT_PROMPTS.get(doc_type, EXTRACTION_PROMPT)

        messages = [{"role": "user", "content": f"{prompt}\n\nDOCUMENT TEXT:\n{text}"}]
        raw = _call_openai(messages)
        result = _parse_json(raw)

        if not result:
            # Try regex fallback for investment types
            result = _regex_fallback(text, doc_type) or {}

        if not result:
            return {"success": False, "error": "No data extracted from text"}

        # Pull out assumptions if AI returned them inside the JSON
        assumptions = []
        if isinstance(result.get("assumptions"), list):
            assumptions = result.pop("assumptions")

        is_ytd = result.pop("is_ytd", False)
        if is_ytd:
            assumptions.insert(0, "YTD payslip detected — values extracted from Grand Total / annual column (already annual, no ×12 needed)")
        elif doc_type == "payslip":
            assumptions.insert(0, "Monthly payslip detected — values are monthly; annualize by ×12 for tax calculation")

        # ── Deterministic HRA override for payslips ──────────────────────────
        # AI often picks only the largest HRA component. Sum ALL HRA rows from
        # the raw text to guarantee correctness regardless of AI behaviour.
        if doc_type == "payslip":
            hra_sum = _sum_all_hra_from_text(text)
            if hra_sum and hra_sum != result.get("hra_received", 0):
                print(f"[HRA_SUM] Overriding AI hra_received {result.get('hra_received')} → {hra_sum}")
                result["hra_received"] = hra_sum
                assumptions.append(f"HRA overridden by deterministic sum of all HRA rows = {hra_sum}")

        print(f"[EXTRACT_TEXT][{doc_type}] result: {result}")

        return {
            "success": True,
            "data": result,
            "confidence": 0.88,
            "metadata": {
                "assumptions": assumptions,
                "duplicates": [],
                "conflicts": [],
                "pages_processed": 1,
                "validation_errors": [],
                "validation_warnings": [],
                "extraction_quality": "high",
                "extraction_method": "text_fast_path"
            }
        }

    except Exception as e:
        print(f"[EXTRACT_TEXT][{doc_type}] error: {e}")
        return {"success": False, "error": str(e)}


def merge_extractions(extractions):
    """Merge multiple extractions with conflict detection.
    - If multiple documents are uploaded (len(extractions)>1), numeric fields are SUMMED across documents.
      This is useful for situations like multiple payslips where values should be aggregated.
    - Otherwise, preserve previous conservative behaviour: for numeric fields prefer first non-zero,
      and if two non-zero numeric values differ by >5% mark a conflict and use the max.
    - Strings: use first non-empty value.
    Returns merged_dict with keys, plus `_merge_conflicts` and `_sources` metadata.
    """
    out = {}
    conflicts = []
    field_sources = {}  # field -> list of {'value':parsed_or_raw, 'raw':original, 'source':source}

    def _parse_num_maybe(v):
        """Return float if v contains a numeric value, otherwise None."""
        try:
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v) if v is not None else ''
            if not re.search(r'\d', s):
                return None
            s2 = s.replace(',', '').replace('₹', '').replace('Rs.', '').replace('INR', '').strip()
            m = re.search(r'-?\d+(\.\d+)?', s2)
            if not m:
                return None
            return float(m.group(0))
        except Exception:
            return None

    for i, ext in enumerate(extractions):
        src = ext.get('_source_filename') or ext.get('_doc_type') or f"doc_{i+1}"
        for k, v in ext.items():
            if k.startswith('_'):
                continue
            parsed = _parse_num_maybe(v)
            entry = {'value': parsed if parsed is not None else v, 'raw': v, 'source': src}
            field_sources.setdefault(k, []).append(entry)

    for k, entries in field_sources.items():
        # Determine if entries are all numeric
        all_numeric = all(isinstance(e['value'], (int, float)) or isinstance(e['value'], float) for e in entries)
        if len(entries) > 1 and all_numeric:
            total = sum(float(e['value']) for e in entries)
            # cast to int when exact
            if float(total).is_integer():
                total = int(total)
            out[k] = total
            continue

        # Fallback: conservative merge for mixed or single entries
        merged_val = None
        for e in entries:
            v = e['value']
            if isinstance(v, (int, float)):
                if merged_val is None or merged_val == 0:
                    merged_val = v
                elif v == 0:
                    continue
                else:
                    diff_pct = abs(merged_val - v) / max(merged_val, v) * 100
                    if diff_pct > 5:
                        conflicts.append({
                            "field": k,
                            "value1": merged_val,
                            "value2": v,
                            "diff_pct": round(diff_pct, 1)
                        })
                    merged_val = max(merged_val, v)
            else:
                # string: first non-empty wins
                if merged_val is None or merged_val == "":
                    merged_val = v

        # Default non-found numeric -> 0, strings -> empty string
        if merged_val is None:
            if any(isinstance(e['value'], (int, float)) for e in entries):
                merged_val = 0
            else:
                merged_val = ""

        out[k] = merged_val

    out['_merge_conflicts'] = conflicts
    out['_sources'] = {k: [{'value': e['raw'], 'source': e['source']} for e in entries] for k, entries in field_sources.items()}
    return out


def validate_form16_payslip_consistency(merged_data, extractions):
    """
    ✅ FORM 16 vs PAYSLIP CONFLICT DETECTION

    Priority Logic:
    1. Form 16 is PRIMARY (official annual summary)
    2. Payslip is SUPPLEMENTARY (monthly breakdown, used to fill gaps)
    3. Flag conflicts when values differ significantly

    Returns: (merged_data_with_form16_priority, conflicts_list)

    IMPORTANT: Does NOT modify merge_extractions() behavior - only adds validation layer
    """

    conflicts = []

    # Find Form 16 and Payslip documents
    form16_doc = None
    payslip_doc = None

    for ext in extractions:
        doc_type = ext.get('_doc_type', '').lower()
        if 'form16' in doc_type or 'form 16' in doc_type:
            form16_doc = ext
        elif 'payslip' in doc_type:
            payslip_doc = ext

    # If only one type of document or no conflict, return as-is
    if not form16_doc or not payslip_doc:
        return merged_data, conflicts

    print("[CONFLICT] Detected both Form 16 and Payslip - validating consistency...")

    # Helper function to safely parse numeric values
    def _to_num(x):
        try:
            if x is None or x == "" or x == 0:
                return 0.0
            if isinstance(x, (int, float)):
                return float(x)
            s = str(x).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
            if not s:
                return 0.0
            return float(s)
        except Exception:
            return 0.0

    # Fields to check (these should be annual in Form 16, monthly in Payslip)
    annual_fields = [
        ('gross_salary', 'Gross Salary'),
        ('basic_salary', 'Basic Salary'),
        ('hra_received', 'HRA'),
        ('pf_employee', 'PF (Employee)'),
    ]

    tolerance = 0.15  # Allow 15% variance (accounts for seasonal variations, bonuses)

    for field_key, field_name in annual_fields:
        form16_val = _to_num(form16_doc.get(field_key))
        payslip_val = _to_num(payslip_doc.get(field_key))

        # Skip if either is missing
        if form16_val == 0 or payslip_val == 0:
            continue

        # Payslip is MONTHLY, Form 16 is ANNUAL
        # Annualize payslip value for comparison
        payslip_annualized = payslip_val * 12

        # Check for significant variance
        variance = abs(payslip_annualized - form16_val) / max(form16_val, payslip_annualized)

        if variance > tolerance:
            # Large discrepancy detected
            conflict = {
                "field": field_key,
                "field_name": field_name,
                "form16_value": form16_val,
                "form16_source": "Form 16 (Annual)",
                "payslip_monthly_value": payslip_val,
                "payslip_annualized_value": round(payslip_annualized, 2),
                "variance_percent": round(variance * 100, 1),
                "severity": "HIGH" if variance > 0.30 else "MEDIUM",
                "recommended_value": form16_val,
                "message": f"{field_name}: Form 16 = ₹{form16_val:,.0f} (annual), "
                          f"Payslip = ₹{payslip_val:,.0f} (monthly, annualized = ₹{payslip_annualized:,.0f}). "
                          f"Difference: {variance*100:.1f}%. Using Form 16 value."
            }
            conflicts.append(conflict)
            print(f"[CONFLICT][{field_key}] {conflict['message']}")

    # Special handling for TDS (should be annual in Form 16, monthly in Payslip)
    form16_tds = _to_num(form16_doc.get('tds_paid'))
    payslip_tds = _to_num(payslip_doc.get('tds_paid'))

    if form16_tds > 0 and payslip_tds > 0:
        payslip_tds_annual = payslip_tds * 12
        tds_variance = abs(payslip_tds_annual - form16_tds) / max(form16_tds, payslip_tds_annual)

        if tds_variance > 0.25:  # 25% tolerance for TDS (wider due to monthly variations)
            conflicts.append({
                "field": "tds_paid",
                "field_name": "TDS Paid",
                "form16_value": form16_tds,
                "payslip_monthly_value": payslip_tds,
                "payslip_annualized_value": round(payslip_tds_annual, 2),
                "variance_percent": round(tds_variance * 100, 1),
                "severity": "MEDIUM",
                "recommended_value": form16_tds,
                "message": f"TDS: Form 16 = ₹{form16_tds:,.0f} (annual), "
                          f"Payslip = ₹{payslip_tds:,.0f} (monthly). "
                          f"Using Form 16 value."
            })
            print(f"[CONFLICT][tds_paid] TDS variance detected: {tds_variance*100:.1f}%")

    # IMPORTANT: Form 16 values take PRIORITY - they're already in merged_data
    # The payslip was summed by merge_extractions, but we want Form 16 as primary
    # If both exist, use Form 16 value (it's the authoritative annual document)
    if form16_doc:
        for field_key, _ in annual_fields:
            form16_val = form16_doc.get(field_key)
            if form16_val and form16_val != 0:
                # Override merged value with Form 16 (primary source)
                merged_data[field_key] = form16_val

        # TDS: use Form 16 (annual)
        if form16_doc.get('tds_paid'):
            merged_data['tds_paid'] = form16_doc.get('tds_paid')

    # Store conflicts for response
    if conflicts:
        merged_data['_form16_payslip_conflicts'] = conflicts
        print(f"[CONFLICT] Detected {len(conflicts)} conflicts between Form 16 and Payslip")

    return merged_data, conflicts


def calculate_tax_ai(data):
    """Call LLM for structured tax calculation with explicit conflict detection & self-validation.
    Returns a dict consistent with expected schema plus detailed assumptions.
    """
    # ✅ SANITIZE input data before sending to API
    if not isinstance(data, dict):
        print("[AI_TAX] Invalid data type (not a dict); cannot calculate")
        return {}

    # Convert all values to safe types for JSON serialization
    clean_data = {}
    for k, v in data.items():
        if v is None or v == "":
            clean_data[k] = 0
        elif isinstance(v, (int, float)):
            clean_data[k] = v
        elif isinstance(v, str):
            # Try to convert string numbers to float; otherwise keep as string
            try:
                clean_data[k] = float(v.replace(',', '').replace('₹', ''))
            except:
                clean_data[k] = str(v)
        elif isinstance(v, dict):
            clean_data[k] = v
        elif isinstance(v, list):
            clean_data[k] = v
        else:
            # For any other type, convert to string
            clean_data[k] = str(v)

    prompt_body = """
You are an exact Indian tax computation assistant for FY 2025-26 (AY 2026-27).

Return ONLY a single JSON object (no surrounding text). All monetary values must be plain numbers (no commas, no currency symbols). Include an `assumptions` array documenting every default, cap, or conversion applied.

CRITICAL:
• Never invent values. Use 0 only if genuinely not provided.
• Convert monthly inputs to annual (state this clearly in assumptions).
• SELF-VALIDATE: Before returning, double-check GTI = Gross + OtherIncome - Sec10 - HomeLoanInt - StdDed - ProfTax. If AI-computed GTI differs from provided GTI by >₹500, recompute and flag in assumptions.
• Detect conflicting values in input (e.g., multiple Form 16s with different gross salaries): flag all conflicts in assumptions; do NOT silently pick one.
• If deductions exceed allowed limits, cap them and document in assumptions.

Required top-level keys: `gross_components`, `other_income`, `section_16`, `section_10_exemptions`, `deductions_80`, `home_loan_interest`, `calculations`, `variant_options`, `compatibility_summary`, `assumptions`, `calculation_notes`, `pdf_summary`.

HRA: compute exact exemption as least of (a) HRA received, (b) Rent paid - 10% of basic, (c) 50% basic (metro) or 40% basic (non-metro).

Home loan interest: report under top-level `home_loan_interest` (Section 24). Do NOT include it under `section_10_exemptions`.

GTI: Gross Salary + total_other_income - total_sec_10_exemptions - home_loan_interest_allowed - standard_deduction - professional_tax.

Apply Section 87A rebate where applicable. Compute slab-wise tax for OLD and NEW regimes; show slab-level taxes, apply 4% cess on tax after rebate. Round slab taxes to nearest rupee; final totals with 2 decimals.

Provide three variants A/B/C (conservative / realistic optimized / aggressive) and recommend a regime.

Deduction caps (enforce strictly):
• Section 80C: ₹150,000 max
• Section 80CCD(1B): ₹50,000 max
• Section 80CCD(2): 10% of basic salary max
• Section 80D: ₹25,000 (self) + ₹50,000 (senior parents) or ₹25,000 (non-senior parents)
• Home loan interest: ₹200,000 max
• NPS: same as 80C/80CCD caps

User Data (raw JSON):
"""
    prompt = prompt_body + "\n" + json.dumps(clean_data)

    messages = [{"role": "user", "content": prompt}]

    try:
        raw = _call_openai(messages, max_tokens=3500)
        calc = _parse_json(raw)

        def _to_num(x):
            try:
                if x is None or x == "":
                    return 0.0
                if isinstance(x, (int, float)):
                    return float(x)
                return float(str(x).replace(',', '').replace('₹', ''))
            except:
                return 0.0

        def _sum_fields(d, keys):
            s = 0.0
            for k in keys:
                s += _to_num(d.get(k, 0))
            return s

        if not isinstance(calc, dict):
            return {}

        # ✅ VALIDATE AI-computed values and enforce limits
        # Ensure deductions don't exceed caps
        sec_80c = _to_num((calc.get('deductions_80') or {}).get('sec_80c') or 0)
        if sec_80c > 150000:
            calc.setdefault('assumptions', []).append(f"Section 80C capped at ₹150000 (AI provided {sec_80c})")
            if 'deductions_80' not in calc:
                calc['deductions_80'] = {}
            calc['deductions_80']['sec_80c'] = 150000

        sec_80ccd_1b = _to_num((calc.get('deductions_80') or {}).get('sec_80ccd_1b') or 0)
        if sec_80ccd_1b > 50000:
            calc.setdefault('assumptions', []).append(f"Section 80CCD(1B) capped at ₹50000 (AI provided {sec_80ccd_1b})")
            if 'deductions_80' not in calc:
                calc['deductions_80'] = {}
            calc['deductions_80']['sec_80ccd_1b'] = 50000

        # move home_loan_interest out of section_10_exemptions if misclassified
        sec10 = calc.get('section_10_exemptions', {}) or {}
        if 'home_loan_interest' in sec10 and sec10.get('home_loan_interest'):
            moved = _to_num(sec10.get('home_loan_interest'))
            calc['home_loan_interest'] = _to_num(calc.get('home_loan_interest', 0)) + moved
            if 'total_sec_10_exemptions' in sec10:
                sec10['total_sec_10_exemptions'] = max(0.0, _to_num(sec10.get('total_sec_10_exemptions')) - moved)
            calc['section_10_exemptions'] = sec10

        # canonicalize
        gross = _to_num((calc.get('gross_components') or {}).get('gross_salary') or calc.get('gross_salary') or data.get('gross_salary') or 0)
        other_income = calc.get('other_income') or {}
        if not isinstance(other_income, dict):
            other_income = {}
        total_other_income = _to_num(other_income.get('total_other_income', 0) if isinstance(other_income, dict) else 0)
        if total_other_income == 0:
            total_other_income = _sum_fields(other_income, ['fd_interest', 'dividend', 'tax_refund_interest'])

        std_ded = _to_num((calc.get('section_16') or {}).get('standard_deduction')) or 0.0
        prof_tax = _to_num((calc.get('section_16') or {}).get('professional_tax')) or 0.0

        # home loan: cap for self-occupied to 200000
        home_loan_interest = _to_num(calc.get('home_loan_interest', 0))
        home_loan_allowed = min(home_loan_interest, 200000)
        if home_loan_allowed != home_loan_interest:
            calc.setdefault('assumptions', []).append(f"Home loan interest capped to ₹200000; provided {home_loan_interest}")
        calc['home_loan_interest'] = home_loan_allowed

        total_sec10 = _to_num((calc.get('section_10_exemptions') or {}).get('total_sec_10_exemptions'))

        # GTI recompute
        recomputed_gti = gross + total_other_income - total_sec10 - home_loan_allowed - std_ded - prof_tax
        recomputed_gti = round(float(recomputed_gti), 2)
        calc.setdefault('calculations', {})
        reported_gti = _to_num(calc['calculations'].get('gti'))
        if abs(reported_gti - recomputed_gti) > 1:
            calc['calculations']['gti'] = recomputed_gti
            calc.setdefault('assumptions', []).append('GTI recomputed server-side to avoid double-counting and ensure consistent treatment of home loan interest and standard deduction.')

        # chapter VIA deductions
        deductions_total = _to_num((calc.get('deductions_80') or {}).get('total_deductions_80'))

        # OLD regime tax
        taxable_old = max(0.0, recomputed_gti - deductions_total)
        old_tax_before_cess = float(tax_engine.slab_tax_old(taxable_old))
        old_total_tax = float(Decimal(old_tax_before_cess * (1 + tax_config.CESS_RATE)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        tds_paid = _to_num(calc.get('compatibility_summary', {}).get('tds_paid') or data.get('tds_paid') or calc.get('tds_paid') or 0)
        old_refund = float(Decimal(tds_paid - old_total_tax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

        # NEW regime tax
        std_new = tax_config.STANDARD_DEDUCTION.get('NEW', 75000)
        gti_new = gross + total_other_income - std_new
        sec_80ccd_2 = _to_num((calc.get('deductions_80') or {}).get('sec_80ccd_2') or calc.get('sec_80ccd_2') or 0)
        taxable_new = max(0.0, gti_new - sec_80ccd_2)
        new_tax_before_cess = float(tax_engine.slab_tax_new(taxable_new))
        new_total_tax = float(Decimal(new_tax_before_cess * (1 + tax_config.CESS_RATE)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        new_refund = float(Decimal(tds_paid - new_total_tax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

        # update calculations
        calc['calculations'].update({
            'gti': recomputed_gti,
            'taxable_old': round(float(taxable_old), 2),
            'old_tax_before_cess': int(round(old_tax_before_cess)),
            'old_total_tax': old_total_tax,
            'old_refund_or_due': old_refund,
            'taxable_new': round(float(taxable_new), 2),
            'new_tax_before_cess': int(round(new_tax_before_cess)),
            'new_total_tax': new_total_tax,
            'new_refund_or_due': new_refund,
        })

        # variants
        variants = calc.get('variant_options') or {}
        if not variants.get('variant_a'):
            variants['variant_a'] = {
                'taxable': calc['calculations']['taxable_old'],
                'total_tax': calc['calculations']['old_total_tax'],
                'refund': calc['calculations']['old_refund_or_due'],
                'regime': 'OLD' if calc['calculations']['old_refund_or_due'] >= calc['calculations']['new_refund_or_due'] else 'NEW'
            }
        if not variants.get('variant_b'):
            sec80c = _to_num((calc.get('deductions_80') or {}).get('sec_80c') or 0)
            optimized_80c = min(150000, sec80c if sec80c > 0 else sec80c)
            opt_deductions = max(deductions_total, optimized_80c)
            opt_taxable = max(0.0, recomputed_gti - opt_deductions)
            opt_tax_before = float(tax_engine.slab_tax_old(opt_taxable))
            opt_total = float(Decimal(opt_tax_before * (1 + tax_config.CESS_RATE)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            opt_refund = float(Decimal(tds_paid - opt_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            variants['variant_b'] = {'taxable': round(opt_taxable, 2), 'total_tax': opt_total, 'refund': opt_refund}
        if not variants.get('variant_c'):
            aggressive_80c = 150000
            aggressive_80ccd_1b = 50000
            agg_deductions = max(deductions_total, aggressive_80c + aggressive_80ccd_1b)
            agg_taxable = max(0.0, recomputed_gti - agg_deductions)
            agg_tax_before = float(tax_engine.slab_tax_old(agg_taxable))
            agg_total = float(Decimal(agg_tax_before * (1 + tax_config.CESS_RATE)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            agg_refund = float(Decimal(tds_paid - agg_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            variants['variant_c'] = {'taxable': round(agg_taxable, 2), 'total_tax': agg_total, 'refund': agg_refund}

        calc['variant_options'] = variants

        # compatibility summary
        comp = calc.get('compatibility_summary') or {}
        comp.update({
            'gross_salary': gross,
            'basic_salary': _to_num((calc.get('gross_components') or {}).get('basic_salary') or calc.get('basic_salary') or data.get('basic_salary') or 0),
            'hra_received': _to_num((calc.get('gross_components') or {}).get('hra_received') or calc.get('hra_received') or data.get('hra_received') or 0),
            'hra_exempt_actual': _to_num((calc.get('section_10_exemptions') or {}).get('hra', {}).get('hra_exemption') or 0),
            'tds_paid': tds_paid,
            'sec_80c': _to_num((calc.get('deductions_80') or {}).get('sec_80c') or 0),
            'sec_80d': _to_num((calc.get('deductions_80') or {}).get('sec_80d') or 0),
            'sec_80ccd_1b': _to_num((calc.get('deductions_80') or {}).get('sec_80ccd_1b') or 0),
            'sec_80ccd_2': sec_80ccd_2,
            'deductions_total': deductions_total,
            'taxable_new': calc['calculations']['taxable_new'],
            'total_tax_new': calc['calculations']['new_total_tax'],
            'refund_new': calc['calculations']['new_refund_or_due'],
            'taxable_old_a': calc['calculations']['taxable_old'],
            'total_tax_old_a': calc['calculations']['old_total_tax'],
            'refund_old_a': calc['calculations']['old_refund_or_due'],
            'variant_a_refund': variants.get('variant_a', {}).get('refund', 0),
            'variant_a_regime': variants.get('variant_a', {}).get('regime', ''),
            'variant_b_refund': variants.get('variant_b', {}).get('refund', 0),
            'variant_c_refund': variants.get('variant_c', {}).get('refund', 0),
            'recommended_regime': 'OLD' if calc['calculations']['old_refund_or_due'] >= calc['calculations']['new_refund_or_due'] else 'NEW'
        })
        calc['compatibility_summary'] = comp

        return calc

    except Exception as e:
        print("AI tax error:", e)
        traceback.print_exc()
        # Return minimal error report instead of empty dict
        return {
            'error': str(e),
            'calculations': {'taxable_old': 0, 'old_total_tax': 0, 'old_refund_or_due': 0,
                           'taxable_new': 0, 'new_total_tax': 0, 'new_refund_or_due': 0},
            'assumptions': ['AI enrichment failed, using engine-only calculations']
        }


def clean_extraction(data):
    """Normalize and validate extracted values. Log all fixes applied."""
    gross = data.get("gross_salary", 0)
    fixes_applied = []
    # Ensure numbers are not negative
    for k, v in list(data.items()):
        if isinstance(v, (int, float)) and v < 0:
            data[k] = 0
            fixes_applied.append(f"Removed negative value from {k}")

    # Normalize tds field name to match HEADERS
    if "tds_deducted" in data and "tds_paid" not in data:
        data["tds_paid"] = data.pop("tds_deducted")
        fixes_applied.append("Normalized tds_deducted -> tds_paid")

    # Prevent insane HRA (common OCR bug): HRA should not exceed 60% of gross
    hra = data.get("hra_received", 0)
    if gross > 0 and hra > gross * 0.6:
        old_hra = hra
        data["hra_received"] = gross * 0.4
        fixes_applied.append(f"Capped unrealistic HRA: {old_hra} -> {data['hra_received']}")

    # Prevent basic > gross
    basic = data.get("basic_salary", 0)
    if gross > 0 and basic > gross:
        old_basic = basic
        data["basic_salary"] = gross * 0.5
        fixes_applied.append(f"Capped basic > gross: {old_basic} -> {data['basic_salary']}")

    # Ensure pf_employee + pf_employer not > 25% of gross (safety clamp)
    pf_emp = data.get("pf_employee", 0)
    pf_emr = data.get("pf_employer", 0)
    if gross > 0 and (pf_emp + pf_emr) > gross * 0.25:
        data["pf_employee"] = min(pf_emp, gross * 0.12)
        data["pf_employer"] = min(pf_emr, gross * 0.12)
        fixes_applied.append(f"Capped excessive PF contributions")

    # --- Sanity clamps and outlier detection using per-field provenance if available ---
    ABSOLUTE_MAX = 10**9  # 1 billion: anything larger is highly suspicious for individual tax filings
    OUTLIER_RATIO = 10     # largest > OUTLIER_RATIO * sum(others) -> outlier
    OUTLIER_MIN = 100000   # only consider outliers above this absolute value
    GROSS_MULTIPLIER = 100 # flag values > gross * this multiplier

    def _parse_num_local(x):
        try:
            if isinstance(x, (int, float)):
                return float(x)
            s = str(x) if x is not None else ''
            s2 = s.replace(',', '').replace('₹', '').replace('Rs.', '').replace('INR', '').strip()
            m = re.search(r'-?\d+(?:\.\d+)?', s2)
            if m:
                return float(m.group(0))
        except Exception:
            pass
        return None

    suspicious = {}

    sources = data.get('_sources') or {}
    for field, srcs in (sources.items() if isinstance(sources, dict) else []):
        # srcs is list of {'value': raw_value, 'source': src}
        numeric_entries = []
        for s in srcs:
            parsed = _parse_num_local(s.get('value'))
            if parsed is not None:
                numeric_entries.append({'value': parsed, 'source': s.get('source'), 'raw': s.get('value')})

        if not numeric_entries:
            continue

        if len(numeric_entries) > 1:
            vals = [e['value'] for e in numeric_entries]
            total = sum(vals)
            largest = max(vals)
            sum_others = total - largest

            if largest >= OUTLIER_MIN and (sum_others == 0 or (largest / max(sum_others, 1)) > OUTLIER_RATIO):
                # Exclude largest contributor as outlier
                outlier = next(e for e in numeric_entries if e['value'] == largest)
                new_total = sum_others
                if float(new_total).is_integer():
                    new_total = int(new_total)
                old_val = data.get(field, None)
                data[field] = new_total
                fixes_applied.append(f"Excluded outlier for {field}: {largest} from {outlier.get('source')}")
                suspicious.setdefault(field, []).append({
                    'reason': 'outlier_excluded',
                    'excluded_value': largest,
                    'excluded_source': outlier.get('source'),
                    'sum_excluding_outlier': new_total
                })

        else:
            # Single numeric entry: clamp if absurd
            val = numeric_entries[0]['value']
            if abs(val) > ABSOLUTE_MAX:
                old_val = data.get(field, val)
                data[field] = int(ABSOLUTE_MAX) if val > 0 else 0
                fixes_applied.append(f"Clamped {field} from {old_val} to {data[field]} due to absolute max")
                suspicious.setdefault(field, []).append({'reason': 'clamped_absolute_max', 'original': val, 'clamped_to': data[field]})

        # Gross-relative flagging
        try:
            curv = data.get(field)
            if isinstance(curv, (int, float)) and gross and curv > gross * GROSS_MULTIPLIER:
                suspicious.setdefault(field, []).append({'reason': 'large_vs_gross', 'value': curv, 'gross': gross})
                fixes_applied.append(f"Flagged {field} large compared to gross: {curv} vs gross {gross}")
        except Exception:
            pass

    # For numeric fields without provenance, apply absolute clamp as a safety net
    for k, v in list(data.items()):
        if k.startswith('_'):
            continue
        if isinstance(v, (int, float)) and abs(v) > ABSOLUTE_MAX:
            old = v
            data[k] = int(ABSOLUTE_MAX) if v > 0 else 0
            fixes_applied.append(f"Clamped {k} from {old} to {data[k]} due to absolute max")
            suspicious.setdefault(k, []).append({'reason': 'clamped_absolute_max', 'original': old, 'clamped_to': data[k]})

    if suspicious:
        data['_suspicious_fields'] = suspicious

    if fixes_applied:
        print(f"[CLEAN] Applied {len(fixes_applied)} fixes: {fixes_applied}")

    return data


def generate_whatsapp_reply(user_text, phone=None, history=None, max_tokens=800):
    """Generate a short conversational reply suitable for WhatsApp.
    - Respects `Config.USE_AI` flag (falls back to canned reply when disabled).
    - `history` may be a list of prior messages in the form {"role": "user|assistant", "content": "..."}.
    """
    if not Config.USE_AI:
        return "Thanks — our team will reply shortly."

    try:
        system_prompt = (
            "You are the FairTax WhatsApp assistant. Keep replies concise (1-3 sentences), "
            "polite, and helpful. Never ask for OTPs, full bank account numbers, or other sensitive "
            "personal authentication details. If the user asks for detailed tax calculations, ask them "
            "to submit their documents via the web form or upload."
        )

        messages = [{"role": "system", "content": system_prompt}]
        if history and isinstance(history, list):
            messages.extend(history[-6:])
        messages.append({"role": "user", "content": user_text})

        raw = _call_openai(messages, max_tokens=max_tokens)
        reply = raw.strip() if isinstance(raw, str) else str(raw)

        # Truncate overly long replies for WhatsApp
        if len(reply) > 1000:
            reply = reply[:997] + "..."

        return reply
    except Exception as e:
        print("AI reply error:", e)
        return "Sorry, I couldn't process that right now. Our team will reply shortly."
