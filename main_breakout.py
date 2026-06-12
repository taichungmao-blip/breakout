import os
import requests
import yfinance as yf
import pandas as pd
import urllib3
from datetime import datetime
import pytz

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
            # 確保資料量足夠計算 20MA 以及回溯前 20 天的盤整 (至少需要 45 天比較保險)
            if df.empty or len(df) < 45: 
                continue
            
            current_close = df['Close'].iloc[-1]
            current_vol = df['Volume'].iloc[-1]
            
            # 條件 1：最新股價小於 20 元
            if current_close >= 20:
                continue
                
            df['MA5'] = df['Close'].rolling(window=5).mean()
            df['MA10'] = df['Close'].rolling(window=10).mean()
            df['MA20'] = df['Close'].rolling(window=20).mean()
            df['Vol_MA5'] = df['Volume'].rolling(window=5).mean()
            
            if pd.isna(df['MA20'].iloc[-1]):
                continue

            # 條件 2：確保「當下」趨勢依然是強勢多頭 (5MA > 10MA > 20MA) 且 收盤價 > 5MA
            ma5 = df['MA5'].iloc[-1]
            ma10 = df['MA10'].iloc[-1]
            ma20 = df['MA20'].iloc[-1]
            
            if not ((ma5 > ma10 > ma20) and (current_close > ma5)):
                continue

            # 條件 3 & 4：檢查過去 5 天內 (包含今天) 是否發生過「盤整後放量突破」
            breakout_occurred = False
            
            # 迴圈檢查倒數第 5 天到最後一天 (-5, -4, -3, -2, -1)
            for i in range(-5, 0):
                # 抓取「該日」的前 20 天作為盤整區間 (例如 i=-1 時，取 -21 到 -2)
                past_20_high = df['High'].iloc[i-21 : i-1].max()
                past_20_low = df['Low'].iloc[i-21 : i-1].min()
                
                if pd.isna(past_20_low) or past_20_low == 0:
                    continue
                    
                # 計算該日之前的盤整振幅
                consolidation_ratio = (past_20_high - past_20_low) / past_20_low
                
                # 如果該日之前的振幅符合盤整條件 (< 15%)
                if consolidation_ratio < 0.15:
                    day_vol = df['Volume'].iloc[i]
                    day_close = df['Close'].iloc[i]
                    prev_vol_ma5 = df['Vol_MA5'].iloc[i-1]
                    
                    # 檢查該日是否放量且突破盤整區間高點
                    if (day_vol > prev_vol_ma5 * 2) and (day_close > past_20_high):
                        breakout_occurred = True
                        break # 只要近 5 天有一日符合突破條件，就達標並跳出迴圈
            
            # 如果過去 5 天都沒有發生突破，則跳過這檔股票
            if not breakout_occurred:
                continue

            # 若全部條件符合，加入清單
            clean_code = ticker.split('.')[0]
            name = stock_dict[ticker]
            yahoo_link = f"<https://tw.stock.yahoo.com/quote/{clean_code}/technical-analysis>"
            matched_stocks.append(
                f"📈 **{clean_code} {name}** | {today_slash_str}\n"
                f"收盤價: `{current_close:.2f}` | 成交量: `{int(current_vol)}`\n"
                f"🔗 {yahoo_link}"
            )
                
        except Exception as e:
            continue

    message = f"🎯 **台股 {today_str} 底部起漲策略清單**\n" + "="*30 + "\n"
    message += "(條件：20元以下、近5日內曾放量突破、目前維持多頭排列)\n\n"
    if matched_stocks:
        message += "\n\n".join(matched_stocks)
    else:
        message += "今天沒有符合此型態的個股。"
    
    send_discord_message(message)

if __name__ == "__main__":
    find_breakout_stocks()
