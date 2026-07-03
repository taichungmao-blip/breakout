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
    # 策略只需要計算 20MA 跟過去 20 天的盤整，抓 3 個月(3mo)的資料綽綽有餘且速度較快
    data = yf.download(" ".join(tickers), period="3mo", group_by='ticker', threads=True, progress=False)
    
    matched_stocks = []
    tw_tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tw_tz)
    
    # 日期格式
    today_str = now.strftime('%Y-%m-%d')
    today_slash_str = now.strftime('%Y/%m/%d')
    
    for ticker in tickers:
        try:
            # 確保有收盤價與成交量資料
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
            
            # 確保均線計算完成 (略過開頭的 NaN)
            if pd.isna(df['MA20'].iloc[-1]):
                continue

            # 條件 2：前期盤整 (檢查倒數第23天到倒數第3天，共20天的振幅小於 15%)
            past_20_high = df['High'].iloc[-23:-3].max()
            past_20_low = df['Low'].iloc[-23:-3].min()
            
            if past_20_low == 0 or pd.isna(past_20_low):
                continue
                
            consolidation_ratio = (past_20_high - past_20_low) / past_20_low
            if consolidation_ratio >= 0.15:
                continue

            # 條件 3：放量突破 (今日成交量大於前一日的5日均量 2 倍以上) 且今日收盤價大於盤整區間高點
            vol_ma5_prev = df['Vol_MA5'].iloc[-2]
            if current_vol <= vol_ma5_prev * 2 or current_close <= past_20_high:
                continue

            # 條件 4：強勢上攻多頭排列 (5MA > 10MA > 20MA) 且 收盤價 > 5MA
            ma5 = df['MA5'].iloc[-1]
            ma10 = df['MA10'].iloc[-1]
            ma20 = df['MA20'].iloc[-1]
            
            if (ma5 > ma10 > ma20) and (current_close > ma5):
                clean_code = ticker.split('.')[0]
                name = stock_dict[ticker]
                
                # --- 取得本益比 ---
                try:
                    stock_info = yf.Ticker(ticker).info
                    pe = stock_info.get('trailingPE', 'N/A')
                    # 確保數值格式化為小數點後兩位
                    if isinstance(pe, (int, float)):
                        pe_str = f"{pe:.2f}"
                    else:
                        pe_str = str(pe)
                except Exception:
                    pe_str = "N/A"
                # -----------------

                yahoo_link = f"<https://tw.stock.yahoo.com/quote/{clean_code}/technical-analysis>"
                matched_stocks.append(
                    f"📈 **{clean_code} {name}** | {today_slash_str}\n"
                    f"收盤價: `{current_close:.2f}` | 成交量: `{int(current_vol / 1000)}` 張 | 本益比: `{pe_str}`\n"
                    f"🔗 {yahoo_link}"
                )
                
        except Exception as e:
            # yfinance 偶爾會有單筆資料解析錯誤，直接略過
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
