"""
VAT Processor — validates and finalises per-line tax codes before QBO
bill posting.

The AI extractor now assigns a `tax_code` (SR / EX / ZR / RC / IG) to each
line item.  This module:

  1. Determines the supplier location category (UAE / GCC / Foreign) from
     TRN + address — used as a safety net.
  2. Validates each line's `tax_code` against the location. If the code is
     missing or inconsistent, it assigns a sensible fallback and flags for
     review.
  3. Maps shorthand codes to the full QBO TaxCode names.
  4. Computes implied tax totals from per-line codes and compares them to
     the invoice-level `vat_amount`. Flags mismatches > threshold.
"""
import re
from typing import List

# ── Shorthand → full QBO TaxCode name ─────────────────────────────────────
TAX_CODE_MAP = {
    "SR": "SR Standard Rated",
    "EX": "EX Exempt",
    "ZR": "ZR Zero Rated",
    "RC": "RC Reverse Charge",
    "IG": "IG Intra GCC",
}

# Tax rates implied by each code (used for mismatch validation)
TAX_RATE_MAP = {
    "SR": 0.05,
    "EX": 0.0,
    "ZR": 0.0,
    "RC": 0.0,
    "IG": 0.0,
}

VALID_CODES = set(TAX_CODE_MAP.keys())

# Mismatch threshold (in invoice currency units)
_MISMATCH_THRESHOLD = 1.0

# ── Location keywords ─────────────────────────────────────────────────────
_UAE_KEYWORDS = [
    "uae", "united arab emirates",
    "dubai", "abu dhabi", "sharjah", "ajman",
    "fujairah", "ras al khaimah", "umm al quwain",
]
_GCC_KEYWORDS = [
    "saudi arabia", "ksa",
    "oman",
    "bahrain",
    "kuwait",
    "qatar",
]


def _is_uae_trn(trn: str) -> bool:
    if not trn:
        return False
    digits = re.sub(r"\D", "", str(trn))
    return len(digits) == 15 and digits.startswith("100")


def get_location_category(invoice_data: dict) -> str:
    """Returns 'UAE', 'GCC', or 'Foreign' based on TRN / address heuristics."""
    trn = str(invoice_data.get("supplier_trn", "") or "").strip()
    address = str(invoice_data.get("supplier_address", "") or "").strip().lower()

    if _is_uae_trn(trn):
        return "UAE"

    for kw in _UAE_KEYWORDS:
        if kw in address:
            return "UAE"

    for kw in _GCC_KEYWORDS:
        if kw in address:
            return "GCC"

    return "Foreign"


# ── Per-line validation helpers ───────────────────────────────────────────

def _valid_codes_for_location(category: str) -> set:
    """Return the set of tax codes that are valid for a given location."""
    if category == "UAE":
        return {"SR", "EX", "ZR"}
    elif category == "GCC":
        return {"IG"}
    else:  # Foreign
        return {"RC"}


def _fallback_code_for_location(category: str, tax_pct, has_invoice_vat: bool) -> str:
    """
    Pick a sensible fallback when the extractor didn't provide a tax_code
    or provided an invalid one.
    """
    if category == "GCC":
        return "IG"
    if category == "Foreign":
        return "RC"
    # UAE — use tax_percentage hint if available
    if tax_pct is not None:
        pct = float(tax_pct)
        if pct == 5.0:
            return "SR"
        if pct == 0.0:
            return "EX"
    # No percentage hint — guess from invoice-level VAT
    return "SR" if has_invoice_vat else "EX"


# ── Main entry point ─────────────────────────────────────────────────────

def process_vat(invoice_data: dict) -> dict:
    """
    Validate per-line tax codes, assign fallbacks where missing, map to
    full QBO names, and run tax-total mismatch check.
    """
    category = get_location_category(invoice_data)
    vat_amount = float(invoice_data.get("vat_amount", 0.0) or 0.0)
    line_items: List[dict] = invoice_data.get("line_items", []) or []
    has_invoice_vat = vat_amount > 0

    print(f"[VAT] Supplier Location: {category} — VAT: {vat_amount}, Lines: {len(line_items)}")

    invoice_data["supplier_location_category"] = category
    valid_codes = _valid_codes_for_location(category)
    review_messages: List[str] = []

    # ── Validate / assign per-line codes ──────────────────────────────────
    for idx, item in enumerate(line_items, start=1):
        raw_code = str(item.get("tax_code", "") or "").upper().strip()

        if raw_code in VALID_CODES:
            # Code is syntactically valid — check it fits the location
            if raw_code not in valid_codes:
                # Mismatch: e.g. extractor said "SR" for a Foreign vendor
                fallback = _fallback_code_for_location(
                    category, item.get("tax_percentage"), has_invoice_vat
                )
                review_messages.append(
                    f"Line {idx}: tax_code '{raw_code}' invalid for {category} vendor, "
                    f"overridden to '{fallback}'"
                )
                raw_code = fallback
        else:
            # Missing or unrecognised code — assign fallback
            fallback = _fallback_code_for_location(
                category, item.get("tax_percentage"), has_invoice_vat
            )
            if raw_code:
                review_messages.append(
                    f"Line {idx}: unrecognised tax_code '{raw_code}', "
                    f"defaulted to '{fallback}'"
                )
            raw_code = fallback

        # Write the validated shorthand back and the full QBO name
        item["tax_code"] = raw_code
        item["qbo_tax_code"] = TAX_CODE_MAP[raw_code]

    # ── Tax mismatch validation ───────────────────────────────────────────
    implied_tax = 0.0
    for item in line_items:
        item_amount = float(item.get("amount", 0.0) or 0.0)
        rate = TAX_RATE_MAP.get(item.get("tax_code", ""), 0.0)
        implied_tax += item_amount * rate

    implied_tax = round(implied_tax, 2)
    diff = abs(implied_tax - vat_amount)

    if diff > _MISMATCH_THRESHOLD:
        msg = (
            f"TAX MISMATCH: per-line implied tax = {implied_tax}, "
            f"invoice vat_amount = {vat_amount}, diff = {diff:.2f}"
        )
        review_messages.append(msg)
        print(f"[VAT] {msg}")

    # ── Assemble review memo ──────────────────────────────────────────────
    if review_messages:
        combined = " | ".join(review_messages)
        existing_memo = invoice_data.get("manual_review_memo", "") or ""
        invoice_data["manual_review_memo"] = (
            f"{existing_memo} | {combined}" if existing_memo else combined
        )
        print(f"[VAT] Review flagged: {combined}")

    # ── Metadata for downstream consumers ─────────────────────────────────
    invoice_data["line_items"] = line_items
    invoice_data["is_uae_invoice"] = (category == "UAE")

    # For GCC / Foreign, zero out vat_amount so QBO doesn't double-count
    if category in ("GCC", "Foreign"):
        invoice_data["vat_amount"] = 0.0

    return invoice_data
