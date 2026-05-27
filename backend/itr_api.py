"""
Flask API endpoints for ITR document extraction.
Integrates with the ITR document processor.
"""

from flask import Blueprint, request, jsonify
from itr_extractor import ITRDocumentProcessor
import os
from datetime import datetime

itr_bp = Blueprint('itr', __name__, url_prefix='/api/itr')

# Initialize the processor
processor = ITRDocumentProcessor(use_ocr=True)

# DEBUG: Test endpoint to verify blueprint is working
@itr_bp.route('/test', methods=['GET'])
def test():
    from flask import current_app
    test_logger = current_app.logger
    test_logger.info("[TEST ENDPOINT] /api/itr/test endpoint called successfully")

    response_data = {
        'status': 'ITR Blueprint is active',
        'timestamp': str(__import__('datetime').datetime.now()),
        'message': 'If you see this, the Blueprint routing is working'
    }

    test_logger.info(f"[TEST ENDPOINT] Returning response: {response_data}")
    return jsonify(response_data), 200


@itr_bp.route('/extract', methods=['POST'])
def extract_itr_data():
    """
    Extract ITR data from uploaded document.

    Expects:
    - file: Document file (PDF or image)
    - doc_type: Optional document type (form16, payslip, homeloan, school, nps, insurance, donation)
               If not provided, defaults to form16

    Supported doc_types:
    - form16: Form 16 (salary document)
    - payslip: Payslip (monthly salary)
    - homeloan: Home Loan interest certificate
    - school: School fee receipt
    - nps: NPS statement
    - insurance: Insurance policy/premium receipt
    - donation: Donation receipt (80G)

    Returns:
    {
        'success': bool,
        'data': {...},
        'errors': {...},
        'confidence': float (0-1),
        'metadata': {...}
    }
    """
    import time
    import sys
    from flask import current_app

    start_time = time.time()

    # Use Flask logger for better capture
    logger = current_app.logger
    logger.info("[ITR_EXTRACT] REQUEST RECEIVED - Function called")
    print("[STDOUT] ITR_EXTRACT endpoint function called", file=sys.stdout, flush=True)

    try:
        # Check if file(s) are provided
        logger.info(f"[ITR_EXTRACT] Checking for file in request")
        file_keys = list(request.files.keys())
        logger.info(f"[ITR_EXTRACT] Request files: {file_keys}")

        if 'file' not in request.files:
            print("[ITR_EXTRACT] [ERROR] No 'file' in request.files")
            return jsonify({
                'success': False,
                'error': 'No file provided',
                'data': {},
            }), 400

        # Handle multiple files - get all files with key 'file'
        files = request.files.getlist('file')
        print(f"[ITR_EXTRACT] Files received: {len(files)} file(s)")

        if not files or all(f.filename == '' for f in files):
            print("[ITR_EXTRACT] [ERROR] No valid files selected")
            return jsonify({
                'success': False,
                'error': 'No file selected',
                'data': {},
            }), 400

        # Get document type from request (default to form16)
        doc_type = request.form.get('doc_type', 'form16').lower().strip()
        print(f"[ITR_EXTRACT] Document type: {doc_type}")

        # Validate doc_type
        supported_doc_types = {'form16', 'payslip', 'homeloan', 'school', 'nps', 'insurance', 'donation'}
        if doc_type not in supported_doc_types:
            return jsonify({
                'success': False,
                'error': f'Unsupported doc_type: {doc_type}. Supported: {", ".join(sorted(supported_doc_types))}',
                'data': {},
            }), 400

        # Process EACH file separately (not combined)
        all_results = []
        for file in files:
            if file.filename == '':
                continue

            # Validate file type
            allowed_extensions = {'pdf', 'jpg', 'jpeg', 'png', 'bmp', 'tiff'}
            if not any(file.filename.lower().endswith('.' + ext) for ext in allowed_extensions):
                continue

            # Read file bytes
            file_bytes = file.read()

            # Check file size (max 50MB)
            if len(file_bytes) > 50 * 1024 * 1024:
                print(f"[ITR_EXTRACT] File too large: {file.filename} ({len(file_bytes) / 1024 / 1024:.2f}MB)")
                all_results.append({
                    'success': False,
                    'error': 'File too large (max 50MB)',
                    'data': {},
                    'filename': file.filename
                })
                continue

            # Process document with specified doc_type (with timeout)
            try:
                file_start = time.time()
                result = processor.process_file(file_bytes, file.filename, doc_type=doc_type)
                file_elapsed = time.time() - file_start
                print(f"[ITR_EXTRACT] {file.filename}: {file_elapsed:.2f}s, success={result.get('success')}")
            except Exception as file_error:
                file_elapsed = time.time() - file_start
                print(f"[ITR_EXTRACT] {file.filename}: ERROR after {file_elapsed:.2f}s: {str(file_error)}")
                all_results.append({
                    'success': False,
                    'error': f'Processing error: {str(file_error)}',
                    'data': {},
                    'filename': file.filename
                })
                continue

            # AUTO-DETECTION: Only when confidence is very low AND document is small
            # (don't re-process large PDFs with every doc type — too expensive)
            conf = result.get("confidence", 0)
            pages = result.get("metadata", {}).get("pages_processed", 1)

            if conf < 0.3 and pages <= 10:
                print(f"[ITR_EXTRACT] Auto-detecting {file.filename}: confidence={conf}, pages={pages}")

                best_result = result
                best_confidence = conf
                best_doc_type = doc_type

                for test_type in ["form16", "payslip", "homeloan", "school", "nps", "insurance", "donation"]:
                    if test_type == doc_type:
                        continue
                    try:
                        test_result = processor.process_file(file_bytes, file.filename, doc_type=test_type)
                        test_confidence = test_result.get("confidence", 0)

                        print(f"[ITR_EXTRACT] {file.filename} as {test_type}: confidence={test_confidence}")

                        if test_confidence > best_confidence:
                            best_result = test_result
                            best_confidence = test_confidence
                            best_doc_type = test_type

                    except Exception as e:
                        print(f"[ITR_EXTRACT] Error trying {test_type} on {file.filename}: {str(e)}")
                        continue

                if best_doc_type != doc_type:
                    print(f"[ITR_EXTRACT] {file.filename} detected as: {best_doc_type} (confidence: {best_confidence})")
                    result = best_result
                    result["auto_detected_doc_type"] = best_doc_type

            all_results.append(result)

        # If no files were successfully processed
        if not all_results:
            return jsonify({
                'success': False,
                'error': 'No valid files could be processed',
                'data': {},
            }), 400

        # If only one file, return its result directly
        if len(all_results) == 1:
            result = all_results[0]
        else:
            # Multiple files: merge results
            print(f"[ITR_EXTRACT] Processing {len(all_results)} files, merging results...")
            merged_data = {}
            merged_confidence = 0
            merged_metadata = {'files_processed': len(all_results), 'individual_results': []}

            for idx, res in enumerate(all_results, 1):
                if res.get('success') and res.get('data'):
                    # Merge data from each file (later files override earlier ones for same fields)
                    merged_data.update(res.get('data', {}))
                    merged_confidence = max(merged_confidence, res.get('confidence', 0))
                    merged_metadata['individual_results'].append({
                        'file': idx,
                        'success': True,
                        'confidence': res.get('confidence', 0)
                    })
                else:
                    merged_metadata['individual_results'].append({
                        'file': idx,
                        'success': False,
                        'error': res.get('error', 'Unknown error')
                    })

            result = {
                'success': bool(merged_data),
                'data': merged_data,
                'confidence': merged_confidence,
                'metadata': merged_metadata
            }

        elapsed = time.time() - start_time
        if result['success']:
            logger.info(f"[ITR_EXTRACT] Success in {elapsed:.2f}s")
            response = jsonify(result)
            logger.info(f"[ITR_EXTRACT] Returning 200 response")
            return response, 200
        else:
            logger.error(f"[ITR_EXTRACT] Failed after {elapsed:.2f}s")
            logger.error(f"[ITR_EXTRACT] Result keys: {result.keys()}")
            logger.error(f"[ITR_EXTRACT] Error message: {result.get('error', 'Unknown error')}")

            response_dict = {
                'success': False,
                'error': result.get('error', 'Extraction failed - no valid data extracted'),
                'data': result.get('data', {}),
                'metadata': {**result.get('metadata', {}), 'elapsed_seconds': round(elapsed, 2)}
            }

            logger.error(f"[ITR_EXTRACT] Building 400 response")
            try:
                response = jsonify(response_dict)
                logger.error(f"[ITR_EXTRACT] Response created successfully, returning 400")
                return response, 400
            except Exception as e:
                logger.error(f"[ITR_EXTRACT] ERROR creating response: {str(e)}", exc_info=True)
                # Fallback minimal response
                return jsonify({'success': False, 'error': 'Response encoding error'}), 400

    except TimeoutError as e:
        elapsed = time.time() - start_time
        logger.error(f"[ITR_EXTRACT] TIMEOUT after {elapsed:.2f}s: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Extraction timeout - file took too long to process. Try a smaller file.',
            'data': {},
            'metadata': {'elapsed_seconds': round(elapsed, 2), 'error_type': 'timeout'}
        }), 408

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[ITR_EXTRACT] EXCEPTION after {elapsed:.2f}s: {str(e)}", exc_info=True)
        logger.error(f"[ITR_EXTRACT] Exception type: {type(e).__name__}")
        return jsonify({
            'success': False,
            'error': f'Extraction error: {str(e)}',
            'data': {},
            'metadata': {'elapsed_seconds': round(elapsed, 2), 'error_type': 'exception'}
        }), 500


@itr_bp.route('/extract-batch', methods=['POST'])
def extract_batch():
    """
    Extract ITR data from multiple documents.

    Expects:
    - files: Multiple document files

    Returns:
    {
        'success': bool,
        'results': [
            {
                'filename': str,
                'success': bool,
                'data': {...},
                'errors': {...}
            }
        ]
    }
    """
    try:
        if 'files' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No files provided',
                'results': [],
            }), 400

        files = request.files.getlist('files')

        if not files:
            return jsonify({
                'success': False,
                'error': 'No files selected',
                'results': [],
            }), 400

        results = []

        for file in files:
            try:
                file_bytes = file.read()
                result = processor.process_file(file_bytes, file.filename)
                results.append({
                    'filename': file.filename,
                    'success': result['success'],
                    'data': result['data'],
                    'errors': result.get('errors', {}),
                })
            except Exception as e:
                results.append({
                    'filename': file.filename,
                    'success': False,
                    'error': str(e),
                    'data': {},
                })

        all_success = all(r['success'] for r in results)

        return jsonify({
            'success': all_success,
            'results': results,
            'processed_count': len(results),
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'results': [],
        }), 500


@itr_bp.route('/validate', methods=['POST'])
def validate_data():
    """
    Validate extracted ITR data.

    Expects:
    {
        'personal': {...},
        'income': {...},
        'deductions': {...},
        'employer': {...},
        'financial': {...}
    }

    Returns:
    {
        'success': bool,
        'errors': {...}
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided',
                'errors': {},
            }), 400

        errors = processor.validator.validate(data)
        is_valid = len(errors) == 0

        return jsonify({
            'success': is_valid,
            'errors': errors,
            'validation_timestamp': datetime.now().isoformat(),
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'errors': {},
        }), 500


@itr_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'ocr_available': processor.use_ocr,
        'timestamp': datetime.now().isoformat(),
    }), 200
