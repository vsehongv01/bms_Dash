import streamlit as st
import pandas as pd
import os
from dotenv import load_dotenv
from supabase import create_client, Client
import sys
import subprocess
import time

# ==========================================
# [1. 페이지 설정]
# ==========================================
st.set_page_config(
    page_title="BMS 담당자별 수령피드백 관리",
    page_icon="📦",
    layout="wide"
)

# ==========================================
# [2. 설정 및 상수]
# ==========================================
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TARGET_TABLE = "bms_orders"

# ==========================================
# [3. 데이터 로드 함수]
# ==========================================
@st.cache_data(ttl=600, show_spinner=False)
def load_data():
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return pd.DataFrame()
        
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        all_data = []
        
        # 🌟 deliveryDetail.memo 추가
        COLS = [
            "id", "createdAt", "status", "code", "frameType", "lensType",
            '"statusDetail.lensStaff"', '"statusDetail.frameStaff"', 
            '"customer.name"', '"customer.contacts"',
            '"frame.size"', '"frame.color"', '"frame.front"', '"frame.temple_color"', '"frame.temple"',
            '"lens.left.skus"', '"lens.right.skus"',
            '"deliveryDetail.memo"'
        ]
        cols = ",".join(COLS)
        
        offset = 0
        page_size = 1000
        loading_text = st.empty()
        
        while True:
            loading_text.text(f"⏳ 전체 과거 데이터를 불러오는 중입니다... ({offset}건 완료)")
            
            response = supabase.table(TARGET_TABLE)\
                .select(cols)\
                .order("id")\
                .range(offset, offset + page_size - 1)\
                .execute()
                
            data = response.data
            if not data:
                break
                
            all_data.extend(data)
            
            if len(data) < page_size:
                break 
                
            offset += page_size
            
        loading_text.empty() 
        
        return pd.DataFrame(all_data) if all_data else pd.DataFrame()
        
    except Exception as e:
        st.error(f"전체 데이터 로드 중 오류: {e}")
        return pd.DataFrame()

# ==========================================
# [4. 데이터 처리 로직 (배송완료)]
# ==========================================
def process_delivered_data(df, selected_staff):
    if df.empty: return pd.DataFrame()
    
    # 전처리
    df['id'] = df['id'].astype(str).str.replace(r'\.0$', '', regex=True)
    df = df.fillna("")

    # 당일 기준 2개월 이상 지난 데이터 제외 (필요시 기간 조정 가능)
    if 'createdAt' in df.columns:
        dt_col = pd.to_datetime(df['createdAt'], errors='coerce', utc=True)
        two_months_ago = pd.Timestamp.now(tz='UTC') - pd.DateOffset(months=2)
        df = df[dt_col.isna() | (dt_col >= two_months_ago)]

    # 🌟 status가 Delivered인 것만 포함
    if 'status' in df.columns:
        df = df[df['status'].astype(str).str.strip().str.lower() == 'delivered']

    # 조건 1: frameType 또는 lensType 이 'custom' 이거나 'as'인 주문
    cond_frame = False
    cond_lens = False
    if 'frameType' in df.columns:
        cond_frame = df['frameType'].astype(str).str.lower().isin(['custom', 'as'])
    if 'lensType' in df.columns:
        cond_lens = df['lensType'].astype(str).str.lower().isin(['custom', 'as'])
    
    # 테/렌즈 정보가 아예 없는 주문(클립온 등) 포함
    cond_empty_frame = False
    cond_empty_lens = False
    if 'frameType' in df.columns:
        cond_empty_frame = df['frameType'].isna() | (df['frameType'] == "") | (df['frameType'].astype(str).str.lower() == 'nan')
    else:
        cond_empty_frame = pd.Series(True, index=df.index)
        
    if 'lensType' in df.columns:
        cond_empty_lens = df['lensType'].isna() | (df['lensType'] == "") | (df['lensType'].astype(str).str.lower() == 'nan')
    else:
        cond_empty_lens = pd.Series(True, index=df.index)
        
    cond_clipon = cond_empty_frame & cond_empty_lens
    
    target_df = df[cond_frame | cond_lens | cond_clipon].copy()
    if target_df.empty: return pd.DataFrame()

    # 조건 2: 담당자 매칭
    cond_staff1 = False
    cond_staff2 = False
    if 'statusDetail.lensStaff' in target_df.columns:
        cond_staff1 = target_df['statusDetail.lensStaff'].astype(str) == str(selected_staff)
    if 'statusDetail.frameStaff' in target_df.columns:
        cond_staff2 = target_df['statusDetail.frameStaff'].astype(str) == str(selected_staff)
    
    my_df = target_df[cond_staff1 | cond_staff2].copy()
    if my_df.empty: return pd.DataFrame()

    # 헬퍼 함수 1: 전화번호 파싱
    def parse_contacts(c_data):
        if not c_data or str(c_data).strip() == "" or str(c_data).lower() == 'nan': 
            return ""
        c_str = str(c_data).strip()
        import re
        phones = re.findall(r"(?:010|02|03[1-3]|04[1-4]|05[1-5]|06[1-4])[-.]?\d{3,4}[-.]?\d{4}", c_str)
        if phones: return ", ".join(phones)
        return c_str

    # 헬퍼 함수 2: 테 정보 예쁘게 파싱
    def clean_prefix(val):
        if pd.isna(val) or str(val).lower() == 'nan': return ""
        v = str(val).strip()
        import re
        v = re.sub(r'^frame_size_', '', v, flags=re.IGNORECASE)
        v = re.sub(r'^(?:[a-z]+_)?front_color_', '', v, flags=re.IGNORECASE)
        v = re.sub(r'^front_', '', v, flags=re.IGNORECASE)
        v = re.sub(r'^temple_(?:[a-z]+_)?(?:temple_color_)?(?:color_)?', '', v, flags=re.IGNORECASE)
        return v

    def build_frame_info(row):
        size = clean_prefix(row.get('frame.size', ''))
        color = clean_prefix(row.get('frame.color', ''))
        front = clean_prefix(row.get('frame.front', ''))
        temple = clean_prefix(row.get('frame.temple', ''))
        
        res = ""
        if front: res += f"👓 {front}"
        if size: res += f" ({size})"
        if color: res += f" 🎨 {color}"
        if temple: res += f" 🦵 {temple}"
        return res.strip()

    # 헬퍼 함수 3: 렌즈 정보 파싱
    def parse_lens_skus(skus_data):
        if pd.isna(skus_data) or str(skus_data).lower() == 'nan' or skus_data == "":
            return ""
        try:
            import ast
            import re
            s_list = ast.literal_eval(skus_data) if isinstance(skus_data, str) else skus_data
            if isinstance(s_list, list) and s_list:
                main_sku = str(s_list[0])
                parts = main_sku.split('-')
                brand_key = parts[0] if len(parts) > 0 else ""
                
                idx_pos = -1
                for i, p in enumerate(parts):
                    if re.match(r'^1\.[5-9]\d*$', p):
                        idx_pos = i; break

                refractive_index = parts[idx_pos] if idx_pos != -1 else ""
                mid_parts = parts[1:idx_pos] if idx_pos != -1 else parts[1:]
                l_type = mid_parts[0] if len(mid_parts) > 0 else ""
                
                main_str = f"[{brand_key.capitalize()}] {l_type} {refractive_index}".strip()
                main_str = re.sub(r'\s+', ' ', main_str)

                # 옵션 파싱 (간략화)
                options = [str(x) for x in s_list[1:]]
                opt_strs = []
                for opt in options:
                    o = re.sub(r'^(zeiss-[a-z]+-|nikon-[a-z]+-|chemi-[a-z]+-|varilux-[a-z]+-|baseColor_|mirrorColor_)', '', opt, flags=re.IGNORECASE)
                    if o and o.lower() != "nan": opt_strs.append(o)

                unique_opts = list(dict.fromkeys(opt_strs))
                opt_str = ", ".join(unique_opts)

                if opt_str: return f"{main_str} / {opt_str}"
                return main_str

        except Exception: return str(skus_data)
        return str(skus_data)

    results = []
    for _, row in my_df.iterrows():
        frame_info = build_frame_info(row)
        
        l_lens_raw = parse_lens_skus(row.get('lens.left.skus', ''))
        r_lens_raw = parse_lens_skus(row.get('lens.right.skus', ''))
        
        l_lens_str = f"🅻 {l_lens_raw}" if l_lens_raw else ""
        r_lens_str = f"🆁 {r_lens_raw}" if r_lens_raw else ""

        f_type = str(row.get('frameType', '')).strip().lower()
        l_type = str(row.get('lensType', '')).strip().lower()
        
        has_frame_detail = bool(frame_info)
        has_lens_detail = bool(l_lens_str or r_lens_str)
        
        if not has_frame_detail and not has_lens_detail:
            order_type_str = "클립온"
        elif f_type == 'custom' or l_type == 'custom':
            order_type_str = "신규"
        elif f_type == 'as' or l_type == 'as':
            order_type_str = "AS주문"
        else:
            order_type_str = "기타"

        createdAt = row.get('createdAt', '')
        date_str = pd.to_datetime(createdAt, errors='coerce').strftime('%Y-%m-%d') if createdAt else ""

        results.append({
            'key_id': row['id'],
            '접수일': date_str,
            '배송메모': row.get('deliveryDetail.memo', ''),
            '주문타입': order_type_str,
            '주문번호': row.get('code', ''),
            '이름': row.get('customer.name', ''),
            '전화번호': parse_contacts(row.get('customer.contacts', '')),
            '테정보': frame_info,
            'L렌즈': l_lens_str,
            'R렌즈': r_lens_str,
        })

    final_df = pd.DataFrame(results)
    if not final_df.empty:
        final_df = final_df.sort_values(by='접수일', ascending=False)
    
    return final_df

# ==========================================
# [5. 메인 UI 함수]
# ==========================================
def main():
    if 'hidden_delivered_ids' not in st.session_state:
        st.session_state['hidden_delivered_ids'] = set()

    try:
        from bms_automation import open_bms_popup
    except ImportError:
        open_bms_popup = None

    # --- 사이드바 ---
    st.sidebar.title("설정")
    
    if st.sidebar.button("🔄 화면 새로고침"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.markdown("---")
    
    if st.sidebar.button("👁️ 숨긴 항목 다시 보기"):
        st.session_state['hidden_delivered_ids'] = set(); st.rerun()
    
    st.sidebar.markdown("---")

    # --- 데이터 로드 및 담당자 선택 ---
    df = load_data()
    if df.empty: st.warning("데이터가 없습니다."); return

    all_staff = set()
    if 'statusDetail.lensStaff' in df.columns: all_staff.update(df['statusDetail.lensStaff'].dropna().astype(str).unique())
    if 'statusDetail.frameStaff' in df.columns: all_staff.update(df['statusDetail.frameStaff'].dropna().astype(str).unique())
    raw_staff_list = [s for s in all_staff if s and s.strip() != "" and s != "nan"]
    def staff_sort_key(name):
        n = name.lower().strip()
        if n == 'sen': return 0
        elif n == 'joel': return 1
        elif n == 'lily': return 2
        return 100
    staff_list = sorted(raw_staff_list, key=lambda x: (staff_sort_key(x), x))
    
    st.sidebar.header("담당자 선택")
    selected_staff = st.sidebar.selectbox("이름을 선택하세요", staff_list)

    # --- 메인 화면 ---
    st.title(f"📦 {selected_staff}님의 수령피드백 관리")
    result_df = process_delivered_data(df, selected_staff)
    
    if result_df.empty: st.info(f"최근 수령피드백 내역이 없습니다."); return

    display_df = result_df[~result_df['key_id'].isin(st.session_state['hidden_delivered_ids'])].copy()

    if display_df.empty: st.balloons(); st.success("모든 건을 확인했습니다! 🎉"); return
    
    # ---------------------------------------------------------
    # [1. 표 영역]
    # ---------------------------------------------------------
    st.markdown(f"**확인 대기 건수: {len(display_df)}건**")
    st.caption("✨ '팝업'에 체크하면 자동으로 브라우저가 열리고 해당 주문을 조회합니다.")
    st.divider()

    if 'delivered_current_page' not in st.session_state: st.session_state['delivered_current_page'] = 1
    ITEMS_PER_PAGE = 20
    total_pages = max(1, (len(display_df) - 1) // ITEMS_PER_PAGE + 1)
    if st.session_state['delivered_current_page'] > total_pages: st.session_state['delivered_current_page'] = total_pages
    current_page = st.session_state['delivered_current_page']
    
    if 'delivered_reset_counter' not in st.session_state:
        st.session_state['delivered_reset_counter'] = 0

    # 컬럼 구조
    view_cols = ['key_id', '배송메모', '주문타입', '주문번호', '접수일', '이름', '전화번호', '테정보', 'L렌즈', 'R렌즈']
    final_view = display_df[[c for c in view_cols if c in display_df.columns]].copy()
    
    final_view.insert(0, "확인", False)
    final_view.insert(3, "팝업", False)

    start_idx = (current_page - 1) * ITEMS_PER_PAGE
    paged_view = final_view.iloc[start_idx:start_idx + ITEMS_PER_PAGE].copy()

    # 컬럼 크기 재설정
    edited_df = st.data_editor(
        paged_view,
        column_config={
            "확인": st.column_config.CheckboxColumn("완료", width="small"),
            "key_id": None,
            "배송메모": st.column_config.TextColumn("배송메모", width="large"),
            "접수일": st.column_config.TextColumn("접수일", width="small"),
            "팝업": st.column_config.CheckboxColumn("BMS 조회", width="small"),
            "주문타입": st.column_config.TextColumn("주문타입", width="small"),
            "주문번호": st.column_config.TextColumn("주문번호", width="medium"),
            "이름": st.column_config.TextColumn("이름", width="small"),
            "전화번호": st.column_config.TextColumn("전화번호", width="medium"),
            "테정보": st.column_config.TextColumn("테정보", width="large"),
            "L렌즈": st.column_config.TextColumn("L렌즈", width="medium"),
            "R렌즈": st.column_config.TextColumn("R렌즈", width="medium"),
        },
        column_order=['확인', '배송메모', '주문타입', '주문번호', '접수일', '팝업', '이름', '전화번호', 
                      '테정보', 'L렌즈', 'R렌즈'],
        height=750, hide_index=True, width="stretch", 
        key=f"delivered_table_page_{current_page}_{st.session_state['delivered_reset_counter']}"
    )

    # 페이지네이션
    col1, col2, col3 = st.columns([1, 3, 1])
    with col1:
        if current_page > 1 and st.button("◀ 이전"): st.session_state['delivered_current_page'] -= 1; st.rerun()
    with col2: st.markdown(f"<div style='text-align: center;'>Page {current_page} / {total_pages}</div>", unsafe_allow_html=True)
    with col3:
        if current_page < total_pages and st.button("다음 ▶"): st.session_state['delivered_current_page'] += 1; st.rerun()

    # --- [로직 처리] ---
    rerun_needed = False
    
    # 1. 완료 처리
    if not edited_df[edited_df["확인"] == True].empty:
        for jids in edited_df[edited_df["확인"] == True]['key_id']:
             for rid in str(jids).split(','): st.session_state['hidden_delivered_ids'].add(rid.strip())
        rerun_needed = True

    # 2. 팝업 자동화 처리
    if not edited_df[edited_df["팝업"] == True].empty:
        target_rows = edited_df[edited_df["팝업"] == True]
        for _, row in target_rows.iterrows():
            code_val = row.get('주문번호', '')
            cust_name = row.get('이름', '')
            
            auto_id = selected_staff
            auto_pw = "qlaflqjsgh"
            
            if open_bms_popup:
                st.toast(f"🚀 {cust_name} ({code_val}) 조회 중...", icon="🤖")
                if open_bms_popup(cust_name, code_val, auto_id, auto_pw):
                    st.toast("✅ 팝업 열기 성공")
                else:
                    st.error("팝업 열기 실패")
            else:
                st.error("자동화 모듈 없음")
        
        st.session_state['delivered_reset_counter'] += 1
        rerun_needed = True

    if rerun_needed:
        st.rerun()

if __name__ == "__main__":
    main()