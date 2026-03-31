import sys
import asyncio
import subprocess
import os
import json
import streamlit as st
import pandas as pd
import ast
import pytz
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

# Windows 루프 정책 설정
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

st.set_page_config(page_title="RX 렌즈 발주 시스템", layout="wide")

# ==========================================
# [1. 설정 및 Supabase 연결]
# ==========================================
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TARGET_TABLE = "bms_orders"
FRAME_TABLE = "frame_specs"
STATUS_TABLE = "rx_order_status" 

def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# [2. DB 기반 주문 상태 관리]
# ==========================================
def load_status_db():
    try:
        supabase = get_supabase()
        response = supabase.table(STATUS_TABLE).select("*").execute()
        if response.data:
            return {item['order_code']: item['status'] for item in response.data}
    except Exception as e:
        print(f"상태 DB 로드 오류: {e}")
    return {}

def update_single_status(order_code, new_status):
    try:
        supabase = get_supabase()
        supabase.table(STATUS_TABLE).upsert({"order_code": order_code, "status": new_status}).execute()
    except Exception as e:
        st.error(f"상태 DB 업데이트 오류: {e}")

# ==========================================
# [3. RX 렌즈 필터링 및 데이터 추출 로직]
# ==========================================
@st.cache_data(ttl=3600)
def load_frame_specs():
    try:
        supabase = get_supabase()
        response = supabase.table(FRAME_TABLE).select(
            "name, size, lensWidth, lensHeight, bridgeWidth, faceFormAngle, pantoscopicTilt"
        ).execute()
        if response.data:
            return {(str(item.get('name', '')).strip().lower(), str(item.get('size', '')).strip()): item for item in response.data}
    except Exception as e:
        st.error(f"테 규격 로드 오류: {e}")
    return {}

@st.cache_data(ttl=601)
def load_rx_data(start_date_str, end_date_str):
    try:
        supabase = get_supabase()
        COLS = [
            "id", "createdAt", "status", "code", "lensType", '"customer.name"', 
            '"lens.left.skus"', '"lens.right.skus"',
            '"optometry.data.optimal.left.sph"', '"optometry.data.optimal.left.cyl"', '"optometry.data.optimal.left.axi"', '"optometry.data.optimal.left.pd"', '"optometry.data.optimal.left.add"',
            '"optometry.data.optimal.right.sph"', '"optometry.data.optimal.right.cyl"', '"optometry.data.optimal.right.axi"', '"optometry.data.optimal.right.pd"', '"optometry.data.optimal.right.add"',
            '"optometry.data.optimal.dist"', "orderItems" 
        ]
        start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
        start_utc = (start_dt - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
        end_utc = (end_dt + timedelta(days=1)).strftime("%Y-%m-%dT23:59:59Z")
        
        response = supabase.table(TARGET_TABLE).select(",".join(COLS))\
            .gte("createdAt", start_utc).lte("createdAt", end_utc)\
            .neq("lensType", "none")\
            .neq("status", "archived")\
            .execute()
            
        df = pd.DataFrame(response.data) if response.data else pd.DataFrame()
        
        if not df.empty:
            if 'lensType' in df.columns:
                df = df[df['lensType'].astype(str).str.lower() != 'none']
            if 'status' in df.columns:
                df = df[df['status'].astype(str).str.lower() != 'archived']
            
        return df
    except Exception as e:
        st.error(f"데이터 로드 오류: {e}")
        return pd.DataFrame()

def extract_rx_lens_info(sku_str):
    try:
        s_list = ast.literal_eval(sku_str) if isinstance(sku_str, str) else sku_str
        if isinstance(s_list, list) and len(s_list) > 0:
            sku_first = str(s_list[0]).lower()
            parts = sku_first.split('-')
            brand = parts[0] if len(parts) > 0 else "기타"
            type_code = parts[1] if len(parts) > 1 else ""
            if type_code in ['ss', 'ssp']: return None, None
            return brand, 'rx'
    except: pass
    return None, None

def extract_order_items_data(order_items):
    oh_l, oh_r, vd, model, size = "", "", "", "", ""
    try:
        text = str(order_items)
        match_oh_l = re.search(r"['\"]rec_proc_oh_l['\"]\s*:\s*['\"]?([0-9.]+)['\"]?", text)
        if match_oh_l: oh_l = match_oh_l.group(1)
        match_oh_r = re.search(r"['\"]rec_proc_oh_r['\"]\s*:\s*['\"]?([0-9.]+)['\"]?", text)
        if match_oh_r: oh_r = match_oh_r.group(1)
        match_vd = re.search(r"['\"]vd['\"]\s*:\s*['\"]?([0-9.]+)['\"]?", text)
        if match_vd: vd = match_vd.group(1)
        match_model = re.search(r"['\"]front_([^'\"]+)['\"]", text)
        if match_model: model = match_model.group(1).strip()
        match_size = re.search(r"['\"]frame_size_([^'\"]+)['\"]", text)
        if match_size: size = match_size.group(1).strip()
    except Exception as e: print(f"텍스트 스캔 중 오류: {e}")
    return oh_l, oh_r, vd, model, size

def get_rx_orders_by_date(df, start_date_str, end_date_str):
    if df.empty: return {}
    frame_specs_dict = load_frame_specs()
    kst = pytz.timezone('Asia/Seoul')
    df['date_only'] = pd.to_datetime(df['createdAt'], utc=True).dt.tz_convert(kst).dt.strftime('%Y-%m-%d')
    df_target = df[(df['date_only'] >= start_date_str) & (df['date_only'] <= end_date_str)].copy()
    
    grouped = {}
    for _, row in df_target.iterrows():
        l_brand, l_cat = extract_rx_lens_info(row.get('lens.left.skus', ''))
        r_brand, r_cat = extract_rx_lens_info(row.get('lens.right.skus', ''))
        
        if l_cat == 'rx' or r_cat == 'rx':
            brand_raw = l_brand if l_brand else r_brand
            brand = {"breezm": "브리즘", "zeiss": "자이스", "nikon": "니콘", "varilux": "바리락스"}.get(brand_raw, "기타")
            if brand not in grouped: grouped[brand] = []
            
            l_sph = row.get('optometry.data.optimal.left.sph', '')
            l_cyl = row.get('optometry.data.optimal.left.cyl', '')
            l_axis = row.get('optometry.data.optimal.left.axi', '')
            r_sph = row.get('optometry.data.optimal.right.sph', '')
            r_cyl = row.get('optometry.data.optimal.right.cyl', '')
            r_axis = row.get('optometry.data.optimal.right.axi', '')
            
            def format_add(val):
                try:
                    v = float(val)
                    if v == 0: return ""
                    return f"+{v:.2f}" if v > 0 else f"{v:.2f}"
                except: return ""
                
            l_add_str = format_add(row.get('optometry.data.optimal.left.add', ''))
            r_add_str = format_add(row.get('optometry.data.optimal.right.add', ''))
            
            dist = str(row.get('optometry.data.optimal.dist', '')).strip()
            if dist not in ['∞', 'nan', 'None', '']:
                try:
                    l_add_val = float(row.get('optometry.data.optimal.left.add', 0) or 0)
                    if l_sph not in ['', 'nan', 'None']:
                        l_sph = f"{(float(l_sph) + l_add_val):.2f}"
                        if float(l_sph) > 0 and not l_sph.startswith('+'): l_sph = f"+{l_sph}"
                except: pass
                try:
                    r_add_val = float(row.get('optometry.data.optimal.right.add', 0) or 0)
                    if r_sph not in ['', 'nan', 'None']:
                        r_sph = f"{(float(r_sph) + r_add_val):.2f}"
                        if float(r_sph) > 0 and not r_sph.startswith('+'): r_sph = f"+{r_sph}"
                except: pass
            
            r_rx_text = f"S:{r_sph} / C:{r_cyl} / A:{r_axis}" + (f" / ADD:{r_add_str}" if r_add_str else "")
            l_rx_text = f"S:{l_sph} / C:{l_cyl} / A:{l_axis}" + (f" / ADD:{l_add_str}" if l_add_str else "")
            
            pd_l = row.get('optometry.data.optimal.left.pd', '')
            pd_r = row.get('optometry.data.optimal.right.pd', '')
            oh_l, oh_r, vd, model, size = extract_order_items_data(row.get('orderItems', []))
            f_spec = frame_specs_dict.get((str(model).strip().lower(), str(size).strip()), {})

            grouped[brand].append({
                "주문번호": row.get('code', ''),
                "이름": row.get('customer.name', ''),
                "렌즈(L/R)": f"{row.get('lens.left.skus', '')} / {row.get('lens.right.skus', '')}",
                "도수(R)": r_rx_text,
                "도수(L)": l_rx_text,
                "PD / OH (R)": f"{pd_r} / {oh_r}",
                "PD / OH (L)": f"{pd_l} / {oh_l}",
                "VD": vd,
                "안경테": f"{model} ({size})" if model else "",
                "테 규격": f"{f_spec.get('lensWidth', '-')} / {f_spec.get('lensHeight', '-')} / {f_spec.get('bridgeWidth', '-')} / {f_spec.get('faceFormAngle', '-')} / {f_spec.get('pantoscopicTilt', '-')}" if f_spec else "규격 없음",
                "orderItems": row.get('orderItems', []) # 👈 로봇에게 원본 데이터를 넘겨주기 위해 보관
            })
    return grouped

# ==========================================
# [4. 단일 자동 발주 실행 로직]
# ==========================================
def execute_single_rx_order(item, script_name):
    """선택한 단일 항목을 JSON 파일로 저장하고 매크로 봇 실행"""
    order_data = {
        "order_id": item.get("주문번호", ""),
        "customer_name": item.get("이름", ""),
        "lens_info": item.get("렌즈(L/R)", ""),
        "rx_r": item.get("도수(R)", ""),
        "rx_l": item.get("도수(L)", ""),
        "pd_oh_r": item.get("PD / OH (R)", ""),
        "pd_oh_l": item.get("PD / OH (L)", ""),
        "vd": item.get("VD", ""),
        "frame": item.get("안경테", ""),
        "frame_specs": item.get("테 규격", ""),
        "order_items_raw": str(item.get("orderItems", "")) # 👈 경사각/설계브릿지 추출을 위해 원본 데이터 추가
    }
    
    payload = [order_data] 
    
    temp_file = f"temp_rx_{item.get('주문번호', 'order')}.json"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    try:
        flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x10) if sys.platform == 'win32' else 0
        subprocess.Popen([sys.executable, script_name, temp_file], creationflags=flags)
        st.toast(f"[{item.get('이름')}] 고객님 주문 로봇 실행됨!", icon='🚀')
    except Exception as e:
        st.error(f"매크로 실행 실패: {e}")

# ==========================================
# [5. 메인 화면 출력]
# ==========================================
def main():
    st.title("🎯 RX(맞춤) 렌즈 개별 발주 시스템")
    
    st.markdown("""
        <style>
        div[data-testid="column"] { display: flex; flex-direction: column; justify-content: center; }
        </style>
    """, unsafe_allow_html=True)
    
    today = datetime.now(pytz.timezone('Asia/Seoul'))
    date_range = st.date_input("조회 기간 선택", value=(today, today))
    
    if st.button("🚀 RX 데이터 조회", type="primary"):
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
        elif isinstance(date_range, tuple) and len(date_range) == 1:
            start_date, end_date = date_range[0], date_range[0]
        else:
            start_date, end_date = date_range, date_range
            
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        
        data = load_rx_data(start_str, end_str)
        st.session_state['rx_grouped_data'] = get_rx_orders_by_date(data, start_str, end_str)
    
    if 'rx_grouped_data' in st.session_state and st.session_state['rx_grouped_data']:
        
        target_order = ["브리즘", "자이스", "니콘", "바리락스", "기타"]
        brand_list = [b for b in target_order if b in st.session_state['rx_grouped_data']]
        
        tabs = st.tabs(brand_list)
        
        for tab, brand in zip(tabs, brand_list):
            with tab:
                brand_data = st.session_state['rx_grouped_data'][brand]
                
                # 도수 열 너비 조정
                col_widths = [1.3, 1.4, 1, 1.8, 2.2, 2.2, 1.2, 1.2, 0.8, 1.4, 2]
                header_cols = st.columns(col_widths)
                headers = ["발주 상태", "주문번호", "이름", "렌즈(L/R)", "도수(R)", "도수(L)", "PD/OH(R)", "PD/OH(L)", "VD", "안경테", "테 규격"]
                
                for col, h_title in zip(header_cols, headers):
                    col.markdown(f"<span style='font-size:14px; color:gray;'><b>{h_title}</b></span>", unsafe_allow_html=True)
                st.divider()
                
                status_db = load_status_db()
                
                for i, item in enumerate(brand_data):
                    cols = st.columns(col_widths)
                    order_id = item['주문번호']
                    
                    current_status = status_db.get(order_id, "주문대기")
                    
                    with cols[0]:
                        if current_status == "주문대기":
                            if st.button("🚀 주문하기", key=f"btn_order_{order_id}", type="primary", use_container_width=True):
                                if brand == "브리즘":
                                    execute_single_rx_order(item, "breezm_auto.py")
                                else:
                                    st.toast(f"{brand} 자동 주문 봇은 아직 준비 중입니다.", icon="ℹ️")
                                
                                update_single_status(order_id, "주문완료")
                                st.rerun()
                        else:
                            if st.button("✅ 주문완료", key=f"btn_done_{order_id}", type="secondary", use_container_width=True):
                                update_single_status(order_id, "주문대기")
                                st.rerun()

                    cols[1].markdown(f"<span style='font-size:13px;'>{item.get('주문번호', '')}</span>", unsafe_allow_html=True)
                    cols[2].markdown(f"<span style='font-size:13px;'>{item.get('이름', '')}</span>", unsafe_allow_html=True)
                    cols[3].markdown(f"<span style='font-size:12px;'>{item.get('렌즈(L/R)', '')}</span>", unsafe_allow_html=True)
                    cols[4].markdown(f"<span style='font-size:13px;'>{item.get('도수(R)', '')}</span>", unsafe_allow_html=True)
                    cols[5].markdown(f"<span style='font-size:13px;'>{item.get('도수(L)', '')}</span>", unsafe_allow_html=True)
                    cols[6].markdown(f"<span style='font-size:13px;'>{item.get('PD / OH (R)', '')}</span>", unsafe_allow_html=True)
                    cols[7].markdown(f"<span style='font-size:13px;'>{item.get('PD / OH (L)', '')}</span>", unsafe_allow_html=True)
                    cols[8].markdown(f"<span style='font-size:13px;'>{item.get('VD', '')}</span>", unsafe_allow_html=True)
                    cols[9].markdown(f"<span style='font-size:13px;'>{item.get('안경테', '')}</span>", unsafe_allow_html=True)
                    cols[10].markdown(f"<span style='font-size:12px;'>{item.get('테 규격', '')}</span>", unsafe_allow_html=True)
                    
                    st.markdown("<hr style='margin: 0.5em 0px; border-top: 1px dashed #ddd;'>", unsafe_allow_html=True)

    elif 'rx_grouped_data' in st.session_state:
        st.info("선택하신 기간에 해당하는 RX(맞춤) 렌즈 발주 데이터가 없습니다.")

if __name__ == "__main__":
    main()