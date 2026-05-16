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
    try:
        # Check if file(s) are provided
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file provided',
                'data': {},
            }), 400

        # Handle multiple files - get all files with key 'file'
        files = request.files.getlist('file')

        if not files or all(f.filename == '' for f in files):
            return jsonify({
                'success': False,
                'error': 'No file selected',
                'data': {},
            }), 400

        # Get document type from request (default to form16)
        doc_type = request.form.get('doc_type', 'form16').lower().strip()

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

            # Process document with specified doc_type
            result = processor.process_file(file_bytes, file.filename, doc_type=doc_type)

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

        return jsonify(result), 200 if result['success'] else 422

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'data': {},
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
