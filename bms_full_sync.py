import requests
import sys
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta
import time
import os
import warnings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

warnings.simplefilter(action='ignore', category=FutureWarning)

# ==========================================
# [설정 구간]
# ==========================================
COOKIE = "connect.sid=s%3AUVy2iaeTlYD_7JsxXi0APfnYvsfuTC_T.%2BBpwa59U7ON9nBA%2F8x9yUcX7bOxIxpoW351Pe%2F54kgQ"
STORE_ID = 12

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TARGET_TABLE = "bms_orders"
# ==========================================

HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
COOKIES = {"connect.sid": COOKIE.split('=')[-1]}

def get_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=5,  # Maximum number of retries
        backoff_factor=1,  # Wait 1, 2, 4, 8, 16 seconds between retries
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(HEADERS)
    session.cookies.update(COOKIES)
    return session

def get_supabase_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_full_data(start_date):
    end_date = datetime.now().strftime("%Y-%m-%d")
    url_list = "https://bmsapi.breezm.com/order/list"
    payload = {"storeIds": [STORE_ID], "startDate": start_date, "endDate": end_date}
    
    print(f"🚀 {start_date} ~ {end_date} 전체 데이터 수집 시작...")
    
    session = get_session()
    
    try:
        res = session.post(url_list, json=payload, timeout=(10, 30))
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
            detail_res = session.get(f"https://bmsapi.breezm.com/order/{oid}/detail", timeout=(5, 15))
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

def sync_to_supabase(new_df):
    supabase = get_supabase_client()
    if not supabase:
        print("❌ Supabase 환경 변수가 설정되지 않았습니다.")
        return
        
    # 1. 리스트 및 딕셔너리 형태를 문자열로 변환하고 글자 수 제한(30,000자) 걸기
    def clean_cell(x):
        if isinstance(x, (list, dict)): val = str(x)
        else: val = x
        if isinstance(val, str) and len(val) > 30000:
            return val[:30000] + "...(중략)"
        return val

    for col in new_df.columns:
        new_df[col] = new_df[col].apply(clean_cell)

    # 2. 레코드 형태 변환 및 NaN/빈 문자열 처리
    import math
    records = new_df.to_dict('records')
    cleaned_records = []
    
    for row in records:
        # 1. 유령 행 제거: id나 code가 아예 없거나 빈 값이면 버림
        if 'id' not in row or 'code' not in row:
            continue
            
        r_id = row['id']
        r_code = row['code']
        if r_id is None or str(r_id).strip() == "" or str(r_id).strip().lower() == "nan":
            continue
        if r_code is None or str(r_code).strip() == "" or str(r_code).strip().lower() == "nan":
            continue
            
        clean_row = {}
        for k, v in row.items():
            if v is None or (isinstance(v, float) and math.isnan(v)):
                clean_row[k] = None
            elif isinstance(v, str) and (v.strip().lower() == "nan" or v == ""):
                clean_row[k] = None
            else:
                # 2. 소수점(.0) 제거 (Id가 포함된 컬럼이거나 실제 정수로 끝나는 숫자 값들)
                val_str = str(v)
                if val_str.endswith('.0') and val_str[:-2].isdigit():
                    clean_row[k] = val_str[:-2]
                else:
                    clean_row[k] = v
                    
        cleaned_records.append(clean_row)

    # 3. 데이터 분할 및 Upsert 전송
    import requests
    url = f"{SUPABASE_URL}/rest/v1/{TARGET_TABLE}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal, resolution=merge-duplicates"
    }

    try:
        print("\n🧹 Supabase에 데이터를 저장(Upsert)합니다...")
        
        chunk_size = 100
        total = len(cleaned_records)
        
        for i in range(0, total, chunk_size):
            chunk = cleaned_records[i : i + chunk_size]
            response = requests.post(url, headers=headers, json=chunk)
            if response.status_code in [200, 201, 204]:
                print(f"📦 {min(i + chunk_size, total)} / {total} 건 처리 완료")
            else:
                print(f"❌ Supabase 데이터 저장 중 오류 (HTTP {response.status_code}): {response.text}")
            time.sleep(0.5)
            
        print(f"\n✅ 동기화 완료! 총 {total}건의 데이터가 성공적으로 저장되었습니다.")
        
    except Exception as e:
        print(f"❌ Supabase 데이터 전송 오류 발생: {e}")


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
            sync_to_supabase(df)
            
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
            sync_to_supabase(df)