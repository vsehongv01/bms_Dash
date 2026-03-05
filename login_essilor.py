import sys
import time
from playwright.sync_api import sync_playwright

def run_login():
    with sync_playwright() as p:
        # 브라우저 실행 (headless=False로 눈으로 확인)
        browser = p.chromium.launch(headless=False)
        
        # 이전 세션이 있다면 불러오고, 없다면 새로 생성
        context = browser.new_context()
        page = context.new_page()

        print("로그인 페이지로 이동 중...")
        page.goto("https://order.essilor.co.kr/member/login.php")

        # 1. 아이디 및 비밀번호 입력
        print("로그인 정보 입력 중...")
        page.fill('#web_id', "460163")
        page.fill('#web_pwd', "dt460163!")

        # 2. 로그인 버튼 클릭 (엔터키 전달)
        print("로그인 시도...")
        page.press('#web_pwd', "Enter")

        # 3. 로그인 결과 확인을 위한 대기
        try:
            # 페이지 이동이 완료될 때까지 최대 10초 대기
            page.wait_for_load_state("networkidle", timeout=10000)
            
            if "login.php" not in page.url:
                print(f"로그인 성공! 현재 페이지: {page.url}")
                # 세션 정보를 파일로 저장 (다음 단계 자동화를 위해 필수)
                context.storage_state(path="auth.json")
                print("인증 상태가 auth.json에 저장되었습니다.")
            else:
                print("로그인에 실패했습니다. 아이디와 비밀번호를 확인해 주세요.")
        except Exception as e:
            print(f"로그인 확인 중 오류 발생: {e}")

        # 작동 확인을 위해 3초 대기 후 종료
        time.sleep(3)
        browser.close()

if __name__ == "__main__":
    run_login()