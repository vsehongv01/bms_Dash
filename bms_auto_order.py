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

# [1. 설정 및 Supabase 연결]
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TARGET_TABLE = "bms_orders"
MAPPING_FILE = "lens_mapping.json"

def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def load_all_mappings():
    """매핑 데이터 로드 (JSON 파일 기반)"""
    try:
        if os.path.exists(MAPPING_FILE):
            with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"로드 실패 디버그: {e}")
        return {}

def save_to_server(sku_str, custom_name):
    """서버에 매핑 저장 (JSON 파일 기반)"""
    try:
        mappings = load_all_mappings()
        if not isinstance(mappings, dict):
            mappings = {}
            
        mappings[sku_str] = custom_name
        
        with open(MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(mappings, f, ensure_ascii=False, indent=4)
            
        # 디버깅용 터미널 로그 출력
        print(f"매핑 저장 완료: {sku_str} -> {custom_name}")
        return True
    except Exception as e:
        st.error(f"저장 중 오류 발생: {e}")
        print(f"상세 에러 로그: {e}")
        return False

@st.cache_data(ttl=601)
def load_data(target_date_str):
    try:
        supabase = get_supabase()
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

# [2. 제품명 유추 로직]
def get_lens_display_name(sku_list, all_mappings):
    sku_str = str(sku_list)
    if sku_str in all_mappings:
        return all_mappings[sku_str]
    
    s_lower = sku_str.lower()
    idx = "1.74" if "1.74" in s_lower else ("1.67" if "1.67" in s_lower else ("1.60" if "1.60" in s_lower else "1.56"))
    design = "D-FREE 양면비구면" if "ssp-dfree" in s_lower else "ASP 비구면"
    
    if "chemi-disc-varsity" in s_lower:
        color = "Gray" if "gray" in s_lower else ("Brown" if "brown" in s_lower else "")
        return f"{idx} {design} 변색 {color}".strip()
    
    coating = "퍼펙트 UV" if "bl-perfect" in s_lower else ("발수" if "uv-ush" in s_lower else "")
    return f"{idx} {design} {coating}".strip()

# [3. 케미 발주 양식 정리]
def execute_chemi_order(selected_rows):
    if selected_rows.empty:
        st.warning("항목을 선택해주세요.")
        return

    all_mappings = load_all_mappings()
    orders_by_lens = {}
    
    for _, row in selected_rows.iterrows():
        for side, dosu in [('L렌즈', 'L도수 (SPH/CYL/AXIS)'), ('R렌즈', 'R도수 (SPH/CYL/AXIS)')]:
            sku_val = row.get(side, '')
            if pd.isna(sku_val) or str(sku_val).strip() in ['', 'nan', 'None']: continue
            try: sku_list = ast.literal_eval(str(sku_val)) if isinstance(sku_val, str) else sku_val
            except: sku_list = [str(sku_val)]
            
            lens_key = str(sku_list)
            if lens_key not in orders_by_lens:
                orders_by_lens[lens_key] = {"sku_list": sku_list, "dosu_map": {}}
            
            parts = str(row.get(dosu, "")).split('/')
            if len(parts) >= 2:
                sph, cyl = parts[0].strip(), parts[1].strip()
                k = f"{sph}" if cyl in ['0', '0.00', '0.0', 'None', '', 'nan'] else f"{sph}/{cyl}"
                if sph not in ['None', 'nan', '']:
                    orders_by_lens[lens_key]["dosu_map"][k] = orders_by_lens[lens_key]["dosu_map"].get(k, 0) + 1

    st.subheader("제품 명칭 확인 및 서버 저장")
    for l_key, l_data in orders_by_lens.items():
        current_name = get_lens_display_name(l_data["sku_list"], all_mappings)
        col1, col2 = st.columns([4, 1])
        new_name = col1.text_input(f"SKU: {l_key}", value=current_name, key=f"in_{l_key}")
        
        if col2.button("서버 저장", key=f"sv_{l_key}"):
            if save_to_server(l_key, new_name):
                st.success(f"서버에 성공적으로 기록되었습니다: {new_name}")
                # 업데이트 이후 세션 상태를 강제로 다시 로드하도록 처리하거나
                # 다시 렌더링되게 만들 수 있습니다. st.rerun()을 하지 않으면
                # 화면에서 즉시 바뀌지 않으므로, toast 메시지를 씁니다.
                st.toast(f"'{new_name}' 저장 완료! 페이지 전환 시 반영됩니다.", icon='✅')

    msg_lines = [f"[케미 여벌 발주 요청] - {datetime.now().strftime('%m/%d %H:%M')}", "--------------------"]
    final_mappings = load_all_mappings()
    for l_key, l_data in orders_by_lens.items():
        p_name = get_lens_display_name(l_data["sku_list"], final_mappings)
        msg_lines.append(f"제품: {p_name}")
        for d, q in l_data["dosu_map"].items():
            msg_lines.append(f" - {d} : {q}짝")
        msg_lines.append("") 

    st.divider()
    st.code("\n".join(msg_lines), language="text")

# [나머지 공통 UI 로직]
def extract_lens_info(sku_str):
    try:
        s_list = ast.literal_eval(sku_str) if isinstance(sku_str, str) else sku_str
        if isinstance(s_list, list) and len(s_list) > 0:
            parts = str(s_list[0]).split('-')
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
        if l_cat in ['ss', 'ssp'] or r_cat in ['ss', 'ssp']:
            brand = {"chemi": "케미", "zeiss": "자이스", "nikon": "니콘"}.get(l_brand or r_brand, "기타")
            if brand not in grouped: grouped[brand] = []
            grouped[brand].append({
                "선택": False, "주문번호": row.get('code', ''), "이름": row.get('customer.name', ''),
                "L렌즈": row.get('lens.left.skus', ''), "R렌즈": row.get('lens.right.skus', ''),
                "L도수 (SPH/CYL/AXIS)": f"{row.get('optometry.data.optimal.left.sph','')} / {row.get('optometry.data.optimal.left.cyl','')}",
                "R도수 (SPH/CYL/AXIS)": f"{row.get('optometry.data.optimal.right.sph','')} / {row.get('optometry.data.optimal.right.cyl','')}"
            })
    return grouped

def main():
    st.title("🤖 여벌렌즈 자동 발주 시스템")
    date = st.date_input("날짜 선택", value=datetime.now(pytz.timezone('Asia/Seoul')))
    if st.button("데이터 조회", type="primary"):
        data = load_data(date.strftime('%Y-%m-%d'))
        st.session_state['grouped_data'] = get_stock_orders_by_date(data, date.strftime('%Y-%m-%d'))
    
    if 'grouped_data' in st.session_state:
        tabs = st.tabs(list(st.session_state['grouped_data'].keys()))
        for tab, brand in zip(tabs, st.session_state['grouped_data'].keys()):
            with tab:
                df = pd.DataFrame(st.session_state['grouped_data'][brand])
                edited = st.data_editor(df, width="stretch", column_config={"선택": st.column_config.CheckboxColumn(default=False)}, hide_index=True, key=f"ed_{brand}")
                sel = edited[edited["선택"] == True]
                
                # 케미 렌즈 탭일 경우, 저장 버튼 문제(Nested Button)를 해결하기 위해 Session State 사용
                if brand == "케미":
                    if st.button(f"케미 발주 양식 생성 ({len(sel)}건)", key="btn_chemi_gen"):
                        st.session_state['show_chemi'] = True
                
                if brand == "케미" and st.session_state.get('show_chemi', False):
                    execute_chemi_order(sel)

if __name__ == "__main__":
    main()