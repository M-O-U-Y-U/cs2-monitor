import requests
import time
import json
import os
import datetime
import urllib.parse
import random

# ================= 配置区域 =================
WXPUSHER_APP_TOKEN = "AT_yHKSDVeK6iT5WJO6UEgHybzBaA0dBpGa"
WXPUSHER_UID = "UID_xpTn3FaNA1yWqDvDMQJYurXEen72"
STEAM_ID = "76561199123057301"
DATA_FILE = "advanced_data.json"

MIN_ITEM_VALUE = 0.5       # 忽略低于0.5元的物品
MIN_INCREASE_PERCENT = 1.0 # 涨幅超过1%才进行日内推送通知

# 随机休眠抖动，防止被识别为机器规律请求 (单位:秒)
MIN_REQUEST_DELAY = 2.0    
MAX_REQUEST_DELAY = 4.0   
# ============================================

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9"
})

def send_wxpusher(title, content):
    if not WXPUSHER_APP_TOKEN or "AT_" not in WXPUSHER_APP_TOKEN: return
    url = "https://wxpusher.zjiecode.com/api/send/message"
    payload = {
        "appToken": WXPUSHER_APP_TOKEN,
        "content": f"<h2>{title}</h2><br>{content}",
        "summary": title, 
        "contentType": 2, 
        "uids": [WXPUSHER_UID]
    }
    try:
        session.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[错误] WxPusher 推送失败: {e}")

def get_inventory():
    url = f"https://steamcommunity.com/inventory/{STEAM_ID}/730/2?l=schinese&count=500"
    items = {}
    try:
        res = session.get(url, timeout=15)
        if res.status_code == 429:
            print("[警告] 获取库存被 Steam 限流 (429)")
            return {}
        data = res.json()
        for item in data.get('descriptions', []):
            if item.get('marketable'):
                hash_name = item['market_hash_name']
                items[hash_name] = item.get('name', hash_name)
        return items
    except Exception as e: 
        print(f"[错误] 获取库存失败: {e}")
        return {}

def get_market_data(hash_name):
    """
    使用 CSGO Backpack 第三方 API 榨干更多专业数据
    """
    url = "https://csgobackpack.net/api/GetItemPrice/"
    params = {"id": hash_name, "currency": "CNY", "time": 1} # time=1 代表取最近 24 小时的数据
    
    # 默认返回结构，加入均价和最高价
    result = {
        "price": -1, 
        "volume": "未知", 
        "median": "未知", 
        "average": "未知", 
        "high_24h": "未知"
    }
    
    try:
        res = session.get(url, params=params, timeout=10)
        if res.status_code == 429:
            print(f"[警告] 获取 {hash_name} 数据被限流 (429)")
            return result
        
        data = res.json()
        if not data.get("success"): 
            return result
            
        # 1. 核心价格：优先用最低在售价，没有的话用中位价兜底
        price_str = data.get("lowest_price") or data.get("median_price")
        if price_str:
            result["price"] = float(str(price_str).replace(',', '').strip())
            
        # 2. 丰富的大盘数据
        if data.get("amount_sold"):
            result["volume"] = data['amount_sold']
        if data.get("median_price"):
            result["median"] = data['median_price']
        if data.get("average_price"):
            result["average"] = data['average_price']
        if data.get("highest_price"):
            result["high_24h"] = data['highest_price']
            
        return result
    except Exception as e: 
        print(f"[错误] 获取 {hash_name} 数据异常: {e}")
        return result

def generate_sparkline_url(prices, is_red):
    """通过 QuickChart API 生成微缩走势图"""
    if not prices: return ""
    if len(prices) == 1: prices.append(prices[0])
    
    color = "rgb(255, 77, 79)" if is_red else "rgb(82, 196, 26)"
    bg_color = "rgba(255, 77, 79, 0.1)" if is_red else "rgba(82, 196, 26, 0.1)"
    
    prices_str = ",".join(map(str, prices))
    config_str = (
        f"{{type:'sparkline',data:{{datasets:[{{"
        f"data:[{prices_str}],fill:true,backgroundColor:'{bg_color}',"
        f"borderColor:'{color}',borderWidth:2,pointRadius:0"
        f"}}]}}}}"
    )
    encoded_config = urllib.parse.quote(config_str)
    return f"https://quickchart.io/chart?w=300&h=80&bkg=white&c={encoded_config}"

def get_random_delay():
    """生成带有小数点的随机抖动时间，完美模拟真人点击"""
    return round(random.uniform(MIN_REQUEST_DELAY, MAX_REQUEST_DELAY), 2)

def main():
    now_utc = datetime.datetime.utcnow()
    now_bj = now_utc + datetime.timedelta(hours=8)
    today_str = now_bj.strftime("%Y-%m-%d")
    current_time_str = now_bj.strftime("%H:%M")
    
    # 只要是晚上22点之后（含23点），且今天没出过报告，即触发晚间复盘
    is_11_pm = (now_bj.hour >= 22)

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f: 
            db = json.load(f)
    else: 
        db = {}

    meta = db.get("_meta", {})
    last_report_date = meta.get("last_report_date", "")
    
    should_generate_daily = (is_11_pm and last_report_date != today_str)
    if should_generate_daily: 
        meta["last_report_date"] = today_str
        
    db["_meta"] = meta

    inventory_items = get_inventory()
    if not inventory_items: 
        print("[提示] 库存为空或获取失败，结束运行。")
        return

    hourly_alerts = []
    daily_summary = []
    valid_items_checked = 0 

    for hash_name, cn_name in inventory_items.items():
        market_data = get_market_data(hash_name)
        price = market_data["price"]
        volume = market_data["volume"]
        median = market_data["median"]
        average = market_data["average"]
        high_24h = market_data["high_24h"]
        
        # 价格低于阈值或获取失败处理
        if price <= MIN_ITEM_VALUE:
            if should_generate_daily and hash_name in db:
                db[hash_name]["start_price"] = db[hash_name].get("last_price", 0)
                db[hash_name]["history"] = [{"time": "昨日收盘", "price": db[hash_name]["start_price"]}]
            
            time.sleep(get_random_delay()) 
            continue
            
        valid_items_checked += 1
        
        # 数据初始化及平滑升级
        if hash_name not in db:
            db[hash_name] = {
                "start_price": price, 
                "last_price": price, 
                "history": [{"time": current_time_str, "price": price}],
                "historical_high": price 
            }
        else:
            old_history = db[hash_name].get("history", [])
            db[hash_name]["history"] = [h if isinstance(h, dict) else {"time": "历史", "price": float(h)} for h in old_history]
            if "historical_high" not in db[hash_name]:
                highest_past = max([x["price"] for x in db[hash_name]["history"]] + [db[hash_name].get("start_price", price)])
                db[hash_name]["historical_high"] = highest_past
                
        item_data = db[hash_name]
        start_price = item_data["start_price"]
        last_price = item_data["last_price"]
        historical_high = item_data["historical_high"]
        
        # ========== 1. 常规异动监控 (白天触发) ==========
        if price > last_price:
            increase_percent = ((price - last_price) / last_price) * 100
            if increase_percent >= MIN_INCREASE_PERCENT:
                
                if price > historical_high:
                    high_tag = "🚀 <span style='color:red;'><b>强势突破历史新高！</b></span>"
                    item_data["historical_high"] = price 
                else:
                    high_tag = "📈 价格回升 (盘中异动)"
                
                msg = (f"<div style='border-bottom: 1px dashed #ccc; padding-bottom: 10px; margin-bottom: 10px;'>"
                       f"<b style='font-size:16px;'>{cn_name}</b><br>"
                       f"当前状态：{high_tag}<br>"
                       f"行情变动：¥{last_price:.2f} ➡️ <b style='font-size:15px; color:#d9534f;'>¥{price:.2f}</b> "
                       f"<span style='color:red;'>(+{increase_percent:.2f}%)</span><br>"
                       f"<div style='font-size:12px; color:#555; background:#f5f5f5; padding:6px; border-radius:4px; margin-top:6px;'>"
                       f"<b>大盘参考：</b><br>"
                       f"24h热度: {volume} 笔 | 24h均价: ¥{average}<br>"
                       f"24h高点: ¥{high_24h} | 中位参考: ¥{median}"
                       f"</div></div>")
                hourly_alerts.append(msg)
        
        # 记录全天波动轨迹
        last_history_price = item_data["history"][-1]["price"] if item_data["history"] else start_price
        if price != last_history_price:
            item_data["history"].append({"time": current_time_str, "price": price})
            
        item_data["last_price"] = price
        
        # ========== 2. 晚间复盘逻辑 (高低点 + 折线图 + 大盘数据) ==========
        if should_generate_daily:
            net_change = ((price - start_price) / start_price * 100) if start_price > 0 else 0
            
            if abs(net_change) >= MIN_INCREASE_PERCENT or len(item_data['history']) > 1:
                trend_color = "#d9534f" if net_change > 0 else "#5cb85c"
                is_red_chart = (net_change >= 0)
                
                all_prices_today = [start_price] + [x['price'] for x in item_data['history']]
                if price not in all_prices_today: all_prices_today.append(price)
                
                day_high = max(all_prices_today)
                day_low = min(all_prices_today)
                
                chart_url = generate_sparkline_url(all_prices_today, is_red_chart)
                
                if day_high > historical_high:
                    high_str = f"<span style='color:#d9534f;'><b>🎊 突破历史新高 (原纪录 ¥{historical_high:.2f})！</b></span>"
                    item_data["historical_high"] = day_high
                else:
                    high_str = f"距历史高位 (¥{historical_high:.2f}) 差 ¥{(historical_high - day_high):.2f}"

                history_str_list = [f"{x['time']}(¥{x['price']:.2f})" for x in item_data['history']]
                history_path = " > ".join(history_str_list)
                
                # 精美排版的每日摘要卡片
                summary_msg = (f"<div style='margin-bottom:20px;'>"
                               f"<b style='font-size:15px;'>{cn_name}</b> <span style='font-size:12px; color:#888;'>({hash_name})</span><br>"
                               f"今日收盘：<b style='font-size:16px;'>¥{price:.2f}</b> "
                               f"<span style='color:{trend_color};'><b>({net_change:+.2f}%)</b></span> "
                               f"<span style='font-size:12px; color:#888;'>(开盘 ¥{start_price:.2f})</span><br>"
                               f"📊 今日探底: ¥{day_low:.2f} | 冲高: ¥{day_high:.2f}<br>"
                               f"👑 {high_str}<br>"
                               f"<div style='font-size:12px; color:#31708f; background:#d9edf7; padding:6px; border-radius:5px; margin:6px 0;'>"
                               f"🛒 <b>CSGO大盘 24H 真实数据</b><br>"
                               f"成交笔数: {volume} 笔 | 24H均价: ¥{average}<br>"
                               f"最高成交: ¥{high_24h} | 中位参考: ¥{median}"
                               f"</div>"
                               f"<img src='{chart_url}' alt='走势图' style='width:100%; max-width:300px; margin-top:2px; border-radius:4px;'><br>"
                               f"<div style='font-size:11px; color:#888; margin-top:6px; padding:4px; background:#f9f9f9; border:1px solid #eee; border-radius:4px;'>"
                               f"<b>盘中轨迹:</b> {history_path}</div>"
                               f"</div>")
                daily_summary.append((net_change, summary_msg))
            
            item_data["start_price"] = price
            item_data["history"] = [{"time": current_time_str, "price": price}]

        time.sleep(get_random_delay())

    with open(DATA_FILE, 'w', encoding='utf-8') as f: 
        json.dump(db, f, ensure_ascii=False, indent=2)

    if hourly_alerts:
        send_wxpusher(f"📈 饰品异动雷达 ({current_time_str})", "".join(hourly_alerts))
    
    if daily_summary:
        daily_summary.sort(key=lambda x: x[0], reverse=True)
        final_summary_html = "<hr style='border:1px dashed #ccc;'>".join([msg for _, msg in daily_summary])
        send_wxpusher(f"📊 饰品大盘深度复盘 ({today_str})", f"今日产生有效波动的饰品汇总：<br><br>{final_summary_html}")

    # ================= 存活心跳 (测试用) =================
    if not hourly_alerts and not daily_summary and valid_items_checked > 0:
        send_wxpusher(f"✅ 监控打卡 ({current_time_str})", f"脚本运行正常，刚刚成功获取了 {valid_items_checked} 件饰品的最新价格。<br>目前大盘平稳，未达到报警阈值。")

if __name__ == "__main__":
    main()