import aiohttp
import asyncio
import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# CMS Patterns
CMS_PATTERNS = {
    'Shopify': r'cdn\.shopify\.com|shopify\.js',
    'BigCommerce': r'cdn\.bigcommerce\.com|bigcommerce\.com',
    'Wix': r'static\.parastorage\.com|wix\.com',
    'Squarespace': r'static1\.squarespace\.com|squarespace-cdn\.com',
    'WooCommerce': r'wp-content/plugins/woocommerce/',
    'Magento': r'static/version\d+/frontend/|magento/',
    'PrestaShop': r'prestashop\.js|prestashop/',
    'OpenCart': r'catalog/view/theme|opencart/',
    'Shopify Plus': r'shopify-plus|cdn\.shopifycdn\.net/',
    'Salesforce Commerce Cloud': r'demandware\.edgesuite\.net/',
    'WordPress': r'wp-content|wp-includes/',
    'Joomla': r'media/jui|joomla\.js|media/system/js|joomla\.javascript/',
    'Drupal': r'sites/all/modules|drupal\.js/|sites/default/files|drupal\.settings\.js/',
    'TYPO3': r'typo3temp|typo3/',
    'Concrete5': r'concrete/js|concrete5/',
    'Umbraco': r'umbraco/|umbraco\.config/',
    'Sitecore': r'sitecore/content|sitecore\.js/',
    'Kentico': r'cms/getresource\.ashx|kentico\.js/',
    'Episerver': r'episerver/|episerver\.js/',
    'Custom CMS': r'(?:<meta name="generator" content="([^"]+)")'
}

# Payment Gateways
PAYMENT_GATEWAYS = [
    "PayPal", "Stripe", "Braintree", "Square", "Cybersource", "lemon-squeezy",
    "Authorize.Net", "2Checkout", "Adyen", "Worldpay", "SagePay",
    "Checkout.com", "Bolt", "Eway", "PayFlow", "Payeezy",
    "Paddle", "Mollie", "Viva Wallet", "Rocketgateway", "Rocketgate",
    "Rocket", "Auth.net", "Authnet", "rocketgate.com", "Recurly",
    "Shopify", "WooCommerce", "BigCommerce", "Magento", "Magento Payments",
    "OpenCart", "PrestaShop", "3DCart", "Ecwid", "Shift4Shop",
    "Shopware", "VirtueMart", "CS-Cart", "X-Cart", "LemonStand",
    "Convergepay", "PaySimple", "oceanpayments", "eProcessing",
    "hipay", "cybersourse", "payjunction", "usaepay", "creo",
    "SquareUp", "ebizcharge", "cpay", "Moneris", "cardknox",
    "Chargify", "Paytrace", "hostedpayments", "securepay",
    "blackbaud", "LawPay", "clover", "cardconnect", "bluepay",
    "fluidpay", "Ebiz", "chasepaymentech", "Auruspay", "sagepayments",
    "paycomet", "geomerchant", "realexpayments", "Razorpay",
    "Apple Pay", "Google Pay", "Samsung Pay", "Cash App",
    "Revolut", "Zelle", "Alipay", "WeChat Pay", "PayPay", "Line Pay",
    "Skrill", "Neteller", "WebMoney", "Payoneer", "Paysafe",
    "Payeer", "GrabPay", "PayMaya", "MoMo", "TrueMoney",
    "Touch n Go", "GoPay", "JKOPay", "EasyPaisa",
    "Paytm", "UPI", "PayU", "PayUBiz", "PayUMoney", "CCAvenue",
    "Mercado Pago", "PagSeguro", "Yandex.Checkout", "PayFort", "MyFatoorah",
    "Kushki", "RuPay", "BharatPe", "Midtrans", "MOLPay",
    "iPay88", "KakaoPay", "Toss Payments", "NaverPay",
    "Bizum", "Culqi", "Pagar.me", "Rapyd", "PayKun", "Instamojo",
    "PhonePe", "BharatQR", "Freecharge", "Mobikwik", "BillDesk",
    "Citrus Pay", "RazorpayX", "Cashfree",
    "Klarna", "Affirm", "Afterpay",
    "Splitit", "Perpay", "Quadpay", "Laybuy", "Openpay",
    "Cashalo", "Hoolah", "Pine Labs", "ChargeAfter",
    "BitPay", "Coinbase Commerce", "CoinGate", "CoinPayments", "Crypto.com Pay",
    "BTCPay Server", "NOWPayments", "OpenNode", "Utrust", "MoonPay",
    "Binance Pay", "CoinsPaid", "BitGo", "Flexa",
    "ACI Worldwide", "Bank of America Merchant Services",
    "JP Morgan Payment Services", "Wells Fargo Payment Solutions",
    "Deutsche Bank Payments", "Barclaycard", "American Express Payment Gateway",
    "Discover Network", "UnionPay", "JCB Payment Gateway",
]

# ================= SESSION =================
_session: aiohttp.ClientSession | None = None

async def init_session():
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(limit=100, ssl=False)
        timeout = aiohttp.ClientTimeout(total=20)
        _session = aiohttp.ClientSession(connector=connector, timeout=timeout)

async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()

# ================= FETCH SITE =================
async def fetch_site(url: str):
    await init_session()

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    domain = urlparse(url).netloc
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": f"https://{domain}/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        async with _session.get(url, headers=headers, allow_redirects=True) as resp:
            text = await resp.text(errors="ignore")
            return resp.status, text, dict(resp.headers)
    except Exception as e:
        return None, "", {}

# ================= DETECTORS =================
def detect_cms(html: str) -> str:
    for cms, pattern in CMS_PATTERNS.items():
        if re.search(pattern, html, re.I):
            if cms == "Custom CMS":
                m = re.search(pattern, html, re.I)
                return f"Custom ({m.group(1)})" if m else "Custom"
            return cms
    return "Unknown / Headless"

def detect_gateways(html: str) -> str:
    found = set()
    lower_html = html.lower()
    for gateway in PAYMENT_GATEWAYS:
        if gateway.lower().replace(" ", "") in lower_html or re.search(rf"\b{re.escape(gateway)}\b", html, re.I):
            found.add(gateway)
    return ", ".join(sorted(found)) if found else "None Detected"

def detect_security(html: str) -> str:
    if re.search(r"3ds|3d\s*secure|verified\s*by\s*visa|mastercard\s*securecode|safe\s*key", html, re.I):
        return "3D Secure Enabled ✅"
    return "2D Only (No 3DS) ❌"

def detect_captcha(html: str) -> str:
    lower = html.lower()
    if "hcaptcha" in lower: return "hCaptcha ✅"
    if "recaptcha" in lower or "g-recaptcha" in lower: return "reCAPTCHA ✅"
    if "cloudflare" in lower and "turnstile" in lower: return "Cloudflare Turnstile ✅"
    if "captcha" in lower: return "Generic Captcha ✅"
    return "No Captcha"

def detect_cloudflare(html: str, headers: dict, status: int | None) -> str:
    header_keys = [k.lower() for k in headers.keys()]
    server = headers.get("Server", "").lower()

    if "cf-ray" in header_keys or "cloudflare" in server:
        if status in (403, 503, 429):
            return "Cloudflare BLOCK / Challenge 🔥"
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.lower() if soup.title else ""
        body = html.lower()
        if any(x in title for x in ("just a moment", "attention required", "checking your browser")) or "cf-browser-verification" in body:
            return "Cloudflare IUAM Challenge 🔥"
        if "turnstile" in body:
            return "Cloudflare Turnstile Active"
        return "Cloudflare CDN Only 🔍"
    return "No Cloudflare"

def detect_graphql(html: str) -> str:
    if re.search(r"/graphql|__graphql|apollo|query\s*\{|mutation\s*\{", html, re.I):
        return "GraphQL Endpoint Exposed ✅"
    return "No GraphQL"

# ================= SCANNER =================
async def scan_single_site(url: str) -> str:
    status, html, headers = await fetch_site(url)

    if status is None:
        access = "Dead / Timeout"
    elif status == 401:
        access = "Auth Required 🔒"
    elif status == 403:
        access = "Forbidden"
    elif status >= 500:
        access = "Server Down"
    elif status >= 300:
        access = f"Redirect ({status})"
    else:
        access = "Live & Accessible"

    cms = detect_cms(html)
    gateways = detect_gateways(html)
    security = detect_security(html)
    captcha = detect_captcha(html)
    cf = detect_cloudflare(html, headers, status)
    gql = detect_graphql(html)

    return (
        "◇━━〔 𝕾𝖈𝖆𝖓 𝕽𝖊𝖘𝖚𝖑𝖙 〕━━◇\n"
        f"⚡ Target ➵ <code>{url}</code>\n"
        f"⚡ Status ➵ {access} ({status or 'N/A'})\n"
        f"⚡ CMS ➵ {cms}\n"
        f"⚡ Gateways ➵ <code>{gateways}</code>\n"
        "――――――――――――――――\n"
        f"⚡ Captcha ➵ {captcha}\n"
        f"⚡ Cloudflare ➵ {cf}\n"
        f"⚡ 3DS ➵ {security}\n"
        f"⚡ GraphQL ➵ {gql}\n"
        "――――――――――――――――"
    )

async def scan_multiple_sites(urls: list[str]) -> str:
    tasks = [scan_single_site(u.strip()) for u in urls if u.strip()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = ["◇━━〔 𝕸𝖆𝖘𝖘 𝕾𝖈𝖆𝖓 𝕽𝖊𝖘𝖚𝖑𝖙𝖘 〕━━◇\n"]
    for i, res in enumerate(results, 1):
        if isinstance(res, Exception):
            output.append(f"Site {i} ➵ 💀 CRASHED: {str(res)}")
        else:
            output.append(res.replace("◇━━〔 𝕾𝖈𝖆𝖓 𝕽𝖊𝖘𝖚𝖑𝖙 〕━━◇", f"Site {i}"))
        output.append("――――――――――――――――")
    return "\n".join(output)

# Example usage (uncomment to run)
# async def main():
#     urls = ["example.com", "shopify-site.com", "wix-site.com"]
#     print(await scan_multiple_sites(urls))
#     await close_session()
#
# if __name__ == "__main__":
#     asyncio.run(main())