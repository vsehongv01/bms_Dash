import streamlit as st
import pandas as pd
import altair as alt
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime

# ==========================================
# [1. 페이지 설정]
# ==========================================
st.set_page_config(
    page_title="근시관리",
    page_icon="👁️",
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
            st.error("Supabase URL or Key is missing.")
            return pd.DataFrame()
        
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        all_data = []
        
        COLS = [
            "id", "createdAt",
            '"customer.name"', '"customer.birthday"', '"customer.contacts"',
            '"lens.left.skus"', '"lens.right.skus"',
            '"optometry.data.optimal.left.sph"', '"optometry.data.optimal.right.sph"'
        ]
        cols = ",".join(COLS)
        
        offset = 0
        page_size = 1000
        loading_text = st.empty()
        
        while True:
            loading_text.text(f"⏳ 데이터 로드 중... ({offset}건 완료)")
            
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
        st.error(f"데이터 로드 중 오류: {e}")
        return pd.DataFrame()

# ==========================================
# [4. 나이 계산 및 필터링]
# ==========================================
def calculate_age(birthday_str):
    if not birthday_str or pd.isna(birthday_str):
        return None
    try:
        # Check lengths or formats. Common formats: YYYY-MM-DD or YYYYMMDD
        birthday_str = str(birthday_str).strip()
        # Some simple cleaning if it contains timezone info
        if 'T' in birthday_str:
            birthday_str = birthday_str.split('T')[0]
            
        bday = pd.to_datetime(birthday_str, errors='coerce')
        if pd.isna(bday):
            return None
            
        today = pd.Timestamp.today()
        # Calculate age
        age = today.year - bday.year - ((today.month, today.day) < (bday.month, bday.day))
        return age
    except Exception:
        return None

def process_myopia_data(df):
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
        
    # Calculate age
    df['age'] = df['customer.birthday'].apply(calculate_age)
    
    # Filter for age <= 17
    df_youth = df[df['age'] <= 17].copy()
    
    if df_youth.empty:
        return df_youth, pd.DataFrame()
        
    # Helper to check for myopia control lens ('sim' in skus)
    def is_myopia_control(row):
        l_skus = str(row.get('lens.left.skus', '')).lower()
        r_skus = str(row.get('lens.right.skus', '')).lower()
        
        return 'sim' in l_skus or 'sim' in r_skus
        
    df_youth['is_myopia_control'] = df_youth.apply(is_myopia_control, axis=1)
    
    # Myopia control lens users
    df_myopia_control = df_youth[df_youth['is_myopia_control']].copy()
    # Format data for display
    def format_row(row):
        createdAt = row.get('createdAt', '')
        date_str = pd.to_datetime(createdAt, errors='coerce').strftime('%Y-%m-%d') if createdAt else ""
        
        # Extract phone from contacts for better uniqueness
        contacts_raw = str(row.get('customer.contacts', ''))
        # Using a very simple extraction or just using the raw string if parsing fails
        # In a real app we might parse the JSON, but raw string is often enough for a unique hash
        uid = f"{row.get('customer.name', '')}_{contacts_raw}"
        
        return {
            'uid': uid,
            'id': row.get('id', ''),
            '이름': row.get('customer.name', ''),
            '나이': row.get('age', ''),
            '생년월일': row.get('customer.birthday', ''),
            '접수일': date_str,
            'L렌즈 SKUs': str(row.get('lens.left.skus', '')).replace('[', '').replace(']', '').replace("'", ""),
            'R렌즈 SKUs': str(row.get('lens.right.skus', '')).replace('[', '').replace(']', '').replace("'", ""),
            'L SPH': row.get('optometry.data.optimal.left.sph', ''),
            'R SPH': row.get('optometry.data.optimal.right.sph', '')
        }
        
    view_youth = pd.DataFrame([format_row(row) for _, row in df_youth.iterrows()])
    view_myopia = pd.DataFrame([format_row(row) for _, row in df_myopia_control.iterrows()])
    
    # Sort by date descending if not empty
    if not view_youth.empty and '접수일' in view_youth.columns:
        view_youth = view_youth.sort_values(by='접수일', ascending=True).reset_index(drop=True)
    if not view_myopia.empty and '접수일' in view_myopia.columns:
        view_myopia = view_myopia.sort_values(by='접수일', ascending=True).reset_index(drop=True)
        
    return view_youth, view_myopia

# ==========================================
# [4.5 UI 헬퍼 함수]
# ==========================================
def render_grouped_table(df, page=1, items_per_page=10):
    if df.empty:
        st.info("데이터가 없습니다.")
        return 0
        
    # Group by uid
    grouped = df.groupby('uid')
    
    # We want to show the EARLIEST record in the main line, and the rest in the history
    unique_records = []
    
    for uid, group in grouped:
        # Since we sorted ascending earlier, the first row is the earliest
        earliest = group.iloc[0]
        history = group.iloc[1:]
        
        unique_records.append({
            'earliest': earliest,
            'history': history,
            'count': len(group)
        })
        
    # Sort unique records by earliest date descending for display
    unique_records.sort(key=lambda x: str(x['earliest']['접수일']) if x['earliest']['접수일'] else "", reverse=True)
    
    total_items = len(unique_records)
    total_pages = max(1, (total_items - 1) // items_per_page + 1)
    
    # Pagination slicing
    start_idx = int(page - 1) * int(items_per_page)
    end_idx = start_idx + int(items_per_page)
    paged_records = unique_records[start_idx:end_idx]
    
    for record in paged_records:
        earliest = record['earliest']
        history = record['history']
        count = record['count']
        
        name = earliest['이름']
        age = earliest['나이']
        date_str = earliest['접수일']
        
        expander_title = f"👤 {name} (나이: {age}세) | 최초 검안일: {date_str} | 총 주문 건수: {count}건"
        
        with st.expander(expander_title):
            # Show original record
            st.markdown(f"**최초 기록 ({date_str})**")
            st.dataframe(pd.DataFrame([earliest]).drop(columns=['uid', 'id']), use_container_width=True, hide_index=True)
            
            if not history.empty:
                st.markdown("**이후 기록**")
                # Sort history descending so newest is first
                history_desc = history.sort_values(by='접수일', ascending=False)
                st.dataframe(history_desc.drop(columns=['uid', 'id']), use_container_width=True, hide_index=True)
                
    return total_pages

# ==========================================
# [5. 메인 UI 함수]
# ==========================================
def main():
    st.title("👁️ 근시관리 페이지")
    st.markdown("만 17세 이하 고객들의 근시 진행 관리 및 근시 억제 렌즈 착용 현황을 확인합니다.")
    
    if st.button("🔄 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()
        
    st.divider()
    
    df = load_data()
    
    if df.empty:
        st.warning("데이터를 불러올 수 없거나 데이터가 없습니다.")
        return
        
    df_youth, df_myopia = process_myopia_data(df)
    
    colA, colB = st.columns([1, 1])
    
    uid_youth_count = len(df_youth['uid'].unique()) if not df_youth.empty and 'uid' in df_youth.columns else 0
    uid_myopia_count = len(df_myopia['uid'].unique()) if not df_myopia.empty and 'uid' in df_myopia.columns else 0
    
    with colA:
        st.metric("만 17세 이하 고객 수 (순수 고객 기준)", f"{uid_youth_count} 명")
    with colB:
        st.metric("근시 억제 렌즈 착용 수 (순수 고객 기준)", f"{uid_myopia_count} 명")
        
    # --- 차트 영역 ---
    if uid_youth_count > 0:
        st.subheader("📊 근시 억제 렌즈 사용자 비율 (전체고객대비)")
        
        control_count = uid_myopia_count
        general_count = uid_youth_count - control_count
        
        chart_data = pd.DataFrame({
            "Category": ["근시 억제 렌즈 사용자 (sim)", "일반 렌즈 사용자"],
            "Count": [control_count, general_count]
        })
        
        donut_chart = alt.Chart(chart_data).mark_arc(innerRadius=50).encode(
            theta=alt.Theta(field="Count", type="quantitative"),
            color=alt.Color(field="Category", type="nominal", scale=alt.Scale(domain=["근시 억제 렌즈 사용자 (sim)", "일반 렌즈 사용자"], range=["#1f77b4", "#cccccc"])),
            tooltip=['Category', 'Count']
        ).properties(
            title="만 17세 이하 사용자 비율 (중복 제외)",
            height=300
        )
        
        st.altair_chart(donut_chart, use_container_width=True)
    
    st.divider()
    
    # --- 표 영역 (Pagination 적용된 Table 2 만 표시) ---
    st.subheader("👓 근시 억제 렌즈 사용자 목록")
    
    if 'myopia_page' not in st.session_state:
        st.session_state['myopia_page'] = 1
        
    ITEMS_PER_PAGE = 10
    
    # Render table and get total pages
    total_pages = render_grouped_table(df_myopia, page=st.session_state['myopia_page'], items_per_page=ITEMS_PER_PAGE)
    
    # Pagination Controls
    if total_pages > 0:
        # Adjust session state if it somehow exceeds total pages
        if st.session_state['myopia_page'] > total_pages:
            st.session_state['myopia_page'] = total_pages
            
        col1, col2, col3 = st.columns([1, 3, 1])
        with col1:
            if st.session_state['myopia_page'] > 1:
                if st.button("◀ 이전 페이지"):
                    st.session_state['myopia_page'] -= 1
                    st.rerun()
        with col2:
            st.markdown(f"<div style='text-align: center; font-weight: bold;'>Page {st.session_state['myopia_page']} / {total_pages}</div>", unsafe_allow_html=True)
        with col3:
            if st.session_state['myopia_page'] < total_pages:
                if st.button("다음 페이지 ▶"):
                    st.session_state['myopia_page'] += 1
                    st.rerun()
        
    st.divider()
    
    # --- 근시 증가 그래프 (Future) ---
    st.subheader("📈 근시 증감 그래프 (추후 업데이트 예정)")
    st.info("추후 근시 억제 렌즈 이용자들의 데이터를 1년 단위로 추적하여, `left.sph`와 `right.sph`의 변화량을 기록하는 그래프가 이 영역에 추가될 예정입니다.")
    # Placeholder for future logic
    # Example placeholder:
    # df_history = load_historical_data()
    # plot_myopia_progression(df_history)

if __name__ == "__main__":
    main()
