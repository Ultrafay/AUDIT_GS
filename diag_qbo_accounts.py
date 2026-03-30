import os
import json
from services.quickbooks import QuickBooksService

qbo = QuickBooksService()

output = {}

# 1. Query an existing Bill
resp = qbo._request("GET", "query", params={"query": "SELECT * FROM Bill MAXRESULTS 2"})
if resp.status_code == 200:
    output['Bills'] = resp.json().get("QueryResponse", {}).get("Bill", [])

# 2. Query Accounts
resp = qbo._request("GET", "query", params={"query": "SELECT * FROM Account WHERE AccountType = 'Expense' MAXRESULTS 5"})
if resp.status_code == 200:
    output['Accounts'] = resp.json().get("QueryResponse", {}).get("Account", [])

with open("qbo_diag_output.json", "w") as f:
    json.dump(output, f, indent=2)
