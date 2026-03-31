import sys
import time
import os
import json
from playwright.sync_api import sync_playwright

# ==========================================
# [1] 자이스 여벌렌즈 매핑 사전 및 추출 함수
# ==========================================
ZEISS_MAPPING = {
    "product": {
        "zeiss-ss-cltsph": "단초점 구면 여벌",
        "zeiss-ss-cltasp": "단초점 비구면 여벌",
        "zeiss-ssp-clw": "단초점 클리어뷰 여벌",
        "zeiss-ssp-dfree": "단초점 수퍼브 여벌"
    },
    "index": {
        "1.50": "1.5",
        "1.56": "1.56",
        "1.60": "1.6",  
        "1.67": "1.67",
        "1.74": "1.74"
    },
    "coating": {
        "zeiss-uv-dp": ["DP", "DP UV"],
        "zeiss-bl-bgdp": ["블루가드 DP UV"],
        "zeiss-uv-lt": ["LT", "로투텍"],
        "zeiss-bl-bp": ["BP", "BP UV"]
    }
}

def get_zeiss_search_keywords(sku_list):
    if not isinstance(sku_list, list) or len(sku_list) == 0:
        return ["", "", []]
    main_sku = sku_list[0].lower()
    coating_sku = sku_list[1].lower() if len(sku_list) > 1 else ""
    product_kw, index_kw, coating_kws = "", "", []

    for key, val in ZEISS_MAPPING["product"].items():
        if key in main_sku: product_kw = val; break
    for key, val in ZEISS_MAPPING["index"].items():
        if key in main_sku: index_kw = val; break
    if coating_sku:
        for key, val in ZEISS_MAPPING["coating"].items():
            if key in coating_sku: coating_kws = val; break
    return [product_kw, index_kw, coating_kws]

# ==========================================
# [2] Playwright 자동화 로직
# ==========================================
def zeiss_login(page, user_id, user_pw):
    page.goto("https://visustore.zeiss.com/INTERSHOP/web/WFS/VISUSTORE-KR-Site/ko_KR/-/KRW/Default-Start")
    page.fill("#ShopLoginForm_Login", user_id)
    page.fill("#ShopLoginForm_Password", user_pw)
    page.click("#login")
    page.wait_for_load_state("networkidle")
    
    page.wait_for_selector("#dash-place-bulk-order")
    page.click("#dash-place-bulk-order")
    page.wait_for_load_state("networkidle")

def process_zeiss_bulk_order(page, payload):
    all_customer_names = []
    for p in payload:
        for order in p['orders']:
            if order.get('names'):
                names_list = [n.strip() for n in order['names'].split(',') if n.strip()]
                for n in names_list:
                    if n not in all_customer_names:
                        all_customer_names.append(n)
    
    reference_text = "DT-" + ", ".join(all_customer_names) if all_customer_names else "DT-여벌발주"
    page.wait_for_selector("#orderReference")
    page.fill("#orderReference", reference_text)
    print(f"✅ [단계 1] 주문 번호 입력 완료: {reference_text}")
    time.sleep(1) # 상단 입력 후 잠깐 숨고르기

    total_orders = sum(len(p['orders']) for p in payload)
    current_idx = 0

    for p in payload:
        lens_info = p['lens_info']
        product_kw, index_kw, coating_kws = get_zeiss_search_keywords(lens_info)

        for item in p['orders']:
            lens_input = f"#lens-{current_idx}"
            sph_input = f"#sphere-{current_idx}"
            cyl_input = f"#cylinder-{current_idx}"
            qty_input = f"#quantity-{current_idx}"
            add_button = f"#button-add-{current_idx}"

            print(f"\n▶ [단계 2] {current_idx + 1}번째 렌즈 입력 시작: {product_kw} / {index_kw}")

            # 💡 [여유 추가] 인풋창이 완전히 자리를 잡고 스크립트가 연결될 때까지 1초 대기
            page.wait_for_selector(lens_input)
            time.sleep(1) 
            page.click(lens_input)
            
            # 💡 [여유 추가] 드롭다운 메뉴가 통신을 거쳐 화면에 쫙 깔릴 때까지 넉넉하게 1.5초 대기
            time.sleep(1.5)

            # 이전 줄의 숨겨진 메뉴를 클릭하는(멈춤) 현상을 방지하기 위해 data-testindex 속성으로 현재 row의 드롭다운 아이템만 타겟팅합니다.
            dropdown_items = page.locator(f"[data-testindex^='lens-{current_idx}-menu-item']")
            count = dropdown_items.count()
            matched = False
            
            for i in range(count):
                d_item = dropdown_items.nth(i)
                element_value = d_item.get_attribute("data-testid") or d_item.inner_text()
                if not element_value: continue

                tokens = element_value.split()
                if (product_kw in element_value) and (index_kw in tokens or f"{index_kw}0" in tokens):
                    if not coating_kws or any(c in element_value for c in coating_kws):
                        d_item.click()
                        print(f"   ✅ [매칭 성공] {element_value}")
                        matched = True
                        break
            
            if not matched:
                print(f"   ❌ [매칭 실패] 조건에 맞는 렌즈가 없습니다.")
                page.keyboard.press("Escape")

            # 💡 [여유 추가] 도수와 수량 입력 사이사이에도 0.3초씩 사람처럼 타이핑 딜레이 추가
            time.sleep(0.5)
            page.fill(sph_input, str(item['sph']))
            time.sleep(0.3)
            
            cyl_val = item['cyl'] if item['cyl'] not in ['None', '', 'nan'] else "0.00"
            page.fill(cyl_input, str(cyl_val))
            time.sleep(0.3)
            
            page.fill(qty_input, str(item['qty']))
            time.sleep(0.3)
            
            page.keyboard.press("Tab") 
            print(f"   ✅ [입력 완료] SPH: {item['sph']}, CYL: {cyl_val}, QTY: {item['qty']}")
            
            # 💡 [여유 추가] 탭 키 누르고 나서 사이트가 인식할 시간 부여
            time.sleep(0.8)

            if current_idx < total_orders - 1:
                print(f"   👉 [단계 3] 다음 입력을 위해 '추가' 버튼({add_button})을 클릭합니다.")
                page.locator(add_button).scroll_into_view_if_needed()
                page.locator(add_button).click(force=True)
                
                next_lens_input = f"#lens-{current_idx + 1}"
                try:
                    page.wait_for_selector(next_lens_input, state="visible", timeout=5000)
                    print(f"   ✅ [단계 4] 새 입력창({next_lens_input}) 생성 확인 완료!")
                    
                    # 💡 [가장 중요한 여유] 
                    # 렌즈 칸이 생겼다고 바로 누르지 않고, 자바스크립트가 완전히 로딩될 때까지 2초 푹 쉼!
                    time.sleep(2) 
                except Exception:
                    print(f"   ⚠️ 새 입력창 대기 타임아웃. 강제 진행합니다.")
            
            current_idx += 1

    print("\n✅ [단계 5] 모든 렌즈 입력 완료! '주문내역 확인' 페이지로 이동합니다.")
    time.sleep(1.5)
    page.click("button.btn-primary:has-text('주문내역 확인')")

# ==========================================
# [3] 메인 실행부
# ==========================================
def main(payload_file):
    with open(payload_file, 'r', encoding='utf-8') as f:
        payload = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        auth_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_zeiss.json")
        context = browser.new_context(storage_state=auth_path if os.path.exists(auth_path) else None)
        page = context.new_page()

        if not os.path.exists(auth_path):
            zeiss_login(page, "1324100", "1324100")
            context.storage_state(path=auth_path)
        else:
            page.goto("https://visustore.zeiss.com/INTERSHOP/web/WFS/VISUSTORE-KR-Site/ko_KR/-/KRW/Default-Start")
            time.sleep(2)
            if page.locator("#ShopLoginForm_Login").is_visible():
                zeiss_login(page, "1324100", "1324100")
                context.storage_state(path=auth_path)
            else:
                page.wait_for_selector("#dash-place-bulk-order")
                page.click("#dash-place-bulk-order")
                page.wait_for_load_state("networkidle")

        try:
            process_zeiss_bulk_order(page, payload)
        except Exception as e:
            print(f"오류 발생: {e}")

        page.wait_for_event("close", timeout=0)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        print("실행 시 payload.json 파일 경로가 필요합니다.")