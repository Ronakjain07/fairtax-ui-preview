"""
Central tax configuration for FY 2026-27 (AY 2027-28).

All slab definitions, standard deductions, rebate thresholds/caps,
cess and surcharge bands should be defined here so the rest of the
codebase uses a single source of truth.
"""

from math import inf

# Slab chunks are defined as (chunk_limit, rate). The engine will
# iterate these in order and apply the rate to each chunk.
SLABS = {
    # Old regime: 0 - 2.5L, 2.5L - 5L, 5L - 10L, >10L
    'OLD': [
        (250000, 0.0),
        (250000, 0.05),
        (500000, 0.20),
        (inf, 0.30),
    ],

    # New regime: 0 - 4L, 4L - 8L, 8L - 12L, 12L - 16L, 16L - 20L, 20L - 24L, >24L
    'NEW': [
        (400000, 0.0),
        (400000, 0.05),
        (400000, 0.10),
        (400000, 0.15),
        (400000, 0.20),
        (400000, 0.25),
        (inf, 0.30),
    ],
}

# Standard deductions by regime (annual)
STANDARD_DEDUCTION = {
    'OLD': 50000,
    'NEW': 75000,
}

# Health & Education cess applied AFTER tax (and surcharge if any)
# Keep as float for simple multiplication; callers may use Decimal if required.
CESS_RATE = 0.04

# Rebate configuration for Section 87A-like rebates. Each entry contains
# the income threshold under which the rebate is available and the maximum
# rebate cap to apply.
REBATE = {
    'OLD': {'threshold': 500000, 'cap': 12500},
    'NEW': {'threshold': 1200000, 'cap': 60000},
}

# Surcharge bands (optional): list of (threshold, surcharge_rate) ordered
# by ascending threshold. Empty by default; fill with FY 2026-27 bands when
# provided.
SURCHARGE_BANDS = [
    # FY 2026-27 surcharge bands (threshold is total income in INR):
    # 50 lakh -> 10%, 1 crore -> 15%, 2 crore -> 25%, 5 crore -> 37%
    (5000000, 0.10),
    (10000000, 0.15),
    (20000000, 0.25),
    (50000000, 0.37),
]

__all__ = [
    'SLABS', 'STANDARD_DEDUCTION', 'CESS_RATE', 'REBATE', 'SURCHARGE_BANDS'
]
