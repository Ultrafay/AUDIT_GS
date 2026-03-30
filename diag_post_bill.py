import json
import logging
from services.quickbooks import QuickBooksService

# Set up logging to stdout so we see the exact error
logging.basicConfig(level=logging.DEBUG)

qbo = QuickBooksService()

dummy_invoice = {
    "date": "2026-03-12",
    "supplier_name": "Test Diagnostics Vendor",
    "total_amount": 100.0,
    "currency": "USD",
    "line_items": [
        {"description": "Test item", "amount": 100.0}
    ]
}

print("Syncing dummy bill...")
try:
    status, bill_id = qbo.sync(dummy_invoice)
    print(f"Status: {status}, Bill ID: {bill_id}")
except Exception as e:
    print(f"Exception during sync: {e}")
