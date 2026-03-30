import json
from services.sheets_service import GoogleSheetsService
from utils.credentials_helper import get_credentials_path
import os
from dotenv import load_dotenv

load_dotenv()

sheets = GoogleSheetsService(
    credentials_path=get_credentials_path(),
    spreadsheet_id=os.getenv("GOOGLE_SHEET_ID")
)

invoices = sheets.get_invoices()
print("Total invoices in Sheets:", len(invoices))
print("\n--- Last 3 Invoices ---")
for inv in invoices[-3:]:
    print({
        "Date": inv.get("Date"),
        "Supplier": inv.get("Supplier Name"),
        "Invoice Number": inv.get("Invoice Number"),
        "QBO Status": inv.get("QBO Status"),
        "QBO Bill ID": inv.get("QBO Bill ID"),
        "Notes": inv.get("Notes")
    })
