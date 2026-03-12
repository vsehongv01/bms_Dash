import bms_auto_order
import time

start = time.time()
print("Starting load_data test with limit 50000...")
try:
    df = bms_auto_order.load_data()
    print(f"Loaded {len(df)} rows in {time.time() - start:.2f} seconds")
except Exception as e:
    print("Error:", e)
