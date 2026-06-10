# -*- coding: utf-8 -*-
"""
KOSPI Daily Index & Investor Trend Telegram Tracker
Bypasses school network firewall blocks by fetching through a Google Apps Script Web App proxy.
"""
import os
import sys
import re
import requests
import urllib3
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import html

# Disable insecure request warnings (for verify=False)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Ensure UTF-8 console output on Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Load environment variables
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GAS_PROXY_URL = os.getenv("GAS_PROXY_URL", "")

def is_gas_proxy_active():
    return GAS_PROXY_URL and "YOUR_GAS_PROXY_URL" not in GAS_PROXY_URL


def send_telegram(msg):
    print(f"[TELEGRAM] {msg}")
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }
        try:
            res = requests.post(url, json=payload, verify=False, timeout=15)
            if res.status_code != 200:
                print(f"텔레그램 전송 실패: {res.status_code} - {res.text}")
        except Exception as e:
            print(f"텔레그램 발송 오류: {e}")
    else:
        print("텔레그램 설정이 누락되어 메시지를 전송하지 못했습니다.")

def fetch_html_via_gas(target_url):
    if not GAS_PROXY_URL or "YOUR_GAS_PROXY_URL" in GAS_PROXY_URL:
        raise ValueError("구글 앱스 스크립트 웹 앱 URL(GAS_PROXY_URL)이 .env 파일에 구성되지 않았습니다.")
    
    # We call our GAS Web App proxy passing the target Naver URL
    params = {"url": target_url}
    try:
        res = requests.get(GAS_PROXY_URL, params=params, verify=False, timeout=20)
        res.raise_for_status()
        text = res.text
        if text.startswith("Error:") or text.startswith("{" + '"error"'):
            raise Exception(f"GAS 프록시 서버 에러: {text}")
        return text
    except Exception as e:
        raise Exception(f"GAS 프록시를 통한 웹 호출 실패: {e}")

def parse_int(text):
    text = text.replace(",", "").replace("+", "").strip()
    try:
        return int(text)
    except ValueError:
        return 0

def get_kospi_index_data():
    url = "https://finance.naver.com/sise/sise_index_day.nhn?code=KOSPI&page=1"
    if is_gas_proxy_active():
        html_content = fetch_html_via_gas(url)
    else:
        # Direct Mode
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://finance.naver.com/"
        }
        res = requests.get(url, headers=headers, verify=False, timeout=15)
        res.raise_for_status()
        html_content = res.content.decode('euc-kr', errors='replace')
        
    soup = BeautifulSoup(html_content, "lxml")
    
    table = soup.find("table", class_="type_1")
    if not table:
        raise ValueError("KOSPI 지수 일별 테이블을 찾을 수 없습니다.")
        
    rows = table.find_all("tr")
    data_rows = []
    
    for r in rows:
        tds = r.find_all("td")
        if len(tds) < 4:
            continue
        date_text = tds[0].get_text(strip=True)
        if not re.match(r"^\d{4}\.\d{2}\.\d{2}$", date_text) and not re.match(r"^\d{2}\.\d{2}\.\d{2}$", date_text):
            continue
            
        # Clean date format to YYYY.MM.DD
        if len(date_text) == 8: # YY.MM.DD
            date_text = "20" + date_text
            
        close_val = tds[1].get_text(strip=True)
        change_val = tds[2].get_text(strip=True)
        fluc_val = tds[3].get_text(strip=True)
        
        # Strip arrow markers
        change_clean = change_val.replace("▲", "").replace("▼", "").replace("상승", "").replace("하락", "").strip()
        
        # Determine sign from fluctuation value
        sign = ""
        if "-" in fluc_val:
            sign = "-"
        elif "+" in fluc_val:
            sign = "+"
            
        data_rows.append({
            "date": date_text,
            "close": close_val,
            "change": f"{sign}{change_clean}",
            "fluc_rate": fluc_val
        })
        
    if not data_rows:
        raise ValueError("KOSPI 지수 데이터 파싱 실패")
        
    return data_rows

def get_kospi_investor_data_from_kis():
    kis_key = os.getenv("KIS_APP_KEY", "")
    kis_secret = os.getenv("KIS_APP_SECRET", "")
    if not kis_key or not kis_secret:
        raise ValueError("KIS API 키가 환경 변수에 설정되어 있지 않습니다.")
        
    print("KIS OpenAPI: Fetching access token...")
    auth_url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    auth_headers = {"content-type": "application/json"}
    auth_body = {
        "grant_type": "client_credentials",
        "appkey": kis_key,
        "appsecret": kis_secret
    }
    auth_res = requests.post(auth_url, headers=auth_headers, json=auth_body, verify=False, timeout=10)
    auth_res.raise_for_status()
    token = auth_res.json()["access_token"]
    
    today = datetime.now()
    start = today - timedelta(days=220)
    today_ymd = today.strftime("%Y%m%d")
    start_ymd = start.strftime("%Y%m%d")
    
    print("KIS OpenAPI: Fetching investor daily market trend...")
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market"
    params = {
        "FID_COND_MRKT_DIV_CODE": "U",
        "FID_INPUT_ISCD": "0001",
        "FID_INPUT_ISCD_1": "",
        "FID_INPUT_DATE_1": start_ymd,
        "FID_INPUT_DATE_2": today_ymd,
        "FID_PERIOD_DIV_CODE": "D"
    }
    headers = {
        "authorization": f"Bearer {token}",
        "appkey": kis_key,
        "appsecret": kis_secret,
        "tr_id": "FHPTJ04040000",
        "custtype": "P"
    }
    
    res = requests.get(url, headers=headers, params=params, verify=False, timeout=15)
    res.raise_for_status()
    json_data = res.json()
    
    if json_data.get("rt_cd") != "0":
        raise ValueError(f"KIS API 리턴 오류: {json_data.get('msg1')}")
        
    output = json_data.get("output", [])
    raw_rows = []
    for row in output:
        date_raw = row.get("stck_bsop_date", "")
        if not date_raw or len(date_raw) != 8:
            continue
        formatted_date = f"{date_raw[0:4]}.{date_raw[4:6]}.{date_raw[6:8]}"
        
        def parse_kis_amt(val):
            try:
                return float(val) / 100.0
            except (ValueError, TypeError):
                return 0.0
                
        raw_rows.append({
            "date": formatted_date,
            "individual": parse_kis_amt(row.get("prsn_ntby_amt", 0)),
            "foreigner": parse_kis_amt(row.get("frgn_ntby_amt", 0)),
            "institution": parse_kis_amt(row.get("orgn_ntby_amt", 0)),
            "fin_inv": parse_kis_amt(row.get("finc_gorg_ntby_amt", 0)),
            "insurance": parse_kis_amt(row.get("insu_ntby_amt", 0)),
            "inv_trust": parse_kis_amt(row.get("trst_ntby_amt", 0)),
            "bank": parse_kis_amt(row.get("bank_ntby_amt", 0)),
            "pension": parse_kis_amt(row.get("peco_ntby_amt", 0)),
            "other_corp": parse_kis_amt(row.get("etc_corp_ntby_amt", 0)),
            "other_fin": parse_kis_amt(row.get("etc_frgn_ntby_amt", 0))
        })
        
    if not raw_rows:
        raise ValueError("KIS API 응답 데이터 파싱 실패")
        
    df = pd.DataFrame(raw_rows)
    return df

def get_kospi_investor_data_from_daum_direct():
    import time
    url = "https://finance.daum.net/api/investor/days?symbolCode=U001&page=1&perPage=30"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://finance.daum.net/domestic/investors",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    session = requests.Session()
    try:
        # Dummy call to domestic/investors page to receive session cookies
        session.get("https://finance.daum.net/domestic/investors", headers=headers, verify=False, timeout=10)
    except Exception:
        pass
    
    res = session.get(url, headers=headers, verify=False, timeout=15)
    res.raise_for_status()
    json_data = res.json()
    
    items = json_data.get("data")
    if not items:
        items = json_data.get("output", json_data)
        
    if not isinstance(items, list) or len(items) == 0:
        raise ValueError(f"다음 금융 데이터 구조 비정상. 응답: {str(json_data)[:150]}")
        
    raw_rows = []
    for item in items:
        raw_date = item.get("date") or item.get("datetime") or ""
        if not raw_date:
            continue
        
        match = re.match(r"^(\d{4})[-.](\d{2})[-.](\d{2})", raw_date)
        if not match:
            continue
        formatted_date = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
        
        ind = item.get("individualNetPurchase") if item.get("individualNetPurchase") is not None else (item.get("individualNetBuy") if item.get("individualNetBuy") is not None else item.get("individual", 0))
        frg = item.get("foreignerNetPurchase") if item.get("foreignerNetPurchase") is not None else (item.get("foreignerNetBuy") if item.get("foreignerNetBuy") is not None else item.get("foreigner", 0))
        inst = item.get("institutionNetPurchase") if item.get("institutionNetPurchase") is not None else (item.get("institutionNetBuy") if item.get("institutionNetBuy") is not None else item.get("institution", 0))
        
        fin = item.get("financialNetPurchase") if item.get("financialNetPurchase") is not None else (item.get("financialNetBuy") if item.get("financialNetBuy") is not None else item.get("financial", 0))
        ins = item.get("insuranceNetPurchase") if item.get("insuranceNetPurchase") is not None else (item.get("insuranceNetBuy") if item.get("insuranceNetBuy") is not None else item.get("insurance", 0))
        tru = item.get("trustNetPurchase") if item.get("trustNetPurchase") is not None else (item.get("trustNetBuy") if item.get("trustNetBuy") is not None else item.get("trust", 0))
        bnk = item.get("bankNetPurchase") if item.get("bankNetPurchase") is not None else (item.get("bankNetBuy") if item.get("bankNetBuy") is not None else item.get("bank", 0))
        pen = item.get("pensionNetPurchase") if item.get("pensionNetPurchase") is not None else (item.get("pensionNetBuy") if item.get("pensionNetBuy") is not None else item.get("pension", 0))
        
        etc_c = item.get("etcCorpNetPurchase") if item.get("etcCorpNetPurchase") is not None else (item.get("etcCorpNetBuy") if item.get("etcCorpNetBuy") is not None else item.get("etcCorp", 0))
        etc_f = item.get("etcFinNetPurchase") if item.get("etcFinNetPurchase") is not None else (item.get("etcFinNetBuy") if item.get("etcFinNetBuy") is not None else item.get("etcFin", 0))
        
        raw_rows.append({
            "date": formatted_date,
            "individual": float(ind),
            "foreigner": float(frg),
            "institution": float(inst),
            "fin_inv": float(fin),
            "insurance": float(ins),
            "inv_trust": float(tru),
            "bank": float(bnk),
            "pension": float(pen),
            "other_corp": float(etc_c),
            "other_fin": float(etc_f)
        })
        
    # Scale calculation
    sum_abs = sum(abs(r["foreigner"]) for r in raw_rows)
    count_valid = len(raw_rows)
    avg_abs = sum_abs / count_valid if count_valid > 0 else 0
    
    divisor = 1.0
    if avg_abs > 10000000:
        divisor = 100000000.0
    elif avg_abs > 100:
        divisor = 100.0
        
    for r in raw_rows:
        r["individual"] = int(round(r["individual"] / divisor))
        r["foreigner"] = int(round(r["foreigner"] / divisor))
        r["institution"] = int(round(r["institution"] / divisor))
        r["fin_inv"] = int(round(r["fin_inv"] / divisor))
        r["insurance"] = int(round(r["insurance"] / divisor))
        r["inv_trust"] = int(round(r["inv_trust"] / divisor))
        r["bank"] = int(round(r["bank"] / divisor))
        r["pension"] = int(round(r["pension"] / divisor))
        r["other_corp"] = int(round(r["other_corp"] / divisor))
        r["other_fin"] = int(round(r["other_fin"] / divisor))
        
    df = pd.DataFrame(raw_rows)
    return df

def get_kospi_investor_data_from_naver_direct():
    import time
    data_rows = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://finance.naver.com/"
    }
    
    for page in range(1, 25):
        url = f"https://finance.naver.com/sise/investorDealTrendDay.nhn?sosok=0&page={page}"
        res = requests.get(url, headers=headers, verify=False, timeout=15)
        res.raise_for_status()
        html_content = res.content.decode('euc-kr', errors='replace')
        
        soup = BeautifulSoup(html_content, "lxml")
        table = soup.find("table")
        if not table:
            continue
            
        rows = table.find_all("tr")
        for r in rows:
            tds = r.find_all("td")
            if len(tds) < 11:
                continue
            date_text = tds[0].get_text(strip=True)
            if not re.match(r"^\d{4}\.\d{2}\.\d{2}$", date_text) and not re.match(r"^\d{2}\.\d{2}\.\d{2}$", date_text):
                continue
                
            if len(date_text) == 8: # YY.MM.DD
                date_text = "20" + date_text
                
            data_rows.append({
                "date": date_text,
                "individual": parse_int(tds[1].get_text(strip=True)),
                "foreigner": parse_int(tds[2].get_text(strip=True)),
                "institution": parse_int(tds[3].get_text(strip=True)),
                "fin_inv": parse_int(tds[4].get_text(strip=True)),
                "insurance": parse_int(tds[5].get_text(strip=True)),
                "inv_trust": parse_int(tds[6].get_text(strip=True)),
                "bank": parse_int(tds[7].get_text(strip=True)),
                "other_fin": parse_int(tds[8].get_text(strip=True)),
                "pension": parse_int(tds[9].get_text(strip=True)),
                "other_corp": parse_int(tds[10].get_text(strip=True))
            })
        time.sleep(0.1)
        
    if not data_rows:
        raise ValueError("네이버 수급 데이터 파싱 실패")
        
    df = pd.DataFrame(data_rows).drop_duplicates(subset=["date"]).reset_index(drop=True)
    df = df.sort_values(by="date", ascending=False).reset_index(drop=True)
    return df

def get_kospi_investor_data():
    if is_gas_proxy_active():
        data_rows = []
        html_content = fetch_html_via_gas("KOSPI_INVESTOR_MULTIPLE")
        soup = BeautifulSoup(html_content, "html.parser")
        
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for r in rows:
                tds = r.find_all("td")
                if len(tds) < 11:
                    continue
                date_text = tds[0].get_text(strip=True)
                if not re.match(r"^\d{4}\.\d{2}\.\d{2}$", date_text) and not re.match(r"^\d{2}\.\d{2}\.\d{2}$", date_text):
                    continue
                    
                if len(date_text) == 8: # YY.MM.DD
                    date_text = "20" + date_text
                    
                data_rows.append({
                    "date": date_text,
                    "individual": parse_int(tds[1].get_text(strip=True)),
                    "foreigner": parse_int(tds[2].get_text(strip=True)),
                    "institution": parse_int(tds[3].get_text(strip=True)),
                    "fin_inv": parse_int(tds[4].get_text(strip=True)),
                    "insurance": parse_int(tds[5].get_text(strip=True)),
                    "inv_trust": parse_int(tds[6].get_text(strip=True)),
                    "bank": parse_int(tds[7].get_text(strip=True)),
                    "other_fin": parse_int(tds[8].get_text(strip=True)),
                    "pension": parse_int(tds[9].get_text(strip=True)),
                    "other_corp": parse_int(tds[10].get_text(strip=True))
                })
                
        if not data_rows:
            raise ValueError("투자자별 매매동향 데이터 파싱 실패")
            
        df = pd.DataFrame(data_rows).drop_duplicates(subset=["date"]).reset_index(drop=True)
        df = df.sort_values(by="date", ascending=False).reset_index(drop=True)
        return df
    else:
        kis_key = os.getenv("KIS_APP_KEY", "")
        kis_secret = os.getenv("KIS_APP_SECRET", "")
        kis_err = None
        
        if kis_key and kis_secret:
            try:
                print("Direct Mode: Fetching data from KIS OpenAPI...")
                return get_kospi_investor_data_from_kis()
            except Exception as ke:
                kis_err = ke
                print(f"Direct Mode: KIS OpenAPI failed ({ke}). Falling back to Daum...")
                
        daum_err = None
        try:
            print("Direct Mode: Fetching data from Daum API...")
            return get_kospi_investor_data_from_daum_direct()
        except Exception as de:
            daum_err = de
            print(f"Direct Mode: Daum API failed ({de}). Falling back to Naver scraping...")
        
        try:
            return get_kospi_investor_data_from_naver_direct()
        except Exception as ne:
            print(f"Direct Mode: Naver scraping failed ({ne}).")
            raise ValueError(f"수급 데이터 수집 모두 실패 (KIS: {kis_err} / Daum: {daum_err} / Naver: {ne})")

def analyze_cumulative_trend(df, num_days):
    df_sub = df.head(num_days)
    if df_sub.empty:
        return None
        
    sum_individual = df_sub["individual"].sum()
    sum_foreigner = df_sub["foreigner"].sum()
    sum_institution = df_sub["institution"].sum()
    
    return {
        "individual": sum_individual,
        "foreigner": sum_foreigner,
        "institution": sum_institution,
        "total_days": len(df_sub)
    }

def analyze_monthly_trend(df, year_month_str):
    # Filter rows that belong to the current month (YYYY-MM)
    # Naver date is YYYY.MM.DD
    target_pattern = year_month_str.replace("-", ".") # "2026.06"
    df_month = df[df["date"].str.startswith(target_pattern)].copy()
    
    if df_month.empty:
        return None
        
    sum_individual = df_month["individual"].sum()
    sum_foreigner = df_month["foreigner"].sum()
    sum_institution = df_month["institution"].sum()
    
    # Calculate buy/sell days
    days_ind_buy = len(df_month[df_month["individual"] > 0])
    days_ind_sell = len(df_month[df_month["individual"] < 0])
    
    days_frg_buy = len(df_month[df_month["foreigner"] > 0])
    days_frg_sell = len(df_month[df_month["foreigner"] < 0])
    
    days_inst_buy = len(df_month[df_month["institution"] > 0])
    days_inst_sell = len(df_month[df_month["institution"] < 0])
    
    return {
        "individual": sum_individual,
        "foreigner": sum_foreigner,
        "institution": sum_institution,
        "ind_days": (days_ind_buy, days_ind_sell),
        "frg_days": (days_frg_buy, days_frg_sell),
        "inst_days": (days_inst_buy, days_inst_sell),
        "total_days": len(df_month)
    }

def format_amount(val):
    sign = "+" if val > 0 else ""
    return f"{sign}{val:,.0f}억"

def main():
    print("KOSPI 시황 및 수급 분석 트래커 가동...")
    
    now = datetime.now()
    today_ymd = now.strftime("%Y.%m.%d")
    today_ym = now.strftime("%Y-%m")
    
    # 10:30 AM or 3:30 PM classification
    current_hour = now.hour
    current_minute = now.minute
    time_label = "오전 장중"
    
    # Argument support for manual run override
    if len(sys.argv) > 1:
        if sys.argv[1] == "--am":
            time_label = "오전 장중 (10:30)"
        elif sys.argv[1] == "--pm":
            time_label = "오후 마감 (15:30)"
        elif sys.argv[1] == "--test":
            time_label = "테스트 실행"
    else:
        if current_hour >= 14 or (current_hour == 15 and current_minute >= 0):
            time_label = "오후 마감 (15:30)"
        else:
            time_label = "오전 장중 (10:30)"
            
    try:
        # Fetch data
        index_history = get_kospi_index_data()
        investor_df = get_kospi_investor_data()
        
        # Today's data (first row)
        latest_index = index_history[0]
        latest_investor = investor_df.iloc[0]
        
        report_date = latest_index["date"]
        
        # Check if today is a trading day
        is_today_trading = (report_date == today_ymd)
        if not is_today_trading and "테스트" not in time_label:
            print(f"오늘({today_ymd})은 개장일이 아닙니다 (최근 거래일: {report_date}). 알림 전송 없이 종료합니다.")
            return
            
        date_display = f"{report_date} {time_label}"
        if not is_today_trading:
            date_display = f"{report_date} (최근 거래일 마감)"
            
        # Calculate 30-day (1-month) and 120-day (6-month) cumulative trends
        trend_30 = analyze_cumulative_trend(investor_df, 30)
        trend_120 = analyze_cumulative_trend(investor_df, 120)
        
        # Safe escape for telegram html format
        esc_time_label = html.escape(time_label)
        esc_date_display = html.escape(date_display)
        esc_close = html.escape(latest_index['close'])
        esc_change = html.escape(latest_index['change'])
        esc_fluc = html.escape(latest_index['fluc_rate'])
        
        # Format subgroup details for institution if active
        inst_details = []
        if latest_investor['fin_inv'] != 0:
            inst_details.append(f"금투 {format_amount(latest_investor['fin_inv'])}")
        if latest_investor['pension'] != 0:
            inst_details.append(f"연기금 {format_amount(latest_investor['pension'])}")
        if latest_investor['inv_trust'] != 0:
            inst_details.append(f"투신 {format_amount(latest_investor['inv_trust'])}")
        inst_detail_str = f" ({' / '.join(inst_details)})" if inst_details else ""

        # Generate message
        msg_lines = [
            f"📊 <b>[코스피 {esc_time_label}]</b> ({esc_date_display})",
            f"• 지수: <b>{esc_close}</b> ({esc_change}, {esc_fluc})",
            "",
            "👥 <b>투자자 순매매</b> (억 원)",
            f"• 개인: <code>{format_amount(latest_investor['individual'])}</code>",
            f"• 외국인: <code>{format_amount(latest_investor['foreigner'])}</code>",
            f"• 기관: <code>{format_amount(latest_investor['institution'])}</code>{inst_detail_str}",
            ""
        ]
        
        # Cumulative statistics
        if trend_30 and trend_120:
            msg_lines.extend([
                "📅 <b>기간별 누적 매매동향</b>",
                f"• 1달(30일): 개인 <code>{format_amount(trend_30['individual'])}</code> | 외인 <code>{format_amount(trend_30['foreigner'])}</code> | 기관 <code>{format_amount(trend_30['institution'])}</code>",
                f"• 6개월(120일): 개인 <code>{format_amount(trend_120['individual'])}</code> | 외인 <code>{format_amount(trend_120['foreigner'])}</code> | 기관 <code>{format_amount(trend_120['institution'])}</code>",
                ""
            ])
            
        # Brief market analysis
        analysis = []
        ind_val = latest_investor['individual']
        frg_val = latest_investor['foreigner']
        inst_val = latest_investor['institution']
        
        if frg_val > 0 and inst_val > 0:
            analysis.append("외인/기관 쌍끌이 매수세 지수 견인.")
        elif frg_val < 0 and inst_val < 0:
            analysis.append("외인/기관 동반 순매도세 수급 압박.")
        elif frg_val > 0:
            analysis.append("기관 매도 속 외인 순매수 지수 방어.")
        elif inst_val > 0:
            analysis.append("외인 매도 속 기관 순매수 지수 지탱.")
            
        if abs(ind_val) > abs(frg_val) and abs(ind_val) > abs(inst_val) and ind_val > 0:
            analysis.append("개인 순매수세로 시장 주도.")
            
        if not analysis:
            analysis.append("투자자별 관망세로 수급 분산.")
            
        msg_lines.extend([
            f"💡 <b>요약:</b> {' '.join(analysis)}"
        ])
        
        telegram_msg = "\n".join(msg_lines)
        send_telegram(telegram_msg)
        print("시황 수급 분석 및 알림 전송 완료.")
        
    except Exception as e:
        err_msg = f"🚨 <b>KOSPI 수급 분석기 실행 실패</b>\n사유: {html.escape(str(e))}"
        print(err_msg)
        send_telegram(err_msg)

if __name__ == "__main__":
    main()
