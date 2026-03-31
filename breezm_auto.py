import sys
import time
import os
import json
import re
import math
from playwright.sync_api import sync_playwright

def parse_rx_string(rx_str):
    """도수 문자열에서 S, C, A, ADD 값을 추출"""
    sph, cyl, axis, add_val = "", "", "", ""
    if not rx_str or rx_str.strip() == "":
        return sph, cyl, axis, add_val
    s_match = re.search(r"S:\s*([+-]?[\d.]+)", rx_str)
    c_match = re.search(r"C:\s*([+-]?[\d.]+)", rx_str)
    a_match = re.search(r"A:\s*([\d]+)", rx_str)
    add_match = re.search(r"ADD:\s*([+-]?[\d.]+)", rx_str)
    if s_match: sph = s_match.group(1)
    if c_match: cyl = c_match.group(1)
    if a_match: axis = a_match.group(1)
    if add_match: add_val = add_match.group(1)
    return sph, cyl, axis, add_val

def format_essilor_add(add_str):
    """'+2.00' -> '200' 변환"""
    if not add_str: return ""
    try: return str(int(round(float(add_str) * 100)))
    except: return ""

def analyze_lens_info(lens_info):
    """렌즈명 분석하여 사이트 옵션 도출"""
    info_lower = str(lens_info).lower()
    lens_type = ""
    if 'bp10' in info_lower: lens_type = 'BP10'
    elif 'bp20' in info_lower: lens_type = 'BP20'
    elif 'bp30' in info_lower: lens_type = 'BP30'
    elif 'bp40' in info_lower: lens_type = 'BP40'
    elif 'bp50' in info_lower: lens_type = 'BP50'
    
    lens_option = 'Clear(착색옵션가능)'
    if 'gens' in info_lower:
        if 'gray' in info_lower: lens_option = '변색 Gray'
        elif 'brown' in info_lower: lens_option = '변색 Brown'
        elif 'green' in info_lower: lens_option = '변색 Green'
    elif 'purebl' in info_lower: 
        lens_option = '퓨어블루'
        
    index_val = ""
    if '1.67' in info_lower: index_val = '1.67'
    elif '1.60' in info_lower or '1.6' in info_lower: index_val = '1.6'
    elif '1.50' in info_lower or '1.5' in info_lower: index_val = '1.5'
    
    coating_text = ""
    if 'seebl' in info_lower: coating_text = 'SEEBLUE'
    elif 'seeuv' in info_lower: coating_text = 'SEE+UV'
    
    # 💡 퓨어블루일 때 코팅 텍스트가 명시되어 있지 않으면 기본으로 SEE+UV를 강제 할당합니다.
    if lens_option == '퓨어블루' and not coating_text:
        coating_text = 'SEE+UV'
        
    return lens_type, lens_option, index_val, coating_text

def extract_json_specs(order_id):
    """
    DB의 orderItems에서 경사각(frame_angle)과 설계 브릿지(bridge_width)를 추출합니다.
    주의: 이 함수는 Streamlit에서 'order_items_raw' 데이터를 넘겨준다고 가정합니다.
    """
    frame_angle = 0
    bridge_design = 0
    return frame_angle, bridge_design

def process_single_order(page, order):
    print(f"\n[START] 주문번호: {order.get('order_id')} 진행 중...")
    page.goto("https://order.essilor.co.kr/order/order.php?order_type=P", timeout=60000)
    time.sleep(3) 

    # 1. 데이터 분석 및 파싱
    lens_type, lens_option, index_val, coating_text = analyze_lens_info(order.get('lens_info', ''))
    r_sph, r_cyl, r_axis, r_add_raw = parse_rx_string(order.get('rx_r', ''))
    l_sph, l_cyl, l_axis, l_add_raw = parse_rx_string(order.get('rx_l', ''))
    r_add, l_add = format_essilor_add(r_add_raw), format_essilor_add(l_add_raw)

    # PD/OH 데이터 추출 (S:xx / C:xx 형태에서 파싱)
    pd_r = order.get('pd_oh_r', '').split('/')[0].strip()
    oh_r = order.get('pd_oh_r', '').split('/')[1].strip() if '/' in order.get('pd_oh_r', '') else ""
    pd_l = order.get('pd_oh_l', '').split('/')[0].strip()
    oh_l = order.get('pd_oh_l', '').split('/')[1].strip() if '/' in order.get('pd_oh_l', '') else ""

    # VD (소수점 내림 정수)
    vd_raw = order.get('vd', '0')
    vd_val = int(math.floor(float(vd_raw if vd_raw else 0)))

    # 테 규격 (lensWidth / lensHeight / bridgeWidth)
    specs = order.get('frame_specs', '').split('/')
    f_w = float(specs[0].strip()) if len(specs) > 0 and specs[0].strip() != '-' else 0
    f_h = float(specs[1].strip()) if len(specs) > 1 and specs[1].strip() != '-' else 0
    f_br = float(specs[2].strip()) if len(specs) > 2 and specs[2].strip() != '-' else 0

    # 💡 중요: DB의 orderItems에서 추가 값 스캔 (경사각, 설계 브릿지)
    full_text = str(order) 
    f_angle_match = re.search(r"['\"]frame_angle['\"]\s*:\s*['\"]?([0-9.]+)['\"]?", full_text)
    b_design_match = re.search(r"['\"]bridge_width['\"]\s*:\s*['\"]?([0-9.]+)['\"]?", full_text)
    
    f_angle = int(round(float(f_angle_match.group(1)))) if f_angle_match else 0
    b_design = float(b_design_match.group(1)) if b_design_match else 0

    side_val = "RL" if r_sph and l_sph else ("R" if r_sph else "L")

    try:
        # --- 제품 선택 섹션 ---
        page.locator("#group_gubn2").evaluate("el => el.click()")
        time.sleep(1.5)
        page.select_option("#brand_code", value="04")
        time.sleep(1.5)
        if lens_type: page.select_option("#lens_type", value=lens_type); time.sleep(1.5)
        if lens_option: page.select_option("#lens_option", value=lens_option); time.sleep(1.5)
        
        if side_val:
            page.locator(f"input[type='radio'][value='{side_val}']").evaluate("el => el.click()")
            time.sleep(0.5)
            
        if index_val:
            # 💡 재질(굴절율) 선택 후 페이지 반영 딜레이 추가
            page.locator(f"input[type='radio'][value='{index_val}']").evaluate("el => el.click()")
            time.sleep(1)
            
        if coating_text:
            # 💡 코팅 라디오 버튼 선택 강화 (라벨을 통째로 클릭 시도)
            try:
                page.locator(f"label:has(span:has-text('{coating_text}'))").first.click()
            except:
                page.locator(f"span:has-text('{coating_text}')").first.click()
            time.sleep(1)

        page.locator("#btn_order_detail").evaluate("el => el.click()")
        time.sleep(3)

        # --- 도수 입력 섹션 ---
        if r_sph: page.fill("#R_sph", r_sph)
        if r_cyl: page.fill("#R_cyl", r_cyl)
        if r_axis: page.fill("#R_axis", r_axis)
        if r_add: page.fill("#R_add", r_add)
        if l_sph: page.fill("#L_sph", l_sph)
        if l_cyl: page.fill("#L_cyl", l_cyl)
        if l_axis: page.fill("#L_axis", l_axis)
        if l_add: page.fill("#L_add", l_add)

        # --- 테 및 설계 정보 입력 섹션 ---
        print(" 🔟 테 정보 및 설계 데이터 입력 중...")
        if oh_r: page.fill("#HEIGHTR_F", oh_r)
        if oh_l: page.fill("#HEIGHTL_F", oh_l)
        if pd_r: page.fill("#PDR_F", pd_r)
        if pd_l: page.fill("#PDL_F", pd_l)

        # 💡 [수정됨] 중복 입력창(안면각, 경사각, VD) 처리 로직 개선
        wrap_inputs = page.locator("#Wrap, [name='Wrap'], [name='Wrap[]']")
        
        if wrap_inputs.count() >= 3:
            wrap_inputs.nth(0).fill("2")           # 안면각 고정
            wrap_inputs.nth(1).fill(str(f_angle))  # 경사각
            wrap_inputs.nth(2).fill(str(vd_val))   # VD 우측
        else:
            # 봇이 묶음으로 찾지 못했을 경우, 자주 쓰이는 개별 ID를 하나씩 타격합니다.
            if page.locator("#Vertex_R").count() > 0: page.fill("#Vertex_R", str(vd_val))
            elif page.locator("#Vertex").count() > 0: page.fill("#Vertex", str(vd_val))
            
            if page.locator("#Tilt").count() > 0: page.fill("#Tilt", str(f_angle))
            elif page.locator("#Panto").count() > 0: page.fill("#Panto", str(f_angle))
            
            if page.locator("#Wrap").count() > 0: page.fill("#Wrap", "2")

        if page.locator("#Vertex_L").is_visible():
            page.fill("#Vertex_L", str(vd_val))    # VD 좌측

        # Precal 체크
        page.locator("#precalcheck").evaluate("el => el.click()")
        time.sleep(1)

        # 테 규격 계산 입력
        if f_w > 0: page.fill("#FramA", f"{f_w + 0.7:.1f}")
        if f_h > 0: page.fill("#FramB", f"{f_h:.1f}")
        page.fill("#FramDBL", f"{f_br + b_design:.1f}")

        # 주문번호 끝 4자리
        order_code = str(order.get('order_id', ''))
        page.fill("#last_name", order_code[-4:] if len(order_code) >= 4 else order_code)

        # 모든 입력 필드 blur 처리하여 사이트에 값 반영
        page.evaluate("() => { document.querySelectorAll('input[type=\"text\"]').forEach(el => el.blur()); }")

        print(f"✅ 입력 완료 (주문번호: {order_code})")
        
    except Exception as e:
        print(f"❌ 오류 발생: {e}")

def main(payload_file):
    with open(payload_file, 'r', encoding='utf-8') as f:
        payload_list = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state="auth.json" if os.path.exists("auth.json") else None)
        page = context.new_page()

        page.goto("https://order.essilor.co.kr/order/order.php?order_type=P", timeout=60000)
        time.sleep(2)
        
        # 로그인 체크 로직
        if "login" in page.url or page.locator('#web_id').count() > 0:
            page.goto("https://order.essilor.co.kr/member/login.php")
            page.fill('#web_id', "460163")
            page.fill('#web_pwd', "dt460163!")
            page.press('#web_pwd', "Enter")
            time.sleep(3)
            context.storage_state(path="auth.json")

        for data in payload_list:
            process_single_order(page, data)

        print("\n📌 [입력 완료] 화면 확인 후 수동으로 진행해 주세요.")
        page.wait_for_event("close", timeout=0)

if __name__ == "__main__":
    if sys.platform == 'win32':
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    if len(sys.argv) > 1: 
        main(sys.argv[1])