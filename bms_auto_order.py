import streamlit as st
import pandas as pd
import ast
import re
from datetime import datetime
import pytz
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os

# ==========================================
# [1. 설정 및 데이터 로드]
# ==========================================
SPREADSHEET_NAME = "BMS_Dashboard_Data"
CREDENTIALS_FILE = "credentials.json"

@st.cache_data(ttl=600) # 10분 캐시
def load_data():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        base_dir = os.path.dirname(os.path.abspath(__file__))
        credentials_path = os.path.join(base_dir, CREDENTIALS_FILE)
        creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SPREADSHEET_NAME).get_worksheet(0)
        data = sheet.get_all_records()
        return pd.DataFrame(data) if data else pd.DataFrame()
    except Exception as e:
        st.error(f"데이터 로드 중 오류 발생: {e}")
        return pd.DataFrame()

# ==========================================
# [2. 여벌 렌즈 추출 핵심 로직]
# ==========================================
def extract_lens_info(sku_str):
    """SKU 문자열에서 브랜드(회사)와 렌즈구분(ss, ssp 등)을 추출합니다."""
    if pd.isna(sku_str) or str(sku_str).strip() == "" or str(sku_str).lower() == 'nan':
        return None, None
    try:
        s_list = ast.literal_eval(sku_str) if isinstance(sku_str, str) else sku_str
        if isinstance(s_list, list) and len(s_list) > 0:
            main_sku = str(s_list[0])
            parts = main_sku.split('-')
            if len(parts) >= 2:
                brand = parts[0].strip().lower() # 예: chemi
                lens_cat = parts[1].strip().lower() # 예: ss, ssp, pi 등
                return brand, lens_cat
    except Exception:
        pass
    return None, None

def get_today_stock_orders(df):
    """오늘 접수된 여벌렌즈(ss, ssp) 주문을 회사별로 분류하여 반환합니다."""
    if df.empty: return {}

    # 1. 당일 데이터 필터링 (한국 시간 KST 기준)
    kst = pytz.timezone('Asia/Seoul')
    today_date = datetime.now(kst).strftime('%Y-%m-%d')
    
    # createdAt을 KST 기준으로 변환 후 날짜 추출 (에러 발생 시 무시)
    df['date_only'] = pd.to_datetime(df['createdAt'], errors='coerce', utc=True).dt.tz_convert(kst).dt.strftime('%Y-%m-%d')
    df_today = df[df['date_only'] == today_date].copy()

    if df_today.empty: return {}

    # 2. 주문 타입 필터링 (lensType == custom or as)
    if 'lensType' in df_today.columns:
        df_today = df_today[df_today['lensType'].astype(str).str.lower().isin(['custom', 'as'])]

    # 3. ss / ssp 필터링 및 회사별 그룹화
    grouped_orders = {}

    for idx, row in df_today.iterrows():
        l_brand, l_cat = extract_lens_info(row.get('lens.left.skus', ''))
        r_brand, r_cat = extract_lens_info(row.get('lens.right.skus', ''))

        is_l_stock = l_cat in ['ss', 'ssp']
        is_r_stock = r_cat in ['ss', 'ssp']

        if is_l_stock or is_r_stock:
            # L렌즈가 여벌이면 L브랜드 기준, 아니면 R브랜드 기준 (일반적으로 양안 브랜드는 동일함)
            target_brand = l_brand if is_l_stock else r_brand
            
            # 브랜드 이름 한글화 (보기 좋게)
            brand_name_map = {"chemi": "케미", "zeiss": "자이스", "nikon": "니콘", "tokai": "토카이", "breezm": "브리즘", "dagas": "다가스"}
            display_brand = brand_name_map.get(target_brand, target_brand.upper() if target_brand else "기타")

            if display_brand not in grouped_orders:
                grouped_orders[display_brand] = []
            
            # 필요한 데이터만 가공해서 저장
            grouped_orders[display_brand].append({
                "주문번호": row.get('code', ''),
                "이름": row.get('customer.name', ''),
                "L렌즈": row.get('lens.left.skus', ''),
                "R렌즈": row.get('lens.right.skus', ''),
                "L도수 (SPH/CYL/AXIS)": f"{row.get('optometry.data.optimal.left.sph','')} / {row.get('optometry.data.optimal.left.cyl','')} / {row.get('optometry.data.optimal.left.axi','')}",
                "R도수 (SPH/CYL/AXIS)": f"{row.get('optometry.data.optimal.right.sph','')} / {row.get('optometry.data.optimal.right.cyl','')} / {row.get('optometry.data.optimal.right.axi','')}",
            })

    return grouped_orders

# ==========================================
# [3. 메인 화면 UI]
# ==========================================
def main():
    st.title("🤖 주문 자동화")
    st.markdown("당일 생성된 주문 중 **여벌렌즈(ss, ssp)**만 추출하여 제조사별로 분류합니다.")
    st.divider()

    df = load_data()

    if st.button("🚀 당일 여벌렌즈 자동주문 조회", type="primary", use_container_width=True):
        if df.empty:
            st.warning("구글 시트에서 데이터를 불러오지 못했습니다.")
            return

        with st.spinner("당일 주문 데이터를 분석 중입니다..."):
            grouped_data = get_today_stock_orders(df)
            
        if not grouped_data:
            st.info("오늘 접수된 여벌렌즈(ss, ssp) 주문 건이 없습니다.")
        else:
            st.success(f"총 {sum(len(v) for v in grouped_data.values())}건의 여벌렌즈 주문을 찾았습니다!")
            
            # 회사별로 탭을 만들어서 예쁘게 보여줌
            tabs = st.tabs(list(grouped_data.keys()))
            
            for tab, brand in zip(tabs, grouped_data.keys()):
                with tab:
                    st.subheader(f"🏢 {brand} 발주 목록 ({len(grouped_data[brand])}건)")
                    
                    # 딕셔너리 리스트를 데이터프레임으로 변환하여 출력
                    brand_df = pd.DataFrame(grouped_data[brand])
                    st.dataframe(brand_df, use_container_width=False, width=1200, hide_index=True)

if __name__ == "__main__":
    main()