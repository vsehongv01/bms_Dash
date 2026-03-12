import json
import os
from dotenv import load_dotenv
from supabase import create_client

# .env 파일에서 접속 정보 로드
load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

def migrate():
    json_file = "lens_mapping.json"
    
    # 1. 파일 존재 확인
    if not os.path.exists(json_file):
        print(f"❌ {json_file} 파일을 찾을 수 없습니다. 경로를 확인하세요.")
        return

    # 2. JSON 데이터 읽기
    with open(json_file, 'r', encoding='utf-8') as f:
        local_data = json.load(f)
    
    if not local_data:
        print("ℹ️ 이전할 데이터가 없습니다.")
        return

    # 3. 서버 형식에 맞게 리스트로 변환
    upload_list = []
    for sku, name in local_data.items():
        upload_list.append({
            "sku_key": sku,
            "custom_name": name
        })

    print(f"🔄 총 {len(upload_list)}건의 데이터를 서버로 전송 중...")

    # 4. Supabase Upsert 실행 (중복 시 업데이트)
    try:
        # 분할 업로드 (데이터가 너무 많을 경우를 대비)
        response = supabase.table("lens_mappings").upsert(upload_list).execute()
        
        if response.data:
            print(f"✅ 성공! {len(response.data)}건의 데이터가 Supabase로 이전되었습니다.")
        else:
            print("⚠️ 응답 데이터가 없습니다. RLS 설정을 다시 확인하세요.")
            
    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    migrate()