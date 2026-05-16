"""
Example usage of the ITR Document Extractor.
Demonstrates how to process different document types.
"""

from itr_extractor import ITRDocumentProcessor
import json
import os


def example_single_document():
    """Example: Extract data from a single document."""
    print("=" * 80)
    print("EXAMPLE 1: Single Document Processing")
    print("=" * 80)

    # Initialize processor
    processor = ITRDocumentProcessor(use_ocr=True)

    # Example with a PDF file
    pdf_path = "./uploads/sample_form.pdf"  # Replace with actual file
    if os.path.exists(pdf_path):
        with open(pdf_path, 'rb') as f:
            file_bytes = f.read()

        result = processor.process_file(file_bytes, "sample_form.pdf")

        print("\n✓ Processing completed!")
        print(f"  Success: {result['success']}")
        print(f"  Errors: {result['errors']}")
        print("\nExtracted Data:")
        print(json.dumps(result['data'], indent=2))

        if result['errors']:
            print("\nValidation Errors:")
            print(json.dumps(result['errors'], indent=2))
    else:
        print(f"File not found: {pdf_path}")


def example_extract_personal_info():
    """Example: Extract specific personal information."""
    print("\n" + "=" * 80)
    print("EXAMPLE 2: Extract Personal Information")
    print("=" * 80)

    from itr_extractor import ITRExtractor

    sample_text = """
    Name: John Doe
    PAN: AAAPJ5055K
    Date of Birth: 15-06-1990
    Phone: +91 9876543210
    Email: john.doe@example.com
    Aadhaar: 1234 5678 9012
    """

    extractor = ITRExtractor()
    personal_info = extractor.extract_personal_info(sample_text)

    print("\nExtracted Personal Information:")
    print(json.dumps(personal_info, indent=2))


def example_extract_income():
    """Example: Extract income information."""
    print("\n" + "=" * 80)
    print("EXAMPLE 3: Extract Income Information")
    print("=" * 80)

    from itr_extractor import ITRExtractor

    sample_text = """
    Gross Salary: Rs. 12,50,000
    Basic Salary: Rs. 8,50,000
    HRA: Rs. 2,00,000
    Dearness Allowance: Rs. 1,00,000
    TDS Deducted: Rs. 1,87,500
    """

    extractor = ITRExtractor()
    income_info = extractor.extract_income(sample_text)

    print("\nExtracted Income Information:")
    print(json.dumps(income_info, indent=2, default=str))


def example_extract_deductions():
    """Example: Extract deduction information."""
    print("\n" + "=" * 80)
    print("EXAMPLE 4: Extract Deductions")
    print("=" * 80)

    from itr_extractor import ITRExtractor

    sample_text = """
    Section 80C: Rs. 1,50,000
    - PPF Contribution: Rs. 50,000
    - LIC Premium: Rs. 50,000
    - School Fees: Rs. 50,000

    Section 80D: Rs. 25,000
    - Health Insurance Premium: Rs. 25,000

    Section 80CCD(1B): Rs. 50,000
    - NPS Contribution: Rs. 50,000

    Home Loan Interest: Rs. 2,00,000
    """

    extractor = ITRExtractor()
    deductions = extractor.extract_deductions(sample_text)

    print("\nExtracted Deductions:")
    print(json.dumps(deductions, indent=2, default=str))


def example_validation():
    """Example: Validate extracted data."""
    print("\n" + "=" * 80)
    print("EXAMPLE 5: Validate Extracted Data")
    print("=" * 80)

    from itr_extractor import DataValidator

    test_data = {
        'personal': {
            'pan': 'AAAPJ5055K',
            'phone': '9876543210',
            'email': 'john@example.com',
        },
        'income': {
            'gross_salary': 1250000,
            'basic_salary': 850000,
            'hra': 200000,
            'tds_paid': 187500,
        },
        'deductions': {
            'section_80c': 150000,
            'section_80d': 25000,
            'section_80ccd': 50000,
            'home_loan_interest': 200000,
        },
        'employer': {},
        'financial': {},
    }

    validator = DataValidator()
    errors = validator.validate(test_data)

    print("\nValidation Result:")
    if errors:
        print("❌ Validation failed with errors:")
        print(json.dumps(errors, indent=2))
    else:
        print("✓ All data is valid!")


def example_batch_processing():
    """Example: Process multiple documents at once."""
    print("\n" + "=" * 80)
    print("EXAMPLE 6: Batch Processing Multiple Documents")
    print("=" * 80)

    processor = ITRDocumentProcessor(use_ocr=True)

    # Simulated batch processing
    files_to_process = [
        "./uploads/form_16.pdf",
        "./uploads/bank_statement.pdf",
        "./uploads/investment_proof.png",
    ]

    results = []
    for file_path in files_to_process:
        if os.path.exists(file_path):
            try:
                with open(file_path, 'rb') as f:
                    file_bytes = f.read()

                result = processor.process_file(file_bytes, os.path.basename(file_path))
                results.append({
                    'filename': os.path.basename(file_path),
                    'success': result['success'],
                    'errors': result['errors'],
                })
            except Exception as e:
                results.append({
                    'filename': os.path.basename(file_path),
                    'success': False,
                    'error': str(e),
                })

    print(f"\nProcessed {len(results)} documents:")
    for r in results:
        status = "✓" if r['success'] else "✗"
        print(f"  {status} {r['filename']}")
        if r.get('errors'):
            print(f"     Errors: {r['errors']}")


def example_pdf_table_extraction():
    """Example: Extract tables from PDF."""
    print("\n" + "=" * 80)
    print("EXAMPLE 7: Extract Tables from PDF")
    print("=" * 80)

    from itr_extractor import PDFTableExtractor

    pdf_path = "./uploads/sample_form.pdf"
    if os.path.exists(pdf_path):
        with open(pdf_path, 'rb') as f:
            file_bytes = f.read()

        tables = PDFTableExtractor.extract_tables(file_bytes)

        print(f"\nFound {len(tables)} tables in PDF")
        for i, table in enumerate(tables[:2]):  # Show first 2 tables
            print(f"\nTable {i + 1}:")
            print(f"  Dimensions: {len(table)} rows x {len(table[0]) if table else 0} columns")
            if table:
                print(f"  Headers: {table[0][:3]}...")  # Show first 3 columns
    else:
        print(f"File not found: {pdf_path}")


if __name__ == "__main__":
    print("\n\nITR DOCUMENT EXTRACTION - USAGE EXAMPLES")
    print("=" * 80)

    # Run examples
    try:
        example_extract_personal_info()
        example_extract_income()
        example_extract_deductions()
        example_validation()
        example_batch_processing()
        example_single_document()
        example_pdf_table_extraction()

    except Exception as e:
        print(f"\n❌ Error running examples: {e}")
        print("Make sure all dependencies are installed:")
        print("  pip install -r requirements.txt")

    print("\n" + "=" * 80)
    print("Examples completed!")
    print("=" * 80)
