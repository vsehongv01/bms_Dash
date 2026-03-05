import os
from dotenv import load_dotenv
from supabase import create_client, Client
import time

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

COLS = [
    "id", "createdAt", "status", "code", "frameType", "lensType",
    '"statusDetail.lensStaff"', '"statusDetail.frameStaff"', 
    '"customer.name"', '"customer.contacts"',
    '"frame.size"', '"frame.color"', '"frame.front"', '"frame.temple_color"', '"frame.temple"',
    '"lens.left.skus"', '"lens.right.skus"',
    '"optometry.data.optimal.left.sph"', '"optometry.data.optimal.left.cyl"', '"optometry.data.optimal.left.axi"', '"optometry.data.optimal.left.add"', '"optometry.data.optimal.left.pd"',
    '"optometry.data.optimal.right.sph"', '"optometry.data.optimal.right.cyl"', '"optometry.data.optimal.right.axi"', '"optometry.data.optimal.right.add"', '"optometry.data.optimal.right.pd"',
    '"data.las.referenceId"', '"data.las.classification"', '"data.las.comment"',
    '"data.fas.referenceId"', '"data.fas.classification"', '"data.fas.comment"'
]
col_str = ",".join(COLS)

start = time.time()
try:
    print("Testing limit 50000...")
    res = supabase.table("bms_orders").select(col_str).order("createdAt", desc=True).limit(50000).execute()
    print(f"Fetched {len(res.data)} rows in {time.time() - start:.2f} seconds")
except Exception as e:
    print(f"Error after {time.time() - start:.2f} seconds:", type(e), e)
