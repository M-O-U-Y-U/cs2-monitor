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

# CSQAQ 国内真实数据 API Token
CSQAQ_API_TOKEN = "JXJTD1B787E8L01767A8Z738" 

MIN_ITEM_VALUE = 0.5       
MIN_INCREASE_PERCENT = 1.0 

# 既然要直连 Steam 官方，必须保证 8~12 秒的休眠防 429 限流
MIN_REQUEST_DELAY = 8.0    
MAX_REQUEST_DELAY = 12.0   
# ============================================

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
    except: pass

def bind_dynamic_ip():
    """【防拦截】自动将当前 GitHub 节点 IP 绑定至 CSQAQ 白名单"""
    if not CSQAQ_API_TOKEN: return
    url = "https://api.csqaq.com/api/v1/sys/bind_local_ip"
    headers = {"ApiToken": CSQAQ_API_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.post(url, headers=headers, json={}, timeout=10)
        data = res.json()
        if data.get("code") == 200:
            print(f"[系统] {data.get('data', '成功将当前IP绑定至白名单！')}")
        else:
            print(f"[系统提示] IP绑定状态: {data.get('msg')}")
    except Exception as e:
        print(f"[错误] 自动绑定IP发生异常: {e}")

def get_inventory():
    """获取库存"""
    url = f"https://steamcommunity.com/inventory/{STEAM_ID}/730/2?l=schinese&count=500"
    items = {}
    try:
        res = session.get(url, timeout=15)
        if res.status_code == 429:
            print("[警告] 获取库存被 Steam 限流 (429)")
            return {}
        try:
            data = res.json()
        except: return {}
            
        for item in data.get('descriptions', []):
            if item.get('marketable'):
                hash_name = item['market_hash_name']
                items[hash_name] = item.get('name', hash_name)
        return items
    except: return {}

def get_steam_market_data(hash_name):
    """【绝对核心】实时获取 Steam 官方在售底价"""
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"appid": 730, "currency": 23, "market_hash_name": hash_name}
    result = {"price": -1}
    
    try:
        res = session.get(url, params=params, timeout=15)
        if res.status_code == 429:
            print(f"[警告] Steam 接口限流 (429): {hash_name}")
            return result
        try:
            data = res.json()
        except: return result

        if not data.get("success"): return result
            
        if "lowest_price" in data:
            result["price"] = float(str(data['lowest_price']).replace('¥', '').replace(',', '').strip())
        return result
    except: return result

def get_csqaq_good_id(hash_name):
    """【辅核第一步】搜索获取 CSQAQ 站内的专属 good_id"""
    if not CSQAQ_API_TOKEN: return None
    url = "https://api.csqaq.com/api/v1/info/get_good_id"
    headers = {"ApiToken": CSQAQ_API_TOKEN, "Content-Type": "application/json"}
    payload = {"page_index": 1, "page_size": 20, "search": hash_name}
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 429: return None
        
        res_json = res.json()
        if res_json.get("code") != 200: return None
            
        data_dict = res_json.get("data", {}).get("data", {})
        for _, item in data_dict.items():
            if item.get("market_hash_name") == hash_name:
                return item.get("id")
    except: pass
    return None

def get_csqaq_max_prices(good_id):
    """【辅核第二步】根据 ID 拉取国内各大平台现金价，并筛出最高价"""
    result = {"max_sell": "未知", "max_buy": "未知"}
    url = f"https://api.csqaq.com/api/v1/info/good?id={good_id}"
    headers = {"ApiToken": CSQAQ_API_TOKEN}
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 429: return result
        
        res_json = res.json()
        if res_json.get("code") != 200: return result
            
        details = res_json.get("data", {}).get("goods_info", {})
        
        sell_prices = []
        buy_prices = []
        platforms = ["buff", "yyyp", "c5", "eco", "igxe"]
        
        for p in platforms:
            sp = details.get(f"{p}_sell_price")
            bp = details.get(f"{p}_buy_price")
            if sp and float(sp) > 0: sell_prices.append(float(sp))
            if bp and float(bp) > 0: buy_prices.append(float(bp))
                
        if sell_prices: result["max_sell"] = f"¥{max(sell_prices):.2f}"
        if buy_prices: result["max_buy"] = f"¥{max(buy_prices):.2f}"
        
        return result
    except: return result

def generate_sparkline_url(prices, is_red):
    """生成走势折线图"""
    if not prices: return ""
    if len(prices) == 1: prices.append(prices[0])
    color = "rgb(255, 77, 79)" if is_red else "rgb(82, 196, 26)"
    bg_color = "rgba(255, 77, 79, 0.1)" if is_red else "rgba(82, 196, 26, 0.1)"
    prices_str = ",".join(map(str, prices))
    config_str = (f"{{type:'sparkline',data:{{datasets:[{{"
                  f"data:[{prices_str}],fill:true,backgroundColor:'{bg_color}',"
                  f"borderColor:'{color}',borderWidth:2,pointRadius:0"
                  f"}}]}}}}")
    return f"https://quickchart.io/chart?w=300&h=80&bkg=white&c={urllib.parse.quote(config_str)}"

def main():
    now_utc = datetime.datetime.utcnow()
    now_bj = now_utc + datetime.timedelta(hours=8)
    today_str = now_bj.strftime("%Y-%m-%d")
    current_time_str = now_bj.strftime("%H:%M")
    
    is_11_pm = (now_bj.hour >= 22)

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f: db = json.load(f)
    else: db = {}

    meta = db.get("_meta", {})
    last_report_date = meta.get("last_report_date", "")
    
    should_generate_daily = (is_11_pm and last_report_date != today_str)
    if should_generate_daily: meta["last_report_date"] = today_str
    db["_meta"] = meta

    inventory_items = get_inventory()
    if not inventory_items: 
        print("[提示] 库存为空或获取失败，结束运行。")
        return

    hourly_alerts = []
    daily_summary = []
    valid_items_checked = 0 

    print("[启动] 核心监控系统启动...")
    # 自动解除 CSQAQ 的动态 IP 风控拦截
    bind_dynamic_ip()
    print("[提示] 正在获取 Steam 实时行情，并辅以国内数据比对...")

    for hash_name, cn_name in inventory_items.items():
        
        if hash_name not in db:
            db[hash_name] = {"history": []}
        item_data = db[hash_name]
        
        # ========== 1. 【主引擎】绝对实时获取 Steam 官方价格 ==========
        steam_data = get_steam_market_data(hash_name)
        price = steam_data["price"]
        
        # 过滤低价值废品或获取失败的饰品
        if price <= MIN_ITEM_VALUE:
            if should_generate_daily and "start_price" in item_data:
                item_data["start_price"] = item_data.get("last_price", 0)
                item_data["history"] = [{"time": "昨日收盘", "price": item_data["start_price"]}]
            
            # 由于访问了 Steam，必须严格休眠防 429
            time.sleep(round(random.uniform(MIN_REQUEST_DELAY, MAX_REQUEST_DELAY), 2))
            continue
            
        valid_items_checked += 1
        
        # ========== 2. 【辅引擎】智能抓取国内现金参考价 ==========
        csqaq_max_sell = "未知"
        csqaq_max_buy = "未知"
        
        # 读取记忆ID，提速
        good_id = item_data.get("csqaq_id")
        if not good_id:
            good_id = get_csqaq_good_id(hash_name) 
            time.sleep(1.5) # CSQAQ单点请求限流
            if good_id: item_data["csqaq_id"] = good_id
                
        if good_id:
            csqaq_data = get_csqaq_max_prices(good_id)
            csqaq_max_sell = csqaq_data["max_sell"]
            csqaq_max_buy = csqaq_data["max_buy"]

        # ========== 核心属性初始化与升级 ==========
        if "start_price" not in item_data:
            item_data["start_price"] = price
            item_data["last_price"] = price
            item_data["history"] = [{"time": current_time_str, "price": price}]
            item_data["historical_high"] = price
            item_data["daily_alert_high"] = price # 初始化今日报警水位线

        start_price = item_data["start_price"]
        last_price = item_data["last_price"]
        historical_high = item_data.get("historical_high", price)
        daily_alert_high = item_data.get("daily_alert_high", start_price)
        
        # ========== 常规异动监控 (防横跳冷却处理) ==========
        if price > last_price and last_price > 0:
            increase_percent = ((price - last_price) / last_price) * 100
            
            if increase_percent >= MIN_INCREASE_PERCENT:
                # 【防打扰核心】只有突破了今天已经报过警的最高价格，才会发送推送
                if price > daily_alert_high:
                    item_data["daily_alert_high"] = price # 更新报警水位线
                    
                    if price > historical_high:
                        high_tag = "🚀 <span style='color:red;'><b>突破 Steam 历史新高！</b></span>"
                        item_data["historical_high"] = price 
                    else:
                        high_tag = "📈 Steam 价格回升"
                    
                    msg = (f"<div style='border-bottom: 1px dashed #ccc; padding-bottom: 10px; margin-bottom: 10px;'>"
                           f"<b style='font-size:16px;'>{cn_name}</b><br>"
                           f"当前状态：{high_tag}<br>"
                           f"Steam余额价：¥{last_price:.2f} ➡️ <b style='font-size:15px; color:#d9534f;'>¥{price:.2f}</b> "
                           f"<span style='color:red;'>(+{increase_percent:.2f}%)</span><br>"
                           f"<div style='font-size:11px; color:#666; background:#f9f9f9; padding:4px 6px; border-radius:4px; margin-top:6px;'>"
                           f"🛒 <b>国内现金参考:</b> 全网最高底价 {csqaq_max_sell} | 最高求购 {csqaq_max_buy}"
                           f"</div></div>")
                    hourly_alerts.append(msg)
        
        last_history_price = item_data["history"][-1]["price"] if item_data["history"] else start_price
        if price != last_history_price:
            item_data["history"].append({"time": current_time_str, "price": price})
            
        item_data["last_price"] = price
        
        # ========== 晚间复盘逻辑 (以 Steam 为准) ==========
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
                
                summary_msg = (f"<div style='margin-bottom:20px;'>"
                               f"<b style='font-size:15px;'>{cn_name}</b> <span style='font-size:12px; color:#888;'>({hash_name})</span><br>"
                               f"Steam 今日收盘：<b style='font-size:16px;'>¥{price:.2f}</b> "
                               f"<span style='color:{trend_color};'><b>({net_change:+.2f}%)</b></span><br>"
                               f"📊 Steam 探底: ¥{day_low:.2f} | 冲高: ¥{day_high:.2f}<br>"
                               f"👑 {high_str}<br>"
                               f"<div style='font-size:11px; color:#31708f; background:#d9edf7; padding:4px 6px; border-radius:4px; margin:6px 0;'>"
                               f"🛒 <b>国内辅助参考:</b> 全网最高底价 {csqaq_max_sell} | 最高求购 {csqaq_max_buy}"
                               f"</div>"
                               f"<img src='{chart_url}' alt='走势图' style='width:100%; max-width:300px; margin-top:2px; border-radius:4px;'><br>"
                               f"<div style='font-size:11px; color:#888; margin-top:6px; padding:4px; background:#f9f9f9; border:1px solid #eee; border-radius:4px;'>"
                               f"<b>Steam 盘中轨迹:</b> {history_path}</div>"
                               f"</div>")
                daily_summary.append((net_change, summary_msg))
            
            item_data["start_price"] = price
            item_data["history"] = [{"time": current_time_str, "price": price}]
            item_data["daily_alert_high"] = price # 复盘时重置报警水位线

        # ================= 极其重要的 Steam 防护休眠 =================
        time.sleep(round(random.uniform(MIN_REQUEST_DELAY, MAX_REQUEST_DELAY), 2))

    with open(DATA_FILE, 'w', encoding='utf-8') as f: 
        json.dump(db, f, ensure_ascii=False, indent=2)

    if hourly_alerts:
        send_wxpusher(f"📈 饰品异动雷达 ({current_time_str})", "".join(hourly_alerts))
    
    if daily_summary:
        daily_summary.sort(key=lambda x: x[0], reverse=True)
        final_summary_html = "<hr style='border:1px dashed #ccc;'>".join([msg for _, msg in daily_summary])
        send_wxpusher(f"📊 Steam 大盘深度复盘 ({today_str})", f"今日产生有效波动的饰品汇总：<br><br>{final_summary_html}")

    if not hourly_alerts and not daily_summary and valid_items_checked > 0:
        send_wxpusher(f"✅ 监控打卡 ({current_time_str})", f"双核看盘系统运行正常！<br>已完成 {valid_items_checked} 件饰品的实时价格排查。<br>目前大盘平稳，未达到报警阈值。")

if __name__ == "__main__":
    main()