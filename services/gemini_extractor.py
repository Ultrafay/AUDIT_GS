import google.generativeai as genai
import json
import base64
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
import os

class LineItem(BaseModel):
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    tax_percentage: Optional[float] = None  # 0, 5, or null
    tax_code: Optional[str] = None  # SR, EX, ZR, RC, IG
    gl_code: Optional[str] = None  # GL Account Name for this line

class InvoiceData(BaseModel):
    date: Optional[str] = None
    supplier_name: Optional[str] = None
    supplier_trn: Optional[str] = None
    supplier_address: Optional[str] = None
    invoice_number: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    credit_terms: Optional[str] = None
    bill_to: Optional[str] = None
    bill_to_trn: Optional[str] = None
    gl_code_suggested: Optional[str] = None
    exclusive_amount: Optional[float] = None
    vat_amount: Optional[float] = None
    invoice_tax_amount: Optional[float] = None  # Total tax from the invoice
    total_amount: Optional[float] = None
    currency: str = "AED"
    line_items: List[LineItem] = []
    extraction_confidence: str = "medium"
    extraction_method: str = "gemini_flash"
    notes: Optional[str] = None
    raw_response: Optional[str] = None

class GeminiExtractor:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Gemini API key is required")
        genai.configure(api_key=api_key)
        # Using 2.0 Flash as 1.5 was not found in available models
        self.model = genai.GenerativeModel('gemini-2.0-flash')
        
        self.prompt = """
        You are an expert invoice data extraction system for a UAE-based company.

        Analyze this invoice and extract ALL relevant data. The invoice may contain English, Arabic, or both languages.

        CRITICAL INSTRUCTIONS:
        1. For Arabic company names, provide both Arabic and English transliteration if visible
        2. All amounts must be numeric only (no currency symbols, no commas)
        3. Dates must be in YYYY-MM-DD format
        4. If a field is not visible or unclear, use null
        5. TRN (Tax Registration Number) in UAE is 15 digits starting with "100"
        6. Extract the supplier's full address as a single string.
        7. For EACH line item, extract the VAT/tax percentage applied (0, 5, or null if not shown).
        8. For EACH line item, assign a tax_code based on the TAX CODE CLASSIFICATION RULES below.

        IDENTIFY CORRECTLY:
        - SUPPLIER = The company SENDING the invoice (usually has logo at top, their bank details)
        - BILL TO = The company RECEIVING the invoice (Elegant Hoopoe or similar)
        - Don't confuse these two!

        TAX CODE CLASSIFICATION RULES:
        Assign one of these codes to EACH line item based on supplier location and item type:

          "SR" — Standard Rated (5% VAT). Normal taxable goods or services from a UAE-based supplier.
          "EX" — Exempt (0%). Government fees, visa charges, labour/immigration fees, fines,
                  bank charges, insurance premiums passed through at cost. Use for any
                  regulatory or government-imposed charge.
          "ZR" — Zero Rated (0%). Exports, international transport, certain education and
                  healthcare supplies. Rare on domestic purchase invoices.
          "RC" — Reverse Charge (0%). ANY supplier located OUTSIDE the UAE and outside the GCC.
          "IG" — Intra GCC (0%). Supplier is in a GCC country (Saudi Arabia, Bahrain, Oman,
                  Kuwait, Qatar) but NOT UAE VAT-registered.

        DECISION LOGIC:
          Step 1: Determine supplier location from their address and TRN.
            - If supplier has a UAE TRN (15 digits starting with 100) or address contains
              a UAE city/emirate → supplier is UAE-based → go to Step 2.
            - If supplier address mentions Saudi Arabia, Bahrain, Oman, Kuwait, or Qatar
              → use "IG" for ALL lines.
            - If supplier is outside UAE and outside GCC → use "RC" for ALL lines.
          Step 2 (UAE suppliers only): Classify EACH line individually.
            - Government/regulatory fees, visa fees, labour fees, fines, stamps,
              attestation charges, municipality fees, permit fees, typing fees,
              medical test fees (for visa), bank charges, insurance premiums
              passed at cost → "EX"
            - Normal taxable goods and services (consulting, supplies, equipment,
              maintenance, medical supplies, marketing, software, professional services)
              → "SR"
            - Exports, international freight/transport, certain education/healthcare
              supplies designated zero-rated → "ZR"
            - When unsure between "EX" and "ZR", default to "EX".
            - When unsure between "EX" and "SR", look at the tax column on the invoice:
              if the line shows 5% tax, use "SR"; if it shows 0% or no tax, use "EX".

        EXTRACT INTO THIS EXACT JSON STRUCTURE:

        {
          "date": "YYYY-MM-DD",
          "supplier_name": "Company issuing the invoice",
          "supplier_trn": "15-digit TRN of supplier or null",
          "supplier_address": "Full supplier address as a single string, or null",
          "invoice_number": "Invoice reference number",
          "description": "Brief summary of goods/services",
          "due_date": "YYYY-MM-DD or null",
          "credit_terms": "NET 30, Cheque, Immediate, etc.",
          "bill_to": "Customer name (usually Elegant Hoopoe)",
          "bill_to_trn": "TRN of customer if visible",
          "gl_code_suggested": "One of: Medical Supplies | Equipment | Marketing & Advertising | Professional Services | Government Fees | Office Supplies | Utilities | Other",
          "exclusive_amount": 0.00,
          "vat_amount": 0.00,
          "total_amount": 0.00,
          "currency": "AED",
          "line_items": [
            {
              "description": "Professional consulting service",
              "quantity": 1,
              "unit_price": 1000.00,
              "amount": 1000.00,
              "tax_percentage": 5,
              "tax_code": "SR"
            },
            {
              "description": "Government visa processing fee",
              "quantity": 1,
              "unit_price": 500.00,
              "amount": 500.00,
              "tax_percentage": 0,
              "tax_code": "EX"
            }
          ],
          "extraction_confidence": "high|medium|low",
          "notes": "Any issues or assumptions or irregularities found"
        }

        GL CODE GUIDANCE:
        - Medical Supplies: Drugs, syringes, Profhilo, medical consumables
        - Equipment: Massage beds, machines, furniture
        - Marketing & Advertising: Meta/Facebook, Google Ads, marketing agencies
        - Professional Services: Consultants, legal, accounting
        - Government Fees: Visas, licenses, document clearing (Al Enjaz type)
        - Office Supplies: Stationery, printing
        - Utilities: Electricity, water, internet

        IMPORTANT:
        - The 'amount' in line_items should be the line total BEFORE tax.
        - tax_percentage per line: use 5 for 5% VAT, 0 for zero-rated/exempt, null if not visible.
        - tax_code per line: MUST be one of SR, EX, ZR, RC, IG. Follow the classification rules above.

        Return ONLY valid JSON. No markdown, no explanation, no code blocks.
        """
    
    def _call_with_retry(self, file_path: str, display_name: str, max_retries: int = 3) -> InvoiceData:
        """Call Gemini with automatic retry on 429 rate limit errors."""
        import time
        
        for attempt in range(max_retries):
            try:
                sample_file = genai.upload_file(path=file_path, display_name=display_name)
                response = self.model.generate_content([sample_file, self.prompt])
                return self._parse_response(response.text)
            except Exception as e:
                error_str = str(e)
                if "429" in error_str and attempt < max_retries - 1:
                    wait_time = 15 * (attempt + 1)  # 15s, 30s, 45s
                    print(f"Rate limited (attempt {attempt+1}/{max_retries}). Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                print(f"Error extracting from {display_name}: {e}")
                raise e

    def extract_from_pdf(self, pdf_path: str) -> InvoiceData:
        """Extract invoice data directly from PDF (Gemini supports native PDF)"""
        return self._call_with_retry(pdf_path, "Invoice PDF")
    
    def extract_from_image(self, image_path: str) -> InvoiceData:
        """Extract invoice data from image file"""
        return self._call_with_retry(image_path, "Invoice Image")

            
    def _parse_response(self, response_text: str) -> InvoiceData:
        try:
            # Clean up markdown if present
            clean_text = response_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_text)
            
            # Validation via Pydantic
            invoice = InvoiceData(**data)
            invoice.raw_response = clean_text # Store raw for debugging if needed
            return invoice
        except Exception as e:
            print(f"Error parsing Gemini response: {e}")
            print(f"Raw response: {response_text}")
            # Return empty or partial object in real world, but for now raise
            raise ValueError("Failed to parse JSON from Gemini response")
