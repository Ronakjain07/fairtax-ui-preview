from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from config import Config
import ai_service, tax_engine, sheets_service, storage_service, whatsapp_service
import base64, traceback, os, requests as _requests, logging
from pdf_service import generate_quote_pdf
from services import document_processor, quality_checker, doc_type_detector
import uuid

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)
logger = logging.getLogger(__name__)
app = Flask(__name__)
app.secret_key = Config.FLASK_SECRET
CORS(app)
from itr_api import itr_bp
app.register_blueprint(itr_bp)


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

try:
    from scheduler_service import start_scheduler
    _scheduler = start_scheduler()
except Exception as _e:
    print(f"[Scheduler] Could not start: {_e}")

@app.route("/api/health")
def health():
    return {"status": "ok"}


# ---------- Phase-by-phase save ----------
@app.route("/api/save-phase", methods=["POST"])
def save_phase():
    try:
        data = request.get_json(force=True)

        # ── LOCAL DEV MODE: skip all Sheets ops when credentials aren't configured ──
        _sa = getattr(Config, 'SERVICE_ACCOUNT_JSON', None)
        _sheets_configured = bool(
            getattr(Config, 'GOOGLE_SHEET_ID', None) and
            _sa and _sa != 'service_account.json'
        )
        if not _sheets_configured:
            submission_id = data.get('submission_id') or str(uuid.uuid4())
            print(f"[SAVE_PHASE][LOCAL] Sheets not configured — returning mock success. submission_id={submission_id}")
            return jsonify({"success": True, "submission_id": submission_id, "referral_code": ""})

        # Ensure a referral code exists early so we can return it to the UI
        # even if Sheets writes are delayed or fail. Use sheets_service helper.
        try:
            if not data.get('referral_code'):
                data['referral_code'] = sheets_service.gen_referral_code(data.get('name'))
        except Exception:
            # Non-fatal: if gen_referral_code unavailable, leave blank and continue
            pass

        # Compatibility normalizations: frontend uses `filing_type`, backend/sheets expect `filing_category`.
        if data.get('filing_type') and not data.get('filing_category'):
            data['filing_category'] = data.get('filing_type')

        submission_id = data.get("submission_id")

        # Enforce filing_category only for NEW submissions (when no submission_id exists)
        # For updates to existing submissions, filing_category is optional
        if not submission_id:
            if not data.get('filing_category') or data.get('filing_category') not in ('regular', 'free'):
                return jsonify({"success": False, "error": "Please select filing type: 'regular' or 'free' before continuing."}), 400

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
@app.route("/api/submit", methods=["POST"])
def submit():
    try:
        data = request.get_json(force=True)

        submission_id = data.get("submission_id")
        if not submission_id:
            return jsonify({"success": False, "error": "submission_id required"}), 400

        row = sheets_service.get_row_by_submission_id(submission_id)
        # If row missing, create it so updates and calculations persist
        if row is None:
            try:
                sheets_service.insert_submission({"submission_id": submission_id, **data})
                row = sheets_service.get_row_by_submission_id(submission_id)
            except Exception:
                row = None

        # ✅ save final data
        sheets_service.update_row(row, data)

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

        sheets_service.save_calculation_by_row(row, calc)

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
        referrer_name = data.get("referrer_name", "") or data.get("name", "")
        for i in range(1, 6):
            ref_name = data.get(f"ref_name_{i}", "").strip()
            ref_phone = data.get(f"ref_phone_{i}", "").strip()
            if ref_name and ref_phone:
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

        return jsonify({
            "success": True,
            "submission_id": submission_id,
            "referral_code": ref_code,
            "message": "Submitted! You'll receive your quote on WhatsApp within 24 hours."
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


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
        referrals = data.get('referrals', [])

        sent_count = 0
        for r in referrals:
            phone = r.get('phone')
            name = r.get('name', '')
            if not phone:
                continue
            wa_phone = whatsapp_service.normalize_phone(phone)

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
        referral_code = data.get("referral_code", "")
        friend_name = data.get("friend_name", "")
        friend_phone = data.get("friend_phone", "")

        if not referral_code or not friend_name or not friend_phone:
            return jsonify({"success": False, "error": "referral_code, friend_name, and friend_phone required"}), 400

        # Normalize phone
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


if __name__ == "__main__":
    import os
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host="0.0.0.0", port=int(os.getenv('PORT', 5000)), debug=debug_mode)