import os
import requests
import yfinance as yf
import pandas as pd
import urllib3
from datetime import datetime
import pytz
from bs4 import BeautifulSoup  # 新增：用於解析網頁 HTML

# 關閉略過 SSL 驗證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_stock_list():
    """取得上市與上櫃股票清單"""
    stock_dict = {}
    print("正在取得上市與上櫃股票清單...")
    
    twse_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    tpex_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
    
    try:
        res_twse = requests.get(twse_url, verify=False, timeout=10)
        if res_twse.status_code == 200:
            for item in res_twse.json():
                code, name = str(item.get('Code', '')), str(item.get('Name', ''))
                if len(code) == 4: stock_dict[f"{code}.TW"] = name
        
        res_tpex = requests.get(tpex_url, verify=False, timeout=10)
        if res_tpex.status_code == 200:
            for item in res_tpex.json():
                code = str(item.get('SecuritiesCompanyCode', ''))
                name = str(item.get('CompanyName', ''))
                if len(code) == 4: stock_dict[f"{code}.TWO"] = name
    except Exception as e:
        print(f"取得清單失敗: {e}")
    return stock_dict

def get_yahoo_pe(stock_code):
    """直接爬取台灣奇摩股市網頁上的本益比"""
    url = f"https://tw.stock.yahoo.com/quote/{stock_code}/technical-analysis"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=5, verify=False)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # 根據截圖中的特徵：尋找包含「本益比 (同業平均)」的 span
            pe_label = soup.find("span", string=lambda t: t and "本益比" in t)
            if pe_label:
                # 找到它的兄弟節點或父節點底下的數值 span (字體為 Fz(16px))
                pe_value_span = pe_label.find_parent().find("span", class_=lambda c: c and "Fz(16px)" in c)
                if pe_value_span:
                    # 取得內容 (例如 "23.40 (22.95)")，並只切出前面的本益比數字
                    full_text = pe_value_span.get_text(strip=True)
                    pe_num = full_text.split("(")[0].strip()
                    return pe_num
    except Exception as e:
        print(f"爬取 {stock_code} 本益比失敗: {e}")
    return "N/A"

def send_discord_message(content):
    """發送至 Discord"""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("未設定 DISCORD_WEBHOOK_URL，將僅印出結果：\n", content)
        return
    # Discord 訊息長度限制為 2000，這裡以 1900 為單位分段發送
    chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
    for chunk in chunks:
        requests.post(webhook_url, json={"content": chunk})

def find_breakout_stocks():
    stock_dict = get_stock_list()
    tickers = list(stock_dict.keys())
    
    print(f"開始分析 {len(tickers)} 檔股票的歷史數據 (下載 3 個月資料)...")
    data = yf.download(" ".join(tickers), period="3mo", group_by='ticker', threads=True, progress=False)
    
    matched_stocks = []
    tw_tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tw_tz)
    
    today_str = now.strftime('%Y-%m-%d')
    today_slash_str = now.strftime('%Y/%m/%d')
    
    for ticker in tickers:
        try:
            df = data[ticker].dropna(subset=['Close', 'Volume']).copy()
            if df.empty or len(df) < 30: 
                continue
            
            current_close = df['Close'].iloc[-1]
            current_vol = df['Volume'].iloc[-1]
            
            # 條件 1：股價小於 20 元
            if current_close >= 20:
                continue
                
            # 計算均線與均量
            df['MA5'] = df['Close'].rolling(window=5).mean()
            df['MA10'] = df['Close'].rolling(window=10).mean()
            df['MA20'] = df['Close'].rolling(window=20).mean()
            df['Vol_MA5'] = df['Volume'].rolling(window=5).mean()
            
            if pd.isna(df['MA20'].iloc[-1]):
                continue

            # 條件 2：前期盤整
            past_20_high = df['High'].iloc[-23:-3].max()
            past_20_low = df['Low'].iloc[-23:-3].min()
            
            if past_20_low == 0 or pd.isna(past_20_low):
                continue
                
            consolidation_ratio = (past_20_high - past_20_low) / past_20_low
            if consolidation_ratio >= 0.15:
                continue

            # 條件 3：放量突破
            vol_ma5_prev = df['Vol_MA5'].iloc[-2]
            if current_vol <= vol_ma5_prev * 2 or current_close <= past_20_high:
                continue

            # 條件 4：強勢上攻多頭排列
            ma5 = df['MA5'].iloc[-1]
            ma10 = df['MA10'].iloc[-1]
            ma20 = df['MA20'].iloc[-1]
            
            if (ma5 > ma10 > ma20) and (current_close > ma5):
                clean_code = ticker.split('.')[0]
                name = stock_dict[ticker]
                
                # --- 改為直接爬取網頁網頁上的本益比 ---
                pe_str = get_yahoo_pe(clean_code)
                # -----------------------------------

                yahoo_link = f"<https://tw.stock.yahoo.com/quote/{clean_code}/technical-analysis>"
                matched_stocks.append(
                    f"📈 **{clean_code} {name}** | {today_slash_str}\n"
                    f"收盤價: `{current_close:.2f}` | 成交量: `{int(current_vol / 1000)}` 張 | 本益比: `{pe_str}`\n"
                    f"🔗 {yahoo_link}"
                )
                
        except Exception as e:
            continue

    # 組合 Discord 訊息
    message = f"🎯 **台股 {today_str} 底部起漲突破策略清單**\n" + "="*30 + "\n"
    message += "(條件：20元以下、盤整後放量突破、均線多頭排列)\n\n"
    if matched_stocks:
        message += "\n\n".join(matched_stocks)
    else:
        message += "今天沒有符合此型態的個股。"
    
    send_discord_message(message)

if __name__ == "__main__":
    find_breakout_stocks()
