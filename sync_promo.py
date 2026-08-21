import os
import time
import math
import requests
import csv
from datetime import datetime
from zoneinfo import ZoneInfo

# ==========================================
# 1. CONFIGURATION
# ==========================================
MB_BASE_URL = "https://mb.givadiva.co"
MB_USERNAME = "pramatheshray.ray@giva.co"
MB_PASSWORD = os.getenv("MB_PASSWORD")
MB_CARD_ID = 23154  

CT_ACCOUNT_ID = "R78-Z5K-847Z"
CT_PASSCODE = os.getenv("CT_PASSCODE")
CT_REGION = "in1"
CT_ADMIN_EMAIL = "shah.neil@giva.co"
CT_CREATOR_NAME = "Pramathesh Ray"

# We keep the dynamic date ONLY for the local success markers
IST = ZoneInfo("Asia/Kolkata")
CT_DATE = datetime.now(IST).strftime("%d%b%y")

# HARDCODED: This exactly matches the segments already in your dashboard
BASE_SEGMENT_NAME = "21Aug26_Promo_Wallet"

MAX_RETRIES = 5
RETRY_DELAY = 60

# ==========================================
# 2. PROFILE UPLOAD FUNCTION
# ==========================================
def upload_profiles(records):
    total_records = len(records)
    if total_records == 0:
        return True

    batch_size = 1000
    total_batches = math.ceil(total_records / batch_size)
    print(f"   📤 Syncing {total_records:,} user properties in {total_batches:,} batches...")
    
    ct_url = f"https://{CT_REGION}.api.clevertap.com/1/upload"
    ct_headers = {
        'X-CleverTap-Account-Id': CT_ACCOUNT_ID,
        'X-CleverTap-Passcode': CT_PASSCODE,
        'Content-Type': 'application/json'
    }
    
    for i in range(0, total_records, batch_size):
        batch = records[i:i + batch_size]
        payload_ct = {"d": batch}
        current_batch = (i // batch_size) + 1
        
        for attempt in range(1, 4):
            try:
                res = requests.post(ct_url, headers=ct_headers, json=payload_ct, timeout=20)
                if res.status_code == 200:
                    break
                elif res.status_code == 429: 
                    time.sleep(3)
                else:
                    print(f"      ❌ API Error on batch {current_batch}: {res.text}")
                    time.sleep(2)
            except Exception as e:
                print(f"      ⚠️ Network issue on attempt {attempt}: {e}")
                time.sleep(3)
    return True

# ==========================================
# 3. SEGMENT UPLOAD FUNCTION
# ==========================================
def upload_segment_part(phones_chunk, digit_num):
    segment_name = f"{BASE_SEGMENT_NAME}_Digit_{digit_num}"
    csv_filename = f"promo_segment_digit_{digit_num}.csv"
    
    print(f"   📝 Writing Segment {digit_num} ({len(phones_chunk):,} users) to CSV...")
    with open(csv_filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['type', 'identity'])
        for phone in phones_chunk:
            writer.writerow(['i', phone])

    base_url = f"https://{CT_REGION}.api.clevertap.com"
    ct_headers = {
        'Content-Type': 'application/json',
        'X-CleverTap-Account-Id': CT_ACCOUNT_ID,
        'X-CleverTap-Passcode': CT_PASSCODE
    }

    print(f"   🔗 Requesting Pre-Signed URL...")
    res1 = requests.post(f"{base_url}/get_custom_list_segment_url", headers=ct_headers)
    if res1.status_code != 200:
        return False
    presigned_url = res1.json().get("presignedS3URL")

    print(f"   📤 Uploading CSV to CleverTap S3...")
    with open(csv_filename, 'rb') as file_data:
        res2 = requests.put(presigned_url, data=file_data)
    if res2.status_code != 200:
        return False

    print(f"   ✅ Registering Segment '{segment_name}'...")
    payload = {
        "name": segment_name,
        "email": CT_ADMIN_EMAIL,
        "filename": csv_filename,
        "creator": CT_CREATOR_NAME,
        "url": presigned_url,
        "replace": True  # This guarantees it overwrites the existing 21Aug26 files
    }
    res3 = requests.post(f"{base_url}/upload_custom_list_segment_completed", json=payload, headers=ct_headers)

    if res3.status_code == 200 and res3.json().get("status") == "success":
        os.remove(csv_filename)
        return True
    return False

# ==========================================
# 4. MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    start = time.time()
    
    try:
        print("🔐 Authenticating with Metabase...")
        session_resp = requests.post(
            f"{MB_BASE_URL}/api/session",
            json={"username": MB_USERNAME, "password": MB_PASSWORD},
            timeout=60
        )
        session_resp.raise_for_status()
        mb_headers = {"X-Metabase-Session": session_resp.json()["id"]}
        
        for digit in range(10):
            print(f"\n==========================================")
            
            success_marker = f"success_{CT_DATE}_digit_{digit}.txt"
            if os.path.exists(success_marker):
                print(f"⏭️ Digit '{digit}' already fully synced today. Skipping...")
                continue
                
            print(f"⬇️ Fetching chunk ending in '{digit}'...")
            payload = {
                "parameters": [{"type": "category", "target": ["variable", ["template-tag", "phone_tail"]], "value": str(digit)}]
            }
            
            records = []
            chunk_phones = []
            fetch_success = False
            
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = requests.post(
                        f"{MB_BASE_URL}/api/card/{MB_CARD_ID}/query/json", 
                        headers=mb_headers, json=payload, timeout=900
                    )
                    resp.raise_for_status() 
                    
                    rows = resp.json()
                    for row in rows:
                        phone = str(row.get('phone', '')).strip()
                        balance = row.get('promotional_wallet_balance', 0)
                        
                        if not phone: continue
                        if len(phone) == 10 and not phone.startswith('+91'):
                            phone = f"+91{phone}"
                            
                        try:
                            balance = int(float(balance))
                        except (ValueError, TypeError):
                            balance = 0

                        records.append({
                            "identity": phone,
                            "type": "profile",
                            "profileData": {"promotional_wallet_balance_pmr": balance}
                        })
                        chunk_phones.append(phone)
                    
                    print(f"   ✅ Fetched {len(rows):,} rows.")
                    fetch_success = True
                    break 
                    
                except requests.exceptions.RequestException as e:
                    print(f"   ⚠️ Attempt {attempt}/{MAX_RETRIES} failed: {e}")
                    if attempt < MAX_RETRIES: time.sleep(RETRY_DELAY)
            
            if not fetch_success:
                print(f"   ❌ FAILED to fetch chunk {digit} after {MAX_RETRIES} attempts. Skipping to next digit...")
                continue  
                
            # EXECUTE BOTH UPLOADS
            print(f"🚀 Starting Uploads for Digit {digit}...")
            profiles_ok = upload_profiles(records)
            segment_ok = upload_segment_part(chunk_phones, digit)
            
            if profiles_ok and segment_ok:
                with open(success_marker, 'w') as f:
                    f.write("done")
                print(f"🎉 Digit {digit} completely synced!")
            else:
                print(f"   ❌ CleverTap upload failed for digit {digit}. Skipping to next digit...")
                continue 
                
            time.sleep(5)
            
    except Exception as e:
        print(f"\n❌ Pipeline stopped: {e}")
        
    print(f"\n⏱️ Total execution time: {(time.time() - start) / 60:.2f} minutes")
