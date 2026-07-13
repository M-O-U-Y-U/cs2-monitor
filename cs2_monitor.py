import requests
import time
import json
import os
import datetime

# ================= 配置区域 =================
# 已经为你填好专属 ID 和 Token，无需再改
STEAM_ID = "76561199123057301"
PUSHPLUS_TOKEN = "eb3fa3982e9e436b9f4bf35ec11384ae"
DATA_FILE = "advanced_data.json"

# 过滤垃圾饰品：低于此价格（元）的饰品不监控，节省请求次数
MIN_ITEM_VALUE = 5.0

# 涨幅报警阈值（百分比）：0.1 表示 0.1% 
# 只要比上一小时上涨 0.1% 及以上，就立刻推送
MIN_INCREASE_PERCENT = 0.1 
# ============================================

def send_pushplus(title, content):
    if not PUSHPLUS_TOKEN: return
    requests.post("http://www.pushplus.plus/send", json={
        "token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "html"
    })

def get_inventory():
    url = f"https://steamcommunity.com/inventory/{STEAM_ID}/730/2?l=schinese&count=500"
    try:
        res = requests.get(url, timeout=10).json()
        return {item['market_hash_name'] for item in res.get('descriptions', []) if item.get('marketable')}
    except: return set()

def get_price(name):
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"appid": 730, "currency": 23, "market_hash_name": name}
    try:
        res = requests.get(url, params=params, timeout=10).json()
        price = res.get('lowest_price', '0').replace('¥', '').replace(',', '')
        return float(price)
    except: return 0

def main():
    # 1. 获取当前时间（转为北京时间）
    now_utc = datetime.datetime.utcnow()
    now_bj = now_utc + datetime.timedelta(hours=8)
    is_11_pm = (now_bj.hour == 23) # 判断是否是晚上 11 点
    current_time_str = now_bj.strftime("%H:%M")

    # 2. 读取数据
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f: db = json.load(f)
    else: db = {}

    items = get_inventory()
    hourly_alerts = []
    daily_summary = []

    for name in items:
        price = get_price(name)
        if price < MIN_ITEM_VALUE:
            time.sleep(5)
            continue
        
        # 首次发现该饰品，初始化数据
        if name not in db:
            db[name] = {"start_price": price, "last_price": price, "history": [price]}
        
        item_data = db[name]
        start_price = item_data["start_price"]
        last_price = item_data["last_price"]
        
        # 3. 每小时涨跌判定逻辑
        if price > last_price:
            increase_percent = ((price - last_price) / last_price) * 100
            
            # 只要涨幅大于等于我们设置的阈值（0.1%），就进推送流程
            if increase_percent >= MIN_INCREASE_PERCENT:
                
                daily_ratio = ((price - start_price) / start_price * 100) if start_price > 0 else 0
                highest_so_far = max(item_data["history"] + [start_price])
                
                # 核心逻辑：判断是否创新高
                if price > highest_so_far:
                    high_tag = "🔥 <span style='color:red;'><b>突破今日新高</b></span>"
                else:
                    high_tag = "📈 价格回升 (波动期)"
                
                msg = (f"<div style='border-bottom: 1px dashed #ccc; padding-bottom: 10px; margin-bottom: 10px;'>"
                       f"<b>{name}</b><br>"
                       f"状态：{high_tag}<br>"
                       f"一小时前：¥{last_price:.2f} ➡️ <b>当前：¥{price:.2f}</b> "
                       f"<span style='color:red;'>(+{increase_percent:.2f}%)</span><br>"
                       f"对比今日开盘(¥{start_price:.2f})：累计走势 <b>{daily_ratio:+.2f}%</b>"
                       f"</div>")
                hourly_alerts.append(msg)
        
        # 记录本次价格到历史轨迹中，并更新last_price
        item_data["history"].append(price)
        item_data["last_price"] = price
        
        # 4. 晚上11点：生成日终复盘
        if is_11_pm:
            net_change = ((price - start_price) / start_price * 100) if start_price > 0 else 0
            if abs(net_change) >= MIN_INCREASE_PERCENT:
                trend_color = "red" if net_change > 0 else "green"
                summary_msg = (f"<b>{name}</b><br>"
                               f"开盘 ¥{start_price:.2f} ➡️ 收盘 ¥{price:.2f} "
                               f"<span style='color:{trend_color};'>({net_change:+.2f}%)</span><br>"
                               f"<span style='font-size:12px; color:#888;'>今日轨迹: {' > '.join(map(lambda x: f'{x:.2f}', item_data['history']))}</span>")
                daily_summary.append((net_change, summary_msg))
            
            # 每日跨夜重置
            item_data["start_price"] = price
            item_data["history"] = [price]

        time.sleep(5) # 必须保留的防封禁延迟

    # 5. 保存数据回文件
    with open(DATA_FILE, 'w', encoding='utf-8') as f: 
        json.dump(db, f, ensure_ascii=False, indent=2)

    # 6. 推送微信消息
    if hourly_alerts:
        send_pushplus(f"CS2饰品上涨通知 ({current_time_str})", "".join(hourly_alerts))
    
    if is_11_pm and daily_summary:
        daily_summary.sort(key=lambda x: x[0], reverse=True)
        final_summary_html = "<br><hr><br>".join([msg for _, msg in daily_summary])
        send_pushplus("📊 CS2饰品今日涨跌复盘", f"以下为今日产生有效波动的饰品：<br><br>{final_summary_html}")

if __name__ == "__main__":
    main()
