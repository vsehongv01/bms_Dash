import bms_new_dashboard
import time

start = time.time()
print("Testing bms_new_dashboard.load_data()...")
df = bms_new_dashboard.load_data()
print(f"Loaded {len(df)} rows in {time.time() - start:.2f} seconds")

import bms_as_dashboard
start = time.time()
print("Testing bms_as_dashboard.load_data()...")
df_as = bms_as_dashboard.load_data()
print(f"Loaded {len(df_as)} rows in {time.time() - start:.2f} seconds")

import bms_auto_order
start = time.time()
print("Testing bms_auto_order.load_data()...")
df_auto = bms_auto_order.load_data()
print(f"Loaded {len(df_auto)} rows in {time.time() - start:.2f} seconds")
