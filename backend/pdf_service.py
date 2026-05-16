from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.pagesizes import A4
from datetime import date as _date

# ── Brand palette ─────────────────────────────────────────────────────────────
_DARK    = HexColor('#0f172a')
_NAVY    = HexColor('#1e293b')
_BLUE    = HexColor('#1d4ed8')
_PURPLE  = HexColor('#6d28d9')
_AMBER   = HexColor('#b45309')
_GREEN   = HexColor('#15803d')
_SLATE   = HexColor('#64748b')
_LIGHT   = HexColor('#f1f5f9')
_BLUE_LT = HexColor('#dbeafe')
_GREEN_LT= HexColor('#dcfce7')
_AMBER_LT= HexColor('#fef3c7')


def _inr(n):
    try:
        v = float(str(n).replace(',', '').replace('₹', '') or 0)
        sign = '- ' if v < 0 else ''
        return f"{sign}Rs.{abs(int(round(v))):,}"
    except Exception:
        return 'Rs.0'


def _styles():
    base = getSampleStyleSheet()
    def S(name, **kw):
        return ParagraphStyle(name, parent=base['Normal'], **kw)

    return {
        'hdr_title': S('hdr_title', fontSize=22, fontName='Helvetica-Bold',
                       textColor=white, alignment=1, spaceAfter=2),
        'hdr_sub':   S('hdr_sub', fontSize=10, fontName='Helvetica',
                       textColor=HexColor('#bfdbfe'), alignment=1),
        'hdr_meta':  S('hdr_meta', fontSize=8, fontName='Helvetica',
                       textColor=HexColor('#94a3b8'), alignment=1, spaceBefore=2),
        'sec':       S('sec', fontSize=12, fontName='Helvetica-Bold',
                       textColor=_DARK, spaceBefore=14, spaceAfter=5),
        'normal':    S('normal', fontSize=9, fontName='Helvetica', textColor=_DARK),
        'bold':      S('bold', fontSize=9, fontName='Helvetica-Bold', textColor=_DARK),
        'small':     S('small', fontSize=8, fontName='Helvetica', textColor=_SLATE),
        'rec_h':     S('rec_h', fontSize=13, fontName='Helvetica-Bold',
                       textColor=white, alignment=1, spaceAfter=2),
        'rec_s':     S('rec_s', fontSize=10, fontName='Helvetica',
                       textColor=HexColor('#bbf7d0'), alignment=1),
        'footer':    S('footer', fontSize=7.5, fontName='Helvetica',
                       textColor=_SLATE, alignment=1, spaceBefore=6),
        'disclaimer':S('disclaimer', fontSize=7, fontName='Helvetica',
                       textColor=HexColor('#94a3b8'), alignment=1, leading=10),
    }


def _tbase(hdr_color, align_right_from=1):
    """Base TableStyle commands."""
    return [
        ('BACKGROUND', (0, 0), (-1, 0), hdr_color),
        ('TEXTCOLOR',  (0, 0), (-1, 0), white),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), 9),
        ('FONTNAME',   (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',   (0, 1), (-1, -1), 9),
        ('TEXTCOLOR',  (0, 1), (-1, -1), _DARK),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN',      (0, 1), (0, -1), 'LEFT'),
        ('ALIGN',      (align_right_from, 1), (-1, -1), 'RIGHT'),
        ('TOPPADDING',    (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING',   (0, 0), (-1, -1), 9),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, _LIGHT]),
        ('GRID',       (0, 0), (-1, -1), 0.25, HexColor('#e2e8f0')),
        ('LINEBELOW',  (0, 0), (-1, 0), 0.8, white),
    ]


def _banner(rows, bg, col_w='100%'):
    """Single-column full-width banner table."""
    t = Table(rows, colWidths=[col_w] if col_w == '100%' else col_w)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), bg),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING',   (0, 0), (-1, -1), 18),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 18),
    ]))
    return t


def generate_quote_pdf(data, filename="quote.pdf", password=None):
    st = _styles()
    doc = SimpleDocTemplate(
        filename, pagesize=A4,
        leftMargin=28, rightMargin=28, topMargin=28, bottomMargin=28
    )
    content = []
    P = lambda txt, s='normal': Paragraph(txt, st[s])
    sp = lambda h=8: Spacer(1, h)
    hr = lambda: HRFlowable(width='100%', thickness=0.4,
                             color=HexColor('#e2e8f0'), spaceAfter=4, spaceBefore=2)

    def n(k, default=0):
        try:
            return float(str(data.get(k) or default).replace(',', '').replace('Rs.', ''))
        except Exception:
            return float(default)

    def s(k, default='—'):
        v = data.get(k)
        return str(v) if v else default

    plans = data.get('plans', [])
    today = _date.today().strftime('%d %B %Y')
    ay = 'AY 2026-27'
    fee = n('auditor_quote_fee')
    upfront = round(fee * 0.5, 0)

    best_plan = max(plans, key=lambda p: float(p.get('refund', 0) or 0)) if plans else {}
    best_plan_id = best_plan.get('id', 'A')
    best_refund = best_plan.get('refund', n('variant_a_refund'))
    best_regime = best_plan.get('regime', s('variant_a_regime', 'NEW'))

    # ── HEADER ────────────────────────────────────────────────────────────────
    content.append(_banner([[P('FairTax Advisory Services', 'hdr_title')]], _DARK))

    content.append(_banner(
        [[P(f'Expert ITR Filing &amp; Tax Optimization  |  {ay}', 'hdr_sub')]],
        _DARK
    ))
    content.append(_banner(
        [[P(f'Report generated: {today}  |  Ref: {s("referral_code")}  |  ID: {s("submission_id")[:12]}', 'hdr_meta')]],
        _NAVY
    ))
    content.append(sp(14))

    # ── 1. CLIENT INFORMATION ─────────────────────────────────────────────────
    content.append(P('1.  CLIENT INFORMATION', 'sec'))
    content.append(hr())
    crows = [
        [P('Name', 'bold'),    P(s('name')),    P('PAN', 'bold'),   P(s('pan'))],
        [P('Phone', 'bold'),   P(s('phone')),   P('Email', 'bold'), P(s('email'))],
        [P('City Type', 'bold'), P(s('city_type').title() if s('city_type') != '—' else '—'),
         P('Assessment Year', 'bold'), P(ay)],
    ]
    tc = Table(crows, colWidths=[70, 170, 85, 170])
    tc.setStyle(TableStyle([
        ('FONTSIZE',      (0, 0), (-1, -1), 9),
        ('ROWBACKGROUNDS',(0, 0), (-1, -1), [_LIGHT, white]),
        ('GRID',          (0, 0), (-1, -1), 0.25, HexColor('#e2e8f0')),
        ('TOPPADDING',    (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING',   (0, 0), (-1, -1), 9),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 9),
    ]))
    content.extend([tc, sp(12)])

    # ── 2. INCOME SUMMARY ────────────────────────────────────────────────────
    content.append(P('2.  INCOME SUMMARY', 'sec'))
    content.append(hr())
    irows = [
        ['Income Component', 'Annual Amount'],
        ['Gross Salary / CTC', _inr(n('gross_salary'))],
        ['Basic Salary', _inr(n('basic_salary'))],
        ['HRA Received', _inr(n('hra_received'))],
        ['PF — Employee Contribution', _inr(n('pf_employee'))],
        ['TDS Deducted at Source', _inr(n('tds_paid'))],
        ['Home Loan Interest (Sec 24b)', _inr(n('home_loan_interest'))],
    ]
    ti = Table(irows, colWidths=[400, 95])
    ti.setStyle(TableStyle(_tbase(_BLUE)))
    content.extend([ti, sp(12)])

    # ── 3. DEDUCTIONS ────────────────────────────────────────────────────────
    content.append(P('3.  DEDUCTIONS CLAIMED', 'sec'))
    content.append(hr())
    drows = [
        ['Deduction Head', 'Amount'],
        ['Section 80C (PF + LIC + ELSS + School Fees)', _inr(n('sec_80c'))],
        ['Section 80D — Self &amp; Family Health Insurance', _inr(n('sec_80d'))],
        ['Section 80CCD(1B) — NPS Self Contribution', _inr(n('sec_80ccd_1b'))],
        ['Section 80CCD(2) — NPS Employer Contribution', _inr(n('sec_80ccd_2'))],
        ['Total Chapter VI-A Deductions', _inr(n('deductions_total'))],
    ]
    td = Table(drows, colWidths=[400, 95])
    dcmds = _tbase(_PURPLE)
    dcmds += [
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), _BLUE_LT),
        ('TEXTCOLOR',  (0, -1), (-1, -1), _BLUE),
        ('LINEABOVE',  (0, -1), (-1, -1), 0.8, _PURPLE),
    ]
    td.setStyle(TableStyle(dcmds))
    content.extend([td, sp(12)])

    # NOTE: Detailed tax computations (old/new regime comparisons) are intentionally omitted
    # from the client-facing PDF. Auditors can view the full calculations in the Google Sheet.

    # ── 5. FILING PLAN OPTIONS ────────────────────────────────────────────────
    content.append(P('5.  FILING PLAN OPTIONS', 'sec'))
    content.append(hr())

    plan_meta = {
        'A': ('Plan A — Conservative', 'Exact figures as declared. Zero risk, fully compliant.'),
        'B': ('Plan B — Optimised',    'Optimised LTA and allowance claims for higher refund.'),
        'C': ('Plan C — Maximum',      'Maximum legal deductions and allowances claimed.'),
    }
    plan_colors = {'A': _BLUE, 'B': _PURPLE, 'C': _AMBER}

    prows = [['Plan', 'Strategy', 'Regime', 'Estimated Refund']]
    for p in plans:
        pid = p.get('id', '')
        lbl, desc = plan_meta.get(pid, (p.get('label', ''), p.get('desc', '')))
        refund_val = p.get('refund', 0)
        # Ensure refund is a valid number
        try:
            refund_val = float(refund_val) if refund_val else 0
        except (ValueError, TypeError):
            refund_val = 0
        refund = _inr(refund_val)
        prows.append([lbl, desc, p.get('regime', ''), refund])

    tp = Table(prows, colWidths=[150, 260, 70, 95])
    pcmds = _tbase(_DARK)
    for i, p in enumerate(plans, start=1):
        col = plan_colors.get(p.get('id', 'A'), _BLUE)
        pcmds.append(('TEXTCOLOR', (0, i), (0, i), col))
        pcmds.append(('FONTNAME',  (0, i), (0, i), 'Helvetica-Bold'))
    tp.setStyle(TableStyle(pcmds))
    content.extend([tp, sp(12)])

    # ── 6. RECOMMENDATION ────────────────────────────────────────────────────
    rec_lbl, _ = plan_meta.get(best_plan_id, (f'Plan {best_plan_id}', ''))
    content.append(_banner([[P(f'OUR RECOMMENDATION: {rec_lbl}', 'rec_h')]], _GREEN))
    content.append(_banner([[P(f'Regime: <b>{best_regime}</b>', 'rec_s')]], HexColor('#166534')))
    content.append(_banner([[P('Detailed tax calculations are available to auditors in Google Sheets only.', 'small')]], _GREEN_LT))
    notes = s('auditor_notes', '')
    if notes and notes != '—':
        content.append(_banner(
            [[P(f'Expert Notes: {notes}', 'small')]],
            _GREEN_LT
        ))
    content.append(sp(12))

    # ── 7. FEE STRUCTURE ─────────────────────────────────────────────────────
    content.append(P('6.  FEE STRUCTURE', 'sec'))
    content.append(hr())
    frows = [
        ['Description', 'Amount'],
        ['Expert ITR Filing Fee', _inr(fee)],
        ['50% Upfront — Pay now to begin filing', _inr(upfront)],
        ['50% Balance — Due after refund is credited', _inr(fee - upfront)],
        ['Payment UPI / GPay ID', 'fairtaxadvisors@upi'],
    ]
    tf = Table(frows, colWidths=[400, 95])
    fcmds = _tbase(_AMBER)
    fcmds += [
        ('FONTNAME',   (0, 2), (-1, 2), 'Helvetica-Bold'),
        ('TEXTCOLOR',  (0, 2), (-1, 2), _GREEN),
        ('BACKGROUND', (0, 2), (-1, 2), _GREEN_LT),
    ]
    tf.setStyle(TableStyle(fcmds))
    content.extend([tf, sp(14)])

    # ── FOOTER ────────────────────────────────────────────────────────────────
    content.append(hr())
    content.append(P(
        'FairTax Advisory Services  |  fairtaxadvisors@gmail.com  |  +91 7397 510 254',
        'footer'
    ))
    content.append(sp(4))
    content.append(P(
        f'This Tax Planning Report is prepared for {s("name")} for {ay}. All figures are estimates based on '
        'documents provided and are subject to final verification. FairTax Advisory is not liable for any '
        'discrepancy in final tax computation. Please consult your assigned expert before filing. '
        'This document is confidential.',
        'disclaimer'
    ))

    doc.build(content)
    # If a password is provided, encrypt the generated PDF using PyPDF2.
    if password:
        try:
            from PyPDF2 import PdfReader, PdfWriter

            reader = PdfReader(filename)
            writer = PdfWriter()
            for p in reader.pages:
                writer.add_page(p)

            try:
                # PyPDF2 >= 3: encrypt(user_password, owner_password=None)
                writer.encrypt(password)
            except TypeError:
                # Fallback for older signatures
                writer.encrypt(user_pwd=password)

            with open(filename, "wb") as outf:
                writer.write(outf)
        except Exception as e:
            print("PDF encryption failed:", e)

    return filename
