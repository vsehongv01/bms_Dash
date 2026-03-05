import sys
import asyncio
import subprocess
import json
import os
import streamlit as st
import pandas as pd
import ast
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

# Windows 루프 정책 설정
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

st.set_page_config(layout="wide")

# [1. 설정 및 데이터 로드]
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TARGET_TABLE = "bms_orders"

@st.cache_data(ttl=601)
def load_data(target_date_str):
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        COLS = ["id", "createdAt", "status", "code", '"customer.name"', '"lens.left.skus"', '"lens.right.skus"',
                '"optometry.data.optimal.left.sph"', '"optometry.data.optimal.left.cyl"',
                '"optometry.data.optimal.right.sph"', '"optometry.data.optimal.right.cyl"']
        target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
        start_utc = (target_dt - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
        end_utc = (target_dt + timedelta(days=1)).strftime("%Y-%m-%dT23:59:59Z")
        response = supabase.table(TARGET_TABLE).select(",".join(COLS)).gte("createdAt", start_utc).lte("createdAt", end_utc).execute()
        return pd.DataFrame(response.data) if response.data else pd.DataFrame()
    except Exception as e:
        st.error(f"데이터 로드 오류: {e}")
        return pd.DataFrame()

# [2. 자동 주문 실행 로직 - 선택 데이터 합산 강화]
def execute_nikon_order(selected_rows):
    if selected_rows.empty:
        st.warning("주문할 항목을 선택해주세요.")
        return

    # 렌즈 종류별로 데이터를 모으는 저장소
    # { "렌즈SKU문자열": {"lens_info": 리스트, "orders_map": {(sph, cyl): 합산수량}} }
    orders_by_lens = {}

    for _, row in selected_rows.iterrows():
        # 왼쪽(L)과 오른쪽(R) 각각 검사하여 합산
        for side_sku, side_dosu in [('L렌즈', 'L도수 (SPH/CYL/AXIS)'), ('R렌즈', 'R도수 (SPH/CYL/AXIS)')]:
            sku_val = row.get(side_sku, '')
            if pd.isna(sku_val) or str(sku_val).strip() in ['', 'nan', 'None']:
                continue
                
            try:
                # 문자열 리스트를 실제 객체로 변환
                sku_list = ast.literal_eval(str(sku_val)) if isinstance(sku_val, str) else sku_val
            except:
                sku_list = [str(sku_val)]
                
            # 렌즈 구성을 고유 키로 생성
            lens_key = str(sku_list)
            
            if lens_key not in orders_by_lens:
                orders_by_lens[lens_key] = {"lens_info": sku_list, "orders_map": {}}
            
            # 도수 추출 및 합산
            dosu_parts = str(row.get(side_dosu, "")).split('/')
            if len(dosu_parts) >= 2:
                sph = dosu_parts[0].strip()
                cyl = dosu_parts[1].strip()
                if sph not in ['None', 'nan', '', '0', '0.0', '0.00']:
                    k = (sph, cyl)
                    # 동일 도수가 이미 있다면 수량 +1, 없으면 1로 시작
                    orders_by_lens[lens_key]["orders_map"][k] = orders_by_lens[lens_key]["orders_map"].get(k, 0) + 1

    # 최종 전송 데이터 구성 (중복 없이 제품별 1개씩)
    payload = []
    for lens_data in orders_by_lens.values():
        if not lens_data["orders_map"]: continue
        
        payload.append({
            "lens_info": lens_data["lens_info"],
            "orders": [{"sph": k[0], "cyl": k[1], "qty": v} for k, v in lens_data["orders_map"].items()]
        })

    if not payload:
        st.warning("합산된 유효 주문 데이터가 없습니다.")
        return
        
    # 가공된 리스트를 JSON 저장
    with open("temp_order.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    with st.status("[INFO] 동일 제품 합산 완료. 자동 주문을 시작합니다...", expanded=True):
        try:
            flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x10) if sys.platform == 'win32' else 0
            subprocess.Popen([sys.executable, "essilor_auto.py", "temp_order.json"], creationflags=flags)
            st.success("에실로 자동화 창이 실행되었습니다. 제품별 일괄 입력 후 장바구니에 담깁니다.")
        except Exception as e:
            st.error(f"실행 실패: {e}")

# [3. UI 및 필터링 로직]
def extract_lens_info(sku_str):
    try:
        s_list = ast.literal_eval(sku_str) if isinstance(sku_str, str) else sku_str
        if isinstance(s_list, list) and len(s_list) > 0:
            parts = str(s_list[0]).split('-')
            # RX(주문형) 제품 제외 필터
            if len(parts) >= 3 and 'rx' in parts[2].lower(): return None, None
            if len(parts) >= 2: return parts[0].lower(), parts[1].lower()
    except: pass
    return None, None

def get_stock_orders_by_date(df, target_date_str):
    if df.empty: return {}
    kst = pytz.timezone('Asia/Seoul')
    df['date_only'] = pd.to_datetime(df['createdAt'], utc=True).dt.tz_convert(kst).dt.strftime('%Y-%m-%d')
    df_target = df[df['date_only'] == target_date_str].copy()
    
    grouped = {}
    for _, row in df_target.iterrows():
        l_brand, l_cat = extract_lens_info(row.get('lens.left.skus', ''))
        r_brand, r_cat = extract_lens_info(row.get('lens.right.skus', ''))
        
        # 여벌 렌즈(ss, ssp)만 그룹화
        if l_cat in ['ss', 'ssp'] or r_cat in ['ss', 'ssp']:
            brand = {"chemi": "케미", "zeiss": "자이스", "nikon": "니콘"}.get(l_brand or r_brand, "기타")
            if brand not in grouped: grouped[brand] = []
            grouped[brand].append({
                "선택": False,
                "주문번호": row.get('code', ''),
                "이름": row.get('customer.name', ''),
                "L렌즈": row.get('lens.left.skus', ''),
                "R렌즈": row.get('lens.right.skus', ''),
                "L도수 (SPH/CYL/AXIS)": f"{row.get('optometry.data.optimal.left.sph','')} / {row.get('optometry.data.optimal.left.cyl','')}",
                "R도수 (SPH/CYL/AXIS)": f"{row.get('optometry.data.optimal.right.sph','')} / {row.get('optometry.data.optimal.right.cyl','')}"
            })
    return grouped

def main():
    st.title("🤖 여벌렌즈 자동 발주 시스템")
    date = st.date_input("📅 발주 날짜 선택", value=datetime.now(pytz.timezone('Asia/Seoul')))
    
    if st.button("🚀 데이터 조회", type="primary", use_container_width=True):
        data = load_data(date.strftime('%Y-%m-%d'))
        st.session_state['grouped_data'] = get_stock_orders_by_date(data, date.strftime('%Y-%m-%d'))
    
    if 'grouped_data' in st.session_state and st.session_state['grouped_data']:
        tabs = st.tabs(list(st.session_state['grouped_data'].keys()))
        for tab, brand in zip(tabs, st.session_state['grouped_data'].keys()):
            with tab:
                df_display = pd.DataFrame(st.session_state['grouped_data'][brand])
                edited = st.data_editor(df_display, width="stretch", column_config={"선택": st.column_config.CheckboxColumn(default=False)}, hide_index=True, key=f"ed_{brand}")
                
                sel = edited[edited["선택"] == True]
                if brand == "니콘" and st.button(f"🔵 에실로(니콘) 자동 합산 주문 ({len(sel)}건)"):
                    execute_nikon_order(sel)

if __name__ == "__main__":
    main()