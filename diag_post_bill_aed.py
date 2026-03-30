import json
import logging
from services.quickbooks import QuickBooksService

logging.basicConfig(level=logging.DEBUG)

qbo = QuickBooksService()

dummy_invoice = {
    "date": "2026-03-12",
    "supplier_name": "Test Diagnostics Vendor AED",
    "total_amount": 105.0,
    "currency": "AED",
    "line_items": [
        {"description": "Test item", "amount": 105.0}
    ]
}

print("Syncing AED dummy bill with new amount...")
status, bill_id = qbo.sync(dummy_invoice)
print(f"Status: {status}, Bill ID: {bill_id}")
