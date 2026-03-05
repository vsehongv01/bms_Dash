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
    page_title="BMS 담당자별 신규 주문 관리",
    page_icon="✨",
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
        two_months_ago = pd.Timestamp.now(tz='UTC') - pd.DateOffset(months=2)
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
        
        try:
            import ast
            c_list = ast.literal_eval(c_str) if c_str.startswith('[') else c_data
            if isinstance(c_list, list):
                return ", ".join([str(item.get('value', '')) for item in c_list if isinstance(item, dict) and 'value' in item])
        except Exception: pass
            
        try:
            import json
            clean_str = c_str.replace("'", '"').replace("True", "true").replace("False", "false")
            c_list = json.loads(clean_str)
            if isinstance(c_list, list):
                return ", ".join([str(item.get('value', '')) for item in c_list if isinstance(item, dict) and 'value' in item])
        except Exception: pass
            
        import re
        phones = re.findall(r"(?:010|02|03[1-3]|04[1-4]|05[1-5]|06[1-4])[-.]?\d{3,4}[-.]?\d{4}", c_str)
        if phones: return ", ".join(phones)
        return c_str

    # 헬퍼 함수 2: 테 정보 파싱 (두 개의 변수로 반환하도록 수정)
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
        temple_color = clean_prefix(row.get('frame.temple_color', ''))
        temple = clean_prefix(row.get('frame.temple', ''))
        
        if not temple_color and temple: 
            temple_color = temple

        line1 = f"👓 {front}" if front else ""
        if size: 
            line1 += f" (Size: {size})" if line1 else f"👓 (Size: {size})"
            
        line2_parts = []
        if color: line2_parts.append(f"Front: {color}")
        if temple_color: line2_parts.append(f"Temple: {temple_color}")
        
        line2 = f"🎨 {' | '.join(line2_parts)}" if line2_parts else ""
        
        return line1.strip(), line2.strip()

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
                options = [str(x) for x in s_list[1:]]

                parts = main_sku.split('-')
                brands = {
                    "zeiss": "자이스", "nikon": "니콘", "chemi": "케미",
                    "varilux": "바리락스", "breezm": "브리즘", "tokai": "토카이",
                    "essilor": "에실로", "dagas": "다가스", "eloptical": "이엘옵티컬",
                    "sundayoptical": "선데이옵티컬", "airtable": "에어테이블"
                }
                names = {
                    "clw": "클리어뷰", "clwrx": "클리어뷰Rx", "sl": "스마트라이프", "sv": "단초점",
                    "drvs": "드라이브세이프", "drvsrx": "드라이브세이프Rx", "myocare": "마이오케어",
                    "dg": "디지털", "sldg": "스마트라이프 디지털",
                    "seemxinf": "씨맥스 인피니트", "seemxmsz": "씨맥스", "seemxutz": "씨맥스",
                    "rlxneo": "릴랙씨 네오", "rlxneopl": "릴랙씨 네오", "myse": "마이씨", "bluvpl": "블루라이트 플러스",
                    "prspz": "프레지오", "hno": "홈앤오피스", "solwn": "솔테스", "solwp": "솔테스",
                    "dfree": "디프리", "asp": "비구면", "aspxdrv": "엑스드라이브", "asprx": "비구면Rx",
                    "mfcds": "매직폼", "mfxt": "매직폼XT", "mffrs": "매직폼", "mfst": "매직폼",
                    "phys": "피지오", "physf": "피지오", "cmfmx": "컴포트 맥스", "cmfmxf": "컴포트 맥스",
                    "xrf": "XR", "xrd": "XR", "lbrtyf": "리버티", "lbrty": "리버티",
                    "stellest": "스텔리스트", "hr": "HR"
                }

                brand_key = parts[0].lower() if len(parts) > 0 else ""
                brand_name = f"[{brands.get(brand_key, parts[0])}]" if brand_key else ""

                idx_pos = -1
                for i, p in enumerate(parts):
                    if re.match(r'^1\.[5-9]\d*$', p):
                        idx_pos = i; break

                refractive_index = parts[idx_pos] if idx_pos != -1 else ""

                mid_parts = parts[1:idx_pos] if idx_pos != -1 else parts[1:]
                l_type = ""
                l_name = ""

                if len(mid_parts) > 0:
                    l_type = mid_parts[0]
                    if len(mid_parts) > 1:
                        raw_name = "-".join(mid_parts[1:]).lower()
                        l_name = names.get(raw_name, "-".join(mid_parts[1:]))
                    else:
                        l_name = names.get(l_type.lower(), l_type)

                type_str = f"({l_type})" if l_type else ""
                main_str = f"{brand_name} {l_name}{type_str} {refractive_index}".strip()
                main_str = re.sub(r'\s+', ' ', main_str)

                coatings = {
                    "bgdp": "BGDP", "purebl": "퓨어블루", "perfect": "퍼펙트UV",
                    "dp": "DP", "dd": "드라이브세이프", "pf": "포토퓨전 변색",
                    "gens": "트랜지션스 GenS", "gen8": "트랜지션스 Gen8",
                    "xtractive": "엑스트라액티브", "ush": "USH", "etcuv": "ETC UV",
                    "innermt": "내면MT", "seeuv": "SEE UV", "seecoat": "씨코트",
                    "bluv": "블루라이트", "seeuvbluv": "블루라이트", "nir": "근적외선", 
                    "photoaid": "포토에이드 변색", "varsity": "바시티 변색", 
                    "crizalprevencia": "프리벤시아", "crizalrock": "크리잘락", 
                    "prism": "프리즘", "bp": "BP", "xdrive": "엑스드라이브", "dvsun": "DV선"
                }
                colors = {
                    "brown": "브라운", "gray": "그레이", "grey": "그레이",
                    "green": "그린", "pioneer": "파이오니어", "black": "블랙",
                    "sapphire": "사파이어", "cocoa brown": "코코아브라운",
                    "ice gray": "아이스그레이", "camel brown": "카멜브라운",
                    "shadow orange": "섀도우오렌지", "khaki brown": "카키브라운"
                }

                opt_strs = []
                for opt in options:
                    o = re.sub(r'^(zeiss-[a-z]+-|nikon-[a-z]+-|chemi-[a-z]+-|varilux-[a-z]+-|tokai-[a-z]+-|dagas-[a-z]+-|so-[a-z]+-|el-[a-z]+-|airtable-[a-z]+-|baseColor_|mirrorColor_)', '', opt, flags=re.IGNORECASE)
                    o_lower = o.lower()
                    if o_lower in coatings: opt_strs.append(coatings[o_lower])
                    elif o_lower in colors: opt_strs.append(colors[o_lower])
                    elif "golf" in o_lower: opt_strs.append("골프")
                    elif o_lower and o_lower != "nan": opt_strs.append(o)

                unique_opts = list(dict.fromkeys(opt_strs))
                opt_str = ", ".join(unique_opts)

                if opt_str: return f"{main_str} / {opt_str}"
                return main_str

        except Exception: return str(skus_data)
        return str(skus_data)

    def format_val(val, unit, prefix=""):
        s_val = str(val).strip()
        if not s_val or s_val.lower() == "nan": return ""
        if prefix: return f"{prefix}: {s_val}{unit}"
        return f"{s_val}{unit}"

    results = []
    for _, row in my_df.iterrows():
        # 테 정보 (모델/사이즈와 색상을 분리)
        frame_model, frame_color = build_frame_info(row)
        
        # 렌즈 정보 분리
        l_lens_raw = parse_lens_skus(row.get('lens.left.skus', ''))
        r_lens_raw = parse_lens_skus(row.get('lens.right.skus', ''))
        
        l_lens_str = f"🅻 {l_lens_raw}" if l_lens_raw else ""
        r_lens_str = f"🆁 {r_lens_raw}" if r_lens_raw else ""

        # 도수 정보 분리
        l_sph = format_val(row.get('optometry.data.optimal.left.sph', ''), 'D', 'SPH')
        l_cyl = format_val(row.get('optometry.data.optimal.left.cyl', ''), 'D', 'CYL')
        l_axi = format_val(row.get('optometry.data.optimal.left.axi', ''), '°', 'AXIS')
        l_add = format_val(row.get('optometry.data.optimal.left.add', ''), 'D', 'ADD')
        l_pd  = format_val(row.get('optometry.data.optimal.left.pd', ''), 'mm', 'PD')
        
        r_sph = format_val(row.get('optometry.data.optimal.right.sph', ''), 'D', 'SPH')
        r_cyl = format_val(row.get('optometry.data.optimal.right.cyl', ''), 'D', 'CYL')
        r_axi = format_val(row.get('optometry.data.optimal.right.axi', ''), '°', 'AXIS')
        r_add = format_val(row.get('optometry.data.optimal.right.add', ''), 'D', 'ADD')
        r_pd  = format_val(row.get('optometry.data.optimal.right.pd', ''), 'mm', 'PD')

        l_opts_arr = [x for x in [l_sph, l_cyl, l_axi, l_add, l_pd] if x]
        r_opts_arr = [x for x in [r_sph, r_cyl, r_axi, r_add, r_pd] if x]
        
        l_opts_str = f"[ L ] {' | '.join(l_opts_arr)}" if l_opts_arr else ""
        r_opts_str = f"[ R ] {' | '.join(r_opts_arr)}" if r_opts_arr else ""
        
        # 주문 타입 판단
        has_optometry = bool(l_opts_arr or r_opts_arr)
        f_type = str(row.get('frameType', '')).strip().lower()
        l_type = str(row.get('lensType', '')).strip().lower()
        
        has_frame_detail = bool(frame_model or frame_color)
        has_lens_detail = bool(l_lens_str or r_lens_str or has_optometry)
        
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
            '주문타입': order_type_str,
            '주문번호': row.get('code', ''),
            '이름': row.get('customer.name', ''),
            '전화번호': parse_contacts(row.get('customer.contacts', '')),
            '테(모델/사이즈)': frame_model,
            '테(색상)': frame_color,
            'L렌즈': l_lens_str,
            'R렌즈': r_lens_str,
            'L도수': l_opts_str,
            'R도수': r_opts_str,
        })

    final_df = pd.DataFrame(results)
    if not final_df.empty:
        final_df = final_df.sort_values(by='접수일', ascending=False)
    
    return final_df

# ==========================================
# [5. 메인 UI 함수]
# ==========================================
def main():
    if 'hidden_new_ids' not in st.session_state:
        st.session_state['hidden_new_ids'] = set()

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
    st.caption("✨ '팝업'에 체크하면 자동으로 브라우저가 열리고 해당 주문을 조회합니다. (로그인: ID=담당자명, PW=qlaflqjsgh)")
    st.divider()

    if 'new_current_page' not in st.session_state: st.session_state['new_current_page'] = 1
    ITEMS_PER_PAGE = 20
    total_pages = max(1, (len(display_df) - 1) // ITEMS_PER_PAGE + 1)
    if st.session_state['new_current_page'] > total_pages: st.session_state['new_current_page'] = total_pages
    current_page = st.session_state['new_current_page']
    
    if 'new_reset_counter' not in st.session_state:
        st.session_state['new_reset_counter'] = 0

    # 컬럼 구조 변경
    view_cols = ['key_id', '주문타입', '주문번호', '접수일', '이름', '전화번호', 
                 '테(모델/사이즈)', '테(색상)', 'L렌즈', 'R렌즈', 'L도수', 'R도수']
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
            "접수일": st.column_config.TextColumn("접수일", width="small"),
            "팝업": st.column_config.CheckboxColumn("BMS 조회", width="small", help="체크 시 자동 조회"),
            "주문타입": st.column_config.TextColumn("주문타입", width="small"),
            "주문번호": st.column_config.TextColumn("주문번호", width="medium"),
            "이름": st.column_config.TextColumn("이름", width="small"),
            "전화번호": st.column_config.TextColumn("전화번호", width="medium"),
            "테(모델/사이즈)": st.column_config.TextColumn("테(모델/사이즈)", width="medium"),
            "테(색상)": st.column_config.TextColumn("테(색상)", width="medium"),
            "L렌즈": st.column_config.TextColumn("L렌즈", width="medium"),
            "R렌즈": st.column_config.TextColumn("R렌즈", width="medium"),
            "L도수": st.column_config.TextColumn("L도수", width="large"),
            "R도수": st.column_config.TextColumn("R도수", width="large"),
        },
        column_order=['확인', '주문타입', '주문번호', '접수일', '팝업', '이름', '전화번호', 
                      '테(모델/사이즈)', '테(색상)', 'L렌즈', 'R렌즈', 'L도수', 'R도수'],
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
            auto_pw = "qlaflqjsgh"
            
            if open_bms_popup:
                st.toast(f"🚀 {cust_name} ({code_val}) 조회 중...", icon="🤖")
                if open_bms_popup(cust_name, code_val, auto_id, auto_pw):
                    st.toast("✅ 팝업 열기 성공")
                else:
                    st.error("팝업 열기 실패")
            else:
                st.error("자동화 모듈 없음")
        
        st.session_state['new_reset_counter'] += 1
        rerun_needed = True

    if rerun_needed:
        st.rerun()

if __name__ == "__main__":
    main()