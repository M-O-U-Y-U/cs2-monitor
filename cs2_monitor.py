import requests
import time
import json
import os
import datetime
import urllib.parse

# ================= 配置区域 =================
WXPUSHER_APP_TOKEN = "AT_yHKSDVeK6iT5WJO6UEgHybzBaA0dBpGa"
WXPUSHER_UID = "UID_xpTn3FaNA1yWqDvDMQJYurXEen72"
STEAM_ID = "76561199123057301"
DATA_FILE = "advanced_data.json"

MIN_ITEM_VALUE = 0.5       # 忽略低于0.5元的物品
MIN_INCREASE_PERCENT = 1.0 # 涨幅超过1%才进行日内推送通知
REQUEST_DELAY = 10         # 【新增】每次查完一个饰品休眠几秒（防Steam封IP，建议8-12秒）
# ============================================

# 全局 Session 与 浏览器伪装 (防封锁)
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://steamcommunity.com/market/"
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
        res = session.get(url, timeout=10)
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
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"appid": 730, "currency": 23, "market_hash_name": hash_name}
    result = {"price": -1, "volume": "未知", "median": "未知"}
    try:
        res = session.get(url, params=params, timeout=10)
        if res.status_code == 429:
            print(f"[警告] 获取 {hash_name} 数据被限流 (429)")
            return result
        data = res.json()
        if not data.get("success"): return result
            
        if "lowest_price" in data:
            result["price"] = float(data['lowest_price'].replace('¥', '').replace(',', '').strip())
        if "volume" in data:
            result["volume"] = data['volume']
        if "median_price" in data:
            result["median"] = data['median_price']
        return result
    except Exception as e: 
        print(f"[错误] 获取 {hash_name} 数据异常: {e}")
        return result

def generate_sparkline_url(prices, is_red):
    """通过 QuickChart API 生成走势图 URL (纯前端渲染)"""
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

def main():
    now_utc = datetime.datetime.utcnow()
    now_bj = now_utc + datetime.timedelta(hours=8)
    today_str = now_bj.strftime("%Y-%m-%d")
    current_time_str = now_bj.strftime("%H:%M")
    
    # 只要是晚上22点之后（含23点），且今天没出过报告，即触发晚间大盘复盘
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
    if not inventory_items: return

    hourly_alerts = []
    daily_summary = []
    valid_items_checked = 0 # 统计成功获取价格的饰品数

    for hash_name, cn_name in inventory_items.items():
        market_data = get_market_data(hash_name)
        price = market_data["price"]
        volume = market_data["volume"]
        median = market_data["median"]
        
        # 价格低于阈值或获取失败(被429限流)的处理
        if price <= MIN_ITEM_VALUE:
            if should_generate_daily and hash_name in db:
                db[hash_name]["start_price"] = db[hash_name].get("last_price", 0)
                db[hash_name]["history"] = [{"time": "昨日收盘", "price": db[hash_name]["start_price"]}]
            time.sleep(REQUEST_DELAY) # 使用配置的延长休眠时间
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
                
                # 动态捕捉盘中突破新高
                if price > historical_high:
                    high_tag = "🚀 <span style='color:red;'><b>突破历史新高！</b></span>"
                    item_data["historical_high"] = price 
                else:
                    high_tag = "📈 价格回升 (波动期)"
                
                msg = (f"<div style='border-bottom: 1px dashed #ccc; padding-bottom: 10px; margin-bottom: 10px;'>"
                       f"<b style='font-size:16px;'>{cn_name}</b><br>"
                       f"状态：{high_tag}<br>"
                       f"价格变动：¥{last_price:.2f} ➡️ <b>¥{price:.2f}</b> "
                       f"<span style='color:red;'>(+{increase_percent:.2f}%)</span><br>"
                       f"<span style='font-size:12px; color:#555;'>"
                       f"24h热度：{volume} 笔 | 中位价：{median}<br>"
                       f"</span></div>")
                hourly_alerts.append(msg)
        
        # 记录全天波动轨迹 (价格发生变化才记录)
        last_history_price = item_data["history"][-1]["price"] if item_data["history"] else start_price
        if price != last_history_price:
            item_data["history"].append({"time": current_time_str, "price": price})
            
        item_data["last_price"] = price
        
        # ========== 2. 晚间复盘逻辑 (高低点 + 折线图) ==========
        if should_generate_daily:
            net_change = ((price - start_price) / start_price * 100) if start_price > 0 else 0
            
            # 只要今天涨跌超过阈值或者产生过价格跳动，就出复盘
            if abs(net_change) >= MIN_INCREASE_PERCENT or len(item_data['history']) > 1:
                trend_color = "red" if net_change > 0 else "green"
                is_red_chart = (net_change >= 0)
                
                all_prices_today = [start_price] + [x['price'] for x in item_data['history']]
                if price not in all_prices_today: all_prices_today.append(price)
                
                day_high = max(all_prices_today)
                day_low = min(all_prices_today)
                
                chart_url = generate_sparkline_url(all_prices_today, is_red_chart)
                
                if day_high > historical_high:
                    high_str = f"<span style='color:red;'><b>突破历史新高 (原¥{historical_high:.2f})！🎊</b></span>"
                    item_data["historical_high"] = day_high
                else:
                    high_str = f"距历史高位(¥{historical_high:.2f})差 ¥{(historical_high - day_high):.2f}"

                history_str_list = [f"{x['time']}(¥{x['price']:.2f})" for x in item_data['history']]
                history_path = " > ".join(history_str_list)
                
                summary_msg = (f"<div style='margin-bottom:15px;'>"
                               f"<b>{cn_name}</b> <span style='font-size:12px; color:#888;'>({hash_name})</span><br>"
                               f"今日走势：开盘 ¥{start_price:.2f} ➡️ 收盘 <b>¥{price:.2f}</b> "
                               f"<span style='color:{trend_color};'><b>({net_change:+.2f}%)</b></span><br>"
                               f"📊 今日最高: ¥{day_high:.2f} | 最低: ¥{day_low:.2f}<br>"
                               f"👑 {high_str}<br>"
                               f"🔥 24h热度: {volume} 笔 | 中位参考: {median}<br>"
                               f"<img src='{chart_url}' alt='走势图' style='width:100%; max-width:300px; margin-top:5px;'><br>"
                               f"<div style='font-size:11px; color:#888; margin-top:4px; padding:4px; background:#f5f5f5; border-radius:4px;'>"
                               f"全天轨迹: {history_path}</div>"
                               f"</div>")
                daily_summary.append((net_change, summary_msg))
            
            # 跨天重置，保留 historical_high 数据
            item_data["start_price"] = price
            item_data["history"] = [{"time": current_time_str, "price": price}]

        time.sleep(REQUEST_DELAY) # 使用配置的延长休眠时间，防 429

    # 数据持久化保存
    with open(DATA_FILE, 'w', encoding='utf-8') as f: 
        json.dump(db, f, ensure_ascii=False, indent=2)

    # 发送推送消息
    if hourly_alerts:
        send_wxpusher(f"📈 CS2饰品异动通知 ({current_time_str})", "".join(hourly_alerts))
    
    if daily_summary:
        daily_summary.sort(key=lambda x: x[0], reverse=True)
        final_summary_html = "<hr>".join([msg for _, msg in daily_summary])
        send_wxpusher(f"📊 CS2饰品今日大盘复盘 ({today_str})", f"今日产生有效波动的饰品汇总：<br><br>{final_summary_html}")

    # ================= 存活心跳 (测试用) =================
    if not hourly_alerts and not daily_summary and valid_items_checked > 0:
        send_wxpusher(f"✅ 监控打卡 ({current_time_str})", f"脚本运行正常，刚刚成功巡查了 {valid_items_checked} 件饰品。<br>目前大盘平稳，未达到 1% 的报警阈值。")

if __name__ == "__main__":
    main()
