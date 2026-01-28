import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import requests
import os
import re  # 新增：用於強化數值清洗
from datetime import datetime, timedelta

# ==========================================
# 1. 策略設定區域 (雙軌制 + 福懋油)
# ==========================================

# 定義原料代號
COMMODITIES = {
    "CORN": {"ticker": "ZC=F", "name": "玉米"},
    "SOY":  {"ticker": "ZS=F", "name": "黃豆"}
}

# 定義監控清單與對應原料
WATCH_LIST = {
    # --- A組：玉米組 (澱粉/果糖) ---
    "1220.TW": {"name": "台榮", "target": "CORN"},
    
    # --- B組：黃豆組 (飼料/肉品/油脂) ---
    "1210.TW": {"name": "大成",   "target": "SOY"},
    "1215.TW": {"name": "卜蜂",   "target": "SOY"},
    "1219.TW": {"name": "福壽",   "target": "SOY"},
    "1225.TW": {"name": "福懋油", "target": "SOY"}
}

LOOKBACK_DAYS = 180
STRATEGY_WINDOW = 20
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# ==========================================
# 2. 外部資料抓取 (營收 - 強化版)
# ==========================================

def get_twse_revenue_data():
    print("☁️ 正在抓取最新營收資料...")
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            if not data:
                print("⚠️ 抓取成功但資料列表為空")
                return {}
            
            rev_map = {}
            keys = list(data[0].keys())
            
            # 1. 智慧尋找「年增率」欄位
            # 優先找同時包含 '增減' 和 '%' 的欄位
            yoy_key = next((k for k in keys if "增減" in k and ("%" in k or "百分比" in k)), None)
            
            # 如果找不到，退而求其次找只含 '增減' 的 (有些欄位可能沒寫 %)
            if not yoy_key:
                yoy_key = next((k for k in keys if "增減" in k and "去年" in k), None)

            if yoy_key:
                print(f"✅ 成功鎖定營收欄位: {yoy_key}")
                # Debug: 印出第一筆數據供檢查
                sample_val = data[0].get(yoy_key)
                print(f"🔍 數據範例 ({data[0].get('公司代號')}): 原值 '{sample_val}'")

                for row in data:
                    code = row.get("公司代號")
                    raw_val = row.get(yoy_key)
                    
                    # 2. 強化數值清洗
                    val = 0.0
                    if raw_val:
                        try:
                            # 移除逗號、%、空格
                            clean_str = str(raw_val).replace(",", "").replace("%", "").strip()
                            # 處理空值或 '-'
                            if clean_str and clean_str != "-":
                                val = float(clean_str)
                        except ValueError:
                            pass # 解析失敗維持 0.0
                    
                    rev_map[code] = val
            else:
                print(f"⚠️ 警告: 找不到符合的營收欄位，可用欄位: {keys[:5]}...")
                
            return rev_map
        else:
            print(f"❌ API 連線失敗: {res.status_code}")
            return {}
    except Exception as e:
        print(f"❌ 營收抓取發生錯誤: {e}")
        return {}

def send_discord_notify(msg, img_path=None):
    if not DISCORD_WEBHOOK_URL:
        print(msg) 
        return
    try:
        data = {"content": msg}
        files = {"file": (os.path.basename(img_path), open(img_path, "rb"))} if img_path else None
        requests.post(DISCORD_WEBHOOK_URL, data=data, files=files)
        if files: files["file"][1].close()
        print("✅ Discord 通知發送成功")
    except Exception as e:
        print(f"❌ Discord 發送錯誤: {e}")

# ==========================================
# 3. 核心邏輯
# ==========================================

def get_data():
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS + 10)).strftime('%Y-%m-%d')
    tickers = [c["ticker"] for c in COMMODITIES.values()] + list(WATCH_LIST.keys())
    print(f"Downloading data for {len(tickers)} tickers...")
    try:
        data = yf.download(tickers, start=start_date, progress=False)['Close']
        if data.empty: return pd.DataFrame()
        return data.ffill()
    except Exception as e:
        print(f"❌ 下載失敗: {e}")
        return pd.DataFrame()

def analyze_stock(stock_code, stock_data, comm_data, comm_name, rev_yoy, prev_stock, prev_comm):
    # 計算變動率 (近 20 日)
    s_pct = ((stock_data.iloc[-1] - prev_stock) / prev_stock) * 100
    c_pct = ((comm_data.iloc[-1] - prev_comm) / prev_comm) * 100
    
    # 計算開口度 Gap (近 180 日累計)
    norm_stock = (stock_data / stock_data.iloc[0]) * 100
    norm_comm = (comm_data / comm_data.iloc[0]) * 100
    gap = norm_stock.iloc[-1] - norm_comm.iloc[-1]
    
    # 策略判斷
    cost_down = c_pct < 0
    rev_up = rev_yoy > 0
    
    signal = "⚖️ 觀望"
    
    if rev_up and s_pct < -5:
        signal = "📉 **預警(背離)**" 
    elif cost_down:
        if gap < -10: signal = "🎯 **黃金買點** (成本降+股價低估)"
        elif rev_up:  signal = "🚀 **雙引擎** (成本降+營收增)"
        else:         signal = "✨ **潛在轉機** (成本優勢)"
    else:
        if not rev_up: signal = "☠️ **雙殺風險**"
        
    res = f"> **{stock_code.split('.')[0]} {WATCH_LIST[stock_code]['name']}** ({comm_name})\n"
    res += f"> 股價 `{s_pct:+.1f}%` | 原料 `{c_pct:+.1f}%` | 營收 `{rev_yoy:+.1f}%`\n"
    res += f"> 策略: {signal} (Gap: {gap:+.1f})\n"
    return res

def plot_dual_chart(df):
    plt.figure(figsize=(12, 10))
    plt.style.use('bmh')
    
    # 子圖 1: 玉米組
    ax1 = plt.subplot(2, 1, 1)
    comm_corn = COMMODITIES["CORN"]["ticker"]
    if comm_corn in df.columns:
        norm_corn = (df[comm_corn] / df[comm_corn].iloc[0]) * 100
        ax1.plot(norm_corn.index, norm_corn, 'r--', linewidth=2, label='Corn (Cost)')
        for code, info in WATCH_LIST.items():
            if info["target"] == "CORN" and code in df.columns:
                norm_s = (df[code] / df[code].iloc[0]) * 100
                ax1.plot(norm_s.index, norm_s, label=f"{info['name']}")
    ax1.set_title(f"Group A: Starch (vs Corn) - {LOOKBACK_DAYS} Days")
    ax1.legend(); ax1.grid(True)

    # 子圖 2: 黃豆組
    ax2 = plt.subplot(2, 1, 2)
    comm_soy = COMMODITIES["SOY"]["ticker"]
    if comm_soy in df.columns:
        norm_soy = (df[comm_soy] / df[comm_soy].iloc[0]) * 100
        ax2.plot(norm_soy.index, norm_soy, 'r--', linewidth=2, label='Soybean (Cost)')
        for code, info in WATCH_LIST.items():
            if info["target"] == "SOY" and code in df.columns:
                norm_s = (df[code] / df[code].iloc[0]) * 100
                ax2.plot(norm_s.index, norm_s, label=f"{info['name']}")
    ax2.set_title(f"Group B: Feed & Oil (vs Soybean) - {LOOKBACK_DAYS} Days")
    ax2.legend(); ax2.grid(True)
    
    plt.tight_layout()
    img_path = "dual_monitor_chart.png"
    plt.savefig(img_path)
    plt.close()
    return img_path

# ==========================================
# 4. 主程式
# ==========================================

def main():
    df = get_data()
    if df.empty: return
    rev_data = get_twse_revenue_data()
    img_path = plot_dual_chart(df)
    
    date_str = df.index[-1].strftime('%Y-%m-%d')
    msg = f"**【食品股 原料雙軌監控系統】**\n📅 `{date_str}`\n\n"
    
    try:
        prev_idx = -STRATEGY_WINDOW
        df.iloc[prev_idx]
    except:
        prev_idx = 0
        
    groups = {"CORN": "🌽 **澱粉組 (對比玉米)**", "SOY": "🥜 **飼料油脂組 (對比黃豆)**"}
    
    for target_key, group_title in groups.items():
        msg += f"{group_title}\n"
        comm_ticker = COMMODITIES[target_key]["ticker"]
        comm_name = COMMODITIES[target_key]["name"]
        
        if comm_ticker not in df.columns: continue

        c_now = df[comm_ticker].iloc[-1]
        c_prev = df[comm_ticker].iloc[prev_idx]
        
        for code, info in WATCH_LIST.items():
            if info["target"] == target_key and code in df.columns:
                rev = rev_data.get(code.split('.')[0], 0.0)
                msg += analyze_stock(
                    code, df[code], df[comm_ticker], comm_name, rev,
                    df[code].iloc[prev_idx], c_prev
                )
        msg += "\n"

    msg += "💡 **操作備忘：**\nGap < -10 (股價落後原料跌幅) 為價值買點。\n"
    msg += "台榮看玉米，飼料看黃豆，精準分組。"
    
    send_discord_notify(msg, img_path)
    print("Done.")

if __name__ == "__main__":
    main()
