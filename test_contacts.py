import os
import sys
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
cols = 'id,"customer.contacts"'
# Fetch 5 rows
response = supabase.table('bms_orders').select(cols).order('id', desc=True).limit(5).execute()

data = response.data
for item in data:
    print(item)
    print(type(item.get('customer.contacts')))
