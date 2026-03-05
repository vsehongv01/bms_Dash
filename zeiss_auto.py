import sys
import time
import os
import json
from playwright.sync_api import sync_playwright

def zeiss_login(page, user_id, user_pw):
    """자이스 Visustore 로그인 로직"""
    page.goto("https://visustore.zeiss.com/INTERSHOP/web/WFS/VISUSTORE-KR-Site/ko_KR/-/KRW/Default-Start")
    
    # 로그인 정보 입력
    page.fill("#ShopLoginForm_Login", user_id)
    page.fill("#ShopLoginForm_Password", user_pw)
    
    # 로그인 버튼 클릭
    page.click("#login")
    page.wait_for_load_state("networkidle")
    print("[INFO] 자이스 로그인 시도 완료")

def process_zeiss_order(page, data):
    """자이스 품목 입력 로직 (추후 격자 분석 후 업데이트 예정)"""
    print(f"[START] {data['lens_info']} 주문 처리 중...")
    # 1. 여벌 렌즈 주문 메뉴 이동 로직 필요
    # 2. 제품 선택 및 도수 입력 로직 필요
    pass

def main(payload_file):
    with open(payload_file, 'r', encoding='utf-8') as f:
        payload_list = json.load(f)

    with sync_playwright() as p:
        # 브라우저 실행
        browser = p.chromium.launch(headless=False)
        # 세션 저장 파일 확인
        storage = "auth_zeiss.json" if os.path.exists("auth_zeiss.json") else None
        context = browser.new_context(storage_state=storage)
        page = context.new_page()

        # 로그인 상태가 아니면 로그인 수행
        if not storage:
            zeiss_login(page, "1324100", "1324100") # 제공해주신 계정 정보
            context.storage_state(path="auth_zeiss.json")

        for data in payload_list:
            try:
                process_zeiss_order(page, data)
            except Exception as e:
                print(f"[ERROR] 항목 처리 중 오류: {e}")

        print("\n[DONE] 모든 처리가 완료되었습니다.")
        page.wait_for_event("close", timeout=0)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])