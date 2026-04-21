# Batch Excel Export Feature - Implementation Instructions

## Project Context
**AUDIT_GS** is a revenue audit OCR pipeline for an audit firm using the Solvevia platform. The system extracts structured data from Sales Orders (SO), Sales Invoices, and Goods Delivery Notes (GDN) using GPT-4o and writes it to Google Sheets.

## Objective
Implement a **Batch Excel Export** feature.
- **Input**: A mixed batch of documents (SO, Invoices, GDNs).
- **Output**: A single `.xlsx` file with three separate tabs, one for each document type, populated with the extracted data.
- **Status**: Standalone feature, parallel to the existing Google Sheets flow.

## Hard Constraints
- **NO MODIFICATIONS** to:
    - `ocr_engine.py`
    - `services/openai_extractor.py`
    - `services/sheets_service.py`
    - `workers/drive_processor.py`
- **NO MODIFICATIONS** to the existing `/api/extract/{doc_type}` endpoint in `app.py`.
- **MINIMAL EDIT** to `app.py`: Only register the new router.
- **REUSE**: Use existing `OpenAIExtractor.classify_document()` and `OpenAIExtractor.extract()`.
- **TEMPLATE**: Use `templates/revenue_audit_3tab.xlsx`. Load, fill, and return a copy (never modify on disk).

## Architecture
- `routers/batch.py` [NEW]: Endpoint `POST /api/batch/extract`.
- `services/excel_export_service.py` [NEW]: Logic for template loading and row writing.
- `templates/revenue_audit_3tab.xlsx` [NEW]: The Excel template file.
- `routers/__init__.py` [NEW]: Empty package init.
- `app.py` [EDIT]: Register the `batch` router.

## Implementation Flow
1. Accept `List[UploadFile]`.
2. Save to temporary files.
3. **Classify**: For each file, determine `doc_type` via `classify_document()`.
4. **Extract**: For each file, extract data via `extract(file_path, doc_type)`.
5. **Bucket**: Organize results into `sales_orders`, `invoices`, and `gdns`.
6. **Populate**: Pass lists to `excel_export_service.populate_template()`.
7. **Response**: Return as `StreamingResponse` (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`).
8. **Cleanup**: Always remove temp files in `finally` block.

## Field Mappings (Row 3 Onwards)

### Tab "Sales Order"
- **B**: `so_number`
- **C**: `customer_name` (fallback: first line item description)
- **D**: `total_quantity` (fallback: first line item quantity)
- **E**: first line item's `rate`
- **G**: `notes`
- *Note: Column F (Amount) is a formula; do not write.*

### Tab "Sales Invoice"
- **B**: `customer_name`
- **C**: `invoice_number`
- **D**: `invoice_date`
- **E**: `total_quantity` (fallback: first line item quantity)
- **F**: first line item's `rate`
- **H**: `total_amount`
- **J**: `notes`
- *Note: Column G (Formula Amount) and I (Difference) are formulas; do not write.*

### Tab "GDN"
- **B**: `customer_name`
- **C**: `delivered_date`
- **D**: `total_quantity_delivered` (fallback: first line item quantity)
- **E**: `gdn_reference`
- **F**: `notes`

## Style & Standards
- Python stdlib → 3rd party → local imports.
- `traceback.print_exc()` for errors; descriptive logs via `print`.
- Use `openpyxl` for Excel manipulation.
- Keep Pydantic models in `services/openai_extractor.py`.
- Handle `HTTPException` in routers; preserve plain exceptions in services.
