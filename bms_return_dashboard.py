
import streamlit as st
import pandas as pd
import os
import ast
import re
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
from supabase import create_client, Client

# ==========================================
# [1. 페이지 설정]
# ==========================================
st.set_page_config(
    page_title="RX 렌즈 반품 관리",
    page_icon="🔙",
    layout="wide"
)

# ==========================================
# [2. 환경 변수 및 상수]
# ==========================================
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TARGET_TABLE = "bms_orders"
MAPPING_TABLE = "lens_mappings"

def get_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
         st.error("Supabase 환경 변수가 없습니다.")
         return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# [3. 공통 로직 - 매핑 로드]
# ==========================================
@st.cache_data(ttl=600, show_spinner=False)
def load_all_mappings():
    try:
        supabase = get_supabase()
        response = supabase.table(MAPPING_TABLE).select("sku_key, custom_name").execute()
        if response.data:
            return {item['sku_key']: item['custom_name'] for item in response.data}
    except Exception:
        pass
    return {}

def get_lens_display_name(sku_list, all_mappings):
    sku_str = str(sku_list)
    if sku_str in all_mappings: 
        return all_mappings[sku_str]
    s_lower = sku_str.lower()
    
    # 간이 임시 변환
    idx = "1.74" if "1.74" in s_lower else ("1.67" if "1.67" in s_lower else ("1.60" if "1.60" in s_lower else "1.56"))
    design = "AS"
    if "dfree" in s_lower or "ssp" in s_lower: design = "D-FREE"
    
    return f"미매핑_RX_({idx} {design})"

# ==========================================
# [4. 주문 데이터 로드]
# ==========================================
@st.cache_data(ttl=300, show_spinner=False)
def load_return_data():
    """최근 3개월치의 custom 및 as 데이터를 가져옴"""
    supabase = get_supabase()
    if not supabase: return pd.DataFrame()
    
    COLS = [
        "id", "createdAt", "code", "lensType", '"customer.id"', '"customer.name"',
        '"orderItems"',
        '"lens.left.skus"', '"lens.right.skus"',
        '"optometry.data.optimal.left.sph"', '"optometry.data.optimal.left.cyl"', '"optometry.data.optimal.left.axi"', '"optometry.data.optimal.left.add"', '"optometry.data.optimal.left.pd"',
        '"optometry.data.optimal.right.sph"', '"optometry.data.optimal.right.cyl"', '"optometry.data.optimal.right.axi"', '"optometry.data.optimal.right.add"', '"optometry.data.optimal.right.pd"'
    ]
    
    start_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%dT00:00:00Z")
    
    try:
        response = supabase.table(TARGET_TABLE)\
            .select(",".join(COLS))\
            .gte("createdAt", start_date)\
            .in_("lensType", ["custom", "as"])\
            .execute()
        
        df = pd.DataFrame(response.data) if response.data else pd.DataFrame()
        return df
    except Exception as e:
        st.error(f"데이터 로드 중 오류: {e}")
        return pd.DataFrame()

# ==========================================
# [5. 렌즈 RX 판별 & 기한 파싱]
# ==========================================
def parse_skus(sku_val):
    if pd.isna(sku_val) or str(sku_val).lower() in ['', 'nan', 'none']: 
        return []
    try:
        s_list = ast.literal_eval(str(sku_val)) if isinstance(sku_val, str) else sku_val
        if isinstance(s_list, list): return s_list
    except:
        pass
    return [str(sku_val)]

def is_rx_lens(sku_list):
    if not sku_list: return False
    parts = str(sku_list[0]).split('-')
    if len(parts) >= 2:
        seg1 = parts[1].lower().strip()
        if seg1 in ['ss', 'ssp']: return False
        return True # ss나 ssp가 아니면 RX!
    return False

def extract_brand(sku_list):
    if not sku_list: return "unknown"
    parts = str(sku_list[0]).split('-')
    return parts[0].lower().strip() if parts else "unknown"

def parse_presubmit(date_str):
    if not date_str or str(date_str).lower() == 'nan': return None
    try:
        dt = pd.to_datetime(date_str)
        if dt.tzinfo is not None:
             dt = dt.tz_convert(pytz.timezone('Asia/Seoul')).replace(tzinfo=None)
        return dt
    except:
        return None

def extract_order_date(row):
    order_items_val = row.get('orderItems', '')
    if pd.isna(order_items_val) or str(order_items_val).strip() == '':
        return parse_presubmit(row.get('createdAt', ''))
        
    try:
        items = ast.literal_eval(str(order_items_val)) if isinstance(order_items_val, str) else order_items_val
        if isinstance(items, list) and items:
            for item in items:
                sd = item.get('statusDetail', {})
                ps_date = sd.get('PreSubmitEndDate') or sd.get('PreSubmitStartDate')
                if ps_date:
                    return parse_presubmit(ps_date)
    except:
        pass
    
    # 폴백
    return parse_presubmit(row.get('createdAt', ''))

def safe_float(val):
    try:
        return float(val) if val else 0.0
    except:
        return 0.0

# ==========================================
# [6. 매칭 & 전처리]
# ==========================================
def process_data(df):
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    
    mappings = load_all_mappings()
    
    parsed_rows = []
    as_rows = []
    
    # 오늘 자정
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst).replace(tzinfo=None)
    
    for _, row in df.iterrows():
        l_type = str(row.get('lensType', '')).strip().lower()
        if l_type == 'as':
            as_rows.append(row)
            continue
            
        if l_type != 'custom': continue
        
        l_skus = parse_skus(row.get('lens.left.skus', ''))
        r_skus = parse_skus(row.get('lens.right.skus', ''))
        
        is_l_rx = is_rx_lens(l_skus)
        is_r_rx = is_rx_lens(r_skus)
        
        if not (is_l_rx or is_r_rx):
            continue
            
        # RX 건 확인됨
        order_date = extract_order_date(row)
        if not order_date: order_date = now # 기본값 fallback
        
        brand = extract_brand(l_skus) if l_skus else extract_brand(r_skus)
        days_to_add = 60 if brand in ['zeiss', 'chemi'] else 55
        return_deadline = order_date + timedelta(days=days_to_add)
        days_left = (return_deadline - now).days
        
        # 상태 & 하이라이트 아이콘
        if days_left < 0:
             status_icon = "🔴 기한 만료"
        elif days_left <= 7:
             status_icon = "🟡 임박"
        else:
             status_icon = "🟢 여유"
             
        # 도수
        l_sph = safe_float(row.get('optometry.data.optimal.left.sph'))
        l_cyl = safe_float(row.get('optometry.data.optimal.left.cyl'))
        l_axi = safe_float(row.get('optometry.data.optimal.left.axi'))
        l_add = safe_float(row.get('optometry.data.optimal.left.add'))
        l_pd  = safe_float(row.get('optometry.data.optimal.left.pd'))

        r_sph = safe_float(row.get('optometry.data.optimal.right.sph'))
        r_cyl = safe_float(row.get('optometry.data.optimal.right.cyl'))
        r_axi = safe_float(row.get('optometry.data.optimal.right.axi'))
        r_add = safe_float(row.get('optometry.data.optimal.right.add'))
        r_pd  = safe_float(row.get('optometry.data.optimal.right.pd'))

        def format_opt(v):
            return f"{v:+.2f}".replace("+0.00", "0.00")
            
        def build_dosu(sph, cyl, axi, add):
            s_str = f"S{format_opt(sph)}"
            c_str = f"C{format_opt(cyl)}"
            a_str = f"A{int(axi)}"
            add_str = f" Add{add:.2f}" if add != 0.0 else ""
            return f"{s_str} {c_str} {a_str}{add_str}"

        dosu_L = build_dosu(l_sph, l_cyl, l_axi, l_add)
        dosu_R = build_dosu(r_sph, r_cyl, r_axi, r_add)
        
        # 렌즈 정보 (매핑본)
        l_name = get_lens_display_name(l_skus, mappings) if l_skus else ""
        r_name = get_lens_display_name(r_skus, mappings) if r_skus else ""
        if l_name == r_name and l_name != "":
            lens_info = l_name
        else:
            lens_info = " / ".join([n for n in [l_name, r_name] if n])
        
        parsed_rows.append({
            '_id': row['id'],
            '_cid': row.get('customer.id', ''),
            '선택(다운로드)': False,
            '고객명': row.get('customer.name', ''),
            '주문번호': row.get('code', ''),
            '렌즈정보': lens_info,
            '비고': f"L:{l_skus[0] if l_skus else ''} R:{r_skus[0] if r_skus else ''}",
            'R도수': dosu_R,
            'L도수': dosu_L,
            '주문일': order_date.strftime("%Y-%m-%d"),
            '반품기한': return_deadline.strftime("%Y-%m-%d"),
            '잔여일': days_left,
            '상태': status_icon,
            '브랜드': brand,
            # 매칭용
            '_L_sph': l_sph, '_L_cyl': l_cyl, '_L_axi': l_axi, '_L_add': l_add, '_L_pd': l_pd,
            '_R_sph': r_sph, '_R_cyl': r_cyl, '_R_axi': r_axi, '_R_add': r_add, '_R_pd': r_pd,
            '반품상황': '반품안함'
        })
        
    df_rx = pd.DataFrame(parsed_rows)
    df_as = pd.DataFrame(as_rows)
    
    # ------------------
    # 반품 완료 상태 체크 로직
    # 동일 customer.id, name 이고 AS건이 존재하면 반품상황='완료'
    # ------------------
    if not df_rx.empty and not df_as.empty:
        for idx, r_row in df_rx.iterrows():
            cid = str(r_row['_cid'])
            cname = str(r_row['고객명'])
            
            matching_as = df_as[(df_as['customer.id'].astype(str) == cid) & (df_as['customer.name'].astype(str) == cname)]
            if not matching_as.empty:
                df_rx.at[idx, '반품상황'] = '✅반품 완료'
                
    return df_rx, df_as

# ==========================================
# [7. 대체 반품 찾기 (매칭)]
# ==========================================
def find_alt_returns(df_rx):
    """자신 외에 과거의 도수가 오차범위 내인 주문 찾기"""
    # 진행중인 건 (반품 완료되지 않은 건)들 중, '기한 만료 안 된 건' 과의 매칭
    if df_rx.empty: return df_rx
    
    df_rx['대체반주문(유사건)'] = ""
    
    def is_match(r1, r2):
        if r1['_id'] == r2['_id']: return False
        
        # 오차 기준 (SPH/CYL/ADD ±0.5, AXIS ±15, PD ±3)
        if abs(r1['_L_sph'] - r2['_L_sph']) > 0.5: return False
        if abs(r1['_L_cyl'] - r2['_L_cyl']) > 0.5: return False
        if abs(r1['_L_add'] - r2['_L_add']) > 0.5: return False
        if abs(r1['_L_axi'] - r2['_L_axi']) > 15: return False
        if abs(r1['_L_pd'] - r2['_L_pd']) > 3: return False
        
        if abs(r1['_R_sph'] - r2['_R_sph']) > 0.5: return False
        if abs(r1['_R_cyl'] - r2['_R_cyl']) > 0.5: return False
        if abs(r1['_R_add'] - r2['_R_add']) > 0.5: return False
        if abs(r1['_R_axi'] - r2['_R_axi']) > 15: return False
        if abs(r1['_R_pd'] - r2['_R_pd']) > 3: return False
        
        return True

    # 반품 가용 대상: 아직 기한 안 지났고, 본인이 아닌 건
    for idx, row in df_rx.iterrows():
        # 과거 ~ 본인보다 이전 주문들 중에서 검색 (단, DataFrame은 시간 순서 정렬 상태)
        matches = []
        for jdx, cand in df_rx.iterrows():
            if idx == jdx: continue
            if is_match(row, cand):
                matches.append(cand['주문번호'] + f" ({cand['잔여일']}일 남음)")
                
        if matches:
            df_rx.at[idx, '대체반주문(유사건)'] = "\n".join(matches)
            
    return df_rx

# ==========================================
# [8. UI 렌더링]
# ==========================================
def main():
    st.title("🔄 브리즘 RX 렌즈 반품 관리")
    st.caption("최근 100일 기준 `lenstype = custom` 중 RX 렌즈 주문만 자동으로 필터링합니다.")
    
    df_raw = load_return_data()
    if df_raw.empty:
        st.warning("데이터가 없습니다 (또는 데이터베이스 연결 오류입니다).")
        return
        
    df_rx, df_as = process_data(df_raw)
    df_rx = find_alt_returns(df_rx)
    
    if df_rx.empty:
         st.info("조회된 RX 반품 관리 대상 내역이 없습니다.")
         return
         
    # 검색 기능
    search_query = st.text_input("🔍 이름 또는 주문번호 검색", "")
    
    if search_query:
        df_rx = df_rx[df_rx['고객명'].str.contains(search_query, case=False) | df_rx['주문번호'].str.contains(search_query, case=False)]
        
    st.divider()
    
    # 디스플레이 테이블 포맷
    display_cols = ['선택', '고객명', '주문번호', '렌즈정보', 'R도수', 'L도수', '반품기한', '반품상황', '대체반주문(유사건)']
    # 체크박스 컬럼명 통일
    df_rx['선택'] = df_rx['선택(다운로드)']
    view_df = df_rx.sort_values(by='주문번호', ascending=False)[display_cols].copy()
    
    st.subheader("📋 전체 RX 리스트 (행 선택시 하단 상세 비교)")

    # --- 페이징 처리 ---
    ROWS_PER_PAGE = 15
    total_rows = len(view_df)
    total_pages = max(1, (total_rows - 1) // ROWS_PER_PAGE + 1)
    
    if "return_board_page" not in st.session_state:
        st.session_state.return_board_page = 1
        
    # 페이지 번호가 전체 페이지를 초과하지 않도록 보정 (검색 결과 등으로 데이터가 줄었을 때)
    if st.session_state.return_board_page > total_pages:
        st.session_state.return_board_page = total_pages
        
    # 상단 페이지네이션 UI
    col1, col2, col3, col4 = st.columns([1, 1, 1, 7])
    
    with col1:
        if st.button("⬅️ 이전", disabled=(st.session_state.return_board_page <= 1), use_container_width=True):
            st.session_state.return_board_page -= 1
            st.rerun()
    with col2:
        st.markdown(f"<div style='text-align: center; padding-top: 5px;'><b>{st.session_state.return_board_page} / {total_pages}</b></div>", unsafe_allow_html=True)
    with col3:
        if st.button("다음 ➡️", disabled=(st.session_state.return_board_page >= total_pages), use_container_width=True):
            st.session_state.return_board_page += 1
            st.rerun()
            
    start_idx = (st.session_state.return_board_page - 1) * ROWS_PER_PAGE
    end_idx = start_idx + ROWS_PER_PAGE
    view_df_page = view_df.iloc[start_idx:end_idx].copy()

    edited_df = st.data_editor(
        view_df_page,
        column_config={
            "선택": st.column_config.CheckboxColumn("선택", width="small", default=False),
            "고객명": st.column_config.TextColumn("고객명", width="small"),
            "반품기한": st.column_config.TextColumn("기한", width="small"),
            "R도수": st.column_config.TextColumn("R도수", width="medium"),
            "L도수": st.column_config.TextColumn("L도수", width="medium"),
            "렌즈정보": st.column_config.TextColumn("렌즈", width="medium"),
            "대체반주문(유사건)": st.column_config.TextColumn("대체 반품", width="medium")
        },
        use_container_width=True,
        hide_index=True
    )
    
    # 다운로드 & 상세비교 처리용 선택 행
    selected_rows = edited_df[edited_df['선택'] == True]
    
    if not selected_rows.empty:
        csv = selected_rows.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button(
            label="💾 선택 항목 반품 신청양식 다운로드(CSV)",
            data=csv,
            file_name=f"rx_return_{datetime.now().strftime('%Y%m%d')}.csv",
            mime='text/csv',
        )
        
    st.divider()
    st.subheader("🔍 상세 조회 및 대체 반품 비교")
    st.caption("위 표에서 체크박스를 클릭하여 1건을 선택하면 해당 주문과 매칭된 대체 주문 도수 비교가 노출됩니다.")
    
    if len(selected_rows) == 1:
        sel_code = selected_rows.iloc[0]['주문번호']
        # 원본 데이터프레임에서 행 추출
        raw_target = df_rx[df_rx['주문번호'] == sel_code]
        
        if not raw_target.empty:
            tgt_row = raw_target.iloc[0]
            st.markdown(f"**🔹 선택된 원 주문: {sel_code} ({tgt_row['고객명']})**")
            st.dataframe(pd.DataFrame([tgt_row])[['주문번호', '고객명', 'R도수', 'L도수', '주문일', '반품기한', '반품상황']], hide_index=True)
            
            # 대체 반품 추출
            alt_str = str(tgt_row['대체반주문(유사건)'])
            alt_codes = re.findall(r'([A-Za-z0-9-]+)\s*\(', alt_str)
            
            if alt_codes:
                st.markdown(f"**🔸 매칭된 대체 주문 (총 {len(alt_codes)}건)**")
                # 전체 df_rx 중 조건 일치하는 건 불러오기
                alt_df = df_rx[df_rx['주문번호'].isin(alt_codes)]
                st.dataframe(alt_df[['주문번호', '고객명', 'R도수', 'L도수', '주문일', '반품기한', '반품상황']], hide_index=True)
            else:
                st.info("매칭된 대체 반품 주문이 없습니다.")
                
            # 기존 AS 건 하위 메뉴
            cids = raw_target['_cid'].unique()
            as_match = df_as[(df_as['customer.id'].isin(cids)) | (df_as['customer.name'] == tgt_row['고객명'])]
            if not as_match.empty:
                st.success(f"📌 이 고객의 하위 'AS' 교환 이력이 {len(as_match)}건 존재합니다.")
                st.dataframe(as_match[['code', 'createdAt']], hide_index=True)
                
    elif len(selected_rows) > 1:
        st.info("상세 비교를 보려면 표에서 1개의 주문만 선택해 주세요.")
    else:
        st.info("표에서 주문을 선택하면 상세 비교 정보가 여기에 나타납니다.")

if __name__ == "__main__":
    main()
