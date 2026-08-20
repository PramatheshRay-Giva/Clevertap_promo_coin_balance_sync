import os
import time
import math
import requests

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

# ==========================================
# 2. METABASE AUTHENTICATION
# ==========================================
def get_metabase_session():
    print("🔐 Authenticating with Metabase...")
    session_resp = requests.post(
        f"{MB_BASE_URL}/api/session",
        json={"username": MB_USERNAME, "password": MB_PASSWORD},
        timeout=60
    )
    session_resp.raise_for_status()
    return session_resp.json()["id"]

# ==========================================
# 3. FETCH & UPLOAD CHUNK
# ==========================================
def fetch_and_upload_chunk(session_id, digit):
    mb_headers = {"X-Metabase-Session": session_id}
    
    print(f"\n==========================================")
    print(f"⬇️ Fetching users with phone ending in '{digit}'...")
    
    payload = {
        "parameters": [
            {
                "type": "category",
                "target": ["variable", ["template-tag", "phone_tail"]],
                "value": str(digit)
            }
        ]
    }
    
    query_resp = requests.post(
        f"{MB_BASE_URL}/api/card/{MB_CARD_ID}/query/json", 
        headers=mb_headers, 
        json=payload,
        timeout=900
    )
    query_resp.raise_for_status()
    
    rows = query_resp.json()
    if not rows:
        print(f"⚠️ No data found for digit {digit}. Skipping.")
        return 0

    print(f"✅ Downloaded {len(rows):,} rows for digit {digit}.")

    # Format records for CleverTap
    records = []
    for row in rows:
        phone = str(row.get('phone', '')).strip()
        balance = row.get('promotional_wallet_balance', 0)
        
        if not phone:
            continue
            
        if len(phone) == 10 and not phone.startswith('+91'):
            formatted_phone = f"+91{phone}"
        else:
            formatted_phone = phone

        try:
            balance = int(float(balance))
        except (ValueError, TypeError):
            balance = 0

        records.append({
            "identity": formatted_phone,
            "type": "profile",
            "profileData": {
                "promotional_wallet_balance_pmr": balance
            }
        })

    # Upload in batches of 1,000
    total_records = len(records)
    if total_records == 0:
        return 0

    batch_size = 1000
    total_batches = math.ceil(total_records / batch_size)
    print(f"📤 Uploading {total_records:,} profiles in {total_batches:,} batches...")
    
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
                    print(f"   ❌ API Error on batch {current_batch}: {res.text}")
                    time.sleep(2)
            except Exception as e:
                print(f"   ⚠️ Network issue on attempt {attempt}: {e}")
                time.sleep(3)
                
        if current_batch % 10 == 0 or current_batch == total_batches:
            print(f"   ✅ Processed {current_batch:,} / {total_batches:,} batches...")

    return total_records

# ==========================================
# 4. MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    start = time.time()
    total_synced = 0
    try:
        session_id = get_metabase_session()
        
        # Loop 0 through 9 to safely process all ~30 lakh users
        for digit in range(10):
            synced_in_chunk = fetch_and_upload_chunk(session_id, digit)
            total_synced += synced_in_chunk
            
        print(f"\n🎉 SUCCESS! Fully synced {total_synced:,} total profiles to CleverTap.")
            
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        
    print(f"⏱️ Total time: {(time.time() - start) / 60:.2f} minutes")
