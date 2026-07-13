import requests
import time
import json
import os
import datetime

# ================= 配置区域 =================
# 已经填入你的 WxPusher 凭证和 Steam ID
WXPUSHER_APP_TOKEN = "AT_yHKSDVeK6iT5WJO6UEgHybzBaA0dBpGa"
WXPUSHER_UID = "UID_xpTn3FaNA1yWqDvDMQJYurXEen72"
STEAM_ID = "76561199123057301"
DATA_FILE = "advanced_data.json"

# 过滤垃圾饰品：低于此价格（元）的饰品不监控，节省请求次数
MIN_ITEM_VALUE = 5.0

# 涨幅报警阈值（百分比）：0.1 表示 0.1% 
# 只要比上一小时上涨 0.1% 及以上，就立刻推送
MIN_INCREASE_PERCENT = 0.1 
# ============================================

def send_wxpusher(title, content):
    """使用 WxPusher 发送微信推送"""
    if not WXPUSHER_APP_TOKEN or "AT_" not in WXPUSHER_APP_TOKEN:
        print("未配置 WxPusher，跳过推送")
        return
        
    url = "https://wxpusher.zjiecode.com/api/send/message"
    payload = {
        "appToken": WXPUSHER_APP_TOKEN,
        # WxPusher 的 HTML 格式需要稍微包装一下
        "content": f"<h2>{title}</h2><br>{content}",
        "summary": title, # 微信聊天列表展示的摘要
        "contentType": 2, # 2 表示 HTML 格式
        "uids": [WXPUSHER_UID]
    }
    try:
        res = requests.post(url, json=payload).json()
        if res.get("code") == 1000:
            print("WxPusher 推送成功！")
        else:
            print(f"WxPusher 推送失败: {res.get('msg')}")
    except Exception as e:
        print(f"WxPusher 请求异常: {e}")

def get_inventory():
    """获取库存，并同时提取用于查价的英文名和用于展示的中文名"""
    url = f"https://steamcommunity.com/inventory/{STEAM_ID}/730/2?l=schinese&count=500"
    items = {}
    try:
        res = requests.get(url, timeout=10).json()
        for item in res.get('descriptions', []):
            if item.get('marketable'):
                # hash_name是英文(查价格必备), cn_name是中文(微信推送展示用)
                hash_name = item['market_hash_name']
                cn_name = item.get('name', hash_name)
                items[hash_name] = cn_name
        return items
    except: return {}

def get_price(hash_name):
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"appid": 730, "currency": 23, "market_hash_name": hash_name}
    try:
        res = requests.get(url, params=params, timeout=10).json()
        price = res.get('lowest_price', '0').replace('¥', '').replace(',', '')
        return float(price)
    except: return 0

def main():
    now_utc = datetime.datetime.utcnow()
    now_bj = now_utc + datetime.timedelta(hours=8)
    is_11_pm = (now_bj.hour == 23) 
    current_time_str = now_bj.strftime("%H:%M")

    # ================= 新增：激活测试功能 =================
    # 判断是否是第一次运行（即当前仓库里有没有 advanced_data.json 这个文件）
    is_first_run = not os.path.exists(DATA_FILE)
    
    if is_first_run:
        db = {}
        # 第一次运行，强制发送一条打招呼的测试信息，验证推送通道
        send_wxpusher("🟢 监控系统激活成功", 
                      "恭喜你！CS2 库存监控脚本已成功连接到微信。<br><br>"
                      "当前系统正在云端首次扫描你的库存并记录中文名称和基础底价。后续只要有饰品涨幅达标，你就会在这里第一时间收到精美的中文涨价报告！")
    else:
        with open(DATA_FILE, 'r', encoding='utf-8') as f: 
            db = json.load(f)
    # ======================================================

    inventory_items = get_inventory()
    hourly_alerts = []
    daily_summary = []

    for hash_name, cn_name in inventory_items.items():
        price = get_price(hash_name)
        if price < MIN_ITEM_VALUE:
            time.sleep(5)
            continue
        
        if hash_name not in db:
            db[hash_name] = {"start_price": price, "last_price": price, "history": [price]}
        
        item_data = db[hash_name]
        start_price = item_data["start_price"]
        last_price = item_data["last_price"]
        
        if price > last_price:
            increase_percent = ((price - last_price) / last_price) * 100
            
            if increase_percent >= MIN_INCREASE_PERCENT:
                daily_ratio = ((price - start_price) / start_price * 100) if start_price > 0 else 0
                highest_so_far = max(item_data["history"] + [start_price])
                
                if price > highest_so_far:
                    high_tag = "🔥 <span style='color:red;'><b>突破今日新高</b></span>"
                else:
                    high_tag = "📈 价格回升 (波动期)"
                
                # 推送时使用 cn_name（中文名）
                msg = (f"<div style='border-bottom: 1px dashed #ccc; padding-bottom: 10px; margin-bottom: 10px;'>"
                       f"<b>{cn_name}</b><br>"
                       f"状态：{high_tag}<br>"
                       f"一小时前：¥{last_price:.2f} ➡️ <b>当前：¥{price:.2f}</b> "
                       f"<span style='color:red;'>(+{increase_percent:.2f}%)</span><br>"
                       f"对比今日开盘(¥{start_price:.2f})：累计走势 <b>{daily_ratio:+.2f}%</b>"
                       f"</div>")
                hourly_alerts.append(msg)
        
        item_data["history"].append(price)
        item_data["last_price"] = price
        
        if is_11_pm:
            net_change = ((price - start_price) / start_price * 100) if start_price > 0 else 0
            if abs(net_change) >= MIN_INCREASE_PERCENT:
                trend_color = "red" if net_change > 0 else "green"
                # 晚间复盘同样使用 cn_name（中文名）
                summary_msg = (f"<b>{cn_name}</b><br>"
                               f"开盘 ¥{start_price:.2f} ➡️ 收盘 ¥{price:.2f} "
                               f"<span style='color:{trend_color};'>({net_change:+.2f}%)</span><br>"
                               f"<span style='font-size:12px; color:#888;'>今日轨迹: {' > '.join(map(lambda x: f'{x:.2f}', item_data['history']))}</span>")
                daily_summary.append((net_change, summary_msg))
            
            item_data["start_price"] = price
            item_data["history"] = [price]

        time.sleep(5)

    with open(DATA_FILE, 'w', encoding='utf-8') as f: 
        json.dump(db, f, ensure_ascii=False, indent=2)

    # 发送常规的每小时上涨推送
    if hourly_alerts:
        send_wxpusher(f"CS2饰品上涨通知 ({current_time_str})", "".join(hourly_alerts))
    
    # 发送晚间复盘
    if is_11_pm and daily_summary:
        daily_summary.sort(key=lambda x: x[0], reverse=True)
        final_summary_html = "<br><hr><br>".join([msg for _, msg in daily_summary])
        send_wxpusher("📊 CS2饰品今日涨跌复盘", f"以下为今日产生有效波动的饰品：<br><br>{final_summary_html}")

if __name__ == "__main__":
    main()
