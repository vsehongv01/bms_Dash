import streamlit as st

pages = {
    "BMS 주문 관리": [
        st.Page("bms_new_dashboard.py", title="신규(NEW) 주문", icon="🆕"),
        st.Page("bms_as_dashboard.py", title="A/S 주문", icon="🛠️"),
        # 👇 방금 만든 배송 완료 페이지를 여기에 추가했습니다!
        st.Page("delivered_dashboard.py", title="수령피드백", icon="📦"),
        st.Page("bms_return_dashboard.py", title="반품 관리", icon="🔙"),
    ],
    "고객 관리": [
        st.Page("bms_myopia_management.py", title="근시관리", icon="👁️"),
        st.Page("bms_dt_special.py", title="DT 특별관리", icon="⭐"),
    ],
    "자동화 시스템": [
        st.Page("bms_auto_order.py", title="여벌렌즈 자동주문", icon="🤖"),
        st.Page("bms_auto_orderRX.py", title="RX(맞춤)렌즈 자동주문", icon="🎯"), 
    ]
}

pg = st.navigation(pages)
pg.run()