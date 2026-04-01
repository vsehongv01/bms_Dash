
import streamlit as st
import pandas as pd
import os
import ast
import re
from datetime import datetime, timedelta
import time
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
# [2.5 수동 등록 관련 DB 함수]
# ==========================================
def load_return_requests():
    """bms_return_requests 테이블에서 등록된 모든 요청을 가져옴"""
    try:
        supabase = get_supabase()
        response = supabase.table("bms_return_requests").select("*").execute()
        if not response.data:
            return pd.DataFrame()
        df = pd.DataFrame(response.data)
        if 'created_at' in df.columns:
            df['created_at'] = pd.to_datetime(df['created_at'])
        if 'returned_at' in df.columns:
            df['returned_at'] = pd.to_datetime(df['returned_at'])
        return df
    except Exception:
        return pd.DataFrame()

def delete_return_request(order_code):
    """bms_return_requests에서 해당 주문번호 레코드 삭제 (원상태 복구)"""
    try:
        supabase = get_supabase()
        supabase.table("bms_return_requests").delete().eq("order_code", order_code).execute()
        return True
    except Exception as e:
        st.error(f"삭제 중 오류: {e}")
        return False


def register_return_request(row_data):
    """수동 반품 요청 등록"""
    try:
        supabase = get_supabase()
        data = {
            "order_code": row_data['주문번호'],
            "id_ref": str(row_data['_id']),
            "customer_id": str(row_data['_cid']),
            "customer_name": row_data['고객명'],
            "lens_info": row_data['렌즈정보'],
            "r_dosu": row_data['R도수'],
            "l_dosu": row_data['L도수'],
            "status": "대체반품대기"
        }
        supabase.table("bms_return_requests").insert(data).execute()
        return True, "성공적으로 등록되었습니다."
    except Exception as e:
        return False, f"등록 중 오류 발생: {str(e)}"

def update_request_status(order_code, new_status, row_data=None):
    """요청 상태 업데이트 (대기 -> 완료 등) / 없으면 생성 (Upsert 효과)"""
    try:
        supabase = get_supabase()
        # 먼저 해당 주문번호의 요청이 있는지 확인
        existing = supabase.table("bms_return_requests").select("order_code").eq("order_code", order_code).execute()
        
        def _is_completed_status(s):
            return s == "반품완료" or s.startswith("대체반품으로사용") or s.startswith("대체반품으로주문")

        if existing.data and len(existing.data) > 0:
            update_data = {"status": new_status}
            if _is_completed_status(new_status):
                update_data["returned_at"] = datetime.now(pytz.timezone('Asia/Seoul')).isoformat()
            supabase.table("bms_return_requests").update(update_data).eq("order_code", order_code).execute()
        elif row_data is not None:
            # 존재하지 않고 row_data가 있으면 새로 등록
            # row_data가 Series일 경우와 dict일 경우를 모두 대응
            if isinstance(row_data, pd.Series):
                id_ref = str(row_data.get('_id', ''))
                customer_id = str(row_data.get('_cid', ''))
                customer_name = str(row_data.get('고객명', ''))
                lens_info = str(row_data.get('렌즈정보', ''))
                r_dosu = str(row_data.get('R도수', ''))
                l_dosu = str(row_data.get('L도수', ''))
            else:
                id_ref = str(row_data.get('_id', ''))
                customer_id = str(row_data.get('_cid', ''))
                customer_name = str(row_data.get('고객명', ''))
                lens_info = str(row_data.get('렌즈정보', ''))
                r_dosu = str(row_data.get('R도수', ''))
                l_dosu = str(row_data.get('L도수', ''))

            data = {
                "order_code": order_code,
                "id_ref": id_ref,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "lens_info": lens_info,
                "r_dosu": r_dosu,
                "l_dosu": l_dosu,
                "status": new_status
            }
            if _is_completed_status(new_status):
                data["returned_at"] = datetime.now(pytz.timezone('Asia/Seoul')).isoformat()
            supabase.table("bms_return_requests").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"상태 업데이트 중 오류: {e}")
        return False

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
@st.cache_data(show_spinner=False)
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
            '반품상황': '반품없음'
        })
        
    df_rx = pd.DataFrame(parsed_rows)
    df_as = pd.DataFrame(as_rows)
    
    # ------------------
    # 반품 필요 상태 체크 로직
    # 동일 customer.id, name 이고 AS건이 존재하면 반품상황='반품필요'
    # ------------------
    if not df_rx.empty and not df_as.empty:
        for idx, r_row in df_rx.iterrows():
            cid = str(r_row['_cid'])
            cname = str(r_row['고객명'])
            
            matching_as = df_as[(df_as['customer.id'].astype(str) == cid) & (df_as['customer.name'].astype(str) == cname)]
            if not matching_as.empty:
                df_rx.at[idx, '반품상황'] = '⚠️반품필요'
    
    return df_rx, df_as


def merge_return_status(df_rx):
    """캐시 밖에서 호출: bms_return_requests의 최신 상태를 df_rx에 병합"""
    if df_rx.empty:
        return df_rx
    df_reqs = load_return_requests()
    if df_reqs.empty:
        return df_rx
    for _, req in df_reqs.iterrows():
        code = req['order_code']
        status = req['status']
        if code in df_rx['주문번호'].values:
            if status == "반품완료":
                icon = "✅"
            elif status == "대체반품대기":
                icon = "📁"
            else:
                icon = "🔄"
            df_rx.loc[df_rx['주문번호'] == code, '반품상황'] = f"{icon}{status}"
            if status == "반품완료" and 'returned_at' in req:
                df_rx.loc[df_rx['주문번호'] == code, '반품완료일'] = req['returned_at']
    return df_rx

# ==========================================
# [7. 대체 반품 찾기 (매칭)]
# ==========================================
@st.cache_data(show_spinner=False)
def find_alt_returns(df_rx):
    """자신 외에 과거의 도수가 오차범위 내인 주문 찾기"""
    if df_rx.empty: return df_rx

    df_rx['대체반주문(유사건)'] = ""

    def is_match(r1, r2):
        if r1['_id'] == r2['_id']: return False
        if str(r1['_cid']) == str(r2['_cid']): return False  # 동일 고객 제외
        if r2['잔여일'] < 0: return False                     # 기한 만료 후보 제외
        if r1['브랜드'] != r2['브랜드']: return False          # 브랜드 불일치 제외

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

    for idx, row in df_rx.iterrows():
        matches = []
        for jdx, cand in df_rx.iterrows():
            if idx == jdx: continue
            if is_match(row, cand):
                matches.append((cand['잔여일'], cand['주문번호'] + f" ({cand['잔여일']}일 남음)"))

        # 잔여일 오름차순 정렬 (기한 촉박한 건 먼저)
        matches.sort(key=lambda x: x[0])
        if matches:
            df_rx.at[idx, '대체반주문(유사건)'] = "\n".join(label for _, label in matches)

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
    df_rx = merge_return_status(df_rx)
    df_rx = find_alt_returns(df_rx)
    
    if df_rx.empty:
         st.info("조회된 RX 반품 관리 대상 내역이 없습니다.")
         return
         
    # [탭 구성 로직 이동 및 반품완료목록 추가]
    tab1, tab2, tab3 = st.tabs(["📋 전체 RX 리스트", "⏳ 대체반품대기", "✅ 반품완료목록"])

    with tab1:
        # 검색 기능
        search_query = st.text_input("🔍 이름 또는 주문번호 검색", "", key="search_all")
        
        if search_query:
            df_rx_display = df_rx[
                df_rx['고객명'].str.contains(search_query, case=False, na=False) | 
                df_rx['주문번호'].str.contains(search_query, case=False, na=False)
            ]
        else:
            df_rx_display = df_rx
        st.divider()
        
        # 디스플레이 테이블 포맷
        # 기존 필드에 '반품완료일'이 있으면 표시 고려 (optional: 여기서는 핵심 display_cols 유지)
        display_cols = ['선택', '고객명', '주문번호', '렌즈정보', 'R도수', 'L도수', '반품기한', '반품상황', '대체반주문(유사건)']
        # 체크박스 컬럼명 통일
        df_rx_display['선택'] = df_rx_display['선택(다운로드)']
        view_df = df_rx_display.sort_values(by='주문번호', ascending=False)[display_cols].copy()
        
        st.subheader("📋 전체 RX 리스트 (행 선택시 하단 상세 비교)")

        # --- 페이징 처리 ---
        ROWS_PER_PAGE = 15
        total_rows = len(view_df)
        total_pages = max(1, (total_rows - 1) // ROWS_PER_PAGE + 1)
        
        if "return_board_page" not in st.session_state:
            st.session_state.return_board_page = 1
        if st.session_state.return_board_page > total_pages:
            st.session_state.return_board_page = total_pages
            
        col_p1, col_p2, col_p3, col_p4 = st.columns([1, 1, 1, 7])
        with col_p1:
            if st.button("⬅️ 이전", disabled=(st.session_state.return_board_page <= 1), use_container_width=True, key="prev_btn"):
                st.session_state.return_board_page -= 1
                st.rerun()
        with col_p2:
            st.markdown(f"<div style='text-align: center; padding-top: 5px;'><b>{st.session_state.return_board_page} / {total_pages}</b></div>", unsafe_allow_html=True)
        with col_p3:
            if st.button("다음 ➡️", disabled=(st.session_state.return_board_page >= total_pages), use_container_width=True, key="next_btn"):
                st.session_state.return_board_page += 1
                st.rerun()
                
        start_idx = (st.session_state.return_board_page - 1) * ROWS_PER_PAGE
        view_df_page = view_df.iloc[start_idx:start_idx + ROWS_PER_PAGE].copy()

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
        
        selected_rows = edited_df[edited_df['선택'] == True]

        # 탭2로 자동 이동 (대체반품대기 등록 후)
        if st.session_state.get('switch_to_tab2'):
            st.session_state['switch_to_tab2'] = False
            st.markdown("""<script>
                (function() {
                    var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
                    if (tabs && tabs.length > 1) { tabs[1].click(); }
                })();
            </script>""", unsafe_allow_html=True)

        # 버튼들 가로 배치
        col_d1, col_d2 = st.columns([1, 1])
        with col_d1:
            btn_wait_label = f"📁 선택한 {len(selected_rows)}건 대체반품대기 등록" if not selected_rows.empty else "📁 대체반품대기 등록"
            if st.button(btn_wait_label, use_container_width=True, disabled=selected_rows.empty):
                success_count = 0
                for _, row in selected_rows.iterrows():
                    full_row = df_rx[df_rx['주문번호'] == row['주문번호']].iloc[0]
                    if update_request_status(row['주문번호'], "대체반품대기", full_row):
                        success_count += 1
                if success_count > 0:
                    st.success(f"{success_count}건이 대체반품대기로 등록되었습니다.")
                    st.session_state['switch_to_tab2'] = True
                    time.sleep(1)
                    st.rerun()
        with col_d2:
            btn_label = f"✅ 선택한 {len(selected_rows)}건 반품완료 등록" if not selected_rows.empty else "✅ 반품완료 등록"
            if st.button(btn_label, type="primary", use_container_width=True, disabled=selected_rows.empty):
                success_count = 0
                for _, row in selected_rows.iterrows():
                    full_row = df_rx[df_rx['주문번호'] == row['주문번호']].iloc[0]
                    if update_request_status(row['주문번호'], "반품완료", full_row):
                        success_count += 1

                if success_count > 0:
                    st.success(f"{success_count}건의 주문이 '반품완료'로 등록되었습니다.")
                    time.sleep(1)
                    st.rerun()
            
        st.divider()
        st.subheader("🔍 상세 조회 및 대체 반품 비교")
        
        if len(selected_rows) == 1:
            sel_code = selected_rows.iloc[0]['주문번호']
            raw_target = df_rx[df_rx['주문번호'] == sel_code]
            
            if not raw_target.empty:
                tgt_row = raw_target.iloc[0]
                st.markdown(f"**🔹 선택된 원 주문: {sel_code} ({tgt_row['고객명']})**")
                
                # 등록 버튼 추가 영역
                col_info, col_reg = st.columns([8, 2])
                with col_info:
                    st.dataframe(pd.DataFrame([tgt_row])[['주문번호', '고객명', '렌즈정보', 'R도수', 'L도수', '주문일', '반품기한', '반품상황']], hide_index=True)
                
                # 대체 주문 리스트
                alt_str = str(tgt_row['대체반주문(유사건)'])
                alt_codes = re.findall(r'([A-Za-z0-9-]+)\s*\(', alt_str)

                # 등록 버튼 로직
                with col_reg:
                    is_already_registered = "📁대체반품대기" in str(tgt_row['반품상황'])
                    if not alt_codes:
                        if st.button("➕ 대체반품필요 등록", disabled=is_already_registered, use_container_width=True, type="primary"):
                            success, msg = register_return_request(tgt_row)
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                    elif is_already_registered:
                        st.info("이미 등록된 건입니다.")

                if alt_codes:
                    st.markdown(f"**🔸 매칭된 대체 주문 (총 {len(alt_codes)}건)**")
                    alt_df = df_rx[df_rx['주문번호'].isin(alt_codes)]
                    for _, alt_row in alt_df.iterrows():
                        col_alt_info, col_alt_btn = st.columns([8, 2])
                        with col_alt_info:
                            st.dataframe(
                                pd.DataFrame([alt_row])[['주문번호', '고객명', '렌즈정보', 'R도수', 'L도수', '주문일', '반품기한', '반품상황']],
                                hide_index=True,
                                use_container_width=True
                            )
                        with col_alt_btn:
                            btn_key = f"alt_return_{alt_row['주문번호']}"
                            if st.button("🔄 대체반품하기", key=btn_key, use_container_width=True, type="primary"):
                                alt_status = f"대체반품으로사용({sel_code} {tgt_row['고객명']})"
                                origin_status = f"대체반품으로주문({alt_row['주문번호']} {alt_row['고객명']})"
                                update_request_status(alt_row['주문번호'], alt_status, alt_row)
                                update_request_status(sel_code, origin_status, tgt_row)
                                st.success(f"완료: [{alt_row['주문번호']}] → 대체반품으로 사용 처리됐습니다.")
                                time.sleep(1)
                                st.rerun()
                else:
                    st.info("매칭된 대체 반품 주문이 없습니다.")
                    
                as_match = df_as[(df_as['customer.id'].astype(str) == str(tgt_row['_cid'])) | (df_as['customer.name'] == tgt_row['고객명'])]
                if not as_match.empty:
                    st.success(f"📌 이 고객의 하위 'AS' 교환 이력이 {len(as_match)}건 존재합니다.")
                    st.dataframe(as_match[['code', 'createdAt']], hide_index=True)
                    
        elif len(selected_rows) > 1:
            st.info("상세 비교를 보려면 표에서 1개의 주문만 선택해 주세요.")
        else:
            st.info("표에서 주문을 선택하면 상세 비교 정보가 여기에 나타납니다.")

    with tab2:
        st.subheader("⏳ 직접 등록된 대체 반품 대기 목록")
        df_reqs_all = load_return_requests()

        if df_reqs_all.empty:
            st.info("등록된 대체 반품 요청이 없습니다.")
        else:
            df_reqs_active = df_reqs_all[df_reqs_all['status'] == "대체반품대기"].copy()

            if df_reqs_active.empty:
                st.info("대기 중인 반품 요청이 없습니다.")
            else:
                # df_rx의 대체반주문 컬럼 병합
                df_reqs_active = df_reqs_active.merge(
                    df_rx[['주문번호', '대체반주문(유사건)', '반품기한', '반품상황']],
                    left_on='order_code', right_on='주문번호', how='left'
                ).drop(columns=['주문번호'])

                req_search = st.text_input("🔍 대기 목록 검색 (고객명/주문번호)", "", key="search_req")
                if req_search:
                    df_reqs_active = df_reqs_active[
                        df_reqs_active['customer_name'].str.contains(req_search, case=False, na=False) |
                        df_reqs_active['order_code'].str.contains(req_search, case=False, na=False)
                    ]

                df_reqs_active.insert(0, '선택', False)

                edited_active = st.data_editor(
                    df_reqs_active[['선택', 'order_code', 'customer_name', 'lens_info', 'r_dosu', 'l_dosu', '반품기한', '반품상황', '대체반주문(유사건)']],
                    column_config={
                        "선택": st.column_config.CheckboxColumn("선택", width="small", default=False),
                        "order_code": st.column_config.TextColumn("주문번호", width="medium"),
                        "customer_name": st.column_config.TextColumn("고객명", width="small"),
                        "lens_info": st.column_config.TextColumn("렌즈정보", width="medium"),
                        "r_dosu": st.column_config.TextColumn("R도수", width="medium"),
                        "l_dosu": st.column_config.TextColumn("L도수", width="medium"),
                        "반품기한": st.column_config.TextColumn("반품기한", width="small"),
                        "반품상황": st.column_config.TextColumn("반품상황", width="small"),
                        "대체반주문(유사건)": st.column_config.TextColumn("대체 반품", width="medium"),
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="req_editor"
                )

                selected_active = edited_active[edited_active['선택'] == True]

                col_save, col_done = st.columns([1, 1])
                with col_save:
                    if st.button("💾 변경 사항 저장", key="save_req_status_final", use_container_width=True):
                        for _, r in edited_active.iterrows():
                            update_request_status(r['order_code'], "대체반품대기")
                        st.success("데이터베이스에 반영되었습니다.")
                        time.sleep(1)
                        st.rerun()
                with col_done:
                    btn_done_label = f"✅ 선택한 {len(selected_active)}건 반품완료 등록" if not selected_active.empty else "✅ 반품완료 등록"
                    if st.button(btn_done_label, type="primary", use_container_width=True, disabled=selected_active.empty, key="tab2_done_btn"):
                        for _, r in selected_active.iterrows():
                            full_row = df_rx[df_rx['주문번호'] == r['order_code']]
                            row_data = full_row.iloc[0] if not full_row.empty else None
                            update_request_status(r['order_code'], "반품완료", row_data)
                        st.success(f"{len(selected_active)}건이 반품완료로 등록되었습니다.")
                        time.sleep(1)
                        st.rerun()

                st.divider()
                st.subheader("🔍 상세 조회 및 대체 반품 비교")

                if len(selected_active) == 1:
                    sel2_code = selected_active.iloc[0]['order_code']
                    raw_target2 = df_rx[df_rx['주문번호'] == sel2_code]

                    if not raw_target2.empty:
                        tgt2_row = raw_target2.iloc[0]
                        st.markdown(f"**🔹 선택된 원 주문: {sel2_code} ({tgt2_row['고객명']})**")

                        col_info2, col_reg2 = st.columns([8, 2])
                        with col_info2:
                            st.dataframe(pd.DataFrame([tgt2_row])[['주문번호', '고객명', '렌즈정보', 'R도수', 'L도수', '주문일', '반품기한', '반품상황']], hide_index=True)

                        alt_str2 = str(tgt2_row['대체반주문(유사건)'])
                        alt_codes2 = re.findall(r'([A-Za-z0-9-]+)\s*\(', alt_str2)

                        with col_reg2:
                            is_already2 = "📁대체반품대기" in str(tgt2_row['반품상황'])
                            if not alt_codes2:
                                if st.button("➕ 대체반품필요 등록", disabled=is_already2, use_container_width=True, type="primary", key="tab2_reg_btn"):
                                    success, msg = register_return_request(tgt2_row)
                                    if success:
                                        st.success(msg)
                                        st.rerun()
                                    else:
                                        st.error(msg)
                            elif is_already2:
                                st.info("이미 등록된 건입니다.")

                        if alt_codes2:
                            st.markdown(f"**🔸 매칭된 대체 주문 (총 {len(alt_codes2)}건)**")
                            alt_df2 = df_rx[df_rx['주문번호'].isin(alt_codes2)]
                            for _, alt2_row in alt_df2.iterrows():
                                col_a2, col_b2 = st.columns([8, 2])
                                with col_a2:
                                    st.dataframe(
                                        pd.DataFrame([alt2_row])[['주문번호', '고객명', '렌즈정보', 'R도수', 'L도수', '주문일', '반품기한', '반품상황']],
                                        hide_index=True, use_container_width=True
                                    )
                                with col_b2:
                                    if st.button("🔄 대체반품하기", key=f"tab2_alt_{alt2_row['주문번호']}", use_container_width=True, type="primary"):
                                        update_request_status(alt2_row['주문번호'], f"대체반품으로사용({sel2_code} {tgt2_row['고객명']})", alt2_row)
                                        update_request_status(sel2_code, f"대체반품으로주문({alt2_row['주문번호']} {alt2_row['고객명']})", tgt2_row)
                                        st.success(f"완료: [{alt2_row['주문번호']}] → 대체반품으로 사용 처리됐습니다.")
                                        time.sleep(1)
                                        st.rerun()
                        else:
                            st.info("매칭된 대체 반품 주문이 없습니다.")

                        as_match2 = df_as[(df_as['customer.id'].astype(str) == str(tgt2_row['_cid'])) | (df_as['customer.name'] == tgt2_row['고객명'])]
                        if not as_match2.empty:
                            st.success(f"📌 이 고객의 하위 'AS' 교환 이력이 {len(as_match2)}건 존재합니다.")
                            st.dataframe(as_match2[['code', 'createdAt']], hide_index=True)
                    else:
                        st.info("전체 RX 목록에서 해당 주문을 찾을 수 없습니다.")

                elif len(selected_active) > 1:
                    st.info("상세 비교를 보려면 1개의 주문만 선택해 주세요.")
                else:
                    st.info("표에서 주문을 선택하면 상세 비교 정보가 여기에 나타납니다.")

    with tab3:
        st.subheader("✅ 반품 완료 목록")
        df_reqs_all = load_return_requests()
        
        if df_reqs_all.empty:
            st.info("완료된 반품 내역이 없습니다.")
        else:
            # 완료 관련 상태 필터링 (반품완료 + 대체반품으로사용/주문)
            done_mask = (
                (df_reqs_all['status'] == "반품완료") |
                df_reqs_all['status'].str.startswith("대체반품으로사용", na=False) |
                df_reqs_all['status'].str.startswith("대체반품으로주문", na=False)
            )
            df_reqs_done = df_reqs_all[done_mask].copy()

            if df_reqs_done.empty:
                st.info("반품 완료된 내역이 아직 없습니다.")
            else:
                # 날짜 기준 내림차순 정렬
                if 'returned_at' in df_reqs_done.columns:
                    df_reqs_done = df_reqs_done.sort_values(by='returned_at', ascending=False)

                done_search = st.text_input("🔍 완료 목록 검색 (고객명/주문번호)", "", key="search_done")
                if done_search:
                    df_reqs_done = df_reqs_done[
                        df_reqs_done['customer_name'].str.contains(done_search, case=False, na=False) |
                        df_reqs_done['order_code'].str.contains(done_search, case=False, na=False)
                    ]

                df_reqs_done.insert(0, '선택', False)

                edited_done = st.data_editor(
                    df_reqs_done[['선택', 'order_code', 'customer_name', 'lens_info', 'status', 'returned_at']],
                    column_config={
                        "선택": st.column_config.CheckboxColumn("선택", width="small", default=False),
                        "order_code": st.column_config.TextColumn("주문번호", width="medium"),
                        "customer_name": st.column_config.TextColumn("고객명", width="small"),
                        "lens_info": st.column_config.TextColumn("렌즈정보", width="medium"),
                        "status": st.column_config.TextColumn("상태", width="large"),
                        "returned_at": st.column_config.DatetimeColumn("처리일시", width="medium"),
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="done_editor"
                )

                selected_done = edited_done[edited_done['선택'] == True]
                btn_revert_label = f"↩️ 선택한 {len(selected_done)}건 원상태로 되돌리기" if not selected_done.empty else "↩️ 원상태로 되돌리기"
                if st.button(btn_revert_label, disabled=selected_done.empty, use_container_width=True):
                    for _, done_row in selected_done.iterrows():
                        status_val = str(done_row['status'])
                        paired_match = re.match(r'대체반품으로(?:사용|주문)\((\S+)', status_val)
                        if paired_match:
                            delete_return_request(paired_match.group(1))
                        delete_return_request(done_row['order_code'])
                    st.success(f"{len(selected_done)}건을 원상태로 복구했습니다.")
                    time.sleep(1)
                    st.rerun()

if __name__ == "__main__":
    main()
