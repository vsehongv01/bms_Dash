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
            "id", "createdAt",
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
def main():
    st.title("👁️ 근시관리 통합 대시보드")
    
    if st.button("🔄 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()
        
    df_raw = load_data()
    if df_raw.empty:
        st.info("데이터가 없습니다.")
        return
    
    df_youth, df_myopia = process_myopia_data(df_raw)
    
    st.columns(2)[0].metric("대상 청소년", f"{len(df_youth['uid'].unique())}명")
    st.columns(2)[1].metric("근시 억제 렌즈", f"{len(df_myopia['uid'].unique())}명")
    
    st.divider()
    
    st.subheader("👓 근시 억제 렌즈 사용자 상세 분석")
    
    if not df_myopia.empty:
        unique_users = []
        for uid, group in df_myopia.groupby('uid'):
            group_sorted = group.sort_values('date_obj')
            earliest = group_sorted.iloc[0]
            unique_users.append({
                'uid': uid, '이름': earliest['이름'], '나이': earliest['나이'], 
                '생년월일': earliest['생년월일'], 'data': group_sorted, '최초': earliest['접수일']
            })
        unique_users.sort(key=lambda x: x['최초'], reverse=True)

        # 렌즈 연구 논문 데이터 매핑 (억제율 설정)
        lens_options = {
            "에실로 스텔리스트 (억제율 67%)": {"rate": 0.67, "name": "스텔리스트"},
            "자이스 마이오케어 (억제율 63%)": {"rate": 0.63, "name": "마이오케어"},
            "호야 마이오스마트 (억제율 60%)": {"rate": 0.60, "name": "마이오스마트"}
        }

        for user in unique_users:
            with st.expander(f"👤 {user['이름']} ({user['나이']}세) | 최초방문: {user['최초']} | 전체 기록 {len(user['data'])}건"):
                
                # 시뮬레이션 렌즈 선택 UI
                st.markdown("##### 🔬 시뮬레이션 설정")
                st.caption("일반 렌즈 착용 시 연간 -0.80D 진행을 가정하고, 각 렌즈의 논문상 억제율을 반영한 그래프입니다.")
                selected_lens_key = st.radio(
                    "렌즈 모델 선택:",
                    list(lens_options.keys()),
                    key=f"radio_{user['uid']}",
                    horizontal=True
                )
                
                eff_rate = lens_options[selected_lens_key]["rate"]
                lens_label = lens_options[selected_lens_key]["name"]
                
                st.write("") # 간격
                
                # 우안 섹션
                st.markdown("### 🔴 우안 (Right Eye)")
                cr1, cr2 = st.columns([2, 3])
                with cr1:
                    st.markdown("**[우안 검안 전체 기록]**")
                    r_df = user['data'].sort_values('date_obj', ascending=False)[['접수일', 'R SPH', 'R CYL', 'R AXI']]
                    st.dataframe(r_df, hide_index=True, use_container_width=True)
                with cr2:
                    st.altair_chart(draw_eye_chart(user['data'], 'R', user['생년월일'], user['나이'], eff_rate, lens_label), use_container_width=True)
                
                st.divider()
                
                # 좌안 섹션
                st.markdown("### 🔵 좌안 (Left Eye)")
                cl1, cl2 = st.columns([2, 3])
                with cl1:
                    st.markdown("**[좌안 검안 전체 기록]**")
                    l_df = user['data'].sort_values('date_obj', ascending=False)[['접수일', 'L SPH', 'L CYL', 'L AXI']]
                    st.dataframe(l_df, hide_index=True, use_container_width=True)
                with cl2:
                    st.altair_chart(draw_eye_chart(user['data'], 'L', user['생년월일'], user['나이'], eff_rate, lens_label), use_container_width=True)

    st.divider()
    
    # 통계 도넛 차트
    st.subheader("📊 통계 데이터")
    u_count = len(df_youth['uid'].unique())
    m_count = len(df_myopia['uid'].unique())
    if u_count > 0:
        chart_df = pd.DataFrame({"Cat": ["근시 억제", "일반"], "Val": [m_count, u_count - m_count]})
        chart_df['Label'] = chart_df.apply(lambda r: f"{r['Cat']} ({round(r['Val']/u_count*100, 1)}%)", axis=1)
        donut = alt.Chart(chart_df).mark_arc(innerRadius=70).encode(
            theta="Val:Q", color=alt.Color("Label:N", scale=alt.Scale(range=['#FF6B6B', '#F1F3F5']), legend=alt.Legend(orient="bottom")),
            tooltip=['Cat', 'Val']
        ).properties(height=350)
        st.altair_chart(donut, use_container_width=True)

if __name__ == "__main__":
    main()