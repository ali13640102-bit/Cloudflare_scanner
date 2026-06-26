import socket
import ssl
import threading
from queue import Queue
import ipaddress
import time
import os
import urllib.request
import re
import random
import sys

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
        secure_sock.sendall(websocket_request.encode())
        response = secure_sock.recv(1024).decode(errors='ignore')
        secure_sock.close()
        if "HTTP/1.1 101" in response or "Sec-WebSocket-Accept" in response:
            return ping_time
        return None
    except Exception: return None

def test_ip_loss_and_ping(ip):
    success_count = 0
    total_ping = 0
    for _ in range(PACKET_TEST_COUNT):
        p = ping_ip(ip)
        if p is not None:
            success_count += 1
            total_ping += p
        time.sleep(0.1)
    loss = int(((PACKET_TEST_COUNT - success_count) / PACKET_TEST_COUNT) * 100)
    avg_ping = int(total_ping / success_count) if success_count > 0 else 999
    return loss, avg_ping

def worker_round_1():
    while not ip_queue.empty():
        ip = ip_queue.get()
        p = ping_ip(ip)
        if p is not None and p <= MAX_ALLOWED_PING:
            round_1_results.append(ip)
        ip_queue.task_done()

def worker_round_2():
    while not ip_queue.empty():
        ip = ip_queue.get()
        loss, ping = test_ip_loss_and_ping(ip)
        if loss < 100 and ping <= MAX_ALLOWED_PING:
            round_2_results.append({'ip': ip, 'loss': loss, 'ping': ping})
        ip_queue.task_done()

def load_ips_from_github():
    urls = [
        "https://raw.githubusercontent.com/vfarid/cf-clean-ips/main/list.txt",
        "https://raw.githubusercontent.com/ircfspace/cf2dns/master/list.txt"
    ]
    ips = set()
    ipv4_pattern = re.compile(r'^⚓?\s*([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})')
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as res:
                content = res.read().decode('utf-8')
                for line in content.split('\n'):
                    line = line.strip()
                    match = ipv4_pattern.match(line)
                    if match: ips.add(match.group(1))
                    elif '/' in line:
                        try:
                            for ip in ipaddress.IPv4Network(line, strict=False).hosts(): ips.add(str(ip))
                        except Exception: pass
        except Exception: pass
    return list(ips)

if __name__ == "__main__":
    print("🚀 Running Cloudflare Worker Engine...")
    all_ips = load_ips_from_github()
    if not all_ips:
        backup_ranges = ["104.16.0.0/12", "172.64.0.0/13"]
        for r in backup_ranges:
            for ip in ipaddress.IPv4Network(r).hosts():
                all_ips.append(str(ip))
                if len(all_ips) > 1500: break

    sampled_ips = random.sample(all_ips, min(len(all_ips), 1500))
    for ip in sampled_ips: ip_queue.put(ip)

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
    
    # خروجی گرفتن و ذخیره مستقیم در ریپازیتوری جهت سینک شدن با حلقه اصلی ربات
    with open("result.txt", "w") as f:
        for item in sorted_ips:
            f.write(f"{item['ip']}\n")
            
    print(f"✅ Scanning Done. Result generated successfully.")
    
