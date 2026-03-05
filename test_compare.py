import os
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client, Client
import requests

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TARGET_TABLE = "bms_orders"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Fetch a row from Supabase
res = supabase.table(TARGET_TABLE).select("*").eq("id", "109538").execute()
if res.data:
    sb_row = res.data[0]
    print("Supabase row createdById:", sb_row.get('createdById'))
    print("Supabase row updatedById:", sb_row.get('updatedById'))

# Also fetch from API to see what the API returns
session = requests.Session()
login_payload = {} # I need to use the COOKIE from bms_full_sync.py
COOKIES = {
    "connect.sid": "s%3AUVy2iaeTlYD_7JsxXi0APfnYvsfuTC_T.%2BBpwa59U7ON9nBA%2F8x9yUcX7bOxIxpoW351Pe%2F54kgQ"
}
session.cookies.update(COOKIES)

detail_res = session.get(f"https://bmsapi.breezm.com/order/109538/detail")
if detail_res.status_code == 200:
    d = detail_res.json()
    flat = pd.json_normalize(d).to_dict('records')[0]
    print("API flat createdById:", flat.get('createdById'))
    print("API flat updatedById:", flat.get('updatedById'))
else:
    print("API fetch failed")
