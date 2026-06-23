import socket
import ssl
import threading
from queue import Queue
import ipaddress
import time
import random
import os
import urllib.request
import urllib.parse

PORT = 443
TIMEOUT = 2.0
THREAD_COUNT_ROUND_1 = 150
THREAD_COUNT_ROUND_2 = 20
MAX_ALLOWED_PING = 450
RANDOM_COUNT = 6

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
        second_ping = ping_ip(ip_info['ip'])
        if second_ping is not None and second_ping <= MAX_ALLOWED_PING:
            avg_ping = int((ip_info['ping'] + second_ping) / 2)
            round_2_results.append({"ip": ip_info['ip'], "ping": avg_ping})
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
        
    chosen_lines = random.sample(lines, min(RANDOM_COUNT, len(lines)))
    
    for line in chosen_lines:
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
    
    sorted_ips = sorted(round_2_results, key=lambda x: x['ping'])
    
    with open("result.txt", "w") as f:
        for item in sorted_ips:
            f.write(f"{item['ip']}\n")
            
    if sorted_ips:
        msg = f"<b>اسکن سریع رنج {chosen_lines[0]} به پایان رسید!</b>\n\n"
        msg += "<b>برترین آی‌پی‌های یافت شده:</b>\n"
        for item in sorted_ips[:10]:
            msg += f"<code>{item['ip']}</code> ➔ {item['ping']}ms\n"
        send_telegram_message(msg)

if __name__ == "__main__":
    main()
    
