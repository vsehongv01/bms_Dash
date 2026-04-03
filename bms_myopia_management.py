import streamlit as st
import pandas as pd
import altair as alt
import os
import numpy as np
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta

# ==========================================
# [1. 페이지 설정]
# ==========================================
st.set_page_config(page_title="근시관리 시스템", page_icon="👁️", layout="wide")

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
            st.error("Supabase 설정이 누락되었습니다.")
            return pd.DataFrame()
        
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        COLS = [
            "id", "createdAt", "lensType",
            '"customer.name"', '"customer.birthday"', '"customer.contacts"',
            '"lens.left.skus"', '"lens.right.skus"',
            '"optometry.data.optimal.left.sph"', '"optometry.data.optimal.left.cyl"', '"optometry.data.optimal.left.axi"',
            '"optometry.data.optimal.right.sph"', '"optometry.data.optimal.right.cyl"', '"optometry.data.optimal.right.axi"'
        ]
        cols = ",".join(COLS)
        
        offset = 0
        page_size = 1000
        all_data = []
        loading_text = st.empty()
        
        while True:
            loading_text.text(f"⏳ 데이터 로드 중... ({offset}건)")
            response = supabase.table(TARGET_TABLE).select(cols).order("id").range(offset, offset + page_size - 1).execute()
            data = response.data
            if not data: break
            all_data.extend(data)
            if len(data) < page_size: break
            offset += page_size
            
        loading_text.empty()
        return pd.DataFrame(all_data) if all_data else pd.DataFrame()
    except Exception as e:
        st.error(f"데이터 로드 오류: {e}")
        return pd.DataFrame()

# ==========================================
# [4. 데이터 전처리 로직]
# ==========================================
def safe_float(value):
    try:
        if value is None or str(value).strip() == "": return 0.0
        return float(value)
    except:
        return 0.0

def calculate_age(birthday_str):
    if not birthday_str or pd.isna(birthday_str): return None
    try:
        bday_dt = pd.to_datetime(str(birthday_str).split('T')[0])
        today = pd.Timestamp.today()
        return today.year - bday_dt.year - ((today.month, today.day) < (bday_dt.month, bday_dt.day))
    except: return None

def process_myopia_data(df):
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    
    df['age'] = df['customer.birthday'].apply(calculate_age)
    df_youth = df[df['age'] <= 17].copy()
    
    def is_myopia_control(row):
        l_skus = str(row.get('lens.left.skus', '')).lower()
        r_skus = str(row.get('lens.right.skus', '')).lower()
        return 'sim' in l_skus or 'sim' in r_skus
        
    df_youth['is_myopia_control'] = df_youth.apply(is_myopia_control, axis=1)
    df_myopia_control = df_youth[df_youth['is_myopia_control']].copy()

    def format_row(row):
        createdAt = row.get('createdAt', '')
        date_dt = pd.to_datetime(createdAt, errors='coerce')
        return {
            'uid': f"{row.get('customer.name', '')}_{row.get('customer.contacts', '')}",
            '이름': row.get('customer.name', ''),
            '나이': row.get('age', ''),
            '생년월일': row.get('customer.birthday', ''),
            '접수일': date_dt.strftime('%Y-%m-%d') if not pd.isna(date_dt) else "",
            'date_obj': date_dt,
            'year_month': date_dt.strftime('%Y-%m') if not pd.isna(date_dt) else "",
            'lensType': str(row.get('lensType', '')).strip().lower(),
            'L SPH': safe_float(row.get('optometry.data.optimal.left.sph')),
            'L CYL': safe_float(row.get('optometry.data.optimal.left.cyl')),
            'L AXI': safe_float(row.get('optometry.data.optimal.left.axi')),
            'R SPH': safe_float(row.get('optometry.data.optimal.right.sph')),
            'R CYL': safe_float(row.get('optometry.data.optimal.right.cyl')),
            'R AXI': safe_float(row.get('optometry.data.optimal.right.axi'))
        }
        
    view_youth = pd.DataFrame([format_row(row) for _, row in df_youth.iterrows()])
    view_myopia = pd.DataFrame([format_row(row) for _, row in df_myopia_control.iterrows()])
    return view_youth, view_myopia

# ==========================================
# [5. 시각화 로직 - 논문 억제율 반영 및 연간 -0.80D 기준]
# ==========================================
def draw_eye_chart(user_df, side, birthday, age, efficacy_rate, lens_name):
    user_df = user_df.sort_values('date_obj')
    first_visit = user_df.iloc[0]['date_obj']
    base_sph = user_df.iloc[0][f'{side} SPH']
    side_name = "우안(R)" if side == 'R' else "좌안(L)"
    
    # --- 근시 진행 상수 설정 (원장님 지정) ---
    # 일반 단초점 렌즈 착용 시 평균 진행: 연간 -0.80D (6개월당 -0.40D)
    NORMAL_PROG_6MO = -0.40
    # 선택된 렌즈의 억제 효과를 반영한 예상 진행 속도
    TREATED_PROG_6MO = NORMAL_PROG_6MO * (1 - efficacy_rate)
    
    # 차트용 데이터 필터링 (같은 달인 경우 절대값이 큰 SPH 선택)
    real_records = user_df.copy()
    real_records['abs_sph'] = real_records[f'{side} SPH'].abs()
    chart_real_df = real_records.sort_values(by=['year_month', 'abs_sph'], ascending=[True, False]).drop_duplicates('year_month')
    
    # 16세 타겟 날짜 계산
    try:
        bday_dt = pd.to_datetime(birthday)
    except:
        bday_dt = first_visit - timedelta(days=365 * (age if age else 10))
    stop_date = bday_dt + timedelta(days=365 * 16)
    
    timeline = []
    curr = first_visit
    while curr <= stop_date:
        timeline.append(curr)
        curr += timedelta(days=182.5) # 정확히 반년 단위
    
    plot_data = []
    for dt in timeline:
        half_years = (dt - first_visit).days / 182.5
        
        # 시뮬레이션 계산
        norm_sph = base_sph + (half_years * NORMAL_PROG_6MO)
        exp_sph = base_sph + (half_years * TREATED_PROG_6MO)
        
        plot_data.append({'날짜': dt, 'SPH': norm_sph, '구분': '일반 단초점 예상 (연 -0.80D)', '유형': '시뮬레이션'})
        plot_data.append({'날짜': dt, 'SPH': exp_sph, '구분': f'{lens_name} 방어선', '유형': '시뮬레이션'})

    for _, r in chart_real_df.iterrows():
        plot_data.append({'날짜': r['date_obj'], 'SPH': r[f'{side} SPH'], '구분': '실제 검안기록', '유형': '실제'})
    
    df_plot = pd.DataFrame(plot_data)
    
    # Y축 0.25 단위 눈금 설정
    y_min, y_max = df_plot['SPH'].min(), df_plot['SPH'].max()
    y_ticks = np.arange(np.floor(y_min*4)/4 - 0.25, np.ceil(y_max*4)/4 + 0.5, 0.25)

    color_range = ['#E63946', '#F1948A', '#FFC300'] if side == 'R' else ['#1D3557', '#A9CCE3', '#2ECC71']
    
    chart = alt.Chart(df_plot).mark_line(point=True).encode(
        x=alt.X('날짜:T', axis=alt.Axis(values=timeline, format='%y-%m'), title='검안 타임라인'),
        y=alt.Y('SPH:Q', 
                axis=alt.Axis(values=y_ticks.tolist(), format='.2f', grid=True), 
                scale=alt.Scale(zero=False, reverse=True), 
                title='굴절력 (SPH)'),
        color=alt.Color('구분:N', scale=alt.Scale(
            domain=['실제 검안기록', '일반 단초점 예상 (연 -0.80D)', f'{lens_name} 방어선'],
            range=color_range
        ), legend=alt.Legend(orient='top')),
        strokeDash=alt.condition(
            "datum.유형 == '실제'",
            alt.value([0, 0]),
            alt.value([4, 2])
        ),
        tooltip=['날짜', '구분', 'SPH']
    ).properties(height=350, title=f"{side_name} 시뮬레이션").interactive()
    
    return chart

# ==========================================
# [6. 메인 UI]
# ==========================================
def get_care_status(data):
    """lensType==custom 기준 마지막 주문 경과 개월 수로 관리 상태 분류"""
    custom_data = data[data['lensType'] == 'custom']
    if custom_data.empty:
        return None, None
    last_custom_dt = custom_data['date_obj'].max()
    if pd.isna(last_custom_dt):
        return None, None
    now = pd.Timestamp.utcnow() if last_custom_dt.tzinfo is not None else pd.Timestamp.today()
    months = (now - last_custom_dt).days / 30.44
    last_str = last_custom_dt.strftime('%Y-%m-%d')
    if months <= 3:
        return "🟢 눈덜나빠지는중", last_str
    elif months <= 6:
        return "🟡 중간체크필요", last_str
    elif months <= 12:
        return "🟠 효과체크필요", last_str
    else:
        return "🔴 이탈주의", last_str


def sph_delta_label(data, side):
    """첫 기록 → 마지막 기록 SPH 변화량 문자열 반환"""
    col = f'{side} SPH'
    sorted_d = data.sort_values('date_obj')
    if len(sorted_d) < 2:
        val = sorted_d.iloc[0][col]
        return f"{val:+.2f}"
    first = sorted_d.iloc[0][col]
    last  = sorted_d.iloc[-1][col]
    delta = last - first
    sign  = "▼" if delta < 0 else ("▲" if delta > 0 else "─")
    return f"{first:+.2f}→{last:+.2f} ({sign}{abs(delta):.2f})"


def main():
    st.title("👁️ 근시관리 통합 대시보드")

    if 'care_filter' not in st.session_state:
        st.session_state.care_filter = None

    col_refresh, col_search, col_lens = st.columns([1, 3, 4])
    with col_refresh:
        if st.button("🔄 새로고침"):
            st.cache_data.clear()
            st.rerun()

    df_raw = load_data()
    if df_raw.empty:
        st.info("데이터가 없습니다.")
        return

    df_youth, df_myopia = process_myopia_data(df_raw)

    # 상단 지표 (이탈 분류는 unique_users 구성 후 계산되므로 여기선 전체 수만)
    m1, m2, m3, m4 = st.columns(4)
    u_count = len(df_youth['uid'].unique())
    m_count = len(df_myopia['uid'].unique()) if not df_myopia.empty else 0
    m1.metric("대상 청소년", f"{u_count}명")
    m2.metric("근시 억제 렌즈 전체", f"{m_count}명")
    m3.metric("지속 관리", "–", help="아래 목록 참고")
    m4.metric("이탈 추정", "–", help="최근 방문 18개월 초과")

    st.divider()

    if df_myopia.empty:
        st.info("근시 억제 렌즈 사용자가 없습니다.")
    else:
        unique_users = []
        for uid, group in df_myopia.groupby('uid'):
            group_sorted = group.sort_values('date_obj')
            earliest = group_sorted.iloc[0]
            latest   = group_sorted.iloc[-1]
            care_status, last_custom_date = get_care_status(group_sorted)
            unique_users.append({
                'uid': uid,
                '이름': earliest['이름'],
                '나이': latest['나이'],
                '생년월일': earliest['생년월일'],
                'data': group_sorted,
                '최초': earliest['접수일'],
                '최근': latest['접수일'],
                'care_status': care_status,
                'last_custom_date': last_custom_date,
            })
        unique_users.sort(key=lambda x: x['최초'], reverse=True)

        cutoff = pd.Timestamp.utcnow() - pd.DateOffset(months=18)
        def _to_utc(s):
            dt = pd.to_datetime(s, errors='coerce', utc=True)
            return dt
        active_users   = [u for u in unique_users if _to_utc(u['최근']) >= cutoff]
        inactive_users = [u for u in unique_users if _to_utc(u['최근']) <  cutoff]

        # 지표 실제 숫자 업데이트
        m3.metric("지속 관리", f"{len(active_users)}명")
        m4.metric("이탈 추정", f"{len(inactive_users)}명")

        # 관리 알림 요약 배너
        cnt_good   = sum(1 for u in unique_users if u['care_status'] == "🟢 눈덜나빠지는중")
        cnt_mid    = sum(1 for u in unique_users if u['care_status'] == "🟡 중간체크필요")
        cnt_effect = sum(1 for u in unique_users if u['care_status'] == "🟠 효과체크필요")
        cnt_warn   = sum(1 for u in unique_users if u['care_status'] == "🔴 이탈주의")
        if cnt_good or cnt_mid or cnt_effect or cnt_warn:
            st.markdown("#### 📋 관리 알림 현황")
            a1, a2, a3, a4, a5 = st.columns(5)

            def _btn_type(status):
                return "primary" if st.session_state.care_filter == status else "secondary"

            def _toggle(status):
                st.session_state.care_filter = None if st.session_state.care_filter == status else status

            with a1:
                if st.button(f"🟢 눈덜나빠지는중\n{cnt_good}명", use_container_width=True,
                             key="btn_good", type=_btn_type("🟢 눈덜나빠지는중"),
                             help="마지막 custom 주문 1~3개월 경과"):
                    _toggle("🟢 눈덜나빠지는중")
                    st.rerun()
            with a2:
                if st.button(f"🟡 중간체크필요\n{cnt_mid}명", use_container_width=True,
                             key="btn_mid", type=_btn_type("🟡 중간체크필요"),
                             help="마지막 custom 주문 4~6개월 경과"):
                    _toggle("🟡 중간체크필요")
                    st.rerun()
            with a3:
                if st.button(f"🟠 효과체크필요\n{cnt_effect}명", use_container_width=True,
                             key="btn_effect", type=_btn_type("🟠 효과체크필요"),
                             help="마지막 custom 주문 7~12개월 경과"):
                    _toggle("🟠 효과체크필요")
                    st.rerun()
            with a4:
                if st.button(f"🔴 이탈주의\n{cnt_warn}명", use_container_width=True,
                             key="btn_warn", type=_btn_type("🔴 이탈주의"),
                             help="마지막 custom 주문 13개월 이상 경과"):
                    _toggle("🔴 이탈주의")
                    st.rerun()
            with a5:
                if st.button("전체 보기", use_container_width=True, key="btn_clear",
                             disabled=st.session_state.care_filter is None):
                    st.session_state.care_filter = None
                    st.rerun()

            if st.session_state.care_filter:
                st.info(f"**{st.session_state.care_filter}** 필터 적용 중")

            # ── 관리 알림 현황 차트 3개 ──
            ch1, ch2, ch3 = st.columns(3)

            # 차트1: 청소년 중 근시억제 vs 일반 비율 (기존 통계)
            with ch1:
                st.markdown("**📊 청소년 렌즈 비율**")
                u_cnt = len(df_youth['uid'].unique())
                m_cnt = len(df_myopia['uid'].unique()) if not df_myopia.empty else 0
                if u_cnt > 0:
                    cdf = pd.DataFrame({
                        "Cat": ["근시 억제", "일반"],
                        "Val": [m_cnt, u_cnt - m_cnt]
                    })
                    cdf['Label'] = cdf.apply(
                        lambda r: f"{r['Cat']} ({round(r['Val']/u_cnt*100,1)}%)", axis=1
                    )
                    donut1 = alt.Chart(cdf).mark_arc(innerRadius=55).encode(
                        theta="Val:Q",
                        color=alt.Color("Label:N",
                            scale=alt.Scale(range=['#FF6B6B', '#E8E8E8']),
                            legend=alt.Legend(orient="bottom")),
                        tooltip=['Cat', 'Val']
                    ).properties(height=230)
                    st.altair_chart(donut1, use_container_width=True)

            # 차트2: 관리 알림 상태 분포
            with ch2:
                st.markdown("**📋 관리 상태 분포**")
                _sdata = [
                    {"상태": "🟢 눈덜나빠지는중", "인원": cnt_good},
                    {"상태": "🟡 중간체크필요",   "인원": cnt_mid},
                    {"상태": "🟠 효과체크필요",   "인원": cnt_effect},
                    {"상태": "🔴 이탈주의",       "인원": cnt_warn},
                ]
                sdf = pd.DataFrame([s for s in _sdata if s["인원"] > 0])
                if not sdf.empty:
                    donut2 = alt.Chart(sdf).mark_arc(innerRadius=55).encode(
                        theta="인원:Q",
                        color=alt.Color("상태:N", scale=alt.Scale(
                            domain=["🟢 눈덜나빠지는중", "🟡 중간체크필요", "🟠 효과체크필요", "🔴 이탈주의"],
                            range=["#2ECC71", "#F1C40F", "#E67E22", "#E74C3C"]
                        ), legend=alt.Legend(orient="bottom")),
                        tooltip=["상태", "인원"]
                    ).properties(height=230)
                    st.altair_chart(donut2, use_container_width=True)

            # 차트3: 연간 SPH 변화 분포 (억제렌즈 대상자 기준)
            with ch3:
                st.markdown("**📉 연간 근시 진행 분포**")
                _prog_cats = []
                for _u in unique_users:
                    _d = _u['data'].sort_values('date_obj')
                    if len(_d) < 2:
                        _prog_cats.append("데이터 부족")
                        continue
                    _years = (_d.iloc[-1]['date_obj'] - _d.iloc[0]['date_obj']).days / 365.25
                    if _years < 0.25:
                        _prog_cats.append("데이터 부족")
                        continue
                    # 양안 중 더 진행한(더 음수인) 쪽 기준
                    _r_delta = _d.iloc[-1]['R SPH'] - _d.iloc[0]['R SPH']
                    _l_delta = _d.iloc[-1]['L SPH'] - _d.iloc[0]['L SPH']
                    _annual = min(_r_delta, _l_delta) / _years
                    if _annual > 0:
                        _prog_cats.append("호전/유지 (>0D/년)")
                    elif _annual >= -0.50:
                        _prog_cats.append("양호 (0~-0.50D/년)")
                    else:
                        _prog_cats.append("진행 (<-0.50D/년)")

                _prog_series = pd.Series(_prog_cats)
                _prog_df = _prog_series.value_counts().reset_index()
                _prog_df.columns = ["구분", "인원"]
                _total = int(_prog_df[_prog_df["구분"] != "데이터 부족"]["인원"].sum())
                _prog_df["비율"] = _prog_df["인원"].apply(
                    lambda v: f"{round(v/_total*100,1)}%" if _total > 0 else "-"
                )
                _color_domain = ["양호 (0~-0.50D/년)", "진행 (<-0.50D/년)", "호전/유지 (>0D/년)", "데이터 부족"]
                _color_range  = ["#2ECC71", "#E74C3C", "#3498DB", "#BDC3C7"]
                donut3 = alt.Chart(_prog_df).mark_arc(innerRadius=55).encode(
                    theta="인원:Q",
                    color=alt.Color("구분:N", scale=alt.Scale(
                        domain=_color_domain, range=_color_range),
                        legend=alt.Legend(orient="bottom")),
                    tooltip=["구분", "인원", "비율"]
                ).properties(height=230)
                st.altair_chart(donut3, use_container_width=True)
                if _total > 0:
                    _good_n = int(_prog_series[_prog_series == "양호 (0~-0.50D/년)"].count())
                    st.caption(f"양호(-0.50~0D/년) 비율: **{round(_good_n/_total*100,1)}%** ({_good_n}/{_total}명)")

            st.divider()

        # 렌즈 선택 — 페이지 상단 1회
        lens_options = {
            "에실로 스텔리스트 (억제율 67%)": {"rate": 0.67, "name": "스텔리스트"},
            "자이스 마이오케어 (억제율 63%)":  {"rate": 0.63, "name": "마이오케어"},
            "호야 마이오스마트 (억제율 60%)":  {"rate": 0.60, "name": "마이오스마트"},
        }
        with col_lens:
            selected_lens_key = st.radio(
                "🔬 시뮬레이션 렌즈",
                list(lens_options.keys()),
                horizontal=True,
                key="global_lens_radio",
            )
        eff_rate   = lens_options[selected_lens_key]["rate"]
        lens_label = lens_options[selected_lens_key]["name"]

        # 이름 검색
        with col_search:
            search = st.text_input("🔍 이름 검색", "", placeholder="이름 입력…")
        if search:
            active_users   = [u for u in active_users   if search in u['이름']]
            inactive_users = [u for u in inactive_users if search in u['이름']]

        # 관리 알림 필터
        if st.session_state.care_filter:
            active_users   = [u for u in active_users   if u['care_status'] == st.session_state.care_filter]
            inactive_users = [u for u in inactive_users if u['care_status'] == st.session_state.care_filter]

        # ── 지속 관리 중
        st.subheader(f"👓 지속 관리 중 ({len(active_users)}명)")
        for user in active_users:
            data = user['data']
            r_label = sph_delta_label(data, 'R')
            l_label = sph_delta_label(data, 'L')
            visits   = len(data)
            badge = f"  {user['care_status']}" if user['care_status'] else ""
            title = (
                f"👤 {user['이름']} ({user['나이']}세){badge}　"
                f"🔴 R: {r_label}　🔵 L: {l_label}　"
                f"│  방문 {visits}회  │  {user['최초']} ~ {user['최근']}"
            )

            with st.expander(title, expanded=False):

                # ── 통합 검안 기록 테이블
                record_df = data.sort_values('date_obj', ascending=False)[
                    ['접수일', 'R SPH', 'R CYL', 'R AXI', 'L SPH', 'L CYL', 'L AXI']
                ].copy()
                st.dataframe(
                    record_df,
                    column_config={
                        "접수일":  st.column_config.TextColumn("접수일",   width="small"),
                        "R SPH":  st.column_config.NumberColumn("R SPH",  width="small", format="%.2f"),
                        "R CYL":  st.column_config.NumberColumn("R CYL",  width="small", format="%.2f"),
                        "R AXI":  st.column_config.NumberColumn("R AXI°", width="small", format="%.0f"),
                        "L SPH":  st.column_config.NumberColumn("L SPH",  width="small", format="%.2f"),
                        "L CYL":  st.column_config.NumberColumn("L CYL",  width="small", format="%.2f"),
                        "L AXI":  st.column_config.NumberColumn("L AXI°", width="small", format="%.0f"),
                    },
                    hide_index=True,
                    use_container_width=True,
                )

                st.caption(f"일반 단초점 기준 연 -0.80D 진행 가정 / {lens_label} 억제율 {int(eff_rate*100)}% 적용")

                # ── 우안 / 좌안 차트 좌우 나란히
                chart_r = draw_eye_chart(data, 'R', user['생년월일'], user['나이'], eff_rate, lens_label)
                chart_l = draw_eye_chart(data, 'L', user['생년월일'], user['나이'], eff_rate, lens_label)
                col_r, col_l = st.columns(2)
                with col_r:
                    st.altair_chart(chart_r, use_container_width=True)
                with col_l:
                    st.altair_chart(chart_l, use_container_width=True)

        # ── 이탈자
        st.divider()
        st.subheader(f"⚠️ 이탈 추정 ({len(inactive_users)}명)  —  최근 방문 18개월 초과")
        if not inactive_users:
            st.info("이탈 추정 인원이 없습니다.")
        else:
            for user in inactive_users:
                data = user['data']
                r_label = sph_delta_label(data, 'R')
                l_label = sph_delta_label(data, 'L')
                last_dt  = pd.to_datetime(user['최근'], errors='coerce')
                last_dt = pd.to_datetime(user['최근'], errors='coerce', utc=True)
                days_ago = (pd.Timestamp.utcnow() - last_dt).days if pd.notna(last_dt) else 0
                badge = f"  {user['care_status']}" if user['care_status'] else ""
                title = (
                    f"👤 {user['이름']} ({user['나이']}세){badge}　"
                    f"🔴 R: {r_label}　🔵 L: {l_label}　"
                    f"│  마지막 방문: {user['최근']} ({days_ago}일 전)"
                )
                with st.expander(title, expanded=False):
                    record_df = data.sort_values('date_obj', ascending=False)[
                        ['접수일', 'R SPH', 'R CYL', 'R AXI', 'L SPH', 'L CYL', 'L AXI']
                    ].copy()
                    st.dataframe(
                        record_df,
                        column_config={
                            "접수일":  st.column_config.TextColumn("접수일",   width="small"),
                            "R SPH":  st.column_config.NumberColumn("R SPH",  width="small", format="%.2f"),
                            "R CYL":  st.column_config.NumberColumn("R CYL",  width="small", format="%.2f"),
                            "R AXI":  st.column_config.NumberColumn("R AXI°", width="small", format="%.0f"),
                            "L SPH":  st.column_config.NumberColumn("L SPH",  width="small", format="%.2f"),
                            "L CYL":  st.column_config.NumberColumn("L CYL",  width="small", format="%.2f"),
                            "L AXI":  st.column_config.NumberColumn("L AXI°", width="small", format="%.0f"),
                        },
                        hide_index=True,
                        use_container_width=True,
                    )
                    chart_r = draw_eye_chart(data, 'R', user['생년월일'], user['나이'], eff_rate, lens_label)
                    chart_l = draw_eye_chart(data, 'L', user['생년월일'], user['나이'], eff_rate, lens_label)
                    col_r, col_l = st.columns(2)
                    with col_r:
                        st.altair_chart(chart_r, use_container_width=True)
                    with col_l:
                        st.altair_chart(chart_l, use_container_width=True)


if __name__ == "__main__":
    main()