import socket
import ssl
import threading
from queue import Queue
import ipaddress
import time

# تنظیمات اصلی برنامه
PORT = 443
TIMEOUT = 2.0
THREAD_COUNT_ROUND_1 = 50  # تعداد ترد برای دور اول (سریع)
THREAD_COUNT_ROUND_2 = 10  # تعداد ترد برای دور دوم (دقیق‌تر)
MAX_ALLOWED_PING = 250     # حداکثر پینگ مجاز در دور دوم (به میلی‌ثانیه) - می‌تونی تغییرش بدی

ip_queue = Queue()
round_1_results = []
round_2_results = []

def ping_ip(ip):
    """تابع پایه برای اتصال و محاسبه پینگ"""
    try:
        start_time = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        secure_sock = context.wrap_socket(sock, server_hostname=ip)
        
        secure_sock.connect((ip, PORT))
        
        # محاسبه پینگ بر حسب میلی‌ثانیه
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
        # اسکن دوباره برای اطمینان از پینگ پایدار
        second_ping = ping_ip(ip_info['ip'])
        
        # اگر در دور دوم هم زنده بود و پینگش از حد مجاز کمتر بود، تایید میشه
        if second_ping is not None and second_ping <= MAX_ALLOWED_PING:
            # میانگین پینگ دور اول و دوم رو برای مرتب‌سازی دقیق‌تر در نظر می‌گیریم
            avg_ping = int((ip_info['ping'] + second_ping) / 2)
            round_2_results.append({"ip": ip_info['ip'], "ping": avg_ping})
            print(f" [✔] Verified IP: {ip_info['ip']} | Final Ping: {avg_ping}ms")
        ip_queue.task_done()

def main():
    print("--- Starting Round 1: Fast Scan ---")
    try:
        with open("ips.txt", "r") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        print("Error: ips.txt file not found!")
        return

    for line in lines:
        line = line.strip()
        if not line: continue
        try:
            for ip in ipaddress.IPv4Network(line, strict=False):
                ip_queue.put(str(ip))
        except ValueError:
            ip_queue.put(line)

    print(f"Total IPs to scan: {ip_queue.qsize()}")
    
    # اجرای دور اول
    threads = []
    for _ in range(THREAD_COUNT_ROUND_1):
        t = threading.Thread(target=worker_round_1)
        t.start()
        threads.append(t)
    for t in threads: t.join()

    print(f"Round 1 finished. Found {len(round_1_results)} alive IPs.")
    print("--- Starting Round 2: Strict Filtering ---")

    # ریختن آی‌پی‌های زنده دور اول به صف برای شروع دور دوم
    for item in round_1_results:
        ip_queue.put(item)

    # اجرای دور دوم
    threads = []
    for _ in range(THREAD_COUNT_ROUND_2):
        t = threading.Thread(target=worker_round_2)
        t.start()
        threads.append(t)
    for t in threads: t.join()

    # مرتب‌سازی نهایی بر اساس کمترین پینگ
    sorted_ips = sorted(round_2_results, key=lambda x: x['ping'])

    # ذخیره کاملاً خام؛ فقط و فقط آی‌پّی به صورت ستونی
    with open("result.txt", "w") as f:
        for item in sorted_ips:
            f.write(f"{item['ip']}\n")

    print(f"All done! {len(sorted_ips)} ultra-clean IPs saved strictly to result.txt")

if __name__ == "__main__":
    main()
    
