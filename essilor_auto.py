import sys
import time
import os
import json
from playwright.sync_api import sync_playwright

# [1] 제품 매핑 테이블
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
    """SPH 변환 (None 입력 시 방어 로직 추가)"""
    try:
        if val is None or str(val).lower() == 'none' or str(val).strip() == '':
            return "+00.00"
        num = float(val)
        sign = '-' if num < 0 else '+'
        if num == 0: sign = '+' 
        return f"{sign}{abs(num):05.2f}"
    except ValueError:
        return "+00.00"

def format_data_cyl(val):
    """CYL 변환 (None 입력 시 방어 로직 추가)"""
    try:
        if val is None or str(val).lower() == 'none' or str(val).strip() == '':
            return "-00.00"
        num = float(val)
        sign = '+' if num > 0 else '-'
        if num == 0: sign = '-'
        return f"{sign}{abs(num):05.2f}"
    except ValueError:
        return "-00.00"

def save_status(order_name, status, detail=""):
    log_file = "order_results.json"
    results = []
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            try: results = json.load(f)
            except: results = []
    
    results.append({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "product": order_name,
        "status": status,
        "detail": detail
    })
    
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

def process_single_product(page, data):
    lens_info = [str(i).strip().lower() for i in data.get('lens_info', [])]
    orders = data.get('orders', [])
    combined = " ".join(lens_info)
    
    target = next((m for m in NIKON_MAPPING if all(k in combined for k in m["keywords"])), None)
    
    if not target:
        print(f"[SKIP] 매칭 실패: {combined}")
        save_status(combined, "매칭 실패", "제품 코드 없음")
        return

    print(f"\n[START] {target['name']} 프로세스 시작")
    
    try:
        page.goto("https://order.essilor.co.kr/order/order.php?order_type=B", timeout=60000)
        time.sleep(1.5)
        
        page.select_option("#brand_code", value="01")
        time.sleep(1)

        lens_type = "GENS 비구면" if "nikon-disc-gens" in combined else ("양면비구면" if any(k in combined for k in ['ssp', 'das']) else "비구면")
        page.select_option("#lens_type", value=lens_type)
        time.sleep(1)

        page.select_option("#group_code", value=target['value'])
        print(f" 🗳️ 제품 선택 완료: {target['name']} ({target['value']})")
        time.sleep(1.5)

        # 코팅 선택 로직
        is_das = (lens_type == "양면비구면")
        if 'bluv' in combined:
            coating = 'BLUV ECCUV' if '1.56' in combined else 'BLUV ECC UV'
        else:
            coating = 'SeeCoat Next' if is_das else 'ECC'
            
        coating_el = page.locator(f"text='{coating}'").first
        coating_el.wait_for(state="attached", timeout=5000)
        coating_el.evaluate("el => el.click()")
        time.sleep(1)

        page.locator("#btn_order_detail").evaluate("el => el.click()")
        time.sleep(3) 

        success_count = 0
        for item in orders:
            # SPH/CYL 값이 'None'인 경우를 대비해 안전하게 변환
            sph_val = item.get('sph')
            cyl_val = item.get('cyl')
            
            sph_attr = format_data_sph(sph_val)  
            cyl_attr = format_data_cyl(cyl_val) 
            
            selector = f'td[data-sph="{sph_attr}"][data-cyl="{cyl_attr}"] input'
            target_input = page.locator(selector)
            
            if target_input.count() > 0:
                target_input.scroll_into_view_if_needed()
                target_input.fill(str(item.get('qty', 0)))
                target_input.evaluate("el => el.blur()")
                success_count += 1
                print(f"  ✅ 입력: {sph_attr}/{cyl_attr} -> {item.get('qty')}개")
            else:
                print(f"  ❌ 도수 없음: {sph_attr} / {cyl_attr}")

        # 장바구니 담기
        if success_count > 0:
            page.once("dialog", lambda d: d.accept())
            page.locator("input[value='장바구니에 넣기'].btn_navy").evaluate("el => el.click()")
            print(f"[DONE] {target['name']} 장바구니 담기 성공")
            save_status(target['name'], "주문완료", f"{success_count}개 품목")
        else:
            print(f"[SKIP] 입력된 수량이 없어 장바구니에 담지 않았습니다.")
            save_status(target['name'], "주문대기", "입력 수량 없음")
        
        time.sleep(2)
        
    except Exception as e:
        print(f"❌ 과정 중 오류 발생: {e}")
        save_status(target['name'] if target else combined, "오류 발생", str(e))

def main(payload_file):
    if not os.path.exists(payload_file):
        print(f"파일을 찾을 수 없습니다: {payload_file}")
        return

    with open(payload_file, 'r', encoding='utf-8') as f:
        try:
            payload_list = json.load(f)
        except json.JSONDecodeError:
            print("JSON 파일 형식이 잘못되었습니다.")
            return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state="auth.json" if os.path.exists("auth.json") else None)
        page = context.new_page()

        page.goto("https://order.essilor.co.kr/order/order.php?order_type=B")
        if page.locator('#web_id').count() > 0:
            page.fill('#web_id', "460163")
            page.fill('#web_pwd', "dt460163!")
            page.press('#web_pwd', "Enter")
            time.sleep(3)
            context.storage_state(path="auth.json")

        for data in payload_list:
            process_single_product(page, data)

        print("\n📌 모든 작업이 완료되었습니다.")
        page.wait_for_event("close", timeout=0)

if __name__ == "__main__":
    if sys.platform == 'win32':
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    if len(sys.argv) > 1: 
        main(sys.argv[1])