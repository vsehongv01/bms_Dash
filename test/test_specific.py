import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TARGET_TABLE = "bms_orders"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

res = supabase.table(TARGET_TABLE).select("id, code, createdById, createdName, updatedById, updatedName").eq("code", "DT-2508-0251").execute()
if res.data:
    print("Record DT-2508-0251 in Supabase:")
    print(res.data[0])
else:
    print("Record not found in Supabase.")
