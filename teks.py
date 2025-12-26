from telethon import TelegramClient, errors, events
import asyncio
import random
from datetime import datetime, timedelta
import psutil
import json
import os

# ====== KONFIGURASI ======
api_id = HARUS-ISI
api_hash = "HARUS-ISI"
phone_number = "HARUS-ISI"
session_name = "session_tele_user"
# ====== HAPUS SESSION LAMA ======
for f in os.listdir():
    if f.startswith(session_name) and f.endswith(".session"):
        os.remove(f)
        print("SESSION LAMA DIHAPUS:", f)

# ====== GRUP ======
GROUP_IDS = [
    -1001522258514, -1001341722781, -1001689707975, -1001257575639,
    -1002481892212, -1002080081522]

# ====== VARIASI PESAN ======
GROUP_MESSAGE = """
      OPEN BEBY
   JOM VC BOGEL
     VIDEO PRIBADI
   JOM VC BOGEL
     VIDEO PRIBADI
SEMUA GRATIS
HANYA UNTUK 5 ORANG SAJA

💬 Call / VC Pribadi 🌙
Siap nemenin ngobrol atau deep talk sesuai pilihan di atas, langsung PC ya ka 🤍
"""

INTERVAL = 30 * 60
LOG_FILE = "log_telegram.txt"
MAX_RETRIES = 3
USER_STATE_FILE = "user_state.json"

# ====== AUTO REPLY ======
# PERBAIKAN: Placeholder {BOT_ID} akan diisi di main() dengan input sederhana
FIRST_MESSAGE_TEMPLATE = (
    "Halo ka \n\n"
    "Langsung klik bot resmi ini: @bolapelangi2_bot \n"
    "Hanya Setelah klik, tekan START di bot.\n\n"
    "kirim bukti ke aku ka \n"
    "Nanti aku langsung VC ka "
)

# PERBAIKAN: Tambahkan SECOND_MESSAGE_TEMPLATE (yang hilang di kode asli) untuk pesan setelah foto dikirim
SECOND_MESSAGE_TEMPLATE = (
    "Terima kasih ka! Bukti sudah diterima. ✨\n\n"
    "Aku langsung VC ya ka. Tunggu sebentar, aku siap-siap dulu ya kak. 💬\n\n"
    "aku kasih waktu 5 menit,kalo dah siap info ya ka🤍"
)

PHOTO_REMINDER = (
    "Hai ka!\n\n"
    "Jangan lupa kirim bukti foto ya ka untuk konfirmasi sudah klik START di bot.\n\n"
    "Setelah kirim foto, aku langsung VC ka."
)

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
    except (json.JSONDecodeError, ValueError):
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

# ====== LOG ======
def write_log(text):
    t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"{t} - {text}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{t} - {text}\n")

def log_system_usage():
    try:
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        write_log(f"Resource Usage -> CPU: {cpu}% | RAM: {ram}%")
    except ImportError:
        write_log("Resource Usage -> psutil not available")

# ====== CHECK GRUP TERDAFTAR ======
async def check_group(client, gid):
    try:
        entity = await client.get_entity(gid)
        write_log(f"Grup terdeteksi: {entity.title} ({gid})")
        return True
    except Exception as e:
        write_log(f"Tidak bisa akses grup {gid}: {e}")
        return False

# ====== SEND SAFE ======
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
            write_log(f"FLOODWAIT {e.seconds}s")
            await asyncio.sleep(e.seconds + 5)
        except Exception as e:
            write_log(f"ERROR {gid} (Attempt {attempt}): {e}")
            await asyncio.sleep(5)
    write_log(f"GAGAL KIRIM -> {gid}")
    return False

# PERBAIKAN: Fungsi baru untuk handling retry di handler pribadi (mengatasi FloodWaitError)
async def send_message_with_retry(client, entity, message, uid, max_retries=3):
    for attempt in range(1, max_retries + 1):
        try:
            await client.send_message(entity, message)
            return  # Sukses, keluar
        except errors.FloodWaitError as e:
            wait_time = e.seconds + 5  # Tambah buffer 5 detik
            write_log(f"FloodWaitError untuk {uid} (Attempt {attempt}): Tunggu {wait_time}s")
            await asyncio.sleep(wait_time)
        except Exception as e:
            write_log(f"Error lain kirim ke {uid} (Attempt {attempt}): {e}")
            await asyncio.sleep(5)  # Jeda singkat untuk error lain
    write_log(f"Gagal kirim setelah {max_retries} retry ke {uid}")

# ====== HANDLER PRIVAT FIXED ======
async def setup_handler(client, FIRST_MESSAGE, SECOND_MESSAGE):
    @client.on(events.NewMessage)
    async def handler(event):
        if not event.is_private:
            return

        uid = str(event.sender_id)
        now = datetime.now()

        # Gunakan entity langsung dari event
        try:
            entity = await event.get_sender()
        except Exception as e:
            write_log(f"User {uid} tidak bisa diakses: {e}")
            return

        async with state_lock:
            if uid not in user_state:
                # User baru
                user_state[uid] = {
                    'status': 'wait_photo',
                    'count': 1,
                    'last_time': now,
                    'blocked_until': None,
                    'sent_second': False
                }
                save_user_state()
                # PERBAIKAN: Ganti dengan send_message_with_retry untuk handling flood
                await send_message_with_retry(client, entity, FIRST_MESSAGE, uid)
                write_log(f"FIRST_MESSAGE terkirim ke user baru {uid}")
                return

            # User lama
            last_time = user_state[uid].get('last_time', now)
            if isinstance(last_time, str):
                last_time = datetime.fromisoformat(last_time)

            delta = (now - last_time).total_seconds()
            if delta > 5 * 60:
                user_state[uid]['count'] = 0
                user_state[uid]['blocked_until'] = None

            blocked_until = user_state[uid].get('blocked_until')
            if blocked_until:
                if isinstance(blocked_until, str):
                    blocked_until = datetime.fromisoformat(blocked_until)
                if now < blocked_until:
                    write_log(f"User {uid} spam, auto-reply dihentikan sementara sampai {blocked_until}")
                    return

            user_state[uid]['count'] += 1
            user_state[uid]['last_time'] = now

            if user_state[uid]['count'] > 3:
                user_state[uid]['blocked_until'] = now + timedelta(minutes=5)
                write_log(f"User {uid} spam 3x, auto-reply dihentikan 5 menit")
                save_user_state()
                return

            save_user_state()

        # ===== AUTO-REPLY FIXED =====
        status = user_state[uid]['status']
        sent_second = user_state[uid].get('sent_second', False)

        try:
            if event.photo:
                if not sent_second:
                    user_state[uid]['status'] = 'photo_sent'
                    user_state[uid]['sent_second'] = True
                    async with state_lock:
                        save_user_state()
                    # PERBAIKAN: Ganti dengan send_message_with_retry
                    await send_message_with_retry(client, entity, SECOND_MESSAGE, uid)
                    write_log(f"SECOND_MESSAGE terkirim ke {uid}")
                else:
                    write_log(f"User {uid} sudah dikirim SECOND_MESSAGE, skip")
            elif status == 'wait_photo':
                # PERBAIKAN: Ganti dengan send_message_with_retry
                await send_message_with_retry(client, entity, PHOTO_REMINDER, uid)
                write_log(f"PHOTO_REMINDER terkirim ke {uid}")
            else:
                # PERBAIKAN: Ganti dengan send_message_with_retry
                await send_message_with_retry(client, entity, FIRST_MESSAGE, uid)
                write_log(f"Fallback FIRST_MESSAGE terkirim ke {uid}")
        except Exception as e:
            write_log(f"Gagal kirim pesan ke {uid}: {e}")

# ====== MAIN ======
async def main():
    # PERBAIKAN: Definisi pesan langsung tanpa input (karena template sudah hardcode)
    FIRST_MESSAGE = FIRST_MESSAGE_TEMPLATE  # Sudah berisi @bolapelangi2_bot
    SECOND_MESSAGE = SECOND_MESSAGE_TEMPLATE  # Pesan setelah foto
    
    client = TelegramClient(session_name, api_id, api_hash)
    await client.start(phone=phone_number)
    write_log("LOGIN OTP SUKSES - SESSION BARU")

    await setup_handler(client, FIRST_MESSAGE, SECOND_MESSAGE)

    while True:
        write_log("MULAI BROADCAST")
        for gid in GROUP_IDS:
            ok = await check_group(client, gid)
            if ok:
                msg = random.choice(GROUP_MESSAGES)
                await send_message_safe(client, gid, msg)
            await asyncio.sleep(random.randint(10, 30))
        write_log("SELESAI BROADCAST - TUNGGU 30 MENIT")
        await asyncio.sleep(INTERVAL)

# ====== RUN ======
if __name__ == "__main__":
    asyncio.run(main())
