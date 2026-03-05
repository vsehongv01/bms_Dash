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

# [1. 설정 및 데이터 연결]
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TARGET_TABLE = "bms_orders"
MAPPING_FILE = "lens_mapping.json"

def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def load_all_mappings():
    try:
        if os.path.exists(MAPPING_FILE):
            with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"로드 실패 디버그: {e}")
        return {}

def save_to_server(sku_str, custom_name):
    try:
        mappings = load_all_mappings()
        if not isinstance(mappings, dict): mappings = {}
        mappings[sku_str] = custom_name
        with open(MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(mappings, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        st.error(f"저장 중 오류 발생: {e}")
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
    if sku_str in all_mappings: return all_mappings[sku_str]
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
            if lens_key not in orders_by_lens: orders_by_lens[lens_key] = {"sku_list": sku_list, "dosu_map": {}}
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
                st.success(f"저장 완료: {new_name}")
                st.toast(f"저장 완료!", icon='✅')

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

# [4. 자이스/니콘 자동 주문 로직 (이름 포함 로직으로 수정됨!)]
def execute_auto_order(selected_rows, brand_name):
    if selected_rows.empty:
        st.warning("항목을 선택해주세요.")
        return
        
    orders_by_lens = {}
    
    for _, row in selected_rows.iterrows():
        customer_name = str(row.get('이름', '')).strip() # 테이블에서 고객 이름 추출
        
        for side, dosu in [('L렌즈', 'L도수 (SPH/CYL/AXIS)'), ('R렌즈', 'R도수 (SPH/CYL/AXIS)')]:
            sku_val = row.get(side, '')
            if pd.isna(sku_val) or str(sku_val).strip() in ['', 'nan', 'None']: continue
            
            try: sku_list = ast.literal_eval(str(sku_val)) if isinstance(sku_val, str) else sku_val
            except: sku_list = [str(sku_val)]
            
            lens_key = str(sku_list)
            if lens_key not in orders_by_lens: 
                orders_by_lens[lens_key] = {"lens_info": sku_list, "orders_map": {}}
                
            dosu_parts = str(row.get(dosu, "")).split('/')
            if len(dosu_parts) >= 2:
                sph, cyl = dosu_parts[0].strip(), dosu_parts[1].strip()
                if sph not in ['None', 'nan', '', '0', '0.00']:
                    k = (sph, cyl)
                    
                    # 도수 키(k)가 없으면 초기화 (수량 0, 이름 리스트 빈 배열)
                    if k not in orders_by_lens[lens_key]["orders_map"]:
                        orders_by_lens[lens_key]["orders_map"][k] = {"qty": 0, "names": []}
                    
                    # 수량 증가 및 고객 이름 추가 (중복 방지)
                    orders_by_lens[lens_key]["orders_map"][k]["qty"] += 1
                    if customer_name and customer_name not in orders_by_lens[lens_key]["orders_map"][k]["names"]:
                        orders_by_lens[lens_key]["orders_map"][k]["names"].append(customer_name)
    
    payload = []
    for d in orders_by_lens.values():
        if not d["orders_map"]: continue
        
        # 이름 배열을 콤마(,)로 연결해서 하나의 문자열로 변환 (예: "홍길동, 김철수")
        orders_list = []
        for k, v in d["orders_map"].items():
            combined_names = ", ".join(v["names"])
            orders_list.append({"sph": k[0], "cyl": k[1], "qty": v["qty"], "names": combined_names})
            
        payload.append({"lens_info": d["lens_info"], "orders": orders_list})

    if not payload:
        st.warning("합산된 유효 데이터가 없습니다.")
        return

    script_name = "zeiss_auto.py" if brand_name == "자이스" else "essilor_auto.py"
    temp_file = "temp_order_zeiss.json" if brand_name == "자이스" else "temp_order.json"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    with st.status(f"[INFO] {brand_name} 자동 주문 시작...", expanded=True):
        try:
            flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x10) if sys.platform == 'win32' else 0
            subprocess.Popen([sys.executable, script_name, temp_file], creationflags=flags)
            st.success(f"{brand_name} 자동화 실행됨")
        except Exception as e:
            st.error(f"실행 실패: {e}")

# [5. 필터링 로직]
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
    
    if st.button("🚀 데이터 조회", type="primary"):
        data = load_data(date.strftime('%Y-%m-%d'))
        st.session_state['grouped_data'] = get_stock_orders_by_date(data, date.strftime('%Y-%m-%d'))
    
    if 'grouped_data' in st.session_state and st.session_state['grouped_data']:
        brand_list = list(st.session_state['grouped_data'].keys())
        tabs = st.tabs(brand_list)
        
        for tab, brand in zip(tabs, brand_list):
            with tab:
                df = pd.DataFrame(st.session_state['grouped_data'][brand])
                edited = st.data_editor(df, width="stretch", column_config={"선택": st.column_config.CheckboxColumn(default=False)}, hide_index=True, key=f"ed_{brand}")
                sel = edited[edited["선택"] == True]
                
                if brand == "케미":
                    if st.button(f"케미 양식 생성 ({len(sel)}건)", key="btn_chemi"):
                        st.session_state['show_chemi'] = True
                    if st.session_state.get('show_chemi', False): execute_chemi_order(sel)
                elif brand == "자이스":
                    if st.button(f"⚪ 자이스 주문 시작 ({len(sel)}건)", key="btn_zeiss"): execute_auto_order(sel, "자이스")
                elif brand == "니콘":
                    if st.button(f"🔵 니콘 주문 시작 ({len(sel)}건)", key="btn_nikon"): execute_auto_order(sel, "니콘")
    elif 'grouped_data' in st.session_state:
        st.info("선택하신 날짜에 해당하는 여벌 렌즈 발주 데이터가 없습니다.")

if __name__ == "__main__":
    main()