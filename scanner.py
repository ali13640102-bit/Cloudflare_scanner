import socket
import ssl
import threading
from queue import Queue
import ipaddress
import time
import os
import urllib.request
import urllib.parse

PORT = 443
TIMEOUT = 2.0
THREAD_COUNT_ROUND_1 = 150
THREAD_COUNT_ROUND_2 = 20
MAX_ALLOWED_PING = 450
PACKET_TEST_COUNT = 3  # تعداد تست پشت سر هم برای پکت‌لاست

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

def send_telegram_message(text):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req)
    except:
        pass

def main():
    try:
        with open("ips.txt", "r") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return
    
    lines = [line.strip() for line in lines if line.strip()]
    if not lines:
        return
    
    for line in lines:
        try:
            for ip in ipaddress.IPv4Network(line, strict=False):
                ip_queue.put(str(ip))
        except ValueError:
            ip_queue.put(line)
            
    threads = []
    for _ in range(THREAD_COUNT_ROUND_1):
        t = threading.Thread(target=worker_round_1)
        t.start()
        threads.append(t)
    for t in threads: t.join()
    
    for item in round_1_results:
        ip_queue.put(item)
        
    threads = []
    for _ in range(THREAD_COUNT_ROUND_2):
        t = threading.Thread(target=worker_round_2)
        t.start()
        threads.append(t)
    for t in threads: t.join()
    
    sorted_ips = sorted(round_2_results, key=lambda x: (x['loss'], x['ping']))
    
    with open("result.txt", "w") as f:
        for item in sorted_ips:
            f.write(f"{item['ip']}\n")
            
    # خواندن تاریخچه قبلی برای قابلیت ۱
    old_history = set()
    if os.path.exists("history.txt"):
        with open("history.txt", "r") as f:
            old_history = set(f.read().splitlines())
            
    # ذخیره تاریخچه جدید
    current_ips = [item['ip'] for item in sorted_ips[:15]]
    with open("history.txt", "w") as f:
        for ip in current_ips:
            f.write(f"{ip}\n")
            
    if sorted_ips:
        # دسته‌بندی آی‌پی‌ها برای قابلیت ۳
        excellent = [i for i in sorted_ips if i['ping'] < 150 and i['loss'] == 0]
        good = [i for i in sorted_ips if 150 <= i['ping'] <= 300 and i['loss'] == 0]
        others = [i for i in sorted_ips if i['ping'] > 300 or i['loss'] > 0]
        
        ranges_str = ", ".join(lines[:3])
        if len(lines) > 3: ranges_str += " و..."
            
        msg = f"<b>📊 گزارش اسکن همه‌جانبه رنج‌های ({ranges_str})</b>\n\n"
        msg += f"🟢 پینگ زیر ۱۵۰ (ثابت): <b>{len(excellent)} آی‌پی</b>\n"
        msg += f"🟡 پینگ ۱۵۰ تا ۳۰۰ (ثابت): <b>{len(good)} آی‌پی</b>\n"
        msg += f"🟠 آی‌پی‌های نوسانی یا کند: <b>{len(others)} آی‌پی</b>\n\n"
        
        msg += "<b>🔥 لیست ۱۰ آی‌پی برتر این دوره:</b>\n"
        msg += "<i>(علامت ✨ یعنی این آی‌پی جدید است و ساعت قبل نبوده)</i>\n\n"
        
        for item in sorted_ips[:10]:
            is_new = "✨ " if item['ip'] not in old_history else ""
            msg += f"{is_new}<code>{item['ip']}</code> ➔ <b>{item['ping']}ms</b> (Loss: {item['loss']}%)\n"
            
        send_telegram_message(msg)

if __name__ == "__main__":
    main()
    
