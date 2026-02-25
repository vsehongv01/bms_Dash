import streamlit as st

pages = {
    "BMS 주문 관리": [
        st.Page("bms_new_dashboard.py", title="신규(NEW) 주문", icon="🆕"),
        st.Page("bms_as_dashboard.py", title="A/S 주문", icon="🛠️"),
    ],
    "자동화 시스템": [
        st.Page("bms_auto_order.py", title="여벌렌즈 자동주문", icon="🤖"),
    ]
}

pg = st.navigation(pages)
pg.run()