import sys
import time
import os
import json
import asyncio
from playwright.sync_api import sync_playwright

# [1] 제품구분 2 정밀 매핑 테이블 (기존과 동일)
NIKON_MAPPING = [
    {"keywords": ["nikon-disc-gens", "1.60", "basecolor_gray"], "value": "518SZ112E1", "name": "GENS NL3 Gray"},
    {"keywords": ["nikon-disc-gens", "1.60", "basecolor_brown"], "value": "518SZ212E1", "name": "GENS NL3 Brown"},
    {"keywords": ["nikon-disc-gens", "1.56", "basecolor_gray"], "value": "383KSZ11NK", "name": "GENS NL2 Gray"},
    {"keywords": ["ssp", "1.74"], "value": "35310005R0", "name": "NL5 DAS (1.74)"},
    {"keywords": ["ssp", "1.67"], "value": "3529425QK0", "name": "NL4 DAS (1.67)"},
    {"keywords": ["ssp", "1.60"], "value": "3519425QK0", "name": "NL3 DAS (1.60)"},
    {"keywords": ["ss", "1.67"], "value": "555100A522", "name": "NL4 ASP (1.67)"},
    {"keywords": ["ss", "1.60"], "value": "13340", "name": "NL3 ASP (1.60)"},
    {"keywords": ["ss", "1.56"], "value": "12340", "name": "NL2 ASP (1.56)"},
]

def format_data_sph(val):
    """SPH 값을 data-sph 형식으로 변환 (-3.50 -> -03.50)"""
    num = float(val)
    sign = '-' if num < 0 else '+'
    if num == 0: sign = '-' # 사이트 규칙상 0.00은 -00.00일 확률이 높음
    return f"{sign}{abs(num):05.2f}"

def get_cyl_colnum(val):
    """사용자가 분석한 CYL -> data-colnum 매핑 규칙"""
    cyl_val = abs(float(val))
    # 0.25 단위로 인덱스가 1씩 증가하는 규칙 적용
    return int(cyl_val / 0.25)

def process_single_product(page, data):
    lens_info = data['lens_info']
    orders = data['orders']
    combined = " ".join(lens_info).lower()
    
    target = next((m for m in NIKON_MAPPING if all(k in combined for k in m["keywords"])), None)
    if not target:
        print(f"[SKIP] 매칭 실패: {lens_info}")
        return

    print(f"\n[START] {target['name']} 주문 프로세스 실행")
    page.goto("https://order.essilor.co.kr/order/order.php?order_type=B", timeout=60000)
    
    # 옵션 선택 (브랜드 -> 타입 -> 그룹 -> 코팅)
    page.select_option("#brand_code", value="01")
    time.sleep(1)

    lens_type = "GENS 비구면" if "nikon-disc-gens" in combined else ("양면비구면" if any(k in combined for k in ['ssp', 'das']) else "비구면")
    page.select_option("#lens_type", value=lens_type)
    time.sleep(1.5)
    page.select_option("#group_code", value=target['value'])
    time.sleep(1.5)

    is_das = (lens_type == "양면비구면")
    coating = 'BLUV ECC UV' if 'bluv' in combined else ('SeeCoat Next' if is_das else 'ECC')
    page.click(f"span:has-text('{coating}')")
    page.click("#btn_order_detail")
    time.sleep(3) # 격자 로딩 대기

    # [핵심] 사용자 분석 data-sph & data-colnum 기반 입력
    print(f"[INFO] {len(orders)}개 품목 입력 시작")
    for item in orders:
        sph_attr = format_data_sph(item['sph'])  # 예: -03.50
        col_num = str(get_cyl_colnum(item['cyl'])) # 예: 2 (CYL -0.50일 때)
        
        try:
            # data-sph와 data-colnum 속성을 동시에 가진 td를 정확히 타겟팅
            # 예: td[data-sph="-03.50"][data-colnum="2"]
            selector = f'td[data-sph="{sph_attr}"][data-colnum="{col_num}"] input'
            target_input = page.locator(selector)
            
            if target_input.count() > 0:
                target_input.scroll_into_view_if_needed()
                target_input.fill(str(item['qty']))
                # 입력 후 blur 처리로 사이트 데이터 갱신 유도
                target_input.evaluate("el => el.blur()")
                print(f"  ✅ 입력 성공: SPH {item['sph']} / CYL {item['cyl']} (col:{col_num}) -> {item['qty']}개")
            else:
                # 보조 수단: 만약 속성값이 사이트마다 다를 경우 기존 ID 방식(m0350_m050)으로 시도
                alt_id = f"{'m' if float(item['sph']) < 0 else 'p'}{int(abs(float(item['sph']))*100):03d}"
                print(f"  ❌ 입력 실패: 위치를 찾을 수 없음 ({sph_attr}, col:{col_num})")
        except Exception as e:
            print(f"  ⚠️ 에러 발생 ({item['sph']}/{item['cyl']}): {e}")

    # 장바구니에 넣기 버튼 클릭
    page.once("dialog", lambda d: d.accept())
    page.click("input[value='장바구니에 넣기'].btn_navy")
    print(f"[DONE] {target['name']} 장바구니 담기 완료")
    time.sleep(2)

def main(payload_file):
    with open(payload_file, 'r', encoding='utf-8') as f:
        payload_list = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state="auth.json" if os.path.exists("auth.json") else None)
        page = context.new_page()

        for data in payload_list:
            try: process_single_product(page, data)
            except Exception as e: print(f"오류: {e}")

        print("\n📌 모든 주문 처리가 끝났습니다. 브라우저에서 최종 확인해 주세요.")
        page.wait_for_event("close", timeout=0)

if __name__ == "__main__":
    if sys.platform == 'win32':
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    if len(sys.argv) > 1: main(sys.argv[1])