import gspread, random, threading
from google.oauth2.service_account import Credentials
from config import Config
from datetime import datetime
import time
from gspread.exceptions import APIError

# Module-level caches + retry tuning
_GC = None
_SPREADSHEET = None
_SPREADSHEET_KEY = None
_SPREADSHEET_TS = 0
_SPREADSHEET_TTL = 300  # seconds to keep cached spreadsheet
_LOCK = threading.Lock()
_MAX_API_RETRIES = 5
_INITIAL_BACKOFF = 1.0

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

# Form fields (visible) + hidden backend fields + 3-variant calc + doc URLs
HEADERS = [
    "submission_id", 
    "timestamp", "phone", "name", "pan", "email", "city_type",
    "filing_category", "free_filing_proof_url",
    "has_form16",

    # Salary (visible to user)
    "gross_salary", "basic_salary", "hra_received",
    "home_loan_interest", "pf_employee", "home_loan_principal",
    "ulip_lic", "school_fees", "medical_self", "medical_parents",
    "parents_senior", "nps_self", "nps_employer",

    # Hidden backend-only fields
    "uniform_allowance", "car_lease_allowance", "maintenance_allowance",
    "laundry_allowance", "lta", "gratuity", "leave_encashment",

    # Other income (structured)
    "rental_income_monthly", "fno_pl", "securities_income",
    "business_nature", "business_income", "other_income_misc",

    # Investment proof (structured — comma-separated for multi-entry)
    "home_loans_json", "insurance_policies_json", "donations_json", "nps_pran",
    "monthly_rent",
        "fd_interest", "dividend", "refund_interest", "savings_interest",
        "sec_80g", "sec_80e",

    # Free eligibility (Senior Citizen / Widow / etc.)
    "free_eligibility", "eligibility_category",

    # Spouse package (20% discount)
    "spouse_name", "spouse_pan", "spouse_phone", "spouse_discount",

    # Pending notices / referral
    "pending_notices", "pending_notices_detail", "referred_by", "referral_code",
    "referrer_name", "referrer_phone",
    "upi_id", "wallet_balance", "referral_count",

    # Tax calculation (3 variants + new regime)
    "tds_paid", "hra_exempt_actual", "home_loan_interest_allowed",
    "sec_80c", "sec_80d", "sec_80db", "sec_80ccd_1b", "sec_80ccd_2", "deductions_total",
    "taxable_new", "total_tax_new", "refund_new",
    "taxable_old_a", "total_tax_old_a", "refund_old_a",
    "taxable_old_b", "total_tax_old_b", "refund_old_b",
    "taxable_old_c", "total_tax_old_c", "refund_old_c",
    "variant_a_refund", "variant_a_regime",
    "variant_b_refund", "variant_c_refund",

    # Auditor workflow
    "approval_status", "auditor_quote_fee", "auditor_notes", "user_chosen_option",
    "payment_status", "filing_status",

    # Document URLs (last columns)
    "doc_form16_urls", "doc_payslip_urls", "doc_homeloan_urls",
    "doc_school_urls", "doc_nps_urls", "doc_insurance_urls", "doc_donation_urls",
]

def _client():
    global _GC
    if _GC is not None:
        return _GC
    creds = Credentials.from_service_account_file(Config.SERVICE_ACCOUNT_JSON, scopes=SCOPES)
    _GC = gspread.authorize(creds)
    return _GC

def _is_rate_limit(e):
    try:
        info = e.args[0]
        if isinstance(info, dict):
            if info.get('code') == 429 or info.get('status') == 'RESOURCE_EXHAUSTED':
                return True
    except Exception:
        pass
    return False


def _call_with_retries(func, *args, **kwargs):
    backoff = _INITIAL_BACKOFF
    for attempt in range(1, _MAX_API_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            if _is_rate_limit(e) and attempt < _MAX_API_RETRIES:
                sleep = backoff + random.random() * backoff
                print(f"[Sheets] Rate limit detected, backing off {sleep:.2f}s (attempt {attempt})")
                time.sleep(sleep)
                backoff *= 2
                continue
            raise
        except Exception:
            raise


def _ws_call(ws, method_name, *args, **kwargs):
    fn = getattr(ws, method_name)
    return _call_with_retries(fn, *args, **kwargs)


def _sheet(name):
    gc = _client()
    global _SPREADSHEET, _SPREADSHEET_KEY, _SPREADSHEET_TS

    with _LOCK:
        now = time.time()
        if _SPREADSHEET and _SPREADSHEET_KEY == Config.GOOGLE_SHEET_ID and (now - _SPREADSHEET_TS) < _SPREADSHEET_TTL:
            sh = _SPREADSHEET
        else:
            sh = _call_with_retries(lambda: gc.open_by_key(Config.GOOGLE_SHEET_ID))
            _SPREADSHEET = sh
            _SPREADSHEET_KEY = Config.GOOGLE_SHEET_ID
            _SPREADSHEET_TS = now

    try:
        return _call_with_retries(sh.worksheet, name)
    except gspread.WorksheetNotFound:
        return _call_with_retries(sh.add_worksheet, name, 1000, 100)

def _ensure_headers(ws, headers):
    existing = _ws_call(ws, 'row_values', 1)
    if existing != headers:
        _ws_call(ws, 'update', "A1", [headers])
        _ws_call(ws, 'format', "1:1", {"textFormat": {"bold": True},
                          "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0}})

def gen_referral_code(name):
    base = ''.join([c for c in (name or "USER").upper() if c.isalpha()])[:4].ljust(4, "X")
    return f"{base}_{random.randint(100, 999)}"

def get_row_by_submission_id(submission_id):
    ws = _sheet("Submissions")

    # ✅ ENSURE HEADERS FIRST
    _ensure_headers(ws, HEADERS)

    all_values = _ws_call(ws, 'get_all_values')

    # ✅ If only header exists → no rows yet
    if len(all_values) <= 1:
        return None

    headers = all_values[0]

    for i, row in enumerate(all_values[1:], start=2):
        row_dict = dict(zip(headers, row))
        if str(row_dict.get("submission_id")) == str(submission_id):
            return i

    return None

def upsert_phase(phone, partial_data):
    """Create or update row by phone. partial_data is a dict; only sets the keys it has."""
    ws = _sheet("Submissions")
    _ensure_headers(ws, HEADERS)
    # Try to find existing row by phone first
    # phone may be empty; in that case we will create a new row
    row_idx = None
    if phone:
        try:
            vals = _ws_call(ws, 'get_all_values')
            headers = vals[0] if vals else HEADERS
            phone_col = headers.index('phone') + 1 if 'phone' in headers else None
            if phone_col:
                found = _ws_call(ws, 'findall', str(phone))
                for c in found:
                    if c.col == phone_col:
                        row_idx = c.row
                        break
        except Exception:
            row_idx = None

    # If a submission_id was provided in partial_data, prefer locating by it
    sid = partial_data.get('submission_id')
    if sid and not row_idx:
        row_idx = get_row_by_submission_id(sid)

    if row_idx is None:
        # Create new row
        new_row = [""] * len(HEADERS)
        # submission_id (if provided) should be first cell
        if partial_data.get('submission_id'):
            new_row[0] = partial_data.get('submission_id')
        else:
            new_row[0] = ""  # will be set by insert_submission path if needed
        new_row[1] = datetime.now().isoformat()
        # phone goes into column 3 (index 2) normally
        if phone:
            try:
                new_row[2] = phone
            except Exception:
                pass
        # Generate referral code on create if name is provided
        if partial_data.get("name") and "referral_code" not in partial_data:
            partial_data["referral_code"] = gen_referral_code(partial_data["name"])
        for k, v in partial_data.items():
            if k in HEADERS:
                # Skip empty string / None to avoid accidental overwrites
                if v is None:
                    continue
                if isinstance(v, str) and v.strip() == "":
                    continue
                new_row[HEADERS.index(k)] = v if not isinstance(v, (dict, list)) else str(v)
        _ws_call(ws, 'append_row', new_row, value_input_option="USER_ENTERED")
        return {"created": True, "referral_code": partial_data.get("referral_code", "")}
    else:
        # Update existing
        updates = []
        for k, v in partial_data.items():
            if k in HEADERS:
                # Skip empty string / None to avoid accidental overwrites
                if v is None:
                    continue
                if isinstance(v, str) and v.strip() == "":
                    continue
                col = HEADERS.index(k) + 1
                cell = gspread.utils.rowcol_to_a1(row_idx, col)
                val = v if not isinstance(v, (dict, list)) else str(v)
                updates.append({"range": cell, "values": [[val]]})
        if updates:
            _ws_call(ws, 'batch_update', updates, value_input_option="USER_ENTERED")
        # Read back referral code
        cell = _ws_call(ws, 'cell', row_idx, HEADERS.index("referral_code") + 1)
        rc = cell.value
        return {"created": False, "referral_code": rc or ""}


def append_doc_urls(submission_id, doc_type_col, urls):
    ws = _sheet("Submissions")
    _ensure_headers(ws, HEADERS)

    row_idx = get_row_by_submission_id(submission_id)
    if row_idx is None:
        return

    col = HEADERS.index(doc_type_col) + 1
    cell = _ws_call(ws, 'cell', row_idx, col)
    existing = cell.value or ""
    existing_parts = [p for p in existing.split(",") if p]
    combined_parts = existing_parts + [u for u in urls if u]
    combined = ",".join(combined_parts)
    _ws_call(ws, 'update_cell', row_idx, col, combined)
def verify_calculation_consistency(submission_id, calc):
    """Verify that calculation data is consistent and safe for PDF/email.
    Returns (is_valid, issues_list)
    """
    def _to_num(x):
        try:
            if x is None or x == "":
                return 0.0
            return float(str(x).replace(',', '').replace('₹', ''))
        except:
            return 0.0

    issues = []

    # Check for presence of required calculation fields (check multiple possible paths)
    required_calcs = [
        ('taxable_new', ['calculations.taxable_new', 'taxable_new', 'compatibility_summary.taxable_new']),
        ('total_tax_new', ['calculations.new_total_tax', 'total_tax_new', 'compatibility_summary.total_tax_new']),
        ('refund_new', ['calculations.new_refund_or_due', 'refund_new', 'compatibility_summary.refund_new'])
    ]

    for field_name, paths in required_calcs:
        found_value = None
        for path in paths:
            if '.' in path:
                parts = path.split('.')
                val = calc
                for part in parts:
                    if isinstance(val, dict):
                        val = val.get(part)
                    else:
                        val = None
                        break
                if val is not None:
                    found_value = val
                    break
            else:
                found_value = calc.get(path)
                if found_value is not None:
                    break

        if found_value is None:
            issues.append(f"Missing critical calculation field: {field_name}")

    # Check for deduction limits (optional validation)
    sec_80c = _to_num((calc.get('deductions_80') or {}).get('sec_80c') or calc.get('sec_80c'))
    if sec_80c > 150000:
        issues.append(f"Section 80C exceeds limit: {sec_80c} > 150000")

    sec_80ccd_1b = _to_num((calc.get('deductions_80') or {}).get('sec_80ccd_1b') or calc.get('sec_80ccd_1b'))
    if sec_80ccd_1b > 50000:
        issues.append(f"Section 80CCD(1B) exceeds limit: {sec_80ccd_1b} > 50000")

    # Check home loan interest cap
    home_loan = _to_num((calc.get('deductions_80') or {}).get('home_loan_interest') or calc.get('home_loan_interest'))
    if home_loan > 200000:
        issues.append(f"Home loan interest exceeds limit: {home_loan} > 200000")

    # Log issues if any
    if issues:
        print(f"[VERIFY][{submission_id}] Calculation consistency issues: {issues}")

    return len(issues) == 0, issues


def log_referral(referrer_code, referred_name, referred_phone):
    rws = _sheet("Referrals")
    _ensure_headers(rws, ["timestamp", "referrer_code", "referred_name", "referred_phone"])
    _ws_call(rws, 'append_row', [datetime.now().isoformat(), referrer_code, referred_name, referred_phone])
    # Increment referrer's count
    ws = _sheet("Submissions")
    cells = _ws_call(ws, 'findall', referrer_code)
    rc_col = HEADERS.index("referral_code") + 1
    count_col = HEADERS.index("referral_count") + 1
    for c in cells:
        if c.col == rc_col:
            cell = _ws_call(ws, 'cell', c.row, count_col)
            cur = cell.value or "0"
            try: cur = int(cur)
            except: cur = 0
            _ws_call(ws, 'update_cell', c.row, count_col, cur + 1)
            break


def insert_submission(data):
    ws = _sheet("Submissions")
    _ensure_headers(ws, HEADERS)

    col_map = get_column_map()

    row_data = [""] * len(col_map)

    def set_field(field, value):
        if field in col_map:
            row_data[col_map[field]-1] = value

    submission_id = data.get("submission_id")

    # If submission_id already exists, update that row instead of appending
    if submission_id:
        existing_row = get_row_by_submission_id(submission_id)
        if existing_row:
            # Use update_row to apply fields and return referral metadata
            update_row(existing_row, data)
            cell = _ws_call(ws, 'cell', existing_row, HEADERS.index("referral_code") + 1)
            rc = cell.value
            return {"created": False, "referral_code": rc or "", "row": existing_row}

    set_field("submission_id", submission_id or "")
    set_field("timestamp", datetime.now().isoformat())

    # Ensure a referral code exists when creating the submission: generate one
    # from the provided name if available, otherwise use a default base.
    if not data.get('referral_code'):
        try:
            data['referral_code'] = gen_referral_code(data.get('name'))
        except Exception:
            data['referral_code'] = ''

    for k, v in data.items():
        set_field(k, v)

    set_field("approval_status", "PENDING")

    _ws_call(ws, 'append_row', row_data, value_input_option="USER_ENTERED")

    # return creation metadata including referral code and row index
    row_index = len(_ws_call(ws, 'get_all_values'))
    return {"created": True, "referral_code": data.get('referral_code', ''), "row": row_index}

def get_column_map():
    ws = _sheet("Submissions")
    headers = _ws_call(ws, 'row_values', 1)

    return {col: idx+1 for idx, col in enumerate(headers)}


def check_approval(submission_id):
    """Return the submission row as a dict (headers -> value) or None if not found.
    This is used by the app to read approval/referral fields for a submission.
    """
    ws = _sheet("Submissions")
    _ensure_headers(ws, HEADERS)

    row_idx = get_row_by_submission_id(submission_id)
    if row_idx is None:
        return None

    values = _ws_call(ws, 'row_values', row_idx)
    # pad to headers length
    values_padded = values + [""] * (len(HEADERS) - len(values))
    return dict(zip(HEADERS, values_padded))

def save_calculation_by_row(row, calc):
    """Save tax calculation results to sheet with validation.
    Ensures all key numeric fields are present and consistent.
    """
    ws = _sheet("Submissions")
    col_map = get_column_map()

    def _to_num(x):
        try:
            if x is None or x == "":
                return 0.0
            return float(str(x).replace(',', '').replace('₹', ''))
        except:
            return 0.0

    def set_cell(field, value):
        if field in col_map:
            _ws_call(ws, 'update_cell', row, col_map[field], value)

    def extract_numeric(calc, *paths):
        """Extract numeric value from nested dict using multiple fallback paths."""
        for path in paths:
            parts = path.split('.')
            val = calc
            for part in parts:
                if isinstance(val, dict):
                    val = val.get(part)
                else:
                    val = None
                    break
            if val is not None and val != "":
                return _to_num(val)
        return 0.0

    def extract_string(calc, *paths):
        """Extract string value from nested dict (no numeric conversion)."""
        for path in paths:
            parts = path.split('.')
            val = calc
            for part in parts:
                if isinstance(val, dict):
                    val = val.get(part)
                else:
                    val = None
                    break
            if val is not None and val != "":
                return str(val)
        return ""

    # Key intermediate values (HRA, home loan cap, TDS)
    set_cell("tds_paid", extract_numeric(calc, "tds_paid", "compatibility_summary.tds_paid"))
    set_cell("hra_exempt_actual", extract_numeric(calc, "hra_exempt_actual", "compatibility_summary.hra_exempt_actual", "section_10_exemptions.hra.hra_exemption"))
    set_cell("home_loan_interest_allowed", extract_numeric(calc, "home_loan_interest_allowed", "compatibility_summary.home_loan_interest_allowed"))

    # NEW regime
    set_cell("taxable_new", extract_numeric(calc, "calculations.taxable_new", "taxable_new", "compatibility_summary.taxable_new", "new_regime.taxable"))
    set_cell("total_tax_new", extract_numeric(calc, "calculations.new_total_tax", "total_tax_new", "compatibility_summary.total_tax_new", "new_regime.total_tax"))
    set_cell("refund_new", extract_numeric(calc, "calculations.new_refund_or_due", "refund_new", "compatibility_summary.refund_new", "new_regime.refund"))

    # OLD regime (A variant)
    set_cell("taxable_old_a", extract_numeric(calc, "calculations.taxable_old", "taxable_old_a", "compatibility_summary.taxable_old_a"))
    set_cell("total_tax_old_a", extract_numeric(calc, "calculations.old_total_tax", "total_tax_old_a", "compatibility_summary.total_tax_old_a"))
    set_cell("refund_old_a", extract_numeric(calc, "calculations.old_refund_or_due", "refund_old_a", "compatibility_summary.refund_old_a"))

    # OLD regime (B and C variants)
    set_cell("taxable_old_b", extract_numeric(calc, "taxable_old_b", "compatibility_summary.taxable_old_b"))
    set_cell("total_tax_old_b", extract_numeric(calc, "total_tax_old_b", "compatibility_summary.total_tax_old_b"))
    set_cell("refund_old_b", extract_numeric(calc, "refund_old_b", "compatibility_summary.refund_old_b"))
    set_cell("taxable_old_c", extract_numeric(calc, "taxable_old_c", "compatibility_summary.taxable_old_c"))
    set_cell("total_tax_old_c", extract_numeric(calc, "total_tax_old_c", "compatibility_summary.total_tax_old_c"))
    set_cell("refund_old_c", extract_numeric(calc, "refund_old_c", "compatibility_summary.refund_old_c"))

    # Variants — regime is a STRING ("OLD"/"NEW"), not numeric
    set_cell("variant_a_refund", extract_numeric(calc, "variant_options.variant_a.refund", "variant_a_refund", "compatibility_summary.variant_a_refund"))
    set_cell("variant_a_regime", extract_string(calc, "variant_options.variant_a.regime", "variant_a_regime", "compatibility_summary.variant_a_regime"))
    set_cell("variant_b_refund", extract_numeric(calc, "variant_options.variant_b.refund", "variant_b_refund", "compatibility_summary.variant_b_refund"))
    set_cell("variant_c_refund", extract_numeric(calc, "variant_options.variant_c.refund", "variant_c_refund", "compatibility_summary.variant_c_refund"))

    # Deductions
    set_cell("sec_80c", extract_numeric(calc, "deductions_80.sec_80c", "sec_80c", "compatibility_summary.sec_80c"))
    set_cell("sec_80d", extract_numeric(calc, "deductions_80.sec_80d", "sec_80d", "compatibility_summary.sec_80d"))
    set_cell("sec_80db", extract_numeric(calc, "sec_80db", "compatibility_summary.sec_80db"))
    set_cell("sec_80ccd_1b", extract_numeric(calc, "deductions_80.sec_80ccd_1b", "sec_80ccd_1b", "compatibility_summary.sec_80ccd_1b"))
    set_cell("sec_80ccd_2", extract_numeric(calc, "deductions_80.sec_80ccd_2", "sec_80ccd_2", "compatibility_summary.sec_80ccd_2"))
    set_cell("deductions_total", extract_numeric(calc, "deductions_80.total_deductions_80", "deductions_total", "compatibility_summary.deductions_total"))

    # Calculated deduction fields only (do NOT overwrite user-input fields like fd_interest, dividend, refund_interest)
    set_cell("sec_80g", extract_numeric(calc, "deductions_80.sec_80g", "sec_80g", "compatibility_summary.sec_80g"))
    set_cell("sec_80e", extract_numeric(calc, "deductions_80.sec_80e", "sec_80e", "compatibility_summary.sec_80e"))
    set_cell("savings_interest", extract_numeric(calc, "deductions_80.savings_interest", "savings_interest", "compatibility_summary.savings_interest"))

    # Always keep approval_status = PENDING (auditor must explicitly approve)
    set_cell("approval_status", "PENDING")


def update_row(row, data):
    if not row:
        print("⚠️ Skipping update — row is None")
        return

    ws = _sheet("Submissions")
    col_map = get_column_map()

    for k, v in data.items():
        if k in col_map:
            # Skip empty string / None to avoid clearing values unintentionally
            if v is None:
                continue
            if isinstance(v, str) and v.strip() == "":
                continue
            try:
                _ws_call(ws, 'update_cell', row, col_map[k], v)
            except Exception as e:
                print(f"Error updating {k}: {e}")