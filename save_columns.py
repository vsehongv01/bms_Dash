import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os

SPREADSHEET_NAME = "BMS_Dashboard_Data"
CREDENTIALS_FILE = "credentials.json"

def save_columns():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        base_dir = os.path.dirname(os.path.abspath(__file__))
        credentials_path = os.path.join(base_dir, CREDENTIALS_FILE)
        
        creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SPREADSHEET_NAME).get_worksheet(0)
        
        data = sheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            with open("columns.txt", "w", encoding="utf-8") as f:
                for col in sorted(df.columns):
                    f.write(f"{col}\n")
            print("Columns saved to columns.txt")
        else:
            print("No data found.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    save_columns()
