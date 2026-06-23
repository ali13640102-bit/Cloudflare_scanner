import socket
import ssl
import threading
from queue import Queue
import ipaddress

# تنطیمات اصلی برنامه
PORT = 443  # پورتی که کلودفلر روی اون فعال هست (HTTPS)
TIMEOUT = 2.0  # مدت زمان انتظار برای پاسخ هر آی‌پی (به ثانیه)
THREAD_COUNT = 100  # تعداد اسکن همزمان (سرعت رو بالا می‌بره)

# صف برای مدیریت آی‌پی‌هایی که باید اسکن بشن
ip_queue = Queue()
# لیستی برای ذخیره آی‌پی‌های سالم و تمیز
healthy_ips = []


def check_ip(ip):
    """این تابع یک آی‌پی رو می‌گیره و تست TCP + WebSocket رو روش انجام میده"""
    try:
        # ۱. ساخت یک سوکت TCP معمولی
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)

        # ۲. ایجاد اتصال امن SSL/TLS (چون پورت 443 هست)
        context = ssl.create_default_context()
        # لغو تایید سخت‌گیرانه گواهی برای جلوگیری از خطای دامنه
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        secure_sock = context.wrap_socket(sock, server_hostname=ip)

        # اتصال به آی‌پی
        secure_sock.connect((ip, PORT))

        # ۳. ارسال درخواست فرضی برای ارتقا به WebSocket (HTTP Handshake)
        # ما یک درخواست HTTP ارسال می‌کنیم و تو هدر می‌گیم که دسترسی WebSocket می‌خوایم
        websocket_request = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {ip}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )

        secure_sock.send(websocket_request.encode("utf-8"))

        # دریافت پاسخ از سرور کلودفلر
        response = secure_sock.recv(1024).decode("utf-8", errors="ignore")

        secure_sock.close()

        # ۴. بررسی پاسخ سرور
        # اگر کلودفلر باشه، معمولاً وضعیت 101 (Switching Protocols) یا کدهای خطای خود کلودفلر (مثل 400) رو میده
        # مهم اینه که پاسخ معتبری از سمت سرورهای کلودفلر دریافت بشه
        if "HTTP/1.1 101" in response or "Server: cloudflare" in response:
            print(True, f" [✔] IP Found: {ip}")
            return True

    except Exception:
        # اگر خطایی رخ بده (تایم‌اوت یا بسته بودن پورت) یعنی آی‌پی سالم نیست
        return False

    return False


def worker():
    """این تابع به نوبت آی‌پی‌ها رو از صف برمی‌داره و بررسی می‌کنه"""
    while not ip_queue.empty():
        ip = ip_queue.get()
        if check_ip(ip):
            healthy_ips.append(ip)
        ip_queue.task_done()


def main():
    print("Starting Cloudflare IP Scanner...")

    # خواندن رنج‌های آی‌پی از فایل ips.txt و تبدیل آن‌ها به آی‌پی‌های تکی
    try:
        with open("ips.txt", "r") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        print("Error: ips.txt file not found!")
        return

    print("Parsing IP ranges...")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            # اگر خط ورودی رنج باشه (مثل 192.168.1.0/24) تمام آی‌پی‌هاش رو استخراج میکنه
            for ip in ipaddress.IPv4Network(line, strict=False):
                ip_queue.put(str(ip))
        except ValueError:
            # اگر فقط یک آی‌پی معمولی باشه
            ip_queue.put(line)

    total_ips = ip_queue.qsize()
    print(f"Total IPs to scan: {total_ips}")
    print(f"Running scanner with {THREAD_COUNT} threads...")

    # ساخت و شروع کارِ رشته‌ها (Threads) برای اسکن همزمان
    threads = []
    for _ in range(THREAD_COUNT):
        t = threading.Thread(target=worker)
        t.start()
        threads.append(t)

    # انتظار برای تمام شدن کار همه رشته‌ها
    for t in threads:
        t.join()

    # ذخیره نتایج نهایی در فایل result.txt
    with open("result.txt", "w") as f:
        for ip in healthy_ips:
            f.write(f"{ip}\n")

    print(
        f"Scan finished! {len(healthy_ips)} healthy IPs saved to result.txt"
    )


if __name__ == "__main__":
    main()
  
