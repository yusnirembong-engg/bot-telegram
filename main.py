# Telegram User API (Telethon) - CMD Interactive Version with Required Inputs & Full Validation
from telethon import TelegramClient, events, errors
from telethon.errors import SessionPasswordNeededError
import asyncio, random, json, os
from datetime import datetime, timedelta
import psutil

# ====== CONFIG ======
INTERVAL = 30 * 60  # 30 menit
MAX_RETRIES = 3
USER_STATE_FILE = "user_state.json"
LOG_FILE = "log_telegram.txt"

# ====== STATE ======
user_state = {}
state_lock = asyncio.Lock()

if os.path.exists(USER_STATE_FILE):
    try:
        if os.path.getsize(USER_STATE_FILE) > 0:
            with open(USER_STATE_FILE, "r") as f:
                raw_state = json.load(f)
                for uid, data in raw_state.items():
                    if 'last_time' in data:
                        data['last_time'] = datetime.fromisoformat(data['last_time'])
                    if 'blocked_until' in data and data['blocked_until'] is not None:
                        data['blocked_until'] = datetime.fromisoformat(data['blocked_until'])
                user_state = raw_state
    except Exception:
        user_state = {}

def save_user_state():
    serializable_state = {}
    for uid, data in user_state.items():
        serializable_state[uid] = data.copy()
        if 'last_time' in data:
            serializable_state[uid]['last_time'] = data['last_time'].isoformat()
        if 'blocked_until' in data and data['blocked_until'] is not None:
            serializable_state[uid]['blocked_until'] = data['blocked_until'].isoformat()
    with open(USER_STATE_FILE, "w") as f:
        json.dump(serializable_state, f, indent=4)

# ====== LOGGING ======
def write_log(text):
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{t} - {text}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{t} - {text}\n")

def log_system_usage():
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    write_log(f"Resource Usage -> CPU: {cpu}% | RAM: {ram}%")

# ====== INPUT VALIDATION ======
def input_required(prompt):
    value = ""
    while not value.strip():
        value = input(prompt).strip()
        if not value:
            print("⚠️  Input wajib diisi!")
    return value

def input_int_required(prompt):
    while True:
        value = input_required(prompt)
        if value.isdigit():
            return int(value)
        print("⚠️  Harus berupa angka!")

def input_id_list(prompt):
    while True:
        raw = input_required(prompt)
        parts = raw.split(",")
        ids = []
        valid = True
        for p in parts:
            p = p.strip()
            if not p.isdigit():
                print(f"⚠️  ID tidak valid: {p}")
                valid = False
                break
            ids.append(int(p))
        if valid:
            return ids

def input_phone_number(prompt):
    while True:
        phone = input_required(prompt)
        phone_clean = phone.replace(" ", "").replace("-", "")
        if phone_clean.startswith("0"):
            phone_clean = "+62" + phone_clean[1:]
        elif not phone_clean.startswith("+"):
            print("⚠️  Nomor harus diawali 0 atau +kode_negara (misal +62)")
            continue
        if not phone_clean[1:].isdigit():
            print("⚠️  Nomor harus terdiri dari angka setelah +")
            continue
        return phone_clean

# ====== CHECK GROUP ======
async def check_group(client, gid):
    try:
        entity = await client.get_entity(gid)
        write_log(f"Grup terdeteksi: {entity.title} ({gid})")
        return True
    except Exception as e:
        write_log(f"Tidak bisa akses grup {gid}: {e}")
        return False

# ====== SEND MESSAGE SAFE ======
async def send_message_safe(client, gid, msg):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            entity = await client.get_entity(gid)
            await client.send_message(entity, msg)
            write_log(f"OK -> {gid}")
            log_system_usage()
            return True
        except errors.ChatForbiddenError:
            write_log(f"SKIP (NO ACCESS) -> {gid}")
            return False
        except errors.FloodWaitError as e:
            write_log(f"FLOODWAIT {e.seconds}s - menunggu...")
            await asyncio.sleep(e.seconds + 5)
        except Exception as e:
            write_log(f"ERROR {gid} (Attempt {attempt}): {e}")
            await asyncio.sleep(5)
    write_log(f"GAGAL KIRIM -> {gid}")
    return False

# ====== PRIVATE HANDLER ======
async def setup_private_handler(client, FIRST_MESSAGE, SECOND_MESSAGE, PHOTO_REMINDER):
    @client.on(events.NewMessage)
    async def handler(event):
        if not event.is_private:
            return

        uid = str(event.sender_id)
        now = datetime.now()

        try:
            entity = await event.get_sender()
        except Exception as e:
            write_log(f"User {uid} tidak bisa diakses: {e}")
            return

        async with state_lock:
            if uid not in user_state:
                user_state[uid] = {
                    'status': 'wait_photo',
                    'count': 1,
                    'last_time': now,
                    'blocked_until': None,
                    'sent_second': False
                }
                save_user_state()
                await client.send_message(entity, FIRST_MESSAGE)
                write_log(f"FIRST_MESSAGE terkirim ke user baru {uid}")
                return

            last_time = user_state[uid].get('last_time', now)
            if isinstance(last_time, str):
                last_time = datetime.fromisoformat(last_time)

            delta = (now - last_time).total_seconds()
            if delta > 5 * 60:
                user_state[uid]['count'] = 0
                user_state[uid]['blocked_until'] = None

            blocked_until = user_state[uid].get('blocked_until')
            if blocked_until and isinstance(blocked_until, datetime) and now < blocked_until:
                write_log(f"User {uid} spam, skip auto-reply sampai {blocked_until}")
                return

            user_state[uid]['count'] += 1
            user_state[uid]['last_time'] = now

            if user_state[uid]['count'] > 3:
                user_state[uid]['blocked_until'] = now + timedelta(minutes=5)
                write_log(f"User {uid} spam >3x, auto-reply dihentikan 5 menit")
                save_user_state()
                return

            save_user_state()

        status = user_state[uid]['status']
        sent_second = user_state[uid].get('sent_second', False)

        try:
            if event.photo:
                if not sent_second:
                    user_state[uid]['status'] = 'photo_sent'
                    user_state[uid]['sent_second'] = True
                    async with state_lock:
                        save_user_state()
                    await client.send_message(entity, SECOND_MESSAGE)
                    write_log(f"SECOND_MESSAGE terkirim ke {uid}")
            elif status == 'wait_photo':
                await client.send_message(entity, PHOTO_REMINDER)
                write_log(f"PHOTO_REMINDER terkirim ke {uid}")
            else:
                await client.send_message(entity, FIRST_MESSAGE)
                write_log(f"Fallback FIRST_MESSAGE terkirim ke {uid}")
        except Exception as e:
            write_log(f"Gagal kirim pesan ke {uid}: {e}")

# ====== MANUAL LOGIN ======
async def manual_login():
    api_id = input_int_required("Masukkan API ID      : ")
    api_hash = input_required("Masukkan API HASH    : ")
    phone_number = input_phone_number("Masukkan No Telegram: ")

    session_name = f"session_{phone_number.replace('+','')}"
    client = TelegramClient(session_name, api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        await client.send_code_request(phone_number)
        code = input_required("Masukkan OTP/Token  : ")
        try:
            await client.sign_in(phone_number, code)
        except SessionPasswordNeededError:
            pw = input_required("Password 2FA        : ")
            await client.sign_in(password=pw)

    write_log("LOGIN SUKSES - SESSION BARU")
    return client

# ====== MAIN LOOP ======
async def main():
    client = await manual_login()

    # Input USER_ID & BOT_ID
    USER_ID = input_required("Masukkan USER_ID untuk FIRST_MESSAGE: ")
    BOT_ID = input_required("Masukkan BOT_ID untuk SECOND_MESSAGE: ")

    # Input ID grup & teks broadcast
    GROUP_IDS = input_id_list("Masukkan ID grup (pisahkan koma jika lebih dari 1):\n> ")

    BROADCAST_COUNT = input_int_required("Berapa variasi teks broadcast? : ")
    GROUP_MESSAGES = []
    for i in range(BROADCAST_COUNT):
        msg = input_required(f"Teks broadcast ke-{i+1}: ")
        GROUP_MESSAGES.append(msg)

    # FIRST_MESSAGE & SECOND_MESSAGE
    FIRST_MESSAGE = f"Halo bosku! 👋\n\nUntuk klaim freebet hari ini, gunakan {USER_ID}."
    SECOND_MESSAGE = f"Klik ID bot resmi: {BOT_ID} untuk panduan klaim otomatis."
    PHOTO_REMINDER = "🙏 Kirim bukti foto agar bisa klaim freebet."

    await setup_private_handler(client, FIRST_MESSAGE, SECOND_MESSAGE, PHOTO_REMINDER)

    while True:
        write_log("MULAI BROADCAST")
        for gid in GROUP_IDS:
            ok = await check_group(client, gid)
            if ok and GROUP_MESSAGES:
                msg = random.choice(GROUP_MESSAGES)
                await send_message_safe(client, gid, msg)
            await asyncio.sleep(random.randint(10, 30))
        write_log("SELESAI BROADCAST - TUNGGU 30 MENIT")
        await asyncio.sleep(INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
