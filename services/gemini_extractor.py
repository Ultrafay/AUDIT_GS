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
    qbo_tax_code: Optional[str] = None  # Full QBO TaxCode name

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
    invoice_tax_percentage: Optional[float] = None  # Explicit tax percentage
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
        8. Assign tax codes (SR, EX, ZR, RC, IG) per line item based on the rules below.
        9. Assign GL categories per line item based on the keyword mapping provided.

        TAX CODE CLASSIFICATION RULES:
        Assign one of these codes to EACH line item based on supplier location and item type:

          "SR" — SR Standard Rated (5%). Normal taxable goods or services from a UAE-based supplier.
          "EX" — EX Exempt (0%). Government fees, visa charges, labour/immigration fees, fines,
                  bank charges, insurance premiums passed through at cost.
          "ZR" — ZR Zero Rated (0%). Exports, international transport, certain education/healthcare.
          "RC" — RC Reverse Charge (0%). ANY supplier located OUTSIDE the UAE and outside the GCC.
          "IG" — IG Intra GCC (0%). Supplier is in a GCC country but NOT UAE VAT-registered.

        DECISION LOGIC (UAE suppliers):
          - Government/regulatory/visa/labour fees, bank charges, at-cost insurance → "EX"
          - Commercial goods, consulting, maintenance, equipment, software, marketing → "SR"
          - If line shows 5% tax → "SR". If 0% or no tax → "EX".

        {gl_prompt}

        EXTRACT INTO THIS EXACT JSON STRUCTURE:
        {
          "date": "YYYY-MM-DD",
          "supplier_name": "Company issuing the invoice",
          "supplier_trn": "15-digit TRN or null",
          "supplier_address": "Full address string",
          "invoice_number": "Reference number",
          "due_date": "YYYY-MM-DD or null",
          "exclusive_amount": 0.00,
          "vat_amount": 0.00,
          "invoice_tax_amount": 0.00,
          "invoice_tax_percentage": null,
          "total_amount": 0.00,
          "currency": "AED (default to USD if unknown)",
          "line_items": [
            {
              "description": "Item description",
              "quantity": 1,
              "unit_price": 1000.00,
              "amount": 1000.00,
              "tax_percentage": 5,
              "tax_code": "SR",
              "gl_code": "Resolved GL Account Name"
            }
          ],
          "notes": "Any issues or assumptions"
        }

        Return ONLY valid JSON.
        """
    
    def set_chart_of_accounts(self, account_names: List[str]):
        """Store chart of accounts for prompt inclusion."""
        self.chart_of_accounts = account_names

    def _get_gl_prompt(self) -> str:
        """Build the GL keyword mapping section using gl_reference_data."""
        try:
            from services.gl_reference_data import build_gl_prompt_section
            return build_gl_prompt_section(getattr(self, "chart_of_accounts", []))
        except ImportError:
            return "Classify EACH line item using general accounting knowledge (COGS, Advertising, Legal, etc.)."

    def _call_with_retry(self, file_path: str, display_name: str, max_retries: int = 3) -> InvoiceData:
        """Call Gemini with automatic retry on 429 rate limit errors."""
        import time
        gl_prompt = self._get_gl_prompt()
        final_prompt = self.prompt.format(gl_prompt=gl_prompt)
        
        for attempt in range(max_retries):
            try:
                sample_file = genai.upload_file(path=file_path, display_name=display_name)
                response = self.model.generate_content([sample_file, final_prompt])
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
