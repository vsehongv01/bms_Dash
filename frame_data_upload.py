import requests
import json
from supabase import create_client, Client

# ==========================================
# 1. Supabase 접속 정보 세팅 (직접 입력해 주세요!)
# ==========================================
SUPABASE_URL = "https://doicohkyxfvpigvjwcuc.supabase.co"
SUPABASE_KEY = "sb_publishable_tsdUjJM2ZLOj0y3CgjPzKA_Y_hlRVF8"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 데이터를 넣을 Supabase 테이블 이름 (예: 'frame_specs')
# 실제 Supabase에 만들어두신 테이블 이름으로 꼭 변경하세요!
TABLE_NAME = "frame_specs" 

# ==========================================
# 2. API에서 데이터 추출 및 정제
# ==========================================
url = "https://bmsapi.breezm.com/product"
headers = {
    "Accept": "application/json, text/plain, */*",
    "Cookie": "mx_utm_source=google; mx_utm_medium=%ED%82%A4%EC%9B%8C%EB%93%9C%EA%B4%91%EA%B3%A0; mx_utm_content=network_g-placement_; _fwb=1792JAKxQ9InWeTjAVMuk3H.1727436619143; mx_utm_campaign=%EB%B8%8C%EB%9E%9C%EB%94%94%EB%93%9C%ED%82%A4%EC%9B%8C%EB%93%9C; mx_utm_term=%EB%B8%8C%EB%A6%AC%EC%A6%98; _kmpid=km|breezm.com|1767975476118|f1818014-95da-415c-89a4-4350f3beae6b; _gcl_au=1.1.154074067.1767975476; _trs_id=eY67675367130146%3F; _fbp=fb.1.1767975476421.67788160878101235; _gcl_aw=GCL.1768970004.CjwKCAiA7LzLBhAgEiwAjMWzCFHqcCRViPz8Y-KKtYq4i4DVoHTyLtAFSOQCs52bLVLuN-PrELGNtBoCtecQAvD_BwE; _gcl_gs=2.1.k1$i1768970001$u247711572; _ga=GA1.2.1206896657.1727436619; _gac_UA-131160459-1=1.1768970004.CjwKCAiA7LzLBhAgEiwAjMWzCFHqcCRViPz8Y-KKtYq4i4DVoHTyLtAFSOQCs52bLVLuN-PrELGNtBoCtecQAvD_BwE; _ga_SN0499J7Z4=GS2.1.s1768970004$o12$g1$t1768970043$j21$l0$h0; _ga_G4VPYE976G=GS2.1.s1768970004$o12$g1$t1768970043$j21$l0$h0; _ga_R1VPLD9M38=GS2.1.s1768970004$o12$g1$t1768970043$j21$l0$h0; connect.sid=s%3AK9Of7aP6TDkxloLnRVgbiTco2wjaKjVj.OAWlTyXUEgnqHm9okY1Vxlh%2BhTarFQSCVw9HZOirWnI"
}

response = requests.post(url, headers=headers)

if response.status_code in [200, 201]:
    frame_data = response.json()
    print("✅ 데이터 다운로드 완료! 파싱을 시작합니다...")
    
    parsed_frames = [] 

    for item in frame_data:
        info = item.get("info", {})
        variable = info.get("variable", {})
        
        if isinstance(variable, dict) and "model" in variable and "size" in variable:
            model_name = variable.get("model") 
            sizes = variable.get("size", {})
            
            for size_key, size_info in sizes.items():
                if size_key.startswith("frame_size_"):
                    size_num = int(size_key.replace("frame_size_", ""))
                    
                    # 💡 중요: 키값을 Supabase 테이블의 실제 컬럼명과 완벽히 똑같이 맞춰야 합니다!
                    frame_row = {
                        "name": model_name,            # 모델명
                        "size": size_num,              # 사이즈
                        "lensWidth": size_info.get("lensWidth"),
                        "lensHeight": size_info.get("lensHeight"),
                        "frameWidth": size_info.get("frameWidth"),
                        "frameHeight": size_info.get("frameHeight"),
                        "framePD": size_info.get("framePD"),
                        "bridgeWidth": size_info.get("bridgeWidth"),
                        "endSide": size_info.get("endSide"),
                        "templeLength": size_info.get("templeLength"),
                        "faceFormAngle": size_info.get("faceFormAngle"),
                        "pantoscopicTilt": size_info.get("pantoscopicTilt")
                    }
                    parsed_frames.append(frame_row)

    print(f"🎉 총 {len(parsed_frames)}줄의 데이터 정제 완료!")
    
    # ==========================================
    # 3. Supabase에 통째로 업로드 (Bulk Insert)
    # ==========================================
    print(f"🚀 Supabase '{TABLE_NAME}' 테이블에 업로드를 시작합니다...")
    try:
        # parsed_frames 리스트를 통째로 insert 하면 알아서 한 번에 들어갑니다.
        data, count = supabase.table(TABLE_NAME).insert(parsed_frames).execute()
        print("✅ 성공적으로 Supabase에 모든 데이터가 업로드되었습니다!!")
    except Exception as e:
        print("❌ 업로드 중 오류가 발생했습니다:", e)

else:
    print("❌ 데이터 가져오기 실패:", response.status_code)