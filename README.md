# FairTax - Tax Filing & Referral Platform

A comprehensive tax filing and referral platform with AI-powered document processing, automated tax calculations, and WhatsApp integration.

## Overview

FairTax is an end-to-end solution for tax return processing, calculation, and management. The platform includes:

- **Document Processing**: AI-powered extraction from ITR forms and tax documents
- **Tax Calculation Engine**: Automated tax computation with detailed reporting
- **Referral System**: Built-in referral and affiliate management
- **WhatsApp Integration**: Direct communication channel for users
- **Cloud Storage**: Secure document management and storage
- **Google Sheets Integration**: Data synchronization and reporting

## Project Structure

```
fairtax/
├── backend/                    # Python backend services
│   ├── app.py                 # Main Flask application
│   ├── tax_engine.py          # Core tax calculation logic
│   ├── itr_extractor.py       # ITR document extraction
│   ├── ai_service.py          # AI/ML service integration
│   ├── pdf_service.py         # PDF processing
│   ├── whatsapp_service.py    # WhatsApp integration
│   ├── sheets_service.py      # Google Sheets API
│   ├── storage_service.py     # Cloud storage
│   ├── scheduler_service.py   # Task scheduling
│   ├── ocr_service.py         # OCR processing
│   ├── services/              # Additional service modules
│   │   ├── document_processor.py
│   │   ├── vision_extractor.py
│   │   ├── validation_service.py
│   │   ├── pdf_processor.py
│   │   ├── ai_provider.py
│   │   ├── doc_type_detector.py
│   │   ├── quality_checker.py
│   │   ├── file_handler.py
│   │   └── normalization_service.py
│   ├── uploads/               # User uploaded documents
│   └── requirements.txt        # Python dependencies
│
├── frontend/                   # Web frontend
│   ├── index.html             # Home page
│   ├── landing.html           # Landing page
│   ├── choice.html            # User choice page
│   ├── referral-filing.html   # Referral filing form
│   ├── referral-offer.html    # Referral offer page
│   ├── status.html            # Filing status tracker
│   ├── wallet.html            # Wallet management
│   ├── about.html
│   ├── contact.html
│   ├── faqs.html
│   ├── privacy-policy.html
│   ├── terms-of-service.html
│   ├── training.html
│   ├── app.js                 # Main frontend logic
│   ├── style.css              # Global styles
│   ├── components/            # Reusable HTML components
│   │   ├── header.html
│   │   └── footer.html
│   └── css/                   # Additional styles
│       └── shared-components.css
│
├── config.py                  # Configuration management
├── tax_config.py              # Tax-specific configuration
├── service_account.json       # Google Cloud credentials
├── run_production.bat          # Windows production runner
├── run_production.ps1          # PowerShell production runner
├── requirements.txt            # Dependencies
└── README.md                  # This file
```

## Features

### Backend Services

- **Tax Engine**: Calculates income tax, deductions, and filing status
- **Document Processing**: Extracts data from ITR forms using AI/ML and OCR
- **API Endpoints**: RESTful APIs for filing, status, referrals
- **WhatsApp Bot**: Automated user communication and updates
- **Cloud Integration**: Google Sheets and Cloud Storage support
- **Scheduling**: Automated task processing and notifications

### Frontend Interface

- **User Dashboard**: File status tracking and document management
- **Referral System**: User referral links and earnings tracking
- **Wallet**: Balance management and transaction history
- **Mobile Responsive**: Works on desktop and mobile devices
- **Educational Content**: FAQs, training, and documentation

## Setup & Installation

### Prerequisites

- Python 3.8+
- Node.js (optional, for frontend build tools)
- Google Cloud account with credentials
- WhatsApp Business API access (optional)

### Backend Setup

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   - Create `.env` file with necessary API keys and credentials
   - Update `config.py` and `tax_config.py` as needed

4. Set up Google Cloud credentials:
   ```bash
   # Place service_account.json in the backend directory
   ```

5. Run the application:
   ```bash
   python app.py
   ```

   Or use production runners:
   ```bash
   # Windows batch
   run_production.bat
   
   # PowerShell
   run_production.ps1
   ```

### Frontend Setup

The frontend is a static HTML/CSS/JS application. Serve files using:

```bash
# Python 3
python -m http.server 8000

# Or any HTTP server
http-server
```

Access at `http://localhost:8000`

## API Endpoints

Key endpoints (see `app.py` for full list):

- `POST /api/upload` - Upload tax documents
- `GET /api/status/<user_id>` - Get filing status
- `POST /api/calculate` - Trigger tax calculation
- `GET /api/referral/<code>` - Get referral details
- `POST /api/whatsapp/webhook` - WhatsApp webhook

## Configuration

### tax_config.py
Contains tax calculations, deduction rules, and rate tables.

### config.py
Database, API keys, and service credentials.

## Testing

Run tests with:

```bash
# Test tax engine
python -m pytest tests/

# Or individual test files
python test_tax_engine.py
python test_itr_extractor.py
```

## Deployment

### Production Deployment

1. Ensure `DEPLOYMENT_READY.txt` checklist is completed
2. Set all environment variables
3. Use production runners:
   ```bash
   run_production.bat (Windows)
   run_production.ps1 (PowerShell)
   ```

4. Verify with `verify_production.py`

### Cloud Deployment

Compatible with:
- Google Cloud Run
- AWS Lambda
- Heroku
- Azure Functions

## File Cleanup

Temporary/test files that can be removed:
- `test_*.py` files (after running tests)
- `uploads/` - old user upload directories
- `ocr_env_backup.env` - backup config
- `example_extraction.py` - reference code

## Documentation

- `CLIENT_DEMO_CHECKLIST.txt` - Demo preparation checklist
- `DEPLOYMENT_READY.txt` - Production deployment checklist
- `logic_comparison.md` - Algorithm documentation
- `TESTING_SUMMARY.txt` - Test coverage summary

## Support & Contact

See `contact.html` and `privacy-policy.html` for user support information.

## License

[Add your license information here]

## Contributors

[Add contributors here]

---

**Last Updated**: May 2026  
**Status**: Production Ready
