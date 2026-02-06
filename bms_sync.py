import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time

# ==========================================
# [설정 구간] - 본인의 정보로 수정하세요
# ==========================================
COOKIE = "connect.sid=s%3AUVy2iaeTlYD_7JsxXi0APfnYvsfuTC_T.%2BBpwa59U7ON9nBA%2F8x9yUcX7bOxIxpoW351Pe%2F54kgQ"
STORE_ID = 12
SPREADSHEET_NAME = "BMS_Dashboard_Data"  # 구글 시트 이름
# ==========================================

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
COOKIES = {"connect.sid": COOKIE.split('=')[-1]}

def get_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    return client.open(SPREADSHEET_NAME).get_worksheet(0)

def fetch_bms_data(start_date):
    end_date = datetime.now().strftime("%Y-%m-%d")
    url_list = "https://bmsapi.breezm.com/order/list"
    payload = {"storeIds": [STORE_ID], "startDate": start_date, "endDate": end_date}
    
    print(f"🚀 {start_date} ~ {end_date} 기간 데이터 요청 중...")
    res = requests.post(url_list, json=payload, headers=HEADERS, cookies=COOKIES)
    order_list = res.json()
    
    all_data = []  # <--- 이 부분 이름을 all_data로 수정했습니다!
    total = len(order_list)
    
    for i, item in enumerate(order_list):
        oid = item['id']
        code = item['code']
        print(f"[{i+1}/{total}] 상세 수집 중: {code}")
        
        try:
            # 상세 API 호출
            detail_res = requests.get(f"https://bmsapi.breezm.com/order/{oid}/detail", headers=HEADERS, cookies=COOKIES)
            d = detail_res.json()
            
            # 데이터 추출
            row = {
                "주문번호": d.get('code'),
                "고객명": d.get('customer', {}).get('name'),
                "현재상태": d.get('status'),
                "주문일": d.get('createdAt')[:10] if d.get('createdAt') else "",
                "담당자": d.get('statusDetail', {}).get('packageStaff'),
                "테모델": d.get('frame', {}).get('front'),
                "렌즈SKU": ", ".join(d.get('lens', {}).get('left', {}).get('skus', [])),
                "결제금액": d.get('paymentDetail', {}).get('finalPrice'),
                "배송메모": d.get('deliveryDetail', {}).get('memo', "").replace("\n", " ")
            }
            all_data.append(row) # 이제 바구니 이름이 일치해서 잘 담길 겁니다.
            time.sleep(0.1) 
        except Exception as e:
            print(f"❌ {code} 오류 발생: {e}")
            
    return pd.DataFrame(all_data)

def sync_to_google(new_df):
    sheet = get_google_sheet()
    rows = sheet.get_all_records()
    existing_df = pd.DataFrame(rows)
    
    if not existing_df.empty:
        # 기존 데이터와 새 데이터를 합치고 주문번호 기준 '마지막' 남기기
        combined_df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['주문번호'], keep='last')
    else:
        combined_df = new_df

    # [중요!] 비어있는 값(NaN)을 구글 시트가 인식할 수 있는 빈 문자열("")로 변환
    combined_df = combined_df.fillna("")

    # 주문일 기준 내림차순 정렬
    combined_df = combined_df.sort_values(by='주문일', ascending=False)
    
    # 시트 업데이트 (리스트 형식으로 변환하여 전송)
    data_to_update = [combined_df.columns.values.tolist()] + combined_df.values.tolist()
    
    sheet.clear()
    sheet.update(data_to_update)
    print(f"✅ 총 {len(combined_df)}건의 데이터가 구글 시트와 동기화되었습니다!")2

if __name__ == "__main__":
    print("=== BMS 데이터 동기화 프로그램 ===")
    print("1. 최근데이터갱신 (최근 3달)")
    print("2. 전체데이터갱신 (2024-08-01부터)")
    choice = input("원하는 작업 번호를 입력하세요: ")

    if choice == '1':
        start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        new_data = fetch_bms_data(start)
        sync_to_google(new_data)
    elif choice == '2':
        new_data = fetch_bms_data("2024-08-01")
        sync_to_google(new_data)
    else:
        print("잘못된 입력입니다.")