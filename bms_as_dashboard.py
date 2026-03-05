import streamlit as st
import pandas as pd
import altair as alt
import os
from dotenv import load_dotenv
from supabase import create_client, Client
import sys
import subprocess
import time
from datetime import datetime

# ==========================================
# [1. 페이지 설정]
# ==========================================
st.set_page_config(
    page_title="BMS 담당자별 AS 관리",
    page_icon="🛠️",
    layout="wide"
)

# ==========================================
# [2. 설정 및 상수]
# ==========================================
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TARGET_TABLE = "bms_orders"
BMS_MAIN_URL = "https://bms.breezm.com/order"

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
        
        # 🌟 핵심 1: 무거운 전체 열(*) 대신 대시보드에 표시할 필수 열만 콕 집어서 요청 (속도 수십 배 향상)
        COLS = [
            "id", "createdAt", "status", "code", "frameType", "lensType",
            '"statusDetail.lensStaff"', '"statusDetail.frameStaff"', 
            '"customer.name"', '"customer.contacts"',
            '"frame.size"', '"frame.color"', '"frame.front"', '"frame.temple_color"', '"frame.temple"',
            '"lens.left.skus"', '"lens.right.skus"',
            '"optometry.data.optimal.left.sph"', '"optometry.data.optimal.left.cyl"', '"optometry.data.optimal.left.axi"', '"optometry.data.optimal.left.add"', '"optometry.data.optimal.left.pd"',
            '"optometry.data.optimal.right.sph"', '"optometry.data.optimal.right.cyl"', '"optometry.data.optimal.right.axi"', '"optometry.data.optimal.right.add"', '"optometry.data.optimal.right.pd"',
            '"data.las.referenceId"', '"data.las.classification"', '"data.las.comment"',
            '"data.fas.referenceId"', '"data.fas.classification"', '"data.fas.comment"'
        ]
        cols = ",".join(COLS)
        
        # 🌟 핵심 2: 1000개씩 나눠서 가져오기 (서버 과부하 원천 차단)
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
                break # 가져온 게 1000개 미만이면 마지막 페이지임
                
            offset += page_size
            
        loading_text.empty() # 완료되면 안내 문구 삭제
        
        return pd.DataFrame(all_data) if all_data else pd.DataFrame()
        
    except Exception as e:
        st.error(f"전체 데이터 로드 중 오류: {e}")
        return pd.DataFrame()

# ==========================================
# [AS 분류 번역 및 스타일링 사전]
# ==========================================
TRANSLATION_MAP = {
    # 기본
    'exchange': '교환 🔄', 'return': '반품 ↩️', 'repair': '수리 🔧',
    'fitting': '피팅 👓', 'quality_issue': '품질불량 ⚠️',
    
    # 고객 사유
    'change_of_mind': '단순변심', 'change_of_mind_customer': '단순변심 (고객)',
    'discomfort': '착용감 불편', 'fit_dissatisfied': '착용감 불편',
    'design_dissatisfied': '디자인 불만', 'lens_dissatisfied': '렌즈 불편',
    'dissatisfied_customer': '고객 불만',
    'breakage': '파손', 'lost_customer': '분실 (고객 과실)',
    'external_shock_customer': '외부 충격 (고객 과실)',
    'prescription_error': '도수 부적응', 'distortion': '어지러움/왜곡',
    
    # 제품/품질 이슈
    'scratch': '스크래치', 'coating': '코팅 불량', 'bubble': '기포 발생',
    'quality': '품질 불량', 
    'slipping_off': '흘러내림', 'temple_pressure': '관자놀이 눌림',
    'nose_bridge_pressure': '코받침 눌림',
    'mastoid_stimulation': '귀 뒤 통증/자극', 'ear_root_stimulation': '귀 뿌리 통증/자극',
    'asymmetry_frontal': '전면 비대칭', 'asymmetry_planar': '평면 비대칭',
    
    # 내부/가공 이슈
    'machining_error_internal': '가공 실수 (내부)', 'ordering_error_internal': '주문 실수 (내부)',
    'design_error_internal': '설계 오류 (내부)', 'internal_assembly': '조립 불량 (내부)',
    'external_shock_internal': '외부 충격 (내부 과실)', 'lost': '분실 (내부)',
    
    # 변경/기타
    'frame_exchange': '테 교환', 'part_replacement': '부품 교체',
    'change_frame': '테 변경', 'change_grade': '등급 변경', 
    'change_index': '굴절률 변경', 'change_type': '타입 변경',
    'reorder': '재주문', 'redesign': '재설계', 'redo_correction': '재교정',
    'etc': '기타', 'Other': '기타', 'other': '기타'
}

def parse_classification(raw_data):
    if not raw_data: return ""
    try:
        import ast
        data_list = ast.literal_eval(raw_data) if isinstance(raw_data, str) else raw_data
        if isinstance(data_list, list) and len(data_list) > 0:
            item = data_list[0]
            f = item.get('first', ''); s = item.get('second', '')
            f_kor = TRANSLATION_MAP.get(f, f.capitalize())
            s_kor = TRANSLATION_MAP.get(s, s.capitalize())
            return f"{f_kor} > {s_kor}" if s_kor else f_kor
    except: return raw_data
    return str(raw_data)

# ==========================================
# [4. 데이터 처리 로직 (핵심)]
# ==========================================
def process_as_data(df, selected_staff):
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    
    # 전처리
    df['id'] = df['id'].astype(str).str.replace(r'\.0$', '', regex=True)
    df = df.fillna("")

    # Archived 제외
    if 'status' in df.columns:
        df = df[~df['status'].astype(str).str.strip().str.lower().eq('archived')]

    # 매핑 생성
    id_to_code = dict(zip(df['id'], df['code']))
    lens_staff_col = 'statusDetail.lensStaff'
    id_to_lens_staff = dict(zip(df['id'], df[lens_staff_col])) if lens_staff_col in df.columns else {}
    frame_staff_col = 'statusDetail.frameStaff'
    id_to_frame_staff = dict(zip(df['id'], df[frame_staff_col])) if frame_staff_col in df.columns else {}

    def clean_ref_id(ref_val):
        s = str(ref_val).strip().replace('[', '').replace(']', '').replace("'", "")
        try: return str(int(float(s)))
        except: return ""

    results = []

    # [Logic 1] 렌즈 AS
    if 'lensType' in df.columns:
        lens_as_candidates = df[df['lensType'] == 'as'].copy()
        if not lens_as_candidates.empty:
            def check_lens_owner(row):
                ref_id = clean_ref_id(row.get('data.las.referenceId', ''))
                orig_staff = id_to_lens_staff.get(ref_id, "")
                return str(orig_staff) == str(selected_staff)

            my_lens_as = lens_as_candidates[lens_as_candidates.apply(check_lens_owner, axis=1)].copy()
            if not my_lens_as.empty:
                my_lens_as['구분'] = '렌즈 AS'
                my_lens_as['AS 분류'] = my_lens_as.get('data.las.classification', '').apply(parse_classification)
                my_lens_as['AS 사유'] = my_lens_as.get('data.las.comment', '').apply(lambda x: f"💎 {x}")
                my_lens_as['원주문번호'] = my_lens_as['data.las.referenceId'].apply(lambda x: id_to_code.get(clean_ref_id(x), ""))
                results.append(my_lens_as)

    # [Logic 2] 테 AS/피팅
    if 'frameType' in df.columns:
        target_types = ['as', 'fitting']
        frame_as_candidates = df[df['frameType'].isin(target_types)].copy()
        if not frame_as_candidates.empty:
            def check_frame_owner(row):
                ref_id = clean_ref_id(row.get('data.fas.referenceId', ''))
                orig_staff = id_to_frame_staff.get(ref_id, "")
                return str(orig_staff) == str(selected_staff)
            
            my_frame_as = frame_as_candidates[frame_as_candidates.apply(check_frame_owner, axis=1)].copy()
            if not my_frame_as.empty:
                my_frame_as['AS 분류'] = my_frame_as.get('data.fas.classification', '').apply(parse_classification)
                def set_info(row):
                    ft = row.get('frameType', '')
                    cmt = row.get('data.fas.comment', '')
                    if ft == 'as': return '테 AS', f"👓 {cmt}"
                    elif ft == 'fitting': return '피팅', f"🛠️ {cmt}"
                    return ft, cmt
                res = my_frame_as.apply(set_info, axis=1, result_type='expand')
                my_frame_as['구분'] = res[0]
                my_frame_as['AS 사유'] = res[1]
                my_frame_as['원주문번호'] = my_frame_as['data.fas.referenceId'].apply(lambda x: id_to_code.get(clean_ref_id(x), ""))
                results.append(my_frame_as)

    if not results:
        return pd.DataFrame(), pd.DataFrame()
        
    final_df = pd.concat(results, ignore_index=True)
    
    # 날짜 포맷팅
    if 'createdAt' in final_df.columns:
        final_df['접수일'] = pd.to_datetime(final_df['createdAt'], errors='coerce').dt.strftime('%Y-%m-%d')
    else:
        final_df['접수일'] = ""

    final_df['AS 주문번호'] = final_df['code']
    final_df['고객명'] = final_df.get('customer.name', '')
    final_df['key_id'] = final_df['id']
    final_df = final_df.sort_values(by='AS 주문번호', ascending=False)
    
    # [수정] 스마트 링크 생성 (날짜 파라미터 포함)
    def generate_smart_link(date_str):
        if not date_str or date_str == "":
            return BMS_MAIN_URL
        return f"{BMS_MAIN_URL}?startDate={date_str}&endDate={date_str}"

    final_df['BMS_LINK'] = final_df['접수일'].apply(generate_smart_link)

    # 병합 로직
    if not final_df.empty:
        # [수정] 정렬을 통해 렌즈 -> 테 -> 피팅 순서 보장 (데이터 정합성 및 가독성 향상)
        # 원주문번호 기준 정렬 후 구분(렌즈/테/피팅) 정렬
        final_df = final_df.sort_values(by=['원주문번호', '구분'])

        agg_rules = {
            'AS 주문번호': lambda x: x.max(), # 가장 최근 번호 (탐색용)
            '구분': lambda x: "\n".join(x), # 단순 결합 (줄바꿈) - 순서 보장
            'AS 분류': lambda x: "\n".join(x.astype(str)), # 순서대로 결합
            'AS 사유': lambda x: "\n".join(x.astype(str)), # 순서대로 결합
            'key_id': lambda x: ",".join(x.astype(str)),
            'BMS_LINK': 'first' # 링크도 병합 (첫번째 날짜 기준)
        }
        
        grouped_df = final_df.groupby(['원주문번호', '접수일', '고객명'], as_index=False).agg(agg_rules)
        grouped_df = grouped_df.sort_values(by='AS 주문번호', ascending=False)
        return grouped_df, final_df
    
    return final_df, final_df

# ==========================================
# [5. 메인 UI 함수]
# ==========================================
# ==========================================
# [5. 메인 UI 함수]
# ==========================================
def main():
    if 'hidden_ids' not in st.session_state:
        st.session_state['hidden_ids'] = set()

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
    st.sidebar.caption("최근 1주일 데이터를 업데이트합니다.")
    
    if st.sidebar.button("🚀 데이터 업데이트 실행"):
        mode = "1week"
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
        st.session_state['hidden_ids'] = set(); st.rerun()
    
    st.sidebar.markdown("---")

    # --- 데이터 로드 및 담당자 선택 ---
    df = load_data()
    if df.empty: st.warning("데이터가 없습니다."); return

    all_staff = set()
    if 'statusDetail.lensStaff' in df.columns: all_staff.update(df['statusDetail.lensStaff'].dropna().astype(str).unique())
    if 'statusDetail.frameStaff' in df.columns: all_staff.update(df['statusDetail.frameStaff'].dropna().astype(str).unique())
    # [수정] 담당자 정렬 (Sen, Joel, Lily 우선)
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
    st.title(f"🛠️ {selected_staff}님의 AS/피팅 관리")
    result_df, raw_df = process_as_data(df, selected_staff)
    
    if result_df.empty: st.info(f"내역이 없습니다."); return

    display_df = result_df[~result_df['key_id'].isin(st.session_state['hidden_ids'])].copy()

    if display_df.empty: st.balloons(); st.success("모든 건을 확인했습니다! 🎉"); return
    
    # ---------------------------------------------------------
    # [1. 표 영역 (Data Editor로 복귀 & 팝업 체크박스)]
    # ---------------------------------------------------------
    st.markdown(f"**미확인 건수: {len(display_df)}건**")
    st.caption("✨ '팝업'에 체크하면 자동으로 브라우저가 열리고 해당 주문을 조회합니다. (로그인: ID=담당자명, PW=qlaflqjsgh)")
    st.divider()

    if 'current_page' not in st.session_state: st.session_state['current_page'] = 1
    ITEMS_PER_PAGE = 20
    total_pages = max(1, (len(display_df) - 1) // ITEMS_PER_PAGE + 1)
    if st.session_state['current_page'] > total_pages: st.session_state['current_page'] = total_pages
    current_page = st.session_state['current_page']
    
    # [수정] 팝업 체크박스 초기화 이슈 해결을 위한 Dynamic Key 적용
    if 'reset_counter' not in st.session_state:
        st.session_state['reset_counter'] = 0

    # 뷰 컬럼 구성 - [수정] 팝업 컬럼 복구
    view_cols = ['key_id', 'AS 주문번호', '접수일', '구분', 'AS 분류', '원주문번호', 'AS 사유', '고객명']
    final_view = display_df[[c for c in view_cols if c in display_df.columns]].copy()
    final_view.insert(0, "확인", False) # 완료 체크
    final_view.insert(3, "팝업", False) # [복구] 자동화 체크

    start_idx = (current_page - 1) * ITEMS_PER_PAGE
    paged_view = final_view.iloc[start_idx:start_idx + ITEMS_PER_PAGE].copy()

    # [수정] st.data_editor로 복귀 (on_select 제거) & key에 counter 추가
    edited_df = st.data_editor(
        paged_view,
        column_config={
            "확인": st.column_config.CheckboxColumn("완료", width="small"),
            "key_id": None,
            "AS 주문번호": st.column_config.TextColumn("AS 번호", width="medium"),
            "접수일": st.column_config.TextColumn("접수일", width="small"),
            "팝업": st.column_config.CheckboxColumn("BMS 조회", width="small", help="체크 시 자동 조회"), # [복구]
            "구분": st.column_config.TextColumn("구분", width="small"),
            "AS 분류": st.column_config.TextColumn("AS 상세 분류", width="medium"),
            "원주문번호": st.column_config.TextColumn("원주문번호", width="medium"),
            "AS 사유": st.column_config.TextColumn("AS/피팅 사유", width="large"),
            "고객명": st.column_config.TextColumn("고객명", width="medium"),
        },
        column_order=['확인', 'AS 주문번호', '접수일', '팝업', '구분', 'AS 분류', '원주문번호', 'AS 사유', '고객명'],
        height=750, hide_index=True, width="stretch", 
        key=f"as_table_page_{current_page}_{st.session_state['reset_counter']}" # <--- Key 변경으로 강제 리셋
    )

    # 페이지네이션
    col1, col2, col3 = st.columns([1, 3, 1])
    with col1:
        if current_page > 1 and st.button("◀ 이전"): st.session_state['current_page'] -= 1; st.rerun()
    with col2: st.markdown(f"<div style='text-align: center;'>Page {current_page} / {total_pages}</div>", unsafe_allow_html=True)
    with col3:
        if current_page < total_pages and st.button("다음 ▶"): st.session_state['current_page'] += 1; st.rerun()

    # --- [로직 처리] ---
    rerun_needed = False
    
    # 1. 완료 처리
    if not edited_df[edited_df["확인"] == True].empty:
        for jids in edited_df[edited_df["확인"] == True]['key_id']:
             for rid in str(jids).split(','): st.session_state['hidden_ids'].add(rid.strip())
        rerun_needed = True

    # 2. 팝업 자동화 처리 (Checkbox Logic 복구)
    if not edited_df[edited_df["팝업"] == True].empty:
        target_rows = edited_df[edited_df["팝업"] == True]
        for _, row in target_rows.iterrows():
            code_val = row.get('AS 주문번호', '')
            cust_name = row.get('고객명', '')
            
            # [핵심] 하드코딩된 로그인 정보 사용
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
        
        # 체크박스 리셋을 위한 리런 (Counter 증가시켜서 Key 변경)
        st.session_state['reset_counter'] += 1
        rerun_needed = True

    if rerun_needed:
        st.rerun()

    # ---------------------------------------------------------
    # [2. 차트 영역 (하단 복구 & 분리 - 3개 차트)]
    # ---------------------------------------------------------
    st.markdown("---")
    st.subheader("📊 월별 AS/피팅 통계")
    
    if not raw_df.empty and 'AS 분류' in raw_df.columns:
        stats_df = raw_df.copy()
        stats_df['Month'] = pd.to_datetime(stats_df['접수일'], errors='coerce').dt.strftime('%Y-%m')
        stats_df['FirstClass'] = stats_df['AS 분류'].apply(lambda x: str(x).split(' > ')[0].strip() if x else "미지정")
        
        month_list = sorted(stats_df['Month'].dropna().unique(), reverse=True)
        if not month_list: st.info("데이터 없음"); return

        col_sel, _ = st.columns([1, 4])
        with col_sel: selected_month = st.selectbox("📅 조회할 월", month_list)

        m_df = stats_df[stats_df['Month'] == selected_month].copy()
        
        # [추가] 소분류 추출 로직 (FirstClass > SubClass 형태의 텍스트 파싱)
        def get_subclass(class_str):
            if not class_str: return "미지정"
            parts = str(class_str).split(' > ')
            return parts[1].strip() if len(parts) > 1 else parts[0].strip()
            
        m_df['SubClass'] = m_df['AS 분류'].apply(get_subclass)
        
        # [수정] 3개 컬럼으로 분리
        col_lens, col_frame, col_fitting = st.columns(3)
        
        detail_data = pd.DataFrame(); detail_titles = []

        # [차트 함수] 반복되는 차트 생성 로직 함수화
        def create_pie_chart(data, title, key_name, group_col='FirstClass'):
            if data.empty:
                st.info("데이터가 없습니다.")
                return None
            
            counts = data[group_col].value_counts().reset_index()
            counts.columns = ['유형', '건수']
            counts['Label'] = counts['유형'] + " (" + counts['건수'].astype(str) + ")"
            
            selection = alt.selection_point(fields=['유형'], name=key_name + "_select")
            
            base = alt.Chart(counts).encode(theta=alt.Theta("건수", stack=True))
            pie = base.mark_arc(outerRadius=100, innerRadius=60).encode(
                color=alt.Color("Label", scale=alt.Scale(scheme='category20'), legend=alt.Legend(title="분류 (건수)")),
                order=alt.Order("건수", sort="descending"),
                tooltip=["유형", "건수"],
                opacity=alt.condition(selection, alt.value(1), alt.value(0.3))
            ).add_params(selection)
            
            return st.altair_chart(pie, width="stretch", on_select="rerun", key=key_name)

        # 1. 렌즈 차트
        with col_lens:
            st.markdown("#### 🔘 렌즈 AS")
            lens_event = create_pie_chart(m_df[m_df['구분'] == '렌즈 AS'], "렌즈 AS", "chart_lens")
            if lens_event and lens_event.selection:
                sel_data = lens_event.selection.get("chart_lens_select", [])
                if sel_data:
                    types = [item['유형'] for item in sel_data]
                    subset = m_df[(m_df['구분'] == '렌즈 AS') & (m_df['FirstClass'].isin(types))]
                    detail_data = pd.concat([detail_data, subset]) if not detail_data.empty else subset
                    detail_titles.append(f"렌즈: {', '.join(types)}")

        # 2. 테 차트
        with col_frame:
            st.markdown("#### 👓 테 AS")
            frame_event = create_pie_chart(m_df[m_df['구분'] == '테 AS'], "테 AS", "chart_frame")
            if frame_event and frame_event.selection:
                sel_data = frame_event.selection.get("chart_frame_select", [])
                if sel_data:
                    types = [item['유형'] for item in sel_data]
                    subset = m_df[(m_df['구분'] == '테 AS') & (m_df['FirstClass'].isin(types))]
                    detail_data = pd.concat([detail_data, subset]) if not detail_data.empty else subset
                    detail_titles.append(f"테: {', '.join(types)}")

        # 3. 피팅 차트
        with col_fitting:
            st.markdown("#### 🛠️ 피팅")
            # 피팅은 대분류가 모두 "피팅"이므로 소분류(SubClass) 기준으로 그룹핑
            fitting_event = create_pie_chart(m_df[m_df['구분'] == '피팅'], "피팅", "chart_fitting", group_col='SubClass')
            if fitting_event and fitting_event.selection:
                sel_data = fitting_event.selection.get("chart_fitting_select", [])
                if sel_data:
                    types = [item['유형'] for item in sel_data]
                    subset = m_df[(m_df['구분'] == '피팅') & (m_df['SubClass'].isin(types))]
                    detail_data = pd.concat([detail_data, subset]) if not detail_data.empty else subset
                    detail_titles.append(f"피팅: {', '.join(types)}")

        # 상세 내역 표시
        if not detail_data.empty:
            st.markdown("---")
            title_str = " / ".join(detail_titles)
            with st.expander(f"🔍 선택항목 상세 내역: {title_str}", expanded=True):
                st.dataframe(detail_data[['AS 주문번호', '구분', 'AS 분류', 'AS 사유', '고객명', '접수일']], hide_index=True, width="stretch")

if __name__ == "__main__":
    main()