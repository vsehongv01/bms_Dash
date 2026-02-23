import streamlit as st
import pandas as pd
import altair as alt
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import sys
import subprocess
import time
from datetime import datetime

# ==========================================
# [1. 페이지 설정]
# ==========================================
st.set_page_config(
    page_title="BMS 담당자별 신규 주문 관리",
    page_icon="✨",
    layout="wide"
)

# ==========================================
# [2. 설정 및 상수]
# ==========================================
SPREADSHEET_NAME = "BMS_Dashboard_Data"
CREDENTIALS_FILE = "credentials.json"
BMS_MAIN_URL = "https://bms.breezm.com/order"

# ==========================================
# [3. 데이터 로드 함수]
# ==========================================
@st.cache_data(ttl=6000)
def load_data():
    """구글 시트에서 전체 데이터를 로드합니다."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        credentials_path = os.path.join(base_dir, CREDENTIALS_FILE)
        
        creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
        client = gspread.authorize(creds)
        
        try:
            sheet = client.open(SPREADSHEET_NAME).get_worksheet(0)
        except gspread.exceptions.SpreadsheetNotFound:
            st.error(f"구글 시트 '{SPREADSHEET_NAME}'를 찾을 수 없습니다.")
            return pd.DataFrame()
            
        data = sheet.get_all_records()
        if not data:
            return pd.DataFrame()
            
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"데이터 로드 중 오류 발생: {e}")
        return pd.DataFrame()

# ==========================================
# [4. 데이터 처리 로직 (신규주문)]
# ==========================================
def process_new_data(df, selected_staff):
    if df.empty: return pd.DataFrame()
    
    # 전처리
    df['id'] = df['id'].astype(str).str.replace(r'\.0$', '', regex=True)
    df = df.fillna("")

    # 당일 기준 2개월 이상 지난 데이터 제외
    if 'createdAt' in df.columns:
        dt_col = pd.to_datetime(df['createdAt'], errors='coerce', utc=True)
        # 60일 전(약 2개월)을 기준으로 필터링
        two_months_ago = pd.Timestamp.now(tz='UTC') - pd.DateOffset(months=2)
        # 날짜가 파싱되지 않은 데이터(NaT)는 일단 보존하고, 날짜가 있는 경우만 비교
        df = df[dt_col.isna() | (dt_col >= two_months_ago)]

    # Archived 및 Delivered 제외
    if 'status' in df.columns:
        df = df[~df['status'].astype(str).str.strip().str.lower().isin(['archived', 'delivered'])]

    # 조건 1: frameType 또는 lensType 이 'custom' 이거나 'as'인 주문
    cond_frame = False
    cond_lens = False
    if 'frameType' in df.columns:
        cond_frame = df['frameType'].astype(str).str.lower().isin(['custom', 'as'])
    if 'lensType' in df.columns:
        cond_lens = df['lensType'].astype(str).str.lower().isin(['custom', 'as'])
    
    # 테/렌즈 정보가 아예 없는 주문도 클립온 등의 목적으로 가져오기 위해 조건 수정
    # frameType/lensType 둘 다 nan이거나 빈 문자열인 경우도 포함
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

    # 조건 2: statusDetail.lensStaff 나 statusDetail.frameStaff 가 지정된 담당자와 일치
    cond_staff1 = False
    cond_staff2 = False
    if 'statusDetail.lensStaff' in target_df.columns:
        cond_staff1 = target_df['statusDetail.lensStaff'].astype(str) == str(selected_staff)
    if 'statusDetail.frameStaff' in target_df.columns:
        cond_staff2 = target_df['statusDetail.frameStaff'].astype(str) == str(selected_staff)
    
    my_df = target_df[cond_staff1 | cond_staff2].copy()
    if my_df.empty: return pd.DataFrame()

    # 헬퍼 함수
    def parse_contacts(c_data):
        if not c_data or str(c_data).strip() == "" or str(c_data).lower() == 'nan': 
            return ""
        
        # 문자열을 파싱
        c_str = str(c_data).strip()
        
        try:
            import ast
            # 파이썬 리스트/딕셔너리 문자열 형태인 경우
            c_list = ast.literal_eval(c_str) if c_str.startswith('[') else c_data
            if isinstance(c_list, list):
                return ", ".join([str(item.get('value', '')) for item in c_list if isinstance(item, dict) and 'value' in item])
        except Exception:
            pass
            
        # JSON 파싱 시전
        try:
            import json
            # 작은따옴표를 큰따옴표로 변환 후 JSON 파싱, 파이썬 불리언 주의
            clean_str = c_str.replace("'", '"').replace("True", "true").replace("False", "false")
            c_list = json.loads(clean_str)
            if isinstance(c_list, list):
                return ", ".join([str(item.get('value', '')) for item in c_list if isinstance(item, dict) and 'value' in item])
        except Exception:
            pass
            
        # 정규표현식으로 전화번호 형태 추출 (만약 파싱 실패시 폴백)
        import re
        phones = re.findall(r"(?:010|02|03[1-3]|04[1-4]|05[1-5]|06[1-4])[-.]?\d{3,4}[-.]?\d{4}", c_str)
        if phones:
            return ", ".join(phones)
            
        return c_str

    def build_frame_info(row):
        cols = ['frame.size', 'frame.color', 'frame.front', 'frame.temple', 'frame.nosepad', 'frame.temple_color']
        parts = [str(row.get(c, '')) for c in cols if str(row.get(c, '')) and str(row.get(c, '')).lower() != 'nan']
        return " / ".join(parts) if parts else ""

    def parse_lens_skus(skus_data):
        if not skus_data or str(skus_data).lower() == 'nan' or skus_data == "": 
            return ""
        try:
            import ast
            s_list = ast.literal_eval(skus_data) if isinstance(skus_data, str) else skus_data
            if isinstance(s_list, list) and s_list:
                return ", ".join([str(x) for x in s_list])
        except: return str(skus_data)
        return str(skus_data)

    def format_val(val, unit):
        s_val = str(val).strip()
        if not s_val or s_val.lower() == "nan": return ""
        return f"{s_val}{unit}"

    results = []
    for _, row in my_df.iterrows():
        # 테/렌즈/도수 문자열 먼저 생성
        frame_info_str = build_frame_info(row)
        
        # 렌즈 정보 (L렌즈 / R렌즈)
        l_lens = parse_lens_skus(row.get('lens.left.skus', ''))
        r_lens = parse_lens_skus(row.get('lens.right.skus', ''))
        lens_info_str = f"L렌즈: {l_lens}\nR렌즈: {r_lens}" if (l_lens or r_lens) else ""

        # 도수 정보
        l_sph = format_val(row.get('optometry.data.optimal.left.sph', ''), 'D')
        l_cyl = format_val(row.get('optometry.data.optimal.left.cyl', ''), 'D')
        l_axi = format_val(row.get('optometry.data.optimal.left.axi', ''), '°')
        l_add = format_val(row.get('optometry.data.optimal.left.add', ''), 'D')
        l_pd  = format_val(row.get('optometry.data.optimal.left.pd', ''), 'mm')
        
        r_sph = format_val(row.get('optometry.data.optimal.right.sph', ''), 'D')
        r_cyl = format_val(row.get('optometry.data.optimal.right.cyl', ''), 'D')
        r_axi = format_val(row.get('optometry.data.optimal.right.axi', ''), '°')
        r_add = format_val(row.get('optometry.data.optimal.right.add', ''), 'D')
        r_pd  = format_val(row.get('optometry.data.optimal.right.pd', ''), 'mm')

        l_opts = (f"L 구면도수(SPH): {l_sph}\nL 난시(CYL): {l_cyl}\nL 난시 축(AXIS): {l_axi}\nL Add: {l_add}\nL PD: {l_pd}")
        r_opts = (f"R 구면도수(SPH): {r_sph}\nR 난시(CYL): {r_cyl}\nR 난시 축(AXIS): {r_axi}\nR Add: {r_add}\nR PD: {r_pd}")
        # 값이 하나도 없지 않은 이상 도수 정보 남김 (전부 비어있다면 표시 x 등)
        has_optometry = any(x for x in [l_sph, l_cyl, l_axi, l_add, l_pd, r_sph, r_cyl, r_axi, r_add, r_pd])
        optometry_info_str = f"[L 도수]\n{l_opts}\n\n[R 도수]\n{r_opts}"
        
        # 주문 타입 판단 로직 수정 (클립온 포함)
        f_type = str(row.get('frameType', '')).strip().lower()
        l_type = str(row.get('lensType', '')).strip().lower()
        
        # 실제 테 사이즈/색상 정보 문자열과 렌즈 도수/SKU 등이 전부 비어있으면 클립온
        has_frame_detail = bool(frame_info_str.strip())
        has_lens_detail = bool(lens_info_str.strip() or has_optometry)
        
        if not has_frame_detail and not has_lens_detail:
            order_type_str = "클립온"
        elif f_type == 'custom' or l_type == 'custom':
            order_type_str = "신규"
        elif f_type == 'as' or l_type == 'as':
            order_type_str = "AS주문"
        else:
            # 기타 경우 (테나 렌즈 정보는 있는데 타입이 애매한 경우)
            order_type_str = "기타"

        createdAt = row.get('createdAt', '')
        date_str = pd.to_datetime(createdAt, errors='coerce').strftime('%Y-%m-%d') if createdAt else ""

        results.append({
            'key_id': row['id'],
            '접수일': date_str,
            '주문타입': order_type_str,
            '주문번호': row.get('code', ''),
            '이름': row.get('customer.name', ''),
            '전화번호': parse_contacts(row.get('customer.contacts', '')),
            '테 정보': frame_info_str,
            '렌즈 정보': lens_info_str,
            '도수 정보': optometry_info_str,
        })

    final_df = pd.DataFrame(results)
    if not final_df.empty:
        final_df = final_df.sort_values(by='접수일', ascending=False)
    
    def generate_smart_link(date_str):
        if not date_str or date_str == "": return BMS_MAIN_URL
        return f"{BMS_MAIN_URL}?startDate={date_str}&endDate={date_str}"
    
    if not final_df.empty:
        final_df['BMS_LINK'] = final_df['접수일'].apply(generate_smart_link)

    return final_df

# ==========================================
# [5. 메인 UI 함수]
# ==========================================
def main():
    if 'hidden_new_ids' not in st.session_state:
        st.session_state['hidden_new_ids'] = set()

    # --- [New] BMS Automation Integration ---
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
    st.sidebar.subheader("데이터 동기화")
    sync_mode = st.sidebar.selectbox("기간 선택", ["최근 1주일 (빠름)", "최근 3개월 (보통)", "전체 기간 (느림)"])
    mode_map = {"최근 1주일 (빠름)": "1week", "최근 3개월 (보통)": "3months", "전체 기간 (느림)": "all"}
    
    if st.sidebar.button("🚀 데이터 업데이트 실행"):
        mode = mode_map[sync_mode]
        progress_bar = st.sidebar.progress(0, text="업데이트 준비 중...")
        status_text = st.sidebar.empty()
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            cmd = [sys.executable, "bms_full_sync.py", mode]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', env=env, bufsize=1, universal_newlines=True)
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None: break
                if line:
                    line = line.strip()
                    if line.startswith("PROGRESS:"):
                        try:
                            _, val = line.split(":")
                            curr, total = map(int, val.strip().split("/"))
                            progress_bar.progress(min(curr / total, 1.0), text=f"수집 중: {curr}/{total}")
                        except: pass
                    else: status_text.caption(f"{line}")
            if process.poll() == 0:
                progress_bar.progress(1.0, text="완료!")
                st.sidebar.success("성공!")
                st.cache_data.clear()
                time.sleep(1); st.rerun()
            else:
                st.sidebar.error("실패")
        except Exception as e: st.sidebar.error(f"에러: {e}")

    if st.sidebar.button("👁️ 숨긴 항목 다시 보기"):
        st.session_state['hidden_new_ids'] = set(); st.rerun()
    
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
    st.title(f"✨ {selected_staff}님의 신규(NEW) 주문 관리")
    result_df = process_new_data(df, selected_staff)
    
    if result_df.empty: st.info(f"내역이 없습니다."); return

    display_df = result_df[~result_df['key_id'].isin(st.session_state['hidden_new_ids'])].copy()

    if display_df.empty: st.balloons(); st.success("모든 건을 확인했습니다! 🎉"); return
    
    # ---------------------------------------------------------
    # [1. 표 영역]
    # ---------------------------------------------------------
    st.markdown(f"**미확인 건수: {len(display_df)}건**")
    st.caption("✨ '팝업'에 체크하면 자동으로 브라우저가 열리고 해당 주문을 조회합니다. (로그인: ID=담당자명, PW=breeword)")
    st.divider()

    if 'new_current_page' not in st.session_state: st.session_state['new_current_page'] = 1
    ITEMS_PER_PAGE = 20
    total_pages = max(1, (len(display_df) - 1) // ITEMS_PER_PAGE + 1)
    if st.session_state['new_current_page'] > total_pages: st.session_state['new_current_page'] = total_pages
    current_page = st.session_state['new_current_page']
    
    if 'new_reset_counter' not in st.session_state:
        st.session_state['new_reset_counter'] = 0

    view_cols = ['key_id', '주문타입', '주문번호', '접수일', '이름', '전화번호', '테 정보', '렌즈 정보', '도수 정보']
    final_view = display_df[[c for c in view_cols if c in display_df.columns]].copy()
    final_view.insert(0, "확인", False) # 완료 체크
    final_view.insert(3, "팝업", False) # 자동화 체크

    start_idx = (current_page - 1) * ITEMS_PER_PAGE
    paged_view = final_view.iloc[start_idx:start_idx + ITEMS_PER_PAGE].copy()

    edited_df = st.data_editor(
        paged_view,
        column_config={
            "확인": st.column_config.CheckboxColumn("완료", width="small"),
            "key_id": None,
            "접수일": st.column_config.TextColumn("접수일", width="small"),
            "팝업": st.column_config.CheckboxColumn("BMS 조회", width="small", help="체크 시 자동 조회"),
            "주문타입": st.column_config.TextColumn("주문타입", width="small"),
            "주문번호": st.column_config.TextColumn("주문번호", width="medium"),
            "이름": st.column_config.TextColumn("이름", width="small"),
            "전화번호": st.column_config.TextColumn("전화번호", width="medium"),
            "테 정보": st.column_config.TextColumn("테 정보", width="large"),
            "렌즈 정보": st.column_config.TextColumn("렌즈 정보", width="medium"),
            "도수 정보": st.column_config.TextColumn("도수 상세 정보", width="large"),
        },
        column_order=['확인', '주문타입', '주문번호', '접수일', '팝업', '이름', '전화번호', '테 정보', '렌즈 정보', '도수 정보'],
        height=750, hide_index=True, width="stretch", 
        key=f"new_table_page_{current_page}_{st.session_state['new_reset_counter']}"
    )

    # 페이지네이션
    col1, col2, col3 = st.columns([1, 3, 1])
    with col1:
        if current_page > 1 and st.button("◀ 이전"): st.session_state['new_current_page'] -= 1; st.rerun()
    with col2: st.markdown(f"<div style='text-align: center;'>Page {current_page} / {total_pages}</div>", unsafe_allow_html=True)
    with col3:
        if current_page < total_pages and st.button("다음 ▶"): st.session_state['new_current_page'] += 1; st.rerun()

    # --- [로직 처리] ---
    rerun_needed = False
    
    # 1. 완료 처리
    if not edited_df[edited_df["확인"] == True].empty:
        for jids in edited_df[edited_df["확인"] == True]['key_id']:
             for rid in str(jids).split(','): st.session_state['hidden_new_ids'].add(rid.strip())
        rerun_needed = True

    # 2. 팝업 자동화 처리
    if not edited_df[edited_df["팝업"] == True].empty:
        target_rows = edited_df[edited_df["팝업"] == True]
        for _, row in target_rows.iterrows():
            code_val = row.get('주문번호', '')
            cust_name = row.get('이름', '')
            
            auto_id = selected_staff
            auto_pw = "breeword"
            
            if open_bms_popup:
                st.toast(f"🚀 {cust_name} ({code_val}) 조회 중...", icon="🤖")
                if open_bms_popup(cust_name, code_val, auto_id, auto_pw):
                    st.toast("✅ 팝업 열기 성공")
                else:
                    st.error("팝업 열기 실패")
            else:
                st.error("자동화 모듈 없음")
        
        # 체크박스 리셋을 위한 리런
        st.session_state['new_reset_counter'] += 1
        rerun_needed = True

    if rerun_needed:
        st.rerun()

if __name__ == "__main__":
    main()
