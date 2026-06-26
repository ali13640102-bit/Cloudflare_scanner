import socket
import ssl
import threading
from queue import Queue
import ipaddress
import time
import os
import urllib.request
import urllib.parse
import json
import re
import random
from datetime import datetime, timedelta

PORT = 443
TIMEOUT = 2.0
THREAD_COUNT_ROUND_1 = 150
THREAD_COUNT_ROUND_2 = 20
MAX_ALLOWED_PING = 450
PACKET_TEST_COUNT = 3

ip_queue = Queue()
round_1_results = []
round_2_results = []

def ping_ip(ip):
    try:
        start_time = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        secure_sock = context.wrap_socket(sock, server_hostname=ip)
        secure_sock.connect((ip, PORT))
        ping_time = int((time.time() - start_time) * 1000)
        
        websocket_request = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {ip}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        secure_sock.send(websocket_request.encode('utf-8'))
        response = secure_sock.recv(1024).decode('utf-8', errors='ignore')
        secure_sock.close()
        if "HTTP/1.1 101" in response or "Server: cloudflare" in response:
            return ping_time
    except:
        return None
    return None

def worker_round_1():
    while not ip_queue.empty():
        ip = ip_queue.get()
        ping = ping_ip(ip)
        if ping is not None:
            round_1_results.append({"ip": ip, "ping": ping})
        ip_queue.task_done()

def worker_round_2():
    while not ip_queue.empty():
        ip_info = ip_queue.get()
        success_count = 0
        total_ping = 0
        for _ in range(PACKET_TEST_COUNT):
            p_time = ping_ip(ip_info['ip'])
            if p_time is not None:
                success_count += 1
                total_ping += p_time
        if success_count > 0:
            avg_ping = int(total_ping / success_count)
            packet_loss = int(((PACKET_TEST_COUNT - success_count) / PACKET_TEST_COUNT) * 100)
            if avg_ping <= MAX_ALLOWED_PING:
                round_2_results.append({"ip": ip_info['ip'], "ping": avg_ping, "loss": packet_loss})
        ip_queue.task_done()

# تابع ساخت نوار گرافیکی پینگ دقیقاً مطابق فرمت درخواستی شما
def get_ping_bar(ping):
    total_blocks = 8
    filled_blocks = max(1, min(total_blocks, int((250 - ping) / 25))) if ping < 250 else 1
    bar = "🟩" * filled_blocks + "⬜" * (total_blocks - filled_blocks)
    return bar

def send_telegram_results(text, raw_ips_text, target_user_id):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token: 
        return
    
    # مقصدهای ارسال پیام اصلی نتایج
    # ۱. کاربر متقاضی (یا سیگنال خودکار) ۲. کانال عمومی شما
    CHANNEL_ID = "@IP_ScannerDR"
    
    destinations = []
    if target_user_id not in ["AUTO_SCAN", "AUTO_SCAN_ALL"]:
        destinations.append(target_user_id)
    
    # اگر اسکن خودکار همگانی بود یا آی‌پی شخصی ارسال شد، به کانال هم فروخته شود
    if target_user_id == "AUTO_SCAN_ALL" or target_user_id not in ["AUTO_SCAN", "AUTO_SCAN_ALL"]:
        destinations.append(CHANNEL_ID)

    for chat_id in destinations:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            
            # ایجاد دکمه شیشه‌ای کپی یکجای آی‌پی‌ها با استفاده از switch_inline_query_current_chat
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "📋 ارسال همه آی‌پی‌ها یک‌جا", "switch_inline_query_current_chat": f"\n\n{raw_ips_text}"}
                ]]
            }
            
            data = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(reply_markup)
            }
            
            req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode("utf-8"), method="POST")
            urllib.request.urlopen(req, timeout=10)
            time.sleep(1)
        except Exception as e:
            print(f"Telegram Error for {chat_id}: {e}")

def fetch_ips_to_scan():
    ips_to_scan = set()
    all_extracted_ips = []
    try:
        url = "https://raw.githubusercontent.com/vfarid/cf-clean-ips/main/list.txt"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            lines = response.read().decode('utf-8').splitlines()
        for line in lines:
            match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', line)
            if match: all_extracted_ips.append(match.group(0))
    except Exception: pass

    if all_extracted_ips:
        for ip in all_extracted_ips: ips_to_scan.add(ip)

    try:
        if os.path.exists("ips.txt"):
            with open("ips.txt", "r") as f: local_lines = f.read().splitlines()
            for line in local_lines:
                if line.strip():
                    try:
                        for ip in ipaddress.IPv4Network(line.strip(), strict=False): ips_to_scan.add(str(ip))
                    except ValueError: ips_to_scan.add(line.strip())
    except Exception: pass
    return list(ips_to_scan)

def main():
    # دریافت آیدی کاربر از متغیرهای محیطی گیت‌هاب اکشنز
    target_user_id = os.environ.get("TARGET_USER_ID", "6453638080")
    
    target_ips = fetch_ips_to_scan()
    if not target_ips: return
    random.shuffle(target_ips)
    
    for ip in target_ips: ip_queue.put(ip)
            
    threads = []
    for _ in range(THREAD_COUNT_ROUND_1):
        t = threading.Thread(target=worker_round_1)
        t.start(); threads.append(t)
    for t in threads: t.join()
    
    for item in round_1_results: ip_queue.put(item)
        
    threads = []
    for _ in range(THREAD_COUNT_ROUND_2):
        t = threading.Thread(target=worker_round_2)
        t.start(); threads.append(t)
    for t in threads: t.join()
    
    sorted_ips = sorted(round_2_results, key=lambda x: (x['loss'], x['ping']))
    
    # ۱. بروزرسانی و ذخیره نتایج در فایل result.txt
    with open("result.txt", "w") as f:
        for item in sorted_ips: f.write(f"{item['ip']}\n")
            
    if sorted_ips:
        # ۲. ساخت متن پیام نتایج دقیقاً مطابق الگوی گرافیکی شما
        msg = f"🛰 <b>[ CLOUDFLARE SCANNER ]</b>\n"
        msg += f"<code>────────────────────────────</code>\n\n"
        
        raw_ips_list = []
        for idx, item in enumerate(sorted_ips[:10]):
            if item['ping'] <= 110: light = "🟢"
            elif item['ping'] <= 190: light = "🟡"
            else: light = "🔴"
                
            ping_bar = get_ping_bar(item['ping'])
            msg += f"⚡️ {light} <b>#{idx+1:02d}</b> ── <code>{item['ip']}</code>  ⚡️ <b>{item['ping']}ms</b>\n"
            msg += f"{ping_bar}\n\n"
            raw_ips_list.append(item['ip'])
            
        msg += f"<code>────────────────────────────</code>\n"
        
        # محاسبه زمان به وقت تهران (GMT+3:30)
        tehran_time = datetime.utcnow() + timedelta(hours=3, minutes=30)
        time_str = tehran_time.strftime("%H:%M:%S")
        
        msg += f"🕒  {time_str}\n"
        msg += f"🌐 @IP_ScannerDR\n"
        msg += f"👤 @Eror_508"
        
        # ۳. ساخت لیست متنی ستونی برای قرار گرفتن پشت دکمه شیشه‌ای کپی
        copy_text_header = "📋 لیست تمام آی‌پی‌های اسکن شده (تک‌کلیک کپی):\n\n"
        copy_all_text = copy_text_header + "\n".join(raw_ips_list)
        
        # ارسال نهایی پیام
        send_telegram_results(msg, copy_all_text, target_user_id)

if __name__ == "__main__":
    main()
    
