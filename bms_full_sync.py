import requests
import sys
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time
import os
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

# ==========================================
# [설정 구간]
# ==========================================
COOKIE = "connect.sid=s%3AUVy2iaeTlYD_7JsxXi0APfnYvsfuTC_T.%2BBpwa59U7ON9nBA%2F8x9yUcX7bOxIxpoW351Pe%2F54kgQ"
STORE_ID = 12
SPREADSHEET_NAME = "BMS_Dashboard_Data"
# ==========================================

HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
COOKIES = {"connect.sid": COOKIE.split('=')[-1]}

def get_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # 절대 경로로 credentials.json 위치 찾기 (FileNotFoundError 해결)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    credentials_path = os.path.join(base_dir, 'credentials.json')
    
    creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
    client = gspread.authorize(creds)
    return client.open(SPREADSHEET_NAME).get_worksheet(0)

def fetch_full_data(start_date):
    end_date = datetime.now().strftime("%Y-%m-%d")
    url_list = "https://bmsapi.breezm.com/order/list"
    payload = {"storeIds": [STORE_ID], "startDate": start_date, "endDate": end_date}
    
    print(f"🚀 {start_date} ~ {end_date} 전체 데이터 수집 시작...")
    try:
        res = requests.post(url_list, json=payload, headers=HEADERS, cookies=COOKIES)
        if res.status_code not in [200, 201]:
            print(f"❌ 목록 가져오기 실패 (Status: {res.status_code})")
            print(f"👉 쿠키가 만료되었거나 권한이 없을 수 있습니다. (Response: {res.text[:100]})")
            return pd.DataFrame()
        order_list = res.json()
    except Exception as e:
        print(f"❌ API 요청 중 치명적 오류 발생: {e}")
        return pd.DataFrame()
    
    all_rows = []
    total = len(order_list)
    
    for i, item in enumerate(order_list):
        oid = item['id']
        print(f"PROGRESS: {i+1}/{total}")
        print(f"[{i+1}/{total}] 모든 상세 정보 추출 중: {item['code']}")
        sys.stdout.flush()
        
        try:
            detail_res = requests.get(f"https://bmsapi.breezm.com/order/{oid}/detail", headers=HEADERS, cookies=COOKIES)
            if detail_res.status_code != 200:
                 print(f"⚠️ 상세 정보 가져오기 실패 ({oid}): {detail_res.status_code}")
                 continue
            d = detail_res.json()
            
            # [원래 의도 유지] json_normalize 사용하여 전체 데이터 플랫화
            flat_data = pd.json_normalize(d)
            all_rows.append(flat_data)
            
            time.sleep(0.05)
        except Exception as e:
            print(f"❌ {item['code']} 실패: {e}")
            
    # 빈 데이터프레임 제거 및 병합 (FutureWarning 해결)
    valid_rows = [df for df in all_rows if not df.empty]
    
    if not valid_rows:
        return pd.DataFrame()
        
    return pd.concat(valid_rows, ignore_index=True)

def sync_to_google(new_df):
    sheet = get_google_sheet()
    
    # 1. 리스트 및 딕셔너리 형태를 문자열로 변환하고 글자 수 제한(30,000자) 걸기
    def clean_cell(x):
        if isinstance(x, (list, dict)): val = str(x)
        else: val = x
        if isinstance(val, str) and len(val) > 30000:
            return val[:30000] + "...(중략)"
        return val

    # 모든 셀에 대해 클리닝 작업 수행
    for col in new_df.columns:
        new_df[col] = new_df[col].apply(clean_cell)

    # 2. NaN(빈값) 처리
    new_df = new_df.fillna("")
    
    # 3. 기존 데이터와 합치기
    try:
        rows = sheet.get_all_records()
        if rows:
            existing_df = pd.DataFrame(rows)
            # FutureWarning 방지: 데이터가 있는 것들만 합침. drop_duplicates는 code 기준
            combined_df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['code'], keep='last')
        else:
            combined_df = new_df
    except:
        combined_df = new_df

    combined_df = combined_df.fillna("")

    # 4. 데이터 전송 (분할 전송 적용)
    data_to_update = [combined_df.columns.values.tolist()] + combined_df.values.tolist()
    
    try:
        sheet.clear()
        print("\n🧹 구글 시트 초기화 완료. 너무 많은 데이터라 1000개씩 쪼개서 전송합니다...")
        
        # 헤더(첫 줄) 먼저 업데이트
        # gspread 버전에 따라 kwargs 호환성 고려
        sheet.update(values=[data_to_update[0]], range_name="A1")
        
        chunk_size = 1000 # 1000줄씩 쪼개기
        row_idx = 2       # 두 번째 줄부터 데이터 시작
        
        for i in range(1, len(data_to_update), chunk_size):
            chunk = data_to_update[i : i + chunk_size]
            start_cell = f"A{row_idx}"
            
            # gspread 버전에 상관없이 작동하도록 kwargs 사용
            sheet.update(values=chunk, range_name=start_cell)
            
            print(f"📦 {i} ~ {i + len(chunk) - 1}번째 줄 전송 완료")
            row_idx += len(chunk)
            
            # 구글 서버가 숨 쉴 틈(1.5초) 주기 (API 과부하 방지)
            time.sleep(1.5) 
            
        print(f"\n✅ 동기화 완료! 총 {len(combined_df)}건의 데이터가 성공적으로 저장되었습니다.")
        
    except Exception as e:
        print(f"❌ 시트 업데이트 중 오류 발생: {e}")


if __name__ == "__main__":
    # 명령행 인자가 있으면 자동 실행 (대시보드에서 호출용)
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        
        if mode == "1week":
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            print(f"🔄 최근 1주일 데이터 업데이트 시작 ({start_date} ~)")
        elif mode == "3months":
            start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
            print(f"🔄 최근 3개월 데이터 업데이트 시작 ({start_date} ~)")
        elif mode == "all":
            start_date = "2024-08-01"
            print(f"🔄 전체 데이터 업데이트 시작 ({start_date} ~)")
        else:
            print("❌ 잘못된 모드입니다. (1week, 3months, all 중 선택)")
            sys.exit(1)
            
        df = fetch_full_data(start_date)
        if not df.empty:
            sync_to_google(df)
            
    # 인자가 없으면 대화형 모드 (기존 방식)
    else:
        print("1. 최근데이터(3달) 2. 전체데이터(2024-08-01) 3. 최근 1주일")
        choice = input("선택: ")
        
        if choice == '1':
            start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        elif choice == '2':
            start = "2024-08-01"
        elif choice == '3':
            start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        else:
            print("잘못된 선택입니다.")
            sys.exit(1)
        
        df = fetch_full_data(start)
        if not df.empty:
            sync_to_google(df)