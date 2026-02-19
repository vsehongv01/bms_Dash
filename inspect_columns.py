import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os

SPREADSHEET_NAME = "BMS_Dashboard_Data"
CREDENTIALS_FILE = "credentials.json"

def inspect_columns():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        base_dir = os.path.dirname(os.path.abspath(__file__))
        credentials_path = os.path.join(base_dir, CREDENTIALS_FILE)
        
        creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SPREADSHEET_NAME).get_worksheet(0)
        
        # Get all records
        data = sheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            print("First row data (non-empty columns):")
            first_row = df.iloc[0]
            for col, val in first_row.items():
                s_val = str(val)
                if s_val and s_val != "nan" and s_val != "":
                    # Print only if it might be relevant
                    lower_col = col.lower()
                    if any(k in lower_col for k in ['name', 'date', 'item', 'order', 'model', 'customer', 'code']):
                        print(f"{col}: {s_val[:100]}")

        else:
            print("No data found in sheet.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_columns()
