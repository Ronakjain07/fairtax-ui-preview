from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from config import Config
import ai_service, tax_engine, sheets_service, storage_service, whatsapp_service
import base64, traceback, os, requests as _requests, logging, sys
from pdf_service import generate_quote_pdf
from services import document_processor, quality_checker, doc_type_detector
from extraction_validator import ExtractionValidator
import uuid

# Configure logging for both console and file (for Waitress visibility)
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    handlers=[
        logging.FileHandler('flask_app.log'),
        logging.StreamHandler(sys.stdout)  # FIXED: Also log to console/Waitress
    ]
)
logger = logging.getLogger(__name__)

# Configure Flask to serve frontend files
# Frontend is in ../frontend relative to this backend directory
frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend')
app = Flask(__name__,
            static_folder=os.path.join(frontend_path),
            static_url_path='',
            template_folder=frontend_path)
app.secret_key = Config.FLASK_SECRET
CORS(app)

# Add file handler with proper flushing
file_handler = logging.FileHandler('flask_app.log', mode='a')
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.DEBUG)

# Ensure output is flushed immediately (for Waitress)
sys.stdout.flush()
sys.stderr.flush()
try:
    from itr_api import itr_bp
    print(f"[DEBUG] itr_bp imported: {itr_bp}, url_prefix={itr_bp.url_prefix}")
    app.register_blueprint(itr_bp)
    print(f"[DEBUG] itr_bp registered with Flask app")
except Exception as e:
    print(f"[ERROR] Failed to register itr_bp: {e}")
    import traceback
    traceback.print_exc()

# Global request logger - log EVERY request with proper logging
@app.before_request
def log_request():
    # Don't read request data here - it can consume the stream!
    if '/itr/extract' in request.path:
        app.logger.info(f"[REQUEST] {request.method} {request.path}")
        app.logger.info(f"  Content-Type: {request.content_type}")
        app.logger.info(f"  Content-Length: {request.content_length}")
        app.logger.info(f"  Files keys: {list(request.files.keys())}")
        app.logger.info(f"  Form keys: {list(request.form.keys())}")

# Global error handler to catch ALL errors
@app.errorhandler(422)
def handle_422(e):
    app.logger.error(f"[422 ERROR] {request.method} {request.path}")
    app.logger.error(f"  Exception type: {type(e).__name__}")
    app.logger.error(f"  Error: {str(e)}")
    import traceback
    app.logger.error(f"  Traceback: {traceback.format_exc()}")
    return jsonify({
        'success': False,
        'error': f'Validation failed: {str(e)}',
        'data': {}
    }), 422


def _safe_float(v):
    try:
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        # Strip common currency/formatting
        s = s.replace(',', '').replace('₹', '').strip()
        if s == '':
            return 0.0
        return float(s)
    except Exception:
        return 0.0

def _normalize_and_validate_phone(phone_raw):
    """Normalize and validate phone number. Returns (is_valid, normalized_phone).

    Validation rules:
    - Input must contain at least 10 digits
    - Returns last 10 digits (handles country codes like +91 prefix)

    Returns:
        tuple: (is_valid, normalized_phone)
        - is_valid: bool indicating if phone is valid
        - normalized_phone: str of 10 digits, or empty string if invalid
    """
    if not phone_raw:
        return False, ""

    # Extract all digits
    digits = ''.join(c for c in str(phone_raw).strip() if c.isdigit())

    # Validate minimum length
    if len(digits) < 10:
        return False, ""

    # Return last 10 digits (handles +91-10digit and variations)
    normalized = digits[-10:]
    return True, normalized

try:
    from scheduler_service import start_scheduler
    _scheduler = start_scheduler()
except Exception as _e:
    print(f"[Scheduler] Could not start: {_e}")

@app.route("/api/health")
def health():
    return {"status": "ok"}


# ---------- Landing Page (Root Route) ----------
@app.route("/")
def landing():
    """Serve landing.html as the default homepage"""
    try:
        return render_template("landing.html")
    except Exception as e:
        print(f"[LANDING] Error serving landing.html: {e}")
        logger.error(f"[LANDING] Error: {e}", exc_info=True)
        return {"error": "Could not load landing page"}, 500


# ---------- Phase-by-phase save ----------
@app.route("/api/save-phase", methods=["POST"])
def save_phase():
    print(">>> [SAVE_PHASE] FUNCTION CALLED - NEW CODE")
    try:
        data = request.get_json(force=True)
        print(f">>> [SAVE_PHASE] Got data with filing_category={data.get('filing_category')}")

        # Compatibility normalizations: frontend uses `filing_type`, backend/sheets expect `filing_category`.
        if data.get('filing_type') and not data.get('filing_category'):
            data['filing_category'] = data.get('filing_type')

        submission_id = data.get("submission_id")

        # Enforce filing_category only for NEW submissions (when no submission_id exists)
        # For updates to existing submissions, filing_category is optional
        if not submission_id:
            if not data.get('filing_category') or data.get('filing_category') not in ('regular', 'free'):
                return jsonify({"success": False, "error": "Please select filing type: 'regular' or 'free' before continuing."}), 400

        # ✅ CRITICAL: For NEW FREE filing, validate BEFORE anything else (BEFORE Sheets check)
        # User must provide: all 5 referrals + referral code (generated by frontend)
        if not submission_id and (data.get('filing_category') == 'free' or data.get('filing_type') == 'free'):
            # Check all 5 referrals are filled with valid names and phones
            filled_count = 0
            for i in range(1, 6):
                ref_name = (data.get(f'ref_name_{i}', '') or '').strip()
                ref_phone = (data.get(f'ref_phone_{i}', '') or '').strip()
                # Extract only digits from phone
                phone_digits = ''.join(c for c in ref_phone if c.isdigit())
                # Check if name exists and phone has 10+ digits
                if ref_name and len(phone_digits) >= 10:
                    filled_count += 1

            # Enforce: ALL 5 must be filled
            if filled_count < 5:
                return jsonify({
                    "success": False,
                    "error": f"Please fill all 5 referrals before proceeding. Currently filled: {filled_count}/5",
                    "type": "incomplete_referrals"
                }), 400

            # Enforce: Referral code MUST be provided by frontend (generated via "Reveal Code")
            if not data.get('referral_code'):
                return jsonify({
                    "success": False,
                    "error": "Please click 'Reveal Code' to generate your referral code before proceeding.",
                    "type": "missing_referral_code"
                }), 400

        # ── LOCAL DEV MODE: skip all Sheets ops when credentials aren't configured ──
        _sa = getattr(Config, 'SERVICE_ACCOUNT_JSON', None)
        _sheets_configured = bool(
            getattr(Config, 'GOOGLE_SHEET_ID', None) and
            _sa and _sa != 'service_account.json'
        )
        if not _sheets_configured:
            referral_code = data.get('referral_code', '')
            print(f"[SAVE_PHASE][LOCAL] Sheets not configured — returning mock success. submission_id={submission_id}")
            return jsonify({"success": True, "submission_id": submission_id, "referral_code": referral_code})

        # Ensure a referral code exists early so we can return it to the UI
        # even if Sheets writes are delayed or fail. Use sheets_service helper.
        # Only auto-generate for REGULAR filings or existing submissions
        try:
            if not data.get('referral_code') and (data.get('filing_category') == 'regular' or submission_id):
                data['referral_code'] = sheets_service.gen_referral_code(data.get('name'))
        except Exception:
            # Non-fatal: if gen_referral_code unavailable, leave blank and continue
            pass

        # Normalize phone to digits (store last 10 digits when available)
        if data.get('phone'):
            digits = ''.join([c for c in str(data.get('phone')) if c.isdigit()])
            if len(digits) >= 10:
                data['phone'] = digits[-10:]
            else:
                data['phone'] = digits

        # If this is a NEW regular filing (no submission_id yet), require basic contact fields
        if not submission_id and data.get('filing_category') == 'regular':
            missing = [f for f in ('name', 'phone', 'email') if not (data.get(f) and str(data.get(f)).strip())]
            if missing:
                return jsonify({"success": False, "error": f"Missing required fields for regular filing: {', '.join(missing)}"}), 400

        # Debug: log incoming save keys for troubleshooting
        try:
            print(f"[SAVE_PHASE] incoming keys={list(data.keys())} phone={data.get('phone')} filing_category={data.get('filing_category')}")
        except Exception:
            pass

        # Unpack JSON investment blobs into individual columns so review page can display them
        if any(k in data for k in ('home_loans_json', 'insurance_policies_json', 'donations_json')):
            try:
                aggregates = _aggregate_investments(data)
                if aggregates:
                    data.update(aggregates)
                    print(f"[SAVE_PHASE] Unpacked investment JSON → {list(aggregates.keys())}")
            except Exception as e:
                print(f"[SAVE_PHASE] Investment aggregation warning: {e}")

        # 🔥 CASE 1: No ID → create new
        if not submission_id:
            submission_id = str(uuid.uuid4())
            data["submission_id"] = submission_id

            try:
                insert_res = sheets_service.insert_submission(data)
            except Exception:
                insert_res = None

        else:
            row = sheets_service.get_row_by_submission_id(submission_id)

            # If submission row doesn't exist yet, create it so extracted data can be saved
            if row is None and submission_id:
                try:
                    insert_res = sheets_service.insert_submission({"submission_id": submission_id})
                    row = sheets_service.get_row_by_submission_id(submission_id)
                except Exception:
                    insert_res = None
                    row = None

            # 🔥 CASE 2: ID exists but row NOT FOUND → insert
            if row is None:
                try:
                    insert_res = sheets_service.insert_submission(data)
                except Exception:
                    insert_res = None

            # 🔥 CASE 3: normal update
            else:
                sheets_service.update_row(row, data)

        # Read back referral code (if generated) so frontend can display it immediately
        try:
            if 'insert_res' in locals() and isinstance(insert_res, dict) and insert_res.get('referral_code'):
                ref_code = insert_res.get('referral_code')
            else:
                rec_after = sheets_service.check_approval(submission_id)
                ref_code = rec_after.get('referral_code', '') if rec_after else ''
            # Fallback to locally generated code in data if sheet read/write didn't yield one
            if not ref_code:
                ref_code = data.get('referral_code', '')
        except Exception:
            ref_code = ''

        return jsonify({
            "success": True,
            "submission_id": submission_id,
            "referral_code": ref_code
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- WhatsApp webhook (incoming messages) ----------
@app.route("/whatsapp/webhook", methods=["GET", "POST"])
def whatsapp_webhook():
    # Verification challenge for Meta webhook setup
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        # Debug: log incoming token vs configured token to help verification
        try:
            print(f"[WEBHOOK VERIFY] received mode={mode!r} hub.verify_token={token!r} expected={Config.WHATSAPP_VERIFY_TOKEN!r}")
        except Exception:
            print("[WEBHOOK VERIFY] received verification request (could not print tokens)")

        if mode == "subscribe" and token == Config.WHATSAPP_VERIFY_TOKEN:
            print("[WEBHOOK VERIFY] token matched — returning challenge")
            return challenge, 200
        print("[WEBHOOK VERIFY] token mismatch — returning 403")
        return "Forbidden", 403

    # POST: incoming webhook events
    try:
        payload = request.get_json(force=True)
        entries = payload.get("entry", []) or []
        for entry in entries:
            for change in entry.get("changes", []) or []:
                value = change.get("value", {}) or {}
                messages = value.get("messages", []) or []
                # iterate over any inbound messages
                for m in messages:
                    phone = m.get("from")
                    if not phone:
                        continue
                    text = None
                    mtype = m.get("type")
                    if mtype == "text":
                        text = m.get("text", {}).get("body")
                    elif mtype == "button":
                        text = m.get("button", {}).get("text")
                    else:
                        # interactive messages (list_reply / button reply)
                        inter = m.get("interactive", {})
                        if inter:
                            if inter.get("type") == "button":
                                btn = inter.get("button", {})
                                text = btn.get("text") or btn.get("payload")
                            elif inter.get("type") == "list_reply":
                                lr = inter.get("list_reply", {})
                                text = lr.get("title") or lr.get("id")

                    if not text:
                        continue

                    # Normalize and respond
                    wa_phone = whatsapp_service.normalize_phone(phone)
                    try:
                        reply = ai_service.generate_whatsapp_reply(text, phone=phone)
                    except Exception as e:
                        print("AI generation error:", e)
                        reply = "Thanks — our team will reply shortly."

                    try:
                        whatsapp_service.send_text(wa_phone, reply)
                    except Exception as e:
                        print("Failed to send WA reply:", e)

        return jsonify({"success": True})
    except Exception as e:
        print("Webhook processing error:", e)
        return jsonify({"success": False, "error": str(e)}), 500
# ---------- Aggregation helpers ----------
def _deduplicate_and_sum_array(items, dedup_key, sum_keys):
    """Deduplicate items by dedup_key, sum numeric fields in sum_keys.
    Returns (total_sum_dict, duplicates_list)
    """
    seen = {}
    duplicates = []

    for item in (items or []):
        if not isinstance(item, dict):
            continue

        key_val = item.get(dedup_key) or ""
        if key_val and key_val in seen:
            # Duplicate detected
            duplicates.append({"original": seen[key_val], "duplicate": item, "key": dedup_key})
        else:
            if key_val:
                seen[key_val] = item

    totals = {}
    for sk in sum_keys:
        totals[sk] = sum(float(str(i.get(sk) or 0).replace(',', '').replace('₹', '')) or 0 for i in seen.values())

    return totals, duplicates


def _aggregate_investments(merged_data):
    """Aggregate multi-entry investment JSON blobs into individual sheet columns.

    IMPORTANT — idempotent & non-accumulating:
    Values are derived purely from the JSON blobs. We do NOT add them on top
    of existing field values (that caused double-counting when the same
    extraction populates both the individual field and the JSON blob).
    """
    import json

    def _to_num(x):
        try:
            if x is None or x == "":
                return 0.0
            return float(str(x).replace(',', '').replace('₹', ''))
        except Exception:
            return 0.0

    aggregates = {}

    # ===== Home Loans =====
    hl = merged_data.get('home_loans_json')
    if hl:
        try:
            loans = json.loads(hl) if isinstance(hl, str) else hl
        except Exception:
            loans = hl if isinstance(hl, list) else []

        totals, dupes = _deduplicate_and_sum_array(
            loans or [],
            'policy_no',
            ['home_loan_interest', 'interest', 'interest_amount', 'home_loan_principal', 'principal']
        )

        if dupes:
            print(f"[AGG] Home loans: {len(dupes)} duplicates detected and merged")
            for d in dupes:
                print(f"  Duplicate loan account {d.get('original', {}).get('policy_no')}")

        sum_interest = totals.get('home_loan_interest', 0) + totals.get('interest', 0) + totals.get('interest_amount', 0)
        # NOTE: 'outstanding' / 'loan_outstanding' is the remaining loan BALANCE,
        # NOT the principal repayment eligible for 80C. Do NOT include it here.
        sum_principal = totals.get('home_loan_principal', 0) + totals.get('principal', 0)

        # Replace (not accumulate) — JSON is the source of truth
        if sum_interest > 0:
            aggregates['home_loan_interest'] = sum_interest
        if sum_principal > 0:
            aggregates['home_loan_principal'] = sum_principal

    # ===== Insurance Policies =====
    ins = merged_data.get('insurance_policies_json')
    if ins:
        try:
            inslist = json.loads(ins) if isinstance(ins, str) else ins
        except Exception:
            inslist = ins if isinstance(ins, list) else []

        totals, dupes = _deduplicate_and_sum_array(
            inslist or [],
            'policy_no',
            ['premium', 'premium_amount', 'premium_amount_rupee']
        )

        if dupes:
            print(f"[AGG] Insurance: {len(dupes)} duplicates detected and merged")
            for d in dupes:
                print(f"  Duplicate policy {d.get('original', {}).get('policy_no')}")

        sum_life_prem = 0.0
        sum_health_self = 0.0
        sum_health_parents = 0.0
        for I in (inslist or []):
            if not isinstance(I, dict):
                continue
            typ = (I.get('type') or I.get('coverage_type') or '').lower()
            prem = 0.0
            for k in ('premium', 'premium_amount', 'premium_amount_rupee'):
                if k in I and I[k] not in (None, ''):
                    prem = _to_num(I[k])
                    break
            if 'health_self' in typ or typ == 'health':
                sum_health_self += prem
            elif 'health_parent' in typ:
                sum_health_parents += prem
            else:
                sum_life_prem += prem

        # Replace (not accumulate) — JSON is the source of truth
        if sum_life_prem > 0:
            aggregates['ulip_lic'] = sum_life_prem
        if sum_health_self > 0:
            aggregates['medical_self'] = sum_health_self
        if sum_health_parents > 0:
            aggregates['medical_parents'] = sum_health_parents

    # ===== Donations =====
    don = merged_data.get('donations_json')
    if don:
        try:
            dons = json.loads(don) if isinstance(don, str) else don
        except Exception:
            dons = don if isinstance(don, list) else []

        totals, dupes = _deduplicate_and_sum_array(
            dons or [],
            'receipt_number',
            ['donation_amount', 'amount']
        )

        if dupes:
            print(f"[AGG] Donations: {len(dupes)} duplicates detected and merged")
            for d in dupes:
                print(f"  Duplicate donation receipt {d.get('original', {}).get('receipt_number')}")

        total_don = totals.get('donation_amount', 0) + totals.get('amount', 0)
        if total_don > 0:
            aggregates['sec_80g'] = total_don

    return aggregates
@app.route("/api/extract", methods=["POST"])
def extract():
    try:
        submission_id = request.form.get("submission_id")
        doc_type = request.form.get("doc_type", "form16")
        files = request.files.getlist("documents")

        row = sheets_service.get_row_by_submission_id(submission_id)

        urls, extractions = [], []

        # ═══════════════════════════════════════════════════════════
        # NEW: Vision-based extraction pipeline
        # ═══════════════════════════════════════════════════════════
        for f in files:
            content = f.read()
            mime = f.mimetype or "image/png"

            f.stream.seek(0)

            # Store file
            url = storage_service.save_file(f, submission_id)
            if url:
                urls.append(url)

            # Process with Vision extraction pipeline
            print(f"[EXTRACT] Processing {f.filename} ({mime}) as doc_type='{doc_type}' with Vision pipeline...")
            result = document_processor.process_documents(content, mime, doc_type)

            # AUTO-DETECTION: Only when confidence is very low AND document is small
            conf = result.get("confidence", 0)
            pages = result["metadata"].get("pages_processed", 1)

            if conf < 0.3 and pages <= 10:
                print(f"[EXTRACT] Auto-detecting: confidence={conf}, pages={pages}. Trying all document types...")

                best_result = result
                best_confidence = result.get("confidence", 0)
                best_doc_type = doc_type

                # Try each document type and keep the one with highest confidence
                for test_type in ["form16", "payslip", "homeloan", "school", "nps", "insurance", "donation"]:
                    if test_type == doc_type:
                        continue  # Skip the current type, we already have that result
                    try:
                        test_result = document_processor.process_documents(content, mime, test_type)
                        test_confidence = test_result.get("confidence", 0)

                        print(f"[EXTRACT] Tried {test_type}: confidence={test_confidence}")

                        if test_confidence > best_confidence:
                            best_result = test_result
                            best_confidence = test_confidence
                            best_doc_type = test_type

                    except Exception as e:
                        print(f"[EXTRACT] Error trying {test_type}: {str(e)}")
                        continue

                # If we found a better match, use it
                if best_doc_type != doc_type:
                    print(f"[EXTRACT] DETECTED DOCUMENT TYPE: {best_doc_type} (confidence: {best_confidence})")
                    result = best_result
                    result["auto_detected_doc_type"] = best_doc_type
                    doc_type = best_doc_type  # Update doc_type for downstream processing

            # Fail fast: if Vision extraction fails, return error to user
            if not result["success"]:
                print(f"[EXTRACT] Vision extraction failed: {result['error']}")
                # Try to suggest correct doc type
                suggestion = doc_type_detector.suggest_correct_doc_type(doc_type, f.filename, {})
                error_msg = result["error"]
                if suggestion.get("should_retry"):
                    error_msg += f" (Hint: Try re-uploading as {suggestion['suggested_type']})"

                return jsonify({
                    "success": False,
                    "error": error_msg
                }), 400

            # Extract normalized data from PASS 1
            extracted_data = result["data"]
            extracted_data["_source_filename"] = f.filename
            extracted_data["_doc_type"] = doc_type
            extracted_data["_confidence"] = result["confidence"]
            extracted_data["_metadata"] = result["metadata"]

            # Preserve auto-detected doc type if it was detected
            if "auto_detected_doc_type" in result:
                extracted_data["_auto_detected_doc_type"] = result["auto_detected_doc_type"]

            extractions.append(extracted_data)

            print(f"[EXTRACT] {f.filename}: confidence={result['confidence']}, "
                  f"pages={result['metadata'].get('pages_processed', 1)}")

        # Merge multiple documents if applicable (existing logic)
        merged = ai_service.merge_extractions(extractions)
        conflicts = merged.pop('_merge_conflicts', [])

        if conflicts:
            print(f"[EXTRACT][{doc_type}] conflicts detected: {conflicts}")

        # ✅ VALIDATION LAYER: Comprehensive extraction validation
        # Validates annual/monthly consistency, Form 16 priority, document reconciliation, etc.
        try:
            validator = ExtractionValidator(extractions, merged)
            validated_data, validation_report = validator.validate()

            # Use validated data and store report for audit trail
            merged.update(validated_data)
            merged['_validation_report'] = validation_report

            print(f"[VALIDATION] Valid={validation_report.get('valid')}, "
                  f"Warnings={len(validation_report.get('warnings', []))}")
        except Exception as e:
            print(f"[VALIDATION] Comprehensive validation failed (non-blocking): {e}")
            # Non-breaking: continue with unvalidated data
            merged['_validation_report'] = {'valid': False, 'error': str(e)}

        # ✅ NEW: Form 16 vs Payslip consistency check (adds specialized conflict detection)
        form16_payslip_conflicts = []
        try:
            merged, form16_payslip_conflicts = ai_service.validate_form16_payslip_consistency(merged, extractions)
            # Merge the new conflicts with existing ones
            if form16_payslip_conflicts:
                conflicts.extend(form16_payslip_conflicts)
                print(f"[EXTRACT] Form 16/Payslip conflicts: {len(form16_payslip_conflicts)}")
        except Exception as e:
            print(f"[EXTRACT] Form 16/Payslip validation failed (non-blocking): {e}")
            # Don't block extraction if validation fails

        # Clean extraction (existing validation)
        merged = ai_service.clean_extraction(merged)

        # Save to Sheets
        sheets_service.update_row(row, merged)

        # Save document URLs by type
        if urls:
            col_map = {
                "form16": "doc_form16_urls",
                "payslip": "doc_payslip_urls",
                "homeloan": "doc_homeloan_urls",
                "school": "doc_school_urls",
                "nps": "doc_nps_urls",
                "insurance": "doc_insurance_urls",
                "donation": "doc_donation_urls"
            }

            sheets_service.append_doc_urls(
                submission_id,
                col_map.get(doc_type, "doc_form16_urls"),
                urls
            )

        print(f"[EXTRACT] Extraction complete for submission {submission_id}")

        # Assess extraction quality and add warnings
        quality_result = quality_checker.assess_extraction_quality(
            {
                "confidence": merged.get("_confidence", 0),
                "metadata": merged.get("_metadata", {})
            },
            doc_type
        )

        # Check data completeness
        completeness = quality_checker.validate_data_completeness(merged, doc_type)

        # Add helpful note about doc_type if using default
        helper_note = None
        if doc_type == "form16":
            helper_note = "Note: For better extraction, specify doc_type in your request. " \
                         "Supported: form16, payslip, homeloan, school, nps, insurance, donation"

        response = {
            "success": True,
            "data": merged,
            "urls": urls,
            "conflicts": conflicts,
            "confidence": merged.get("_confidence", 0),
            "doc_type_used": doc_type,
            "metadata": merged.get("_metadata", {}),
            "quality": {
                "level": quality_result["quality_level"],
                "confidence_score": quality_result["confidence_score"],
                "warnings": quality_result["warnings"],
                "user_action_required": quality_result["user_action_required"],
                "feedback": quality_result["actionable_feedback"]
            },
            "completeness": {
                "complete": completeness["complete"],
                "missing_fields": completeness["missing_fields"],
                "feedback": completeness["feedback"]
            }
        }

        # Add auto_detected_doc_type if it was auto-detected
        if extractions and len(extractions) > 0 and "_auto_detected_doc_type" in extractions[0]:
            response["auto_detected_doc_type"] = extractions[0]["_auto_detected_doc_type"]
            response["helper_note"] = f"✅ Document type auto-detected as: {extractions[0]['_auto_detected_doc_type']}"
        elif helper_note:
            response["helper_note"] = helper_note

        return jsonify(response)

    except Exception as e:
        traceback.print_exc()
        print(f"[EXTRACT] Unexpected error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- Serve uploads ----------
@app.route("/uploads/<submission_id>/<filename>")
def serve_upload(submission_id, filename):
    folder = os.path.join(Config.UPLOAD_DIR, submission_id)
    return send_from_directory(folder, filename)


# ---------- Final submit ----------
@app.route("/api/minimal", methods=["POST"])
def minimal():
    return jsonify({"test": "minimal"})

@app.route("/api/test-json", methods=["POST"])
def test_json():
    """Minimal endpoint to test JSON parsing"""
    try:
        # Try to parse JSON WITHOUT calling get_data first
        data = request.get_json(force=True)

        return jsonify({
            "success": True,
            "keys": list(data.keys()) if isinstance(data, dict) else "not a dict"
        })
    except Exception as e:
        import traceback
        return jsonify({
            "success": False,
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc()[:500]
        }), 500

@app.route("/api/submit", methods=["POST"])
def submit():
    try:
        # CRITICAL: Werkzeug development server needs explicit handling
        # Try to parse request with safe defaults
        try:
            data = request.get_json(force=True)
            if not isinstance(data, dict):
                data = {}
        except Exception as json_err:
            # If JSON parsing fails, try again with cache=False
            try:
                data = request.get_json(force=True, cache=False)
                if not isinstance(data, dict):
                    data = {}
            except:
                # Last resort: return empty dict
                data = {}

        print(f"[SUBMIT] Data received: {list(data.keys())}", flush=True)

        submission_id = data.get("submission_id")
        print(f"[SUBMIT] submission_id: {submission_id}")
        if not submission_id:
            print("[SUBMIT] No submission_id provided")
            return jsonify({"success": False, "error": "submission_id required"}), 400

        row = sheets_service.get_row_by_submission_id(submission_id)
        print(f"[SUBMIT] Initial row lookup: {row}")

        # If row missing, create it so updates and calculations persist
        if row is None:
            try:
                print(f"[SUBMIT] Creating new submission in Sheets...")
                result = sheets_service.insert_submission({"submission_id": submission_id, **data})
                print(f"[SUBMIT] Insert result: {result}")
                print(f"[SUBMIT] Referral code generated: {result.get('referral_code')}")
                # Update data with generated referral code
                if result.get('referral_code'):
                    data['referral_code'] = result['referral_code']
                row = sheets_service.get_row_by_submission_id(submission_id)
                print(f"[SUBMIT] Row after insert: {row}")
            except Exception as insert_err:
                logger.error(f"[SUBMIT] ERROR during insert_submission: {insert_err}")
                logger.error(f"[SUBMIT] Traceback: {traceback.format_exc()}")
                print(f"[SUBMIT] ERROR during insert_submission: {insert_err}", flush=True)
                # Check if it's a quota error
                if "RESOURCE_EXHAUSTED" in str(insert_err) or "Quota exceeded" in str(insert_err):
                    logger.warning("[SUBMIT] Google Sheets quota exceeded - data will be retried later")
                row = None

        # ✅ Regenerate referral code with actual name (was generated as USER_FAIRTAX## before name was collected)
        # BUT: Do NOT regenerate for referral filings (code should use REFERRER's name, not referred person's name)
        # Check if this is a pure regular filing (not a referral redirect)
        is_referral_filing = data.get('filing_category') == 'free' or data.get('referrer_name') or data.get('_referral_handoff')
        if (not is_referral_filing and data.get('name') and
            data.get('referral_code', '').startswith('USER_')):
            data['referral_code'] = sheets_service.gen_referral_code(data.get('name'))
            print(f"[SUBMIT] Regenerated referral code with actual name: {data['referral_code']}")

        # ✅ save final data
        print(f"[SUBMIT] Updating row with data...")
        sheets_service.update_row(row, data)
        print(f"[SUBMIT] Update complete")

        # Merge sheet row (has OCR-extracted investment data) with submitted form data
        existing_rec = sheets_service.check_approval(submission_id)
        if existing_rec:
            # Sheet data as base; submitted form fields override
            merged_data = {**existing_rec, **data}
        else:
            merged_data = data
        print(f"[SUBMIT] merged_data keys: {list(merged_data.keys())}")

        # ✅ Aggregate multi-entry JSON fields with duplicate detection
        try:
            aggregates = _aggregate_investments(merged_data)
            if aggregates:
                sheets_service.update_row(row, aggregates)
                for k, v in aggregates.items():
                    merged_data[k] = v
        except Exception as _agg_e:
            print('Aggregation error:', _agg_e)


        # Ensure rent alias: map frontend `rent_paid` (monthly) to `monthly_rent` expected by engine
        try:
            if merged_data.get('rent_paid') and not merged_data.get('monthly_rent'):
                merged_data['monthly_rent'] = merged_data.get('rent_paid')
        except Exception:
            pass

        # ✅ VALIDATION: Use validation report from extraction (if available)
        # Validator runs in /api/extract, not here in /api/submit
        validation_report = merged_data.get('_validation_report', {})
        if validation_report:
            print(f"[VALIDATION] Valid={validation_report.get('valid')}, "
                  f"Errors={len(validation_report.get('errors', []))}, "
                  f"Warnings={len(validation_report.get('warnings', []))}")
            if not validation_report.get('valid'):
                logger.warning(f"[VALIDATION] Submission has validation errors: "
                              f"{validation_report.get('errors')}")
        else:
            print("[VALIDATION] No validation report from extraction (normal if not Form16/Payslip)")

        # ✅ TAX CALC — deterministic engine is the source of truth;
        #    AI enrichment (assumptions, notes) is optional overlay.
        engine_calc = {}
        try:
            engine_calc = tax_engine.calculate(merged_data)
            print(f"[TAX_CALC] Engine OK — sec_80c={engine_calc.get('sec_80c')}, "
                  f"deductions_total={engine_calc.get('deductions_total')}, "
                  f"taxable_old_a={engine_calc.get('taxable_old_a')}")
        except Exception as te:
            print(f"[TAX_CALC] Engine failed: {te}")
            traceback.print_exc()

        # Try AI for enrichment (assumptions, pdf_summary, calculation_notes)
        ai_calc = None
        try:
            ai_calc = ai_service.calculate_tax_ai(merged_data)
        except Exception as e:
            print(f"[TAX_CALC] AI enrichment failed (non-blocking): {e}")

        # Merge: start with AI (rich structure) then override all numeric
        # tax/deduction fields with the deterministic engine values
        if ai_calc and isinstance(ai_calc, dict):
            calc = ai_calc
            # Engine values override AI for every numeric field
            for k, v in engine_calc.items():
                calc[k] = v
            # Also patch nested structures that save_calculation_by_row reads
            calc.setdefault('deductions_80', {}).update({
                'sec_80c': engine_calc.get('sec_80c', 0),
                'sec_80d': engine_calc.get('sec_80d', 0),
                'sec_80e': engine_calc.get('sec_80e', 0),
                'sec_80g': engine_calc.get('sec_80g', 0),
                'sec_80ccd_1b': engine_calc.get('sec_80ccd_1b', 0),
                'sec_80ccd_2': engine_calc.get('sec_80ccd_2', 0),
                'savings_interest': engine_calc.get('savings_interest', 0),
                'total_deductions_80': engine_calc.get('deductions_total', 0),
            })
            calc.setdefault('calculations', {}).update({
                'taxable_new': engine_calc.get('taxable_new', 0),
                'new_total_tax': engine_calc.get('total_tax_new', 0),
                'new_refund_or_due': engine_calc.get('refund_new', 0),
                'taxable_old': engine_calc.get('taxable_old_a', 0),
                'old_total_tax': engine_calc.get('total_tax_old_a', 0),
                'old_refund_or_due': engine_calc.get('refund_old_a', 0),
            })
            calc.setdefault('compatibility_summary', {}).update(engine_calc)
            print("[TAX_CALC] Merged engine values into AI enrichment")
        else:
            calc = engine_calc

        # ✅ ADD VALIDATION STATUS TO CALC before saving
        # Recommendation should only run if validation passed
        calc['_validation_passed'] = validation_report.get('valid', False)
        calc['_validation_errors'] = validation_report.get('errors', [])
        calc['_validation_warnings'] = validation_report.get('warnings', [])

        sheets_service.save_calculation_by_row(row, calc)

        # ✅ Flag data conflicts for auditor review (if any were detected during extraction)
        try:
            conflicts_list = merged_data.get('_form16_payslip_conflicts', [])
            if conflicts_list:
                # Build conflict summary for auditor notes
                conflict_summary = f"⚠️ DATA CONFLICTS DETECTED ({len(conflicts_list)} conflicts):\n"
                for conflict in conflicts_list:
                    conflict_summary += (
                        f"• {conflict.get('field_name', conflict.get('field'))}: "
                        f"Form 16 = ₹{conflict.get('form16_value'):,.0f}, "
                        f"Payslip (annualized) = ₹{conflict.get('payslip_annualized_value'):,.0f} "
                        f"({conflict.get('variance_percent', 0):.1f}% diff). "
                        f"Using Form 16 value. Severity: {conflict.get('severity', 'MEDIUM')}\n"
                    )

                # Append to auditor_notes in Sheets for review
                existing_notes = (merged_data.get('auditor_notes') or "")
                conflict_summary += f"\nResolution: Used Form 16 (primary) over Payslip (monthly). Auditor should verify if discrepancy is due to mid-year salary changes, bonuses, or leaves."

                if existing_notes:
                    conflict_summary = existing_notes + "\n---\n" + conflict_summary

                sheets_service.update_row(row, {"auditor_notes": conflict_summary})
                print(f"[CONFLICT] Flagged {len(conflicts_list)} conflicts for auditor review")
        except Exception as conflict_flag_e:
            print(f"[CONFLICT] Failed to flag conflicts for auditor (non-blocking): {conflict_flag_e}")

        # ✅ Verify calculation consistency before finalizing
        is_valid, issues = sheets_service.verify_calculation_consistency(submission_id, calc)
        if not is_valid:
            print(f"[SUBMIT][{submission_id}] Calculation validation failed: {issues}")
            # Log but don't block submission — auditor will review

        # ✅ Determine referral code to return. Prefer client-provided value
        # (sent from frontend/localStorage) so UI shows it immediately; fallback
        # to sheet value when available.
        rec = sheets_service.check_approval(submission_id)
        ref_code = data.get('referral_code') or (rec.get("referral_code", "") if rec else "")

        # referral logging
        if data.get("referred_by"):
            sheets_service.log_referral(
                data["referred_by"],
                data.get("name", ""),
                data.get("phone", "")
            )

        # Log 5 referrals from referral-filing form (if present)
        # BACKEND VALIDATION: Normalize and validate all referral data
        referrer_name = data.get("referrer_name", "") or data.get("name", "")
        logged_phones = set()  # Track logged phones to prevent duplicates

        for i in range(1, 6):
            ref_name = (data.get(f"ref_name_{i}", "") or "").strip()
            ref_phone_raw = (data.get(f"ref_phone_{i}", "") or "").strip()

            # Skip empty entries
            if not ref_name or not ref_phone_raw:
                continue

            # Normalize phone: extract digits and take last 10
            phone_digits = ''.join(c for c in ref_phone_raw if c.isdigit())

            # VALIDATION: Phone must be at least 10 digits
            if len(phone_digits) < 10:
                print(f"[REFERRAL] Skipped referral {i}: Invalid phone format '{ref_phone_raw}' (needs 10+ digits)")
                continue

            # Use last 10 digits for Indian phone numbers
            ref_phone = phone_digits[-10:]

            # DEDUPLICATION: Skip if same phone already logged in this batch
            if ref_phone in logged_phones:
                print(f"[REFERRAL] Skipped referral {i}: Duplicate phone {ref_phone}")
                continue

            logged_phones.add(ref_phone)

            # Log the validated referral
            try:
                sheets_service.log_referral(ref_code, ref_name, ref_phone)
                print(f"[REFERRAL] Logged referral {i}: {ref_name} ({ref_phone})")
            except Exception as e:
                print(f"[REFERRAL] Error logging referral {i}: {e}")

        # WhatsApp (still uses phone) — non-blocking, errors don't block submission
        try:
            wa_phone = whatsapp_service.normalize_phone(data.get("phone", ""))
            if wa_phone:
                # Send WhatsApp template and log response for debugging
                wa_resp = whatsapp_service.send_template(
                    wa_phone,
                    "submission_received",
                    [data.get("name", "there"), ref_code]
                )
                print(f"[WA][submit] template send response: {wa_resp}")
        except Exception as wa_err:
            print(f"[WA][submit] WARNING - WhatsApp notification failed (non-blocking): {wa_err}")
            # Continue with submission regardless — WhatsApp is secondary

        # Apps Script webhook (fire-and-forget, non-blocking)
        if Config.APPS_SCRIPT_WEBHOOK_URL:
            try:
                _requests.post(Config.APPS_SCRIPT_WEBHOOK_URL, json={
                    "event": "new_submission",
                    "submission_id": submission_id,
                    "name": data.get("name", ""),
                    "phone": data.get("phone", ""),
                    "referral_code": ref_code,
                    "timestamp": data.get("timestamp", "")
                }, timeout=5)
            except Exception:
                pass

        response_data = {
            "success": True,
            "submission_id": submission_id,
            "referral_code": ref_code,
            "message": "Submitted! You'll receive your quote on WhatsApp within 24 hours.",
            "refund_old_a": engine_calc.get('refund_old_a', 0),
            "refund_old_b": engine_calc.get('refund_old_b', 0),
            "refund_old_c": engine_calc.get('refund_old_c', 0),
        }
        print(f"[SUBMIT] Returning success response: {response_data}")
        return jsonify(response_data)

    except Exception as e:
        exc_traceback = traceback.format_exc()
        error_msg = str(e)
        print(f"[SUBMIT] EXCEPTION in submit endpoint: {error_msg}", flush=True)
        print(f"[SUBMIT] Traceback:\n{exc_traceback}", flush=True)

        # Try to return error response
        try:
            error_response = {
                "success": False,
                "error": error_msg
            }
            print(f"[SUBMIT] Created error_response dict", flush=True)
            result = jsonify(error_response)
            print(f"[SUBMIT] jsonify succeeded", flush=True)
            return result, 500
        except Exception as json_err:
            print(f"[SUBMIT] ERROR: Could not jsonify error response: {json_err}", flush=True)
            return {"success": False, "error": error_msg}, 500


# ---------- Quote ----------
@app.route("/api/quote/<submission_id>")
def quote(submission_id):
    rec = sheets_service.check_approval(submission_id)
    if not rec:
        return jsonify({"success": False, "error": "Not found"}), 404

    if rec.get("approval_status") != "APPROVED":
        return jsonify({"success": True, "approved": False,
                        "message": "Your filing is under expert review. You'll receive a WhatsApp notification once approved."})

    def f(k):
        try: return float(rec.get(k) or 0)
        except: return 0.0

    fee = f("auditor_quote_fee")
    fee_upfront = round(fee * 0.5, 2)

    def clean_regime(r):
        """Convert regime value, handling '0' or empty strings."""
        r = str(r or "").strip()
        return r if r and r not in ("0", "—") else "NEW"

    plans = [
        {"id": "A", "label": "Plan A — Safe",
         "desc": "Conservative deductions, exact figures as filed. Lowest risk.",
         "refund": f("variant_a_refund"), "regime": clean_regime(rec.get("variant_a_regime"))},
        {"id": "B", "label": "Plan B — Optimized",
         "desc": "Optimised LTA & allowance claims for a higher refund.",
         "refund": f("variant_b_refund"), "regime": "OLD"},
        {"id": "C", "label": "Plan C — Maximum",
         "desc": "Maximum legal deductions & allowances claimed.",
         "refund": f("variant_c_refund"), "regime": "OLD"},
    ]

    filename = f"quote_{submission_id}.pdf"
    pdf_password = None
    try:
        pdf_data = {**rec, "plans": plans}
        # Derive PDF password: prefer last 4 digits of user's phone, fallback to submission_id tail
        try:
            phone = rec.get("phone", "") if rec else ""
            digits = "".join([c for c in str(phone) if c.isdigit()])
            if digits and len(digits) >= 4:
                pdf_password = digits[-4:]
            else:
                pdf_password = submission_id[-6:] if submission_id else None
        except Exception:
            pdf_password = submission_id[-6:] if submission_id else None

        generate_quote_pdf(pdf_data, filename, password=pdf_password)
        print(f"[PDF] Generated successfully: {filename} with password: {pdf_password}")
    except Exception as _pe:
        print(f"[PDF] Generation error for {submission_id}: {_pe}")
        traceback.print_exc()

    pdf_url = f"{Config.PUBLIC_BASE_URL}/api/download/{filename}" if Config.PUBLIC_BASE_URL else ""

    # Auto-send WhatsApp quote notification exactly once — only mark QUOTE_SENT if WA send succeeds
    if not rec.get("filing_status"):
        resp = None
        wa_phone = whatsapp_service.normalize_phone(rec.get("phone", ""))
        print(f"[QUOTE] Attempting WhatsApp send for {submission_id}: phone={wa_phone}, pdf_url={pdf_url}")
        if wa_phone:
            best_refund = max(f("variant_a_refund"), f("variant_b_refund"), f("variant_c_refund"))
            try:
                # The quote_ready template has a URL button that needs the filename
                # (or unique part of the URL) as a dynamic parameter
                print(f"[QUOTE] Sending WhatsApp template 'quote_ready' to {wa_phone} with refund: {best_refund}, pdf_url: {pdf_url}")
                resp = whatsapp_service.send_template(
                    wa_phone,
                    "quote_ready",
                    [rec.get("name", "there"), str(int(best_refund))],
                    button_url_param=pdf_url,
                )
                print(f"[QUOTE] WhatsApp response: {resp}")
                # Consider send successful if response is truthy and contains no 'error' key
                success = bool(resp) and not (isinstance(resp, dict) and resp.get('error'))
            except Exception as _we:
                print(f"[QUOTE] WhatsApp send exception for {submission_id}: {_we}")
                traceback.print_exc()
                success = False
        else:
            print(f"[QUOTE] No WhatsApp phone for {submission_id}; original phone='{rec.get('phone', '')}'")
            success = False

        if success:
            row = sheets_service.get_row_by_submission_id(submission_id)
            sheets_service.update_row(row, {"filing_status": "QUOTE_SENT"})
            print(f"[QUOTE] ✅ WhatsApp sent successfully and filing_status updated to QUOTE_SENT for {submission_id}")
        else:
            print(f"[QUOTE] ❌ WhatsApp send failed or skipped for {submission_id}: {resp}")

    return jsonify({
        "success": True,
        "approved": True,
        "name": rec.get("name", ""),
        "recommended_regime": rec.get("variant_a_regime", "NEW"),
        "fee": fee,
        "fee_upfront": fee_upfront,
        "fee_on_refund": round(fee - fee_upfront, 2),
        "plans": plans,
        "pdf_url": pdf_url,
        "pdf_password": pdf_password,
        "auditor_notes": rec.get("auditor_notes", ""),
        "filing_status": rec.get("filing_status", ""),
        "payment_status": rec.get("payment_status", ""),
        "user_chosen_option": rec.get("user_chosen_option", ""),
    })


# ---------- Choose Option ----------
@app.route("/api/choose-option", methods=["POST"])
def choose_option():
    try:
        data = request.get_json(force=True)
        submission_id = data.get("submission_id")
        plan_id = str(data.get("plan_id", "")).upper()
        if not submission_id or plan_id not in ("A", "B", "C"):
            return jsonify({"success": False, "error": "submission_id and plan_id (A/B/C) required"}), 400

        row = sheets_service.get_row_by_submission_id(submission_id)
        if not row:
            return jsonify({"success": False, "error": "Submission not found"}), 404

        sheets_service.update_row(row, {
            "user_chosen_option": plan_id,
            "filing_status": "OPTION_CHOSEN",
        })

        rec = sheets_service.check_approval(submission_id)
        fee = float(rec.get("auditor_quote_fee") or 0)
        upfront = round(fee * 0.5, 2)

        wa_phone = whatsapp_service.normalize_phone(rec.get("phone", ""))
        if wa_phone:
            whatsapp_service.send_template(wa_phone, "payment_instructions",
                                           [rec.get("name", "there"), f"Plan {plan_id}", str(int(upfront)),
                                            Config.PAYMENT_UPI_ID])

        return jsonify({
            "success": True,
            "plan_id": plan_id,
            "fee_upfront": upfront,
            "payment_upi": Config.PAYMENT_UPI_ID,
            "message": f"Plan {plan_id} confirmed. Please pay ₹{upfront:.0f} to {Config.PAYMENT_UPI_ID}."
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- Filing Status ----------
@app.route("/api/status/<submission_id>")
def filing_status(submission_id):
    try:
        rec = sheets_service.check_approval(submission_id)
        if not rec:
            return jsonify({"success": False, "error": "Not found"}), 404

        approval = rec.get("approval_status", "PENDING")
        filing = rec.get("filing_status", "")
        payment = rec.get("payment_status", "")
        chosen = rec.get("user_chosen_option", "")

        filing_up = filing.upper()
        payment_up = payment.upper()

        if "FILED" in filing_up or "COMPLET" in filing_up:
            stage = "FILED"
        elif "FILING" in filing_up or "IN_PROGRESS" in filing_up:
            stage = "FILING"
        elif "FULL" in payment_up or "COMPLET" in payment_up:
            stage = "PAID_FULL"
        elif "PAID" in payment_up or "HALF" in payment_up:
            stage = "PAID_HALF"
        elif chosen:
            stage = "OPTION_CHOSEN"
        elif filing == "QUOTE_SENT":
            stage = "QUOTE_SENT"
        else:
            stage = "SUBMITTED"

        return jsonify({
            "success": True,
            "name": rec.get("name", ""),
            "submission_id": submission_id,
            "approval_status": approval,
            "filing_status": filing,
            "payment_status": payment,
            "user_chosen_option": chosen,
            "auditor_notes": rec.get("auditor_notes", ""),
                "stage": stage,
                # Include canonical calculation fields (if present in sheet) so frontend
                # can render canonical refund/plan amounts rather than client-side heuristics.
                "calculations": {
                    "taxable_new": _safe_float(rec.get("taxable_new")),
                    "total_tax_new": _safe_float(rec.get("total_tax_new")),
                    "refund_new": _safe_float(rec.get("refund_new")),
                    "taxable_old_a": _safe_float(rec.get("taxable_old_a")),
                    "total_tax_old_a": _safe_float(rec.get("total_tax_old_a")),
                    "refund_old_a": _safe_float(rec.get("refund_old_a")),
                    "variant_a_refund": _safe_float(rec.get("variant_a_refund")),
                    "variant_b_refund": _safe_float(rec.get("variant_b_refund")),
                    "variant_c_refund": _safe_float(rec.get("variant_c_refund")),
                    "variant_a_regime": (rec.get("variant_a_regime") or "")
                },
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/notify-referrals", methods=["POST"])
def notify_referrals():
    try:
        data = request.get_json(force=True)
        submission_id = data.get('submission_id')
        referrer_name = data.get('referrer_name') or 'Your friend'
        referral_code = data.get('referral_code') or ''

        # BACKEND VALIDATION: Handle referrals as string or list
        referrals_raw = data.get('referrals', [])
        if isinstance(referrals_raw, str):
            try:
                referrals = json.loads(referrals_raw)
            except:
                referrals = []
        else:
            referrals = referrals_raw if isinstance(referrals_raw, list) else []

        sent_count = 0
        for r in referrals:
            # VALIDATION: Ensure r is a dict with required fields
            if not isinstance(r, dict):
                continue

            phone_raw = r.get('phone', '').strip()
            name = (r.get('name', '') or '').strip()

            # VALIDATION: Skip empty entries
            if not phone_raw:
                continue

            # NORMALIZATION: Extract digits and validate
            phone_digits = ''.join(c for c in phone_raw if c.isdigit())

            # VALIDATION: Phone must be at least 10 digits
            if len(phone_digits) < 10:
                print(f"[NOTIFY] Skipping referral {name}: Invalid phone {phone_raw}")
                continue

            # Use last 10 digits for Indian phone numbers
            phone_normalized = phone_digits[-10:]
            wa_phone = whatsapp_service.normalize_phone(phone_normalized)

            # Try approved template first; fall back to plain text
            try:
                whatsapp_service.send_template(
                    wa_phone, 'referred_notification',
                    [referrer_name, referral_code or 'N/A']
                )
            except Exception:
                pass

            # Always send a detailed plain-text message
            msg = (
                f"Hi{(' ' + name) if name else ''}! You have been referred by {referrer_name} "
                f"to FairTax Advisors for hassle-free ITR filing.\n\n"
                f"Please fill in your details for smooth tax filing and get your quote in 24 hours.\n\n"
                f"Start here: https://fairtaxadvisors.in\n\n"
                f"Please don't forget your referral code: {referral_code}\n"
                f"Enter this code while submitting your application to unlock exclusive rewards.\n\n"
                f"— Team FairTax"
            )
            try:
                whatsapp_service.send_text(wa_phone, msg)
                sent_count += 1
            except Exception as e:
                logger.warning(f"[notify-referrals] Failed to send text to {wa_phone}: {e}")

        return jsonify({'success': True, 'sent': sent_count})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/winners')
def winners():
    # simple stubbed winners list for frontend widget
    return jsonify({
        'winners': [
            {'name': 'Asha R.', 'reward': '₹2,500'},
            {'name': 'Kumar S.', 'reward': 'Free Filing'},
            {'name': 'Ritu M.', 'reward': '₹1,000'}
        ]
    })


# ---------- Download ----------
@app.route("/api/download/<filename>")
def download_pdf(filename):
    return send_from_directory(".", filename, as_attachment=False)


# ---------- Wallet ----------
@app.route("/api/wallet/<referral_code>")
def wallet(referral_code):
    try:
        ws = sheets_service._sheet("Submissions")
        vals = ws.get_all_values()
        if len(vals) <= 1:
            return jsonify({"success": False, "error": "Not found"}), 404

        headers = vals[0]
        rec = None
        for row in vals[1:]:
            r = dict(zip(headers, row + [""] * (len(headers) - len(row))))
            if r.get("referral_code", "").upper() == referral_code.upper():
                rec = r
                break

        if not rec:
            return jsonify({"success": False, "error": "Referral code not found"}), 404

        # Count confirmed referrals from Referrals sheet
        try:
            rws = sheets_service._sheet("Referrals")
            rvals = rws.get_all_values()
            rcount = sum(
                1 for rv in rvals[1:]
                if len(rv) > 1 and rv[1].upper() == referral_code.upper()
            )
        except Exception:
            rcount = int(rec.get("referral_count") or 0)

        # Calculate earned amount based on milestone tiers
        if rcount >= 10:
            earned = 15000
        elif rcount >= 5:
            earned = 5000
        elif rcount >= 3:
            earned = 1000
        elif rcount >= 1:
            earned = 250 * rcount
        else:
            earned = 0

        # Honour manually set wallet_balance if auditor has overridden it
        manual_balance = rec.get("wallet_balance", "")
        if manual_balance:
            try:
                earned = float(manual_balance)
            except Exception:
                pass

        return jsonify({
            "success": True,
            "name": rec.get("name", ""),
            "referral_code": rec.get("referral_code", ""),
            "referral_count": rcount,
            "wallet_balance": earned,
            "upi_id": rec.get("upi_id", ""),
            "submission_id": rec.get("submission_id", "")
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/withdraw", methods=["POST"])
def withdraw():
    try:
        data = request.get_json(force=True)
        referral_code = data.get("referral_code", "")
        upi_id = data.get("upi_id", "")
        amount = float(data.get("amount") or 0)

        if not referral_code or not upi_id or amount <= 0:
            return jsonify({"success": False, "error": "referral_code, upi_id and amount required"}), 400

        # Log the withdrawal request in a Withdrawals sheet
        wws = sheets_service._sheet("Withdrawals")
        sheets_service._ensure_headers(wws, [
            "timestamp", "referral_code", "upi_id", "amount", "status"
        ])
        from datetime import datetime
        wws.append_row([datetime.now().isoformat(), referral_code, upi_id, amount, "PENDING"])

        # Notify via WhatsApp to admin number (same phone id)
        whatsapp_service.send_template(
            whatsapp_service.normalize_phone("917397510254"),
            "withdrawal_request",
            [referral_code, str(amount), upi_id]
        )

        return jsonify({
            "success": True,
            "message": f"Withdrawal request of ₹{amount:.0f} to {upi_id} logged. Processed every Thursday 3:30 PM."
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- Add Referral Friend ----------
@app.route("/api/add-referral", methods=["POST"])
def add_referral():
    try:
        data = request.get_json(force=True)
        referral_code = data.get("referral_code", "").strip()
        friend_name = (data.get("friend_name", "") or "").strip()
        friend_phone_raw = (data.get("friend_phone", "") or "").strip()

        # VALIDATION: Check required fields
        if not referral_code or not friend_name or not friend_phone_raw:
            return jsonify({"success": False, "error": "referral_code, friend_name, and friend_phone required"}), 400

        # VALIDATION: Phone format validation BEFORE normalization
        phone_digits = ''.join(c for c in friend_phone_raw if c.isdigit())
        if len(phone_digits) < 10:
            return jsonify({"success": False, "error": "Invalid phone number (must have at least 10 digits)"}), 400

        # NORMALIZATION: Use last 10 digits for Indian phone numbers
        friend_phone = phone_digits[-10:]

        # NORMALIZATION: Also normalize via whatsapp_service for consistency
        friend_phone = whatsapp_service.normalize_phone(friend_phone)
        if not friend_phone or len(friend_phone) < 10:
            return jsonify({"success": False, "error": "Invalid phone number"}), 400

        # Append to Referrals sheet
        rws = sheets_service._sheet("Referrals")
        sheets_service._ensure_headers(rws, [
            "timestamp", "referral_code", "friend_name", "friend_phone", "status", "confirmed_date"
        ])

        from datetime import datetime
        rws.append_row([
            datetime.now().isoformat(),
            referral_code.upper(),
            friend_name,
            friend_phone,
            "PENDING",
            ""
        ])

        # Send WhatsApp notification to friend
        try:
            referrer_name = ""
            # Find referrer name from Submissions sheet
            ws = sheets_service._sheet("Submissions")
            vals = ws.get_all_values()
            if len(vals) > 1:
                headers = vals[0]
                for row in vals[1:]:
                    r = dict(zip(headers, row + [""] * (len(headers) - len(row))))
                    if r.get("referral_code", "").upper() == referral_code.upper():
                        referrer_name = r.get("name", "")
                        break

            whatsapp_service.send_template(
                friend_phone,
                "referred_notification",
                [referrer_name or "Your friend", referral_code]
            )
        except Exception as e:
            print(f"[WARN] Could not send WhatsApp: {e}")

        return jsonify({
            "success": True,
            "message": f"Referral added for {friend_name}. Notification sent to +91{friend_phone[-10:]}."
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- Get Referral Status ----------
@app.route("/api/referral-status/<referral_code>")
def referral_status(referral_code):
    try:
        # Get all referrals for this code
        rws = sheets_service._sheet("Referrals")
        vals = rws.get_all_values()

        referrals = []
        if len(vals) > 1:
            headers = vals[0]
            for row in vals[1:]:
                r = dict(zip(headers, row + [""] * (len(headers) - len(row))))
                if r.get("referral_code", "").upper() == referral_code.upper():
                    referrals.append({
                        "name": r.get("friend_name", ""),
                        "phone": r.get("friend_phone", ""),
                        "status": r.get("status", "PENDING"),
                        "date_added": r.get("timestamp", ""),
                        "confirmed_date": r.get("confirmed_date", "")
                    })

        # Calculate milestones
        confirmed_count = sum(1 for ref in referrals if ref["status"].upper() == "CONFIRMED")

        milestones = {
            "current": confirmed_count,
            "next_milestone": None,
            "next_reward": None,
            "current_reward": None
        }

        if confirmed_count >= 10:
            milestones["current_reward"] = "₹15,000 (Maximum)"
        elif confirmed_count >= 5:
            milestones["current_reward"] = "₹5,000 + FREE Filing"
            milestones["next_milestone"] = 10
            milestones["next_reward"] = "₹15,000"
        elif confirmed_count >= 3:
            milestones["current_reward"] = "₹1,000"
            milestones["next_milestone"] = 5
            milestones["next_reward"] = "₹5,000 + FREE Filing"
        elif confirmed_count >= 1:
            milestones["current_reward"] = "₹250 × " + str(confirmed_count)
            milestones["next_milestone"] = 3
            milestones["next_reward"] = "₹1,000"
        else:
            milestones["next_milestone"] = 1
            milestones["next_reward"] = "₹250"

        return jsonify({
            "success": True,
            "referral_code": referral_code.upper(),
            "referrals": referrals,
            "milestones": milestones,
            "total_referrals": len(referrals),
            "confirmed_referrals": confirmed_count
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- Payment Collection ----------
@app.route("/api/payment-status/<submission_id>")
def payment_status(submission_id):
    try:
        row_idx = sheets_service.get_row_by_submission_id(submission_id)
        if not row_idx:
            return jsonify({"success": False, "error": "Submission not found"}), 404

        ws = sheets_service._sheet("Submissions")
        all_values = ws.get_all_values()
        if len(all_values) <= row_idx - 1:
            return jsonify({"success": False, "error": "Submission not found"}), 404

        headers = all_values[0]
        row_data = all_values[row_idx - 1]
        rec = dict(zip(headers, row_data + [""] * (len(headers) - len(row_data))))

        payment_status = rec.get("payment_status", "")
        payment_amount = rec.get("payment_amount", "0")
        payment_proof_url = rec.get("payment_proof_url", "")
        auditor_quote_fee = rec.get("auditor_quote_fee", "0")

        try:
            fee = float(auditor_quote_fee) if auditor_quote_fee else 0
            upfront = round(fee * 0.5, 2)
            balance_due = round(fee - upfront, 2)
        except:
            upfront = 0
            balance_due = 0

        return jsonify({
            "success": True,
            "submission_id": submission_id,
            "payment_status": payment_status,
            "payment_amount": float(payment_amount) if payment_amount else 0,
            "payment_proof_url": payment_proof_url,
            "total_fee": fee,
            "upfront_due": upfront,
            "balance_due": balance_due
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/upload-payment-proof", methods=["POST"])
def upload_payment_proof():
    try:
        submission_id = request.form.get("submission_id")
        files = request.files.getlist("proof")

        if not submission_id or not files:
            return jsonify({"success": False, "error": "submission_id and proof file required"}), 400

        urls = []
        for f in files:
            content = f.read()
            url = storage_service.save_file(f, submission_id)
            if url:
                urls.append(url)

        # Update payment status in sheets
        row = sheets_service.get_row_by_submission_id(submission_id)
        if row:
            sheets_service.update_row(row, {
                "payment_status": "PARTIAL",
                "payment_proof_url": urls[0] if urls else ""
            })

        # Send WhatsApp notification to admin
        rec = sheets_service.check_approval(submission_id)
        if rec:
            whatsapp_service.send_template(
                whatsapp_service.normalize_phone("917397510254"),
                "payment_proof_received",
                [rec.get("name", "User"), submission_id, urls[0] if urls else "No URL"]
            )

        return jsonify({
            "success": True,
            "message": "Payment proof uploaded. We'll verify and confirm within 24 hours.",
            "urls": urls
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- Filing Status Tracking ----------
@app.route("/api/filing-status/<submission_id>")
def filing_status_api(submission_id):
    try:
        rec = sheets_service.check_approval(submission_id)
        if not rec:
            return jsonify({"success": False, "error": "Submission not found"}), 404

        filing_status = rec.get("filing_status", "SUBMITTED")
        approval_status = rec.get("approval_status", "PENDING")
        payment_status = rec.get("payment_status", "PENDING")

        # Calculate stage
        stages = {
            "SUBMITTED": 10,
            "UNDER_REVIEW": 20,
            "APPROVED": 30,
            "PAYMENT_PENDING": 40,
            "PAYMENT_RECEIVED": 50,
            "FILING_IN_PROGRESS": 60,
            "FILED": 100
        }

        current_stage = filing_status.upper()
        stage_progress = stages.get(current_stage, 10)

        return jsonify({
            "success": True,
            "submission_id": submission_id,
            "filing_status": filing_status,
            "approval_status": approval_status,
            "payment_status": payment_status,
            "stage_progress": stage_progress,
            "timestamp": rec.get("timestamp", "")
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/update-filing-status", methods=["POST"])
def update_filing_status_api():
    try:
        data = request.get_json(force=True)
        submission_id = data.get("submission_id")
        new_status = data.get("filing_status")

        if not submission_id or not new_status:
            return jsonify({"success": False, "error": "submission_id and filing_status required"}), 400

        row = sheets_service.get_row_by_submission_id(submission_id)
        if not row:
            return jsonify({"success": False, "error": "Submission not found"}), 404

        # Update status
        sheets_service.update_row(row, {"filing_status": new_status})

        # Get updated record as dict
        updated_rec = sheets_service.check_approval(submission_id)

        # Send WhatsApp notification if filing is complete
        if updated_rec and ("FILED" in new_status.upper() or "COMPLETE" in new_status.upper()):
            wa_phone = whatsapp_service.normalize_phone(updated_rec.get("phone", ""))
            if wa_phone:
                whatsapp_service.send_template(
                    wa_phone,
                    "filing_completed",
                    [updated_rec.get("name", "there"), submission_id]
                )

        return jsonify({
            "success": True,
            "message": f"Filing status updated to {new_status}",
            "filing_status": new_status
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ---------- Scheduled Messages Setup ----------
def schedule_reminder_messages():
    """Send 3-day reminder messages to users who submitted but didn't pay"""
    try:
        from datetime import datetime, timedelta

        ws = sheets_service._sheet("Submissions")
        vals = ws.get_all_values()

        if len(vals) <= 1:
            return

        headers = vals[0]
        three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()

        for row in vals[1:]:
            rec = dict(zip(headers, row + [""] * (len(headers) - len(row))))

            # Check if submitted 3 days ago and payment not received
            timestamp = rec.get("timestamp", "")
            payment_status = rec.get("payment_status", "")
            phone = rec.get("phone", "")

            if timestamp < three_days_ago and payment_status != "PAID":
                wa_phone = whatsapp_service.normalize_phone(phone)
                if wa_phone:
                    try:
                        whatsapp_service.send_template(
                            wa_phone,
                            "payment_reminder",
                            [rec.get("name", "there"), rec.get("submission_id", "")]
                        )
                        print(f"[SCHEDULER] Sent 3-day reminder to {wa_phone}")
                    except Exception as e:
                        print(f"[SCHEDULER] Failed to send reminder: {e}")

    except Exception as e:
        print(f"[SCHEDULER] Error in schedule_reminder_messages: {e}")


def schedule_referral_status_updates():
    """Send referral status updates to referrers"""
    try:
        from datetime import datetime, timedelta

        ws = sheets_service._sheet("Submissions")
        vals = ws.get_all_values()

        if len(vals) <= 1:
            return

        headers = vals[0]

        for row in vals[1:]:
            rec = dict(zip(headers, row + [""] * (len(headers) - len(row))))

            referral_code = rec.get("referral_code", "")
            phone = rec.get("phone", "")
            referral_count = rec.get("referral_count", "0")

            if referral_code and phone:
                wa_phone = whatsapp_service.normalize_phone(phone)
                if wa_phone:
                    try:
                        # Get referral milestones
                        count = int(referral_count) if referral_count else 0
                        milestone_msg = ""

                        if count >= 10:
                            milestone_msg = "🌟 You've hit the LEGENDARY milestone! ₹15,000 earned!"
                        elif count >= 5:
                            milestone_msg = "🏆 5 referrals done! FREE filing + ₹5,000 cashback unlocked!"
                        elif count >= 3:
                            milestone_msg = "🎊 3 referrals! ₹1,000 cashback on the way."
                        elif count >= 1:
                            milestone_msg = f"🎉 {count} referral(s) done! Keep going for more rewards."

                        if milestone_msg:
                            whatsapp_service.send_template(
                                wa_phone,
                                "referral_update",
                                [rec.get("name", "there"), str(count), milestone_msg]
                            )
                            print(f"[SCHEDULER] Sent referral update to {wa_phone}")
                    except Exception as e:
                        print(f"[SCHEDULER] Failed to send referral update: {e}")

    except Exception as e:
        print(f"[SCHEDULER] Error in schedule_referral_status_updates: {e}")


# DIAGNOSTIC ENDPOINT - For debugging when tests fail
@app.route("/api/diagnostic", methods=["POST"])
def diagnostic():
    """Debug endpoint to test data flow and logging"""
    try:
        data = request.get_json(force=True) or {}

        # Log to both file and console
        logger.info(f"[DIAGNOSTIC] Received data: {data}")
        print(f"[DIAGNOSTIC] Print statement: {data}", flush=True)

        # Test Sheets access
        sheets_status = "OK" if sheets_service._client() else "NO CLIENT"
        logger.info(f"[DIAGNOSTIC] Sheets client: {sheets_status}")

        # Test data persistence
        test_id = data.get("submission_id", "diagnostic-test")
        result = sheets_service.insert_submission({
            "submission_id": test_id,
            "name": data.get("name", "Test"),
            "phone": data.get("phone", "0000000000")
        })
        logger.info(f"[DIAGNOSTIC] Insert result: {result}")

        # Check if data was saved
        row = sheets_service.get_row_by_submission_id(test_id)
        logger.info(f"[DIAGNOSTIC] Row lookup: {row}")

        return jsonify({
            "success": True,
            "diagnostic": {
                "sheets_client": sheets_status,
                "insert_result": result,
                "row_found": row is not None,
                "row_number": row
            },
            "message": "Check flask_app.log for detailed output"
        }), 200

    except Exception as e:
        logger.error(f"[DIAGNOSTIC] Error: {e}")
        logger.error(f"[DIAGNOSTIC] Traceback: {traceback.format_exc()}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":
    import os
    import sys
    # Force unbuffered output
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1, encoding='utf-8', errors='replace')
    sys.stderr = open(sys.stderr.fileno(), mode='w', buffering=1, encoding='utf-8', errors='replace')

    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(
        host="0.0.0.0",
        port=int(os.getenv('PORT', 5000)),
        debug=debug_mode,
        use_reloader=False,
        threaded=True
    )