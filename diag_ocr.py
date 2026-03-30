import os
from pathlib import Path
from utils.credentials_helper import get_credentials_path
from dotenv import load_dotenv, find_dotenv

# Force reload dotenv from scratch
load_dotenv(find_dotenv(), override=True)

import ocr_engine

print(f"Is QBO initialized in ocr_engine? {ocr_engine.qbo is not None}")

# Find any test invoice
test_img = Path("c:/Users/DELL/apps/Invoice_ocr/example/test_invoice.jpg")
if not test_img.exists():
    print("Test image not found, using whatever is in uploads/")
    uploads = list(Path("c:/Users/DELL/apps/Invoice_ocr/uploads").glob("*.*"))
    if uploads:
        test_img = uploads[-1]
    else:
        print("No image found to test")
        exit(1)

file_id = "test-qbo-sync-1234"
print(f"Processing {test_img} with file_id: {file_id}")

try:
    result = ocr_engine.process_invoice(test_img, file_id)
    print("FINISHED PROCESSING. Check Sheets and QBO.")
except Exception as e:
    import traceback
    traceback.print_exc()
