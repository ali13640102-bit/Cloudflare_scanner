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

def send_telegram(text):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    MY_PERSONAL_ID = "6453638080"
    CHANNEL_ID = "-1004451276132"
    
    if not bot_token: return
    destinations = [MY_PERSONAL_ID, CHANNEL_ID]
    
    for chat_id in destinations:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode("utf-8"))
            urllib.request.urlopen(req)
            time.sleep(1)
        except Exception as e:
            print(f"Telegram Error for {chat_id}: {e}")

def fetch_ips_to_scan():
    ips_to_scan = set()
    
    # ۱. دانلود تمام تک‌آی‌پی‌های موجود در سایت منبع
    try:
        url = "https://raw.githubusercontent.com/vfarid/cf-clean-ips/main/list.txt"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            lines = response.read().decode('utf-8').splitlines()
            
        for line in lines:
            match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', line)
            if match:
                ips_to_scan.add(match.group(0)) # اضافه کردن مستقیم تک‌آی‌پی بدون تبدیل به رنج
    except Exception as e:
        print(f"Error fetching online IPs: {e}")

    # ۲. اضافه کردن رنج‌ها یا آی‌پی‌های دستی شما از فایل ips.txt (در صورت وجود)
    try:
        if os.path.exists("ips.txt"):
            with open("ips.txt", "r") as f:
                local_lines = f.read().splitlines()
            for line in local_lines:
                if line.strip():
                    try:
                        # اگر در فایل داخلی رنج نوشته بودید، آی‌پی‌های آن رنج را باز می‌کند
                        for ip in ipaddress.IPv4Network(line.strip(), strict=False):
                            ips_to_scan.add(str(ip))
                    except ValueError:
                        ips_to_scan.add(line.strip())
    except Exception as e:
        print(f"Error reading local ips.txt: {e}")
        
    return list(ips_to_scan)

def main():
    target_ips = fetch_ips_to_scan()
    if not target_ips: return
    
    # مخلوط کردن آی‌پی‌ها برای اسکن عادلانه
    random.shuffle(target_ips)
    
    for ip in target_ips:
        ip_queue.put(ip)
            
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
    
    with open("result.txt", "w") as f:
        for item in sorted_ips: f.write(f"{item['ip']}\n")
            
    if sorted_ips:
        msg = f"⚡️ <b>برترین آی‌پی‌های تمیز کلودفلر</b>\n"
        msg += f"───────────────────\n"
        
        raw_ips_list = []
        for idx, item in enumerate(sorted_ips[:10]):
            if item['ping'] <= 110:
                light = "🟢"
            elif item['ping'] <= 190:
                light = "🟡"
            else:
                light = "🔴"
                
            if item['loss'] == 0:
                signal = "📶 عالی"
            elif item['loss'] <= 33:
                signal = "⚡️ پایدار"
            else:
                signal = "⚠️ نوسانی"
                
            msg += f"{light} <code>{item['ip']}</code>  ➔  ⏱ <b>{item['ping']}ms</b> | {signal}\n"
            raw_ips_list.append(item['ip'])
            
        msg += f"───────────────────\n"
        
        copy_all_text = "\n".join(raw_ips_list)
        msg += f"👇 <b>برای کپی یکجای تمام آی‌پی‌ها روی کادر زیر بزنید:</b>\n"
        msg += f"<code>{copy_all_text}</code>\n"
        msg += f"───────────────────\n"
        
        tehran_time = datetime.utcnow() + timedelta(hours=3, minutes=30)
        time_str = tehran_time.strftime("%H:%M")
        
        msg += f"📢 <b>@IP_ScannerDR</b> | 🕒 <i>ساعت اسکن: {time_str} به وقت تهران</i>"
        
        send_telegram(msg)

if __name__ == "__main__":
    main()
        
