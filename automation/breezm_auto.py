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

def format_essilor_rx_num(val_str):
    """소수점 제거 및 4자리 변환 (예: -0.25 -> -025, +1.00 -> +100)"""
    if not val_str: return ""
    try:
        num = float(val_str)
        if num == 0: return "+000"
        val_int = int(round(num * 100))
        res = f"{val_int:+03d}"  # 부호 포함 포맷팅
        if len(res) < 4:
            res = res[0] + "0" + res[1:]
        return res
    except:
        return str(val_str)

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
    
    r_sph = format_essilor_rx_num(r_sph)
    r_cyl = format_essilor_rx_num(r_cyl)
    l_sph = format_essilor_rx_num(l_sph)
    l_cyl = format_essilor_rx_num(l_cyl)
    
    r_add, l_add = format_essilor_add(r_add_raw), format_essilor_add(l_add_raw)

    # PD/OH 데이터 추출 (S:xx / C:xx 형태에서 파싱)
    pd_r = order.get('pd_oh_r', '').split('/')[0].strip()
    oh_r = order.get('pd_oh_r', '').split('/')[1].strip() if '/' in order.get('pd_oh_r', '') else ""
    pd_l = order.get('pd_oh_l', '').split('/')[0].strip()
    oh_l = order.get('pd_oh_l', '').split('/')[1].strip() if '/' in order.get('pd_oh_l', '') else ""

    # VD (소수점 내림 정수)
    def safe_float(v, default=0.0):
        try:
            if not v or str(v).strip() == '' or '없음' in str(v): return default
            return float(v)
        except: return default

    vd_raw = order.get('vd', '0')
    vd_val = int(math.floor(safe_float(vd_raw)))

    # 테 규격 (lensWidth / lensHeight / bridgeWidth)
    specs = order.get('frame_specs', '').split('/')
    f_w = safe_float(specs[0].strip()) if len(specs) > 0 and specs[0].strip() != '-' else 0
    f_h = safe_float(specs[1].strip()) if len(specs) > 1 and specs[1].strip() != '-' else 0
    f_br = safe_float(specs[2].strip()) if len(specs) > 2 and specs[2].strip() != '-' else 0

    # 💡 중요: DB의 orderItems에서 추가 값 스캔 (경사각, 설계 브릿지)
    full_text = str(order) 
    f_angle_match = re.search(r"['\"]frame_angle['\"]\s*:\s*['\"]?([0-9.]+)['\"]?", full_text)
    b_design_match = re.search(r"['\"]bridge_width['\"]\s*:\s*['\"]?([0-9.]+)['\"]?", full_text)
    
    f_angle = int(round(float(f_angle_match.group(1)))) if f_angle_match else 0
    b_design = float(b_design_match.group(1)) if b_design_match else 0

    side_val = "RL" if r_sph and l_sph else ("R" if r_sph else "L")

    try:
        def click_visual(selector):
            loc = page.locator(selector)
            if loc.count() > 0:
                loc.first.evaluate("""el => {
                    if (el.tagName === 'INPUT' && (el.type === 'radio' || el.type === 'checkbox')) {
                        let label = el.id ? document.querySelector('label[for="' + el.id + '"]') : null;
                        if (!label && el.labels && el.labels.length > 0) label = el.labels[0];
                        if (label) { label.click(); return; }
                        if (el.nextElementSibling && el.nextElementSibling.tagName === 'LABEL') { el.nextElementSibling.click(); return; }
                        if (el.parentElement) { el.parentElement.click(); return; }
                    }
                    el.click();
                }""")

        # --- 제품 선택 섹션 ---
        click_visual("#group_gubn2")
        time.sleep(1.5)
        page.select_option("#brand_code", value="04")
        time.sleep(1.5)
        if lens_type: page.select_option("#lens_type", value=lens_type); time.sleep(1.5)
        if lens_option: page.select_option("#lens_option", value=lens_option); time.sleep(1.5)
        
        if side_val:
            click_visual(f"input[type='radio'][value='{side_val}']")
            time.sleep(0.5)
            
        if index_val:
            # 💡 재질(굴절율) 선택 후 페이지 반영 딜레이 추가
            click_visual(f"input[type='radio'][value='{index_val}']")
            time.sleep(1)
            
        if coating_text:
            # 💡 코팅 라디오 버튼 선택 강화 (라벨을 통째로 클릭 시도)
            try:
                page.locator(f"label:has(span:has-text('{coating_text}'))").first.click()
            except:
                page.locator(f"span:has-text('{coating_text}')").first.click()
            time.sleep(1)

        page.locator("#btn_order_detail").click(force=True)
        time.sleep(3)

        # --- 도수 입력 섹션 ---
        def slow_type(selector, text):
            loc = page.locator(selector)
            if loc.count() > 0:
                # 에실로 입력 마스크 필터링 회피를 위해 직접 주입 방식(fill) 사용 후 change 이벤트 강제 발동
                loc.first.fill(str(text))
                loc.first.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); el.blur(); }")
                time.sleep(0.05)

        if r_sph: slow_type("#R_sph", r_sph)
        if r_cyl: slow_type("#R_cyl", r_cyl)
        if r_axis: slow_type("#R_axis", r_axis)
        if r_add: slow_type("#R_add", r_add)
        if l_sph: slow_type("#L_sph", l_sph)
        if l_cyl: slow_type("#L_cyl", l_cyl)
        if l_axis: slow_type("#L_axis", l_axis)
        if l_add: slow_type("#L_add", l_add)

        # --- 테 및 설계 정보 입력 섹션 ---
        print(" 🔟 테 정보 및 설계 데이터 입력 중...")
        if oh_r: slow_type("#HEIGHTR_F", oh_r)
        if oh_l: slow_type("#HEIGHTL_F", oh_l)
        if pd_r: slow_type("#PDR_F", pd_r)
        if pd_l: slow_type("#PDL_F", pd_l)

        # 💡 [수정됨] 중복 입력창(안면각, 경사각, VD) 처리 로직 개선
        wrap_inputs = page.locator("#Wrap, [name='Wrap'], [name='Wrap[]']")
        
        if wrap_inputs.count() >= 3:
            wrap_inputs.nth(0).fill("")
            wrap_inputs.nth(0).press_sequentially("2", delay=30)
            wrap_inputs.nth(0).evaluate("el => { el.dispatchEvent(new Event('change', {bubbles: true})); el.blur(); }")
            wrap_inputs.nth(1).fill("")
            wrap_inputs.nth(1).press_sequentially(str(f_angle), delay=30)
            wrap_inputs.nth(1).evaluate("el => { el.dispatchEvent(new Event('change', {bubbles: true})); el.blur(); }")
            wrap_inputs.nth(2).fill("")
            wrap_inputs.nth(2).press_sequentially(str(vd_val), delay=30)
            wrap_inputs.nth(2).evaluate("el => { el.dispatchEvent(new Event('change', {bubbles: true})); el.blur(); }")
        else:
            if page.locator("#Vertex_R").count() > 0: slow_type("#Vertex_R", vd_val)
            elif page.locator("#Vertex").count() > 0: slow_type("#Vertex", vd_val)
            
            if page.locator("#Tilt").count() > 0: slow_type("#Tilt", f_angle)
            elif page.locator("#Panto").count() > 0: slow_type("#Panto", f_angle)
            
            if page.locator("#Wrap").count() > 0: slow_type("#Wrap", "2")

        if page.locator("#Vertex_L").is_visible():
            slow_type("#Vertex_L", vd_val)

        # Precal 체크
        click_visual("#precalcheck")
        time.sleep(1)

        # 💡 테 종류 기본값(플라스틱) 강제 선택 추가
        print(" 🎯 필수값(테 타입: 플라스틱) 자동 선택 중...")
        try:
            page.locator("label:has-text('플라스틱')").first.click(force=True)
            time.sleep(0.5)
        except Exception as e:
            print("테 종류 선택 생략됨:", e)

        # 테 규격 계산 입력
        try:
            if f_w > 0: slow_type("#FramA", f"{f_w + 0.7:.1f}")
            if f_h > 0: slow_type("#FramB", f"{f_h:.1f}")
            slow_type("#FramDBL", f"{f_br + b_design:.1f}")
        except Exception as fe:
            print(f" ⚠️ 테 규격 입력 중 건너뜀 (데이터 부족): {fe}")

        # 💡 성명 필수 입력 (에실로 결제창 등에서 빈칸이면 막히는 현상 방지)
        cust_name = str(order.get('customer_name', '고객')).strip()
        if not cust_name: cust_name = "고객"
        
        if page.locator("#first_name").count() > 0:
            slow_type("#first_name", cust_name)
        elif page.locator("input[name='first_name']").count() > 0:
            slow_type("input[name='first_name']", cust_name)

        # 주문번호 끝 4자리
        order_code = str(order.get('order_id', ''))
        slow_type("#last_name", order_code[-4:] if len(order_code) >= 4 else order_code)

        # 💡 에실로 사이트 내부의 [저장/확인 버튼 활성화] 체크 스크립트를 깨우기 위한 엔터 연타
        page.keyboard.press("Enter")
        time.sleep(0.2)
        page.keyboard.press("Enter")
        time.sleep(0.5)

        # 모든 입력 필드 blur 처리하여 사이트에 값 반영
        page.evaluate("() => { document.querySelectorAll('input[type=\"text\"]').forEach(el => el.blur()); }")

        print(f"✅ 입력 완료 (주문번호: {order_code})")
        
    except Exception as e:
        print(f"❌ 개별 주문 처리 중 오류 발생: {e}")
        # 오류가 나더라도 실행 중인 브라우저는 종료되지 않도록 함

def main(payload_file):
    with open(payload_file, 'r', encoding='utf-8') as f:
        payload_list = json.load(f)

    with sync_playwright() as p:
        # 로컬 폴더에 봇 전용 크롬 프로필 생성 (평소 쓰는 크롬 켜져있어도 상관없음)
        user_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_profile")
        auth_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.json")
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir,
                channel="chrome",
                headless=False,
                args=["--start-maximized"]
            )
        except Exception as e:
            print(f"\n=======================================================")
            print(f"❌ 크롬 브라우저 실행 실패!")
            print(f"=======================================================")
            print(f"이미 자동주문 봇 크롬 창이 켜져있어서 실행에 실패했습니다.")
            print(f"열려있는 봇(자동주문) 크롬 창을 닫고 다시 버튼을 눌러주세요.\n에러 상세: {e}")
            input("\n종료하려면 엔터 키를 누르세요...")
            sys.exit(1)
            
        page = context.pages[0] if len(context.pages) > 0 else context.new_page()

        # 💡 핵심 원인 해결: Playwright의 팝업 자동 취소(Dismiss) 차단 및 '확인(Accept)' 강제 처리
        # 봇은 사이트에서 confirm() 알림창이 뜨면 내부적으로 0.1초만에 '취소'를 눌러버리는 기본 작동 방식이 있습니다.
        page.on("dialog", lambda dialog: dialog.accept())

        page.goto("https://order.essilor.co.kr/order/order.php?order_type=P", timeout=60000)
        time.sleep(2)
        
        # 로그인 체크 로직
        if "login" in page.url or page.locator('#web_id').count() > 0:
            page.goto("https://order.essilor.co.kr/member/login.php")
            page.fill('#web_id', "460163")
            page.fill('#web_pwd', "dt460163!")
            page.press('#web_pwd', "Enter")
            time.sleep(3)
            context.storage_state(path=auth_path)

        for data in payload_list:
            try:
                process_single_order(page, data)
            except Exception as e:
                print(f"❌ 주문 처리 실패: {e}")

        print("\n📌 [알림] 입력 작업이 종료되었습니다. 브라우저를 닫지 마세요.")
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass

if __name__ == "__main__":
    if sys.platform == 'win32':
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    if len(sys.argv) > 1: 
        main(sys.argv[1])