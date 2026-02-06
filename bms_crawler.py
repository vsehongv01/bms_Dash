import requests
import pandas as pd
from datetime import datetime

# --- [설정 구간: 이 부분만 본인 정보로 수정하세요] ---
COOKIE = "connect.sid=s%3AUVy2iaeTlYD_7JsxXi0APfnYvsfuTC_T.%2BBpwa59U7ON9nBA%2F8x9yUcX7bOxIxpoW351Pe%2F54kgQ" # 아까 복사한 값
STORE_ID = 12  # 본인의 매장 ID
START_DATE = "2024-08-01"
END_DATE = datetime.now().strftime("%Y-%m-%d") # 오늘 날짜 자동 생성
# ----------------------------------------------

headers = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
cookies = {"connect.sid": COOKIE.split('=')[1]}

def get_order_list():
    """주문 목록 API에서 모든 주문 ID를 가져옴"""
    url = "https://bmsapi.breezm.com/order/list"
    payload = {
        "storeIds": [STORE_ID],
        "startDate": START_DATE,
        "endDate": END_DATE
    }
    print(f"🚀 {START_DATE} ~ {END_DATE} 데이터를 불러오는 중...")
    res = requests.post(url, json=payload, headers=headers, cookies=cookies)
    return res.json()

def get_order_detail(order_id):
    """주문 ID 하나에 대한 상세 데이터를 가져옴"""
    url = f"https://bmsapi.breezm.com/order/{order_id}/detail"
    res = requests.get(url, headers=headers, cookies=cookies)
    return res.json()

def run():
    orders = get_order_list()
    all_data = []

    for i, item in enumerate(orders):
        order_id = item['id']
        order_code = item['code']
        print(f"[{i+1}/{len(orders)}] 데이터 수집 중: {order_code}")

        try:
            detail = get_order_detail(order_id)
            
            # 원하는 데이터만 '딱딱' 뽑기
            row = {
                "주문ID": order_id,
                "주문번호": detail.get('code'),
                "고객명": detail.get('customer', {}).get('name'),
                "상태": detail.get('status'),
                "담당자": detail.get('statusDetail', {}).get('packageStaff'),
                "테모델": detail.get('frame', {}).get('front'),
                "렌즈SKU": ", ".join(detail.get('lens', {}).get('left', {}).get('skus', [])),
                "결제금액": detail.get('paymentDetail', {}).get('finalPrice'),
                "주문일": detail.get('createdAt')[:10] # 날짜만 추출
            }
            all_data.append(row)
        except Exception as e:
            print(f"❌ {order_code} 실패: {e}")

    # 엑셀 저장
    df = pd.DataFrame(all_data)
    df.to_excel("bms_order_data.xlsx", index=False)
    print("✅ 모든 수집 완료! 'bms_order_data.xlsx' 파일을 확인하세요.")

if __name__ == "__main__":
    run()