import streamlit as st
import pandas as pd
import os
import ast
import re
from dotenv import load_dotenv
from supabase import create_client

st.set_page_config(page_title="DT 특별관리", page_icon="⭐", layout="wide")

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

def get_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Supabase 환경 변수가 없습니다.")
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 특별관리 고객 목록 로드
# ==========================================
@st.cache_data(ttl=60, show_spinner=False)
def load_special_customers():
    try:
        sb = get_supabase()
        if not sb: return pd.DataFrame()
        res = sb.table("bms_special_customers").select("*").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception as e:
        st.error(f"특별관리 고객 로드 오류: {e}")
        return pd.DataFrame()

# ==========================================
# 해당 고객들의 전체 주문 로드
# ==========================================
@st.cache_data(ttl=60, show_spinner=False)
def load_orders_for_customers(customer_ids: tuple):
    if not customer_ids:
        return pd.DataFrame()
    try:
        sb = get_supabase()
        if not sb: return pd.DataFrame()
        COLS = [
            "id", "createdAt", "status", "code", "frameType", "lensType",
            '"customer.id"', '"customer.name"', '"customer.contacts"',
            '"frame.size"', '"frame.color"', '"frame.front"', '"frame.temple"',
            '"lens.left.skus"', '"lens.right.skus"',
            '"optometry.data.optimal.left.sph"', '"optometry.data.optimal.left.cyl"',
            '"optometry.data.optimal.left.axi"', '"optometry.data.optimal.left.add"', '"optometry.data.optimal.left.pd"',
            '"optometry.data.optimal.right.sph"', '"optometry.data.optimal.right.cyl"',
            '"optometry.data.optimal.right.axi"', '"optometry.data.optimal.right.add"', '"optometry.data.optimal.right.pd"',
            '"statusDetail.lensStaff"', '"statusDetail.frameStaff"',
            '"data.frameCounsel.content"',
            '"data.fas.comment"', '"optometry.note"', '"deliveryDetail.memo"',
        ]
        all_data = []
        # Supabase in_ filter (batch if large)
        res = sb.table("bms_orders")\
            .select(",".join(COLS))\
            .in_('"customer.id"', list(customer_ids))\
            .order("createdAt", desc=True)\
            .execute()
        if res.data:
            all_data.extend(res.data)
        return pd.DataFrame(all_data) if all_data else pd.DataFrame()
    except Exception as e:
        st.error(f"주문 로드 오류: {e}")
        return pd.DataFrame()

# ==========================================
# 특별관리 구분 변경 / 삭제
# ==========================================
def update_special_category(customer_id, new_category):
    try:
        sb = get_supabase()
        sb.table("bms_special_customers").update({"special_category": new_category}).eq("customer_id", customer_id).execute()
        return True
    except Exception as e:
        st.error(f"구분 변경 오류: {e}")
        return False

def remove_special_customer(customer_id):
    try:
        sb = get_supabase()
        sb.table("bms_special_customers").delete().eq("customer_id", customer_id).execute()
        return True
    except Exception as e:
        st.error(f"해제 오류: {e}")
        return False

# ==========================================
# 포매팅 헬퍼 (신규주문 동일 기준)
# ==========================================
STATUS_MAP = {
    'created': '🆕 주문생성', 'payment_completed': '💳 결제완료',
    'production': '⚙️ 생산중', 'shipped': '🚚 배송중',
    'delivered': '✅ 배송완료', 'canceled': '❌ 취소됨',
    'archived': '📁 보관됨', 'ready': '📦 준비완료',
}

def beautify_status(v):
    return STATUS_MAP.get(str(v).strip().lower(), str(v))

def _clean_prefix(val):
    if not val or str(val).lower() in ['nan', 'none', '']: return ""
    v = str(val).strip()
    v = re.sub(r'^frame_size_', '', v, flags=re.IGNORECASE)
    v = re.sub(r'^(?:[a-z]+_)?front_color_', '', v, flags=re.IGNORECASE)
    v = re.sub(r'^front_', '', v, flags=re.IGNORECASE)
    v = re.sub(r'^temple_(?:[a-z]+_)?(?:temple_color_)?(?:color_)?', '', v, flags=re.IGNORECASE)
    return v

def build_frame_info(row):
    size   = _clean_prefix(row.get('frame.size', ''))
    color  = _clean_prefix(row.get('frame.color', ''))
    front  = _clean_prefix(row.get('frame.front', ''))
    temple = _clean_prefix(row.get('frame.temple', ''))
    res = ""
    if front:  res += f"👓 {front}"
    if size:   res += f" ({size})"
    if color:  res += f" 🎨 {color}"
    if temple: res += f" 🦵 {temple}"
    return res.strip()

def parse_contacts(c_data):
    if not c_data or str(c_data).strip().lower() in ['', 'nan', 'none']: return ""
    c_str = str(c_data).strip()
    try:
        c_list = ast.literal_eval(c_str) if c_str.startswith('[') else c_data
        if isinstance(c_list, list):
            phones = []
            for item in c_list:
                if isinstance(item, dict):
                    val = item.get('data', {}).get('value') if isinstance(item.get('data'), dict) else None
                    if not val: val = item.get('value')
                    if val: phones.append(str(val))
            if phones: return ", ".join(phones)
    except Exception: pass
    phones = re.findall(r"(?:010|02|03[1-3]|04[1-4]|05[1-5]|06[1-4])[-.]?\d{3,4}[-.]?\d{4}", c_str)
    return ", ".join(phones) if phones else c_str

def parse_lens_skus(skus_data):
    if not skus_data or str(skus_data).lower() in ['nan', 'none', '']: return ""
    try:
        s_list = ast.literal_eval(str(skus_data)) if isinstance(skus_data, str) else skus_data
        if isinstance(s_list, list) and s_list:
            return str(s_list[0])
    except Exception: pass
    return str(skus_data)

def _fv(v):
    s = str(v).strip()
    return s if s and s.lower() not in ['nan', 'none', ''] else None

def _clean_val(v):
    """None/nan/빈값 제거 후 문자열 반환"""
    if v is None: return ""
    s = str(v).strip()
    return "" if s.lower() in ['nan', 'none', ''] else s

def format_dosu(sph, cyl, axi, add, pd_val):
    parts = [x for x in [
        f"[ R ] SPH{_fv(sph)}" if _fv(sph) else None,
        f"CYL{_fv(cyl)}"       if _fv(cyl) else None,
        f"AXIS{int(float(_fv(axi)))}" if _fv(axi) else None,
        f"ADD{_fv(add)}"       if _fv(add) else None,
        f"PD{_fv(pd_val)}"     if _fv(pd_val) else None,
    ] if x]
    return " | ".join(parts)

def format_dosu_l(sph, cyl, axi, add, pd_val):
    parts = [x for x in [
        f"[ L ] SPH{_fv(sph)}" if _fv(sph) else None,
        f"CYL{_fv(cyl)}"       if _fv(cyl) else None,
        f"AXIS{int(float(_fv(axi)))}" if _fv(axi) else None,
        f"ADD{_fv(add)}"       if _fv(add) else None,
        f"PD{_fv(pd_val)}"     if _fv(pd_val) else None,
    ] if x]
    return " | ".join(parts)

# ==========================================
# 주문 행 표시용 DataFrame 변환 (신규주문 동일 형식)
# ==========================================
def build_order_display(df_orders):
    rows = []
    for _, row in df_orders.iterrows():
        created = pd.to_datetime(row.get('createdAt', ''), errors='coerce')
        date_str = created.strftime('%Y-%m-%d') if pd.notna(created) else ''

        f_type = str(row.get('frameType', '')).strip().lower()
        l_type = str(row.get('lensType', '')).strip().lower()
        frame_info = build_frame_info(row)
        l_lens_raw = parse_lens_skus(row.get('lens.left.skus', ''))
        r_lens_raw = parse_lens_skus(row.get('lens.right.skus', ''))
        has_frame  = bool(frame_info)
        has_lens   = bool(l_lens_raw or r_lens_raw)

        if not has_frame and not has_lens:
            order_type = "클립온"
        elif f_type in ('custom', 'as') or l_type in ('custom', 'as'):
            order_type = "신규" if 'custom' in (f_type, l_type) else "AS주문"
        else:
            order_type = "기타"

        rows.append({
            '접수일':   date_str,
            '상태':     beautify_status(row.get('status', '')),
            '주문타입': order_type,
            '주문번호': row.get('code', ''),
            '이름':     row.get('customer.name', ''),
            '전화번호': parse_contacts(row.get('customer.contacts', '')),
            '테정보':   frame_info,
            'L렌즈':    f"🅻 {l_lens_raw}" if l_lens_raw else "",
            'R렌즈':    f"🆁 {r_lens_raw}" if r_lens_raw else "",
            'L도수':    format_dosu_l(
                            row.get('optometry.data.optimal.left.sph'),
                            row.get('optometry.data.optimal.left.cyl'),
                            row.get('optometry.data.optimal.left.axi'),
                            row.get('optometry.data.optimal.left.add'),
                            row.get('optometry.data.optimal.left.pd'),
                        ),
            'R도수':    format_dosu(
                            row.get('optometry.data.optimal.right.sph'),
                            row.get('optometry.data.optimal.right.cyl'),
                            row.get('optometry.data.optimal.right.axi'),
                            row.get('optometry.data.optimal.right.add'),
                            row.get('optometry.data.optimal.right.pd'),
                        ),
            '사전체크': _clean_val(row.get('data.frameCounsel.content')),
            '코멘트':   " / ".join(filter(None, [
                            _clean_val(row.get('data.fas.comment')),
                            _clean_val(row.get('optometry.note')),
                            _clean_val(row.get('deliveryDetail.memo')),
                        ])),
        })
    return pd.DataFrame(rows)

# ==========================================
# 고객 유형 정의
# ==========================================
SPECIAL_TYPES = [
    "1. 전투적 우기기형",
    "2. 만성 불편 호소형",
    "3. 무한 트집 및 제품 불만형",
    "4. 책임 전가 및 뒤집어씌우기형",
    "5. 기억 왜곡형",
    "6. 맹목적 의존형",
    "7. 최고급 지향 및 허세형",
    "8. 가성비 집착 및 가격 민감형",
    "9. 생색내기 '사줄게'형",
    "10. 단순 관망 및 소통 불가형",
    "11. 동반자 맹신형",
    "12. 통제 불능 및 막무가내형",
]

TYPE_INFO = {
    "1. 전투적 우기기형": {
        "설명": "대화를 '의견 조율'이 아닌 '기싸움'으로 받아들이며 자신의 고집을 꺾지 않으려는 유형.",
        "대처": "'나는 고객님과 같은 편'이라는 인식을 무의식중에 심어주는 것이 핵심. 대화 중 공통점을 지속적으로 어필하고 동조하여 적대적 분위기를 사전에 허물어야 함.",
    },
    "2. 만성 불편 호소형": {
        "설명": "논리적으로 납득해야 하는 타입 / 무조건 당장 편안해야 한다고 요구하는 타입으로 구분됨.",
        "대처": "전자는 맞춤 렌즈의 기술력과 과정을 명확히 설명해 동의 확보, 후자는 적응 과정의 불편 요소를 지속적으로 사전 인지시킴.",
    },
    "3. 무한 트집 및 제품 불만형": {
        "설명": "원하는 바를 얻기 위해 꼬투리를 잡거나 미세한 마감까지 지속적으로 불편함을 어필하는 유형.",
        "대처": "목적을 빠르게 파악해 가능하면 해결, 불가능하면 즉시 환불. 품질 불만엔 제조사의 객관적 확답을 받아 전달.",
    },
    "4. 책임 전가 및 뒤집어씌우기형": {
        "설명": "본인 부주의를 안경원 탓으로 돌리며 피해를 부풀려 과도한 보상을 요구하는 유형.",
        "대처": "논쟁을 피하고 최소한의 선에서 타협 후 관계를 빠르게 끊어냄.",
    },
    "5. 기억 왜곡형": {
        "설명": "타 매장 구매를 우기거나 상담 시 본인이 했던 말을 다르게 기억해 억지를 부리는 유형.",
        "대처": "상대가 기분 나쁘지 않게 오해 지점을 부드럽게 짚어주고, 불가능한 부분은 현실적 설명으로 명확히 선을 그음.",
    },
    "6. 맹목적 의존형": {
        "설명": "안경사 추천에 전적으로 의존하다 만족도 저하 시 모든 클레임을 쏟아내는 유형.",
        "대처": "친절히 유도하되 주관적 만족도·제품 한계 등 '안 되는 부분'은 사전에 확실히 선을 그어 둠.",
    },
    "7. 최고급 지향 및 허세형": {
        "설명": "무조건 좋은 것만 찾으며 기대치와 실망감이 모두 큰 유형.",
        "대처": "최고가 제품을 먼저 보여준 뒤 '고객님께는 이 렌즈가 더 맞습니다'로 합리적 가격대로 유도(다운셀링)하여 신뢰감을 주고 기대치를 낮춤.",
    },
    "8. 가성비 집착 및 가격 민감형": {
        "설명": "사전 조사가 많고 가성비를 극도로 따지며 질문이 많아 고가 제품 유도가 어려운 유형.",
        "대처": "'가성비' 단어 사용 금지. 각 제품의 스펙·특징 위주로 고객이 원하는 방향의 렌즈를 정확하고 직관적으로 제시.",
    },
    "9. 생색내기 '사줄게'형": {
        "설명": "선심 쓰듯 구매하거나 멀리서 왔다는 것을 어필해 무리한 할인·서비스를 당연하게 요구하는 유형.",
        "대처": "무리하게 팔려 하지 말고, 응대 중간중간 '조건이 안 맞으시면 다른 곳에 가셔도 된다'는 점을 넌지시 어필해 무리한 요구를 차단.",
    },
    "10. 단순 관망 및 소통 불가형": {
        "설명": "단순 체험 목적이거나 자신의 생각을 전혀 말하지 않아 상호 소통이 불가한 유형.",
        "대처": "케미가 맞는지 빠르게 파악하고 흥미를 끌 요소를 찾아 반응을 유도하며 신뢰를 쌓아야 환불 없는 구매로 이어짐.",
    },
    "11. 동반자 맹신형": {
        "설명": "가족·지인과 함께 방문하여 본인 주관보다 동반자의 의견에 심하게 휩쓸리는 유형.",
        "대처": "두 사람의 관계를 빠르게 파악하고 실질적 결정권자에게 설명을 집중하여 결론이 나지 않는 상황을 방지.",
    },
    "12. 통제 불능 및 막무가내형": {
        "설명": "만취 상태이거나 감정 통제가 불가해 매장에서 화를 내며 영업을 심각하게 방해하는 유형.",
        "대처": "말수를 최소화하고 철저히 무시. 잘못 인지한 부분만 단호히 짚고, 환불 요구 시 즉각 처리. 심할 경우 경찰 요청 후 시간을 끎.",
    },
}

# ==========================================
# 메인
# ==========================================
def main():
    st.title("⭐ DT 특별관리")

    if st.button("🔄 새로고침", key="refresh_special"):
        st.cache_data.clear()
        st.rerun()

    df_special = load_special_customers()
    if df_special.empty:
        st.info("등록된 특별관리 고객이 없습니다. 신규주문 페이지에서 ⭐특별관리 체크박스로 등록하세요.")
        return

    # 전체 구분 목록
    categories = sorted(df_special['special_category'].dropna().unique().tolist())

    # 주문 로드 (customer_id 튜플로 캐시키 고정)
    all_customer_ids = tuple(df_special['customer_id'].dropna().unique().tolist())
    df_orders = load_orders_for_customers(all_customer_ids)

    st.markdown(f"**총 {len(df_special)}명** | 구분: {', '.join(categories)}")
    st.divider()

    # 구분별 섹션
    for category in categories:
        customers_in_cat = df_special[df_special['special_category'] == category]
        info = TYPE_INFO.get(category, {})

        col_hd, col_pop = st.columns([8, 1])
        with col_hd:
            st.markdown(f"## 📂 {category} ({len(customers_in_cat)}명)")
        with col_pop:
            if info:
                with st.popover("대처법 ℹ️"):
                    st.markdown(f"**{category}**")
                    st.markdown(f"*{info.get('설명', '')}*")
                    st.markdown("---")
                    st.markdown(f"💡 **대처법**\n\n{info.get('대처', '')}")

        for _, cust in customers_in_cat.iterrows():
            cid = cust['customer_id']
            cname = cust['customer_name'] or '이름 없음'

            # 해당 고객의 주문
            if df_orders.empty:
                cust_orders = pd.DataFrame()
            else:
                cust_orders = df_orders[df_orders['customer.id'].astype(str) == str(cid)]

            order_count = len(cust_orders)
            latest_date = ""
            if order_count > 0 and 'createdAt' in cust_orders.columns:
                latest = pd.to_datetime(cust_orders['createdAt'], errors='coerce').max()
                if pd.notna(latest):
                    latest_date = f" | 최근 주문: {latest.strftime('%Y-%m-%d')}"

            label = f"👤 {cname}  —  총 {order_count}건{latest_date}"

            with st.expander(label, expanded=False):
                col_cat, col_del, _ = st.columns([2, 1, 5])
                with col_cat:
                    cur_idx = SPECIAL_TYPES.index(cust['special_category']) if cust['special_category'] in SPECIAL_TYPES else 0
                    new_cat = st.selectbox("구분 변경", SPECIAL_TYPES, index=cur_idx, key=f"cat_{cid}")
                    if st.button("저장", key=f"save_cat_{cid}"):
                        if update_special_category(cid, new_cat):
                            st.success("구분이 변경되었습니다.")
                            st.cache_data.clear()
                            st.rerun()
                with col_del:
                    st.write("")
                    st.write("")
                    if st.button("🗑️ 특별관리 해제", key=f"del_{cid}"):
                        remove_special_customer(cid)
                        st.cache_data.clear()
                        st.rerun()

                if cust_orders.empty:
                    st.info("주문 내역이 없습니다.")
                else:
                    display_df = build_order_display(cust_orders)
                    st.dataframe(
                        display_df,
                        column_config={
                            "접수일":   st.column_config.TextColumn("접수일",   width="small"),
                            "상태":     st.column_config.TextColumn("상태",     width="medium"),
                            "주문타입": st.column_config.TextColumn("주문타입", width="small"),
                            "주문번호": st.column_config.TextColumn("주문번호", width="medium"),
                            "이름":     st.column_config.TextColumn("이름",     width="small"),
                            "전화번호": st.column_config.TextColumn("전화번호", width="medium"),
                            "테정보":   st.column_config.TextColumn("테정보",   width="large"),
                            "L렌즈":    st.column_config.TextColumn("L렌즈",   width="medium"),
                            "R렌즈":    st.column_config.TextColumn("R렌즈",   width="medium"),
                            "L도수":    st.column_config.TextColumn("L도수",   width="large"),
                            "R도수":    st.column_config.TextColumn("R도수",   width="large"),
                            "사전체크": st.column_config.TextColumn("사전체크", width="large"),
                            "코멘트":   st.column_config.TextColumn("코멘트",   width="large"),
                        },
                        use_container_width=True,
                        hide_index=True,
                    )

        st.divider()

if __name__ == "__main__":
    main()
