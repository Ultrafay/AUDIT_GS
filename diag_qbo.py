
import os
from services.quickbooks import QuickBooksService
from dotenv import load_dotenv

load_dotenv()

print(f"QBO_REALM_ID: {os.getenv('QBO_REALM_ID')}")
print(f"AUTO_PUSH_TO_QBO: {os.getenv('AUTO_PUSH_TO_QBO')}")

try:
    qbo = QuickBooksService()
    print("QuickBooksService initialized successfully.")
    
    # Try a simple request
    print("Testing QBO API connectivity...")
    # Just query some vendors
    query = "SELECT * FROM Vendor MAXRESULTS 1"
    resp = qbo._request("GET", "query", params={"query": query})
    print(f"Status Code: {resp.status_code}")
    if resp.status_code == 200:
        print("API connectivity OK.")
    else:
        print(f"API Error: {resp.text}")

except Exception as e:
    print(f"Error: {e}")
