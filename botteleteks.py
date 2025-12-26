from telethon import TelegramClient, errors, events
import asyncio
import random
from datetime import datetime, timedelta
import psutil
import json
import os
import sqlite3

# ====== FUNGSI UMUM ======
def write_log(text, log_file):
    t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"{t} - {text}")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{t} - {text}\n")

def log_system_usage(log_file):
    try:
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        write_log(f"Resource Usage -> CPU: {cpu}% | RAM: {ram}%", log_file)
    except Exception as e:
        write_log(f"Error log_system_usage: {e}", log_file)

async def send_message_with_retry(client, entity, message, uid, log_file, max_retries=5):
    for attempt in range(1, max_retries + 1):
        try:
            await client.send_message(entity, message)
            return True
        except errors.FloodWaitError as e:
            write_log(f"FloodWaitError {uid}: sleeping {e.seconds}s", log_file)
            await asyncio.sleep(e.seconds + 5)
        except errors.RPCError as e:
            write_log(f"RPCError {uid}: {e}, retry {attempt}", log_file)
            await asyncio.sleep(5)
        except errors.PersistentTimestampOutdatedError:
            write_log(f"PersistentTimestampOutdatedError {uid}, retry {attempt}", log_file)
            await asyncio.sleep(5)
        except Exception as e:
            write_log(f"Error sending to {uid}: {e}, retry {attempt}", log_file)
            await asyncio.sleep(5)
    write_log(f"Gagal kirim ke {uid} setelah {max_retries} percobaan", log_file)
    return False

async def send_message_safe(client, gid, msg, log_file):
    try:
        entity = await client.get_entity(gid)
        ok = await send_message_with_retry(client, entity, msg, gid, log_file)
        if ok:
            write_log(f"OK -> {gid}", log_file)
        else:
            write_log(f"Bot tidak bisa menulis di grup {gid}, skip.", log_file)
        log_system_usage(log_file)
        return ok
    except Exception as e:
        write_log(f"Tidak bisa akses grup {gid}: {e}", log_file)
        return False

async def check_group(client, gid, log_file):
    try:
        entity = await client.get_entity(gid)
        write_log(f"Grup terdeteksi: {entity.title} ({gid})", log_file)
        return True
    except Exception as e:
        write_log(f"Tidak bisa akses grup {gid}: {e}", log_file)
        return False

# ====== CLASS BOT ======
class TelegramBot:
    def __init__(self, api_id, api_hash, phone_number, session_name, log_file, user_state_file,
                 group_ids, group_messages, first_message, second_message, photo_reminder, interval=1800):
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone_number = phone_number
        self.session_name = session_name
        self.log_file = log_file
        self.user_state_file = user_state_file
        self.group_ids = group_ids
        self.group_messages = group_messages
        self.first_message = first_message
        self.second_message = second_message
        self.photo_reminder = photo_reminder
        self.interval = interval
        self.user_state = {}
        self.state_lock = asyncio.Lock()
        self.reply_queue = asyncio.Queue()
        self.broadcast_semaphore = asyncio.Semaphore(3)
        self.client = None

        if os.path.exists(self.user_state_file) and os.path.getsize(self.user_state_file) > 0:
            try:
                with open(self.user_state_file, "r") as f:
                    raw_state = json.load(f)
                    for uid, data in raw_state.items():
                        if 'last_time' in data:
                            data['last_time'] = datetime.fromisoformat(data['last_time'])
                        if 'blocked_until' in data and data['blocked_until'] is not None:
                            data['blocked_until'] = datetime.fromisoformat(data['blocked_until'])
                    self.user_state = raw_state
            except:
                self.user_state = {}

    def save_user_state(self):
        serializable_state = {}
        for uid, data in self.user_state.items():
            serializable_state[uid] = data.copy()
            if 'last_time' in data:
                serializable_state[uid]['last_time'] = data['last_time'].isoformat()
            if 'blocked_until' in data and data['blocked_until'] is not None:
                serializable_state[uid]['blocked_until'] = data['blocked_until'].isoformat()
        with open(self.user_state_file, "w") as f:
            json.dump(serializable_state, f, indent=4)

    # ================= LOGIN OTP BERURUTAN =================
    async def login(self):
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)

        # Retry untuk database locked
        retry_count = 0
        while retry_count < 5:
            try:
                await self.client.connect()
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    write_log(f"Database locked, retry {retry_count+1}/5", self.log_file)
                    retry_count += 1
                    await asyncio.sleep(2)
                else:
                    raise e
        else:
            write_log("Gagal connect karena database tetap locked", self.log_file)
            return False

        if not await self.client.is_user_authorized():
            write_log(f"Mengirim OTP ke {self.phone_number}", self.log_file)
            try:
                await self.client.send_code_request(self.phone_number)
            except errors.FloodWaitError as e:
                write_log(f"FloodWait OTP {e.seconds}s", self.log_file)
                await asyncio.sleep(e.seconds + 5)
                await self.client.send_code_request(self.phone_number)

            code = input(f"MASUKKAN OTP UNTUK {self.phone_number}: ")
            try:
                await self.client.sign_in(self.phone_number, code)
            except errors.SessionPasswordNeededError:
                password = input("Masukkan Password 2FA Telegram: ")
                await self.client.sign_in(password=password)

        write_log(f"LOGIN OTP SUKSES - SESSION ({self.session_name})", self.log_file)
        return True

    async def start(self):
        if self.client is None:
            await self.login()

        asyncio.create_task(self.reply_worker())
        self.client.add_event_handler(self.private_handler, events.NewMessage)

        while True:
            try:
                await self.broadcast_loop()
            except errors.PersistentTimestampOutdatedError:
                write_log("PersistentTimestampOutdatedError detected, reconnecting client...", self.log_file)
                await asyncio.sleep(5)
                await self.client.disconnect()
                await self.client.connect()
            except Exception as e:
                write_log(f"Broadcast loop error: {e}", self.log_file)
                await asyncio.sleep(5)

    async def reply_worker(self):
        while True:
            uid, entity, message = await self.reply_queue.get()
            try:
                await send_message_with_retry(self.client, entity, message, uid, self.log_file)
            except:
                pass
            self.reply_queue.task_done()

    async def private_handler(self, event):
        if not event.is_private:
            return
        uid = str(event.sender_id)
        now = datetime.now()
        try:
            entity = await event.get_sender()
        except:
            return

        async with self.state_lock:
            if uid not in self.user_state:
                self.user_state[uid] = {'status':'wait_photo','count':1,'last_time':now,'blocked_until':None,'sent_second':False}
                self.save_user_state()
                await self.reply_queue.put((uid, entity, self.first_message))
                return

            last_time = self.user_state[uid].get('last_time', now)
            delta = (now - last_time).total_seconds()
            if delta > 300:
                self.user_state[uid]['count'] = 0
                self.user_state[uid]['blocked_until'] = None

            blocked_until = self.user_state[uid].get('blocked_until')
            if blocked_until and now < blocked_until:
                return

            self.user_state[uid]['count'] += 1
            self.user_state[uid]['last_time'] = now
            if self.user_state[uid]['count'] > 3:
                self.user_state[uid]['blocked_until'] = now + timedelta(minutes=5)
                self.save_user_state()
                return
            self.save_user_state()

        status = self.user_state[uid]['status']
        sent_second = self.user_state[uid].get('sent_second', False)
        if event.photo:
            if not sent_second:
                self.user_state[uid]['status'] = 'photo_sent'
                self.user_state[uid]['sent_second'] = True
                async with self.state_lock:
                    self.save_user_state()
                await self.reply_queue.put((uid, entity, self.second_message))
        elif status == 'wait_photo':
            await self.reply_queue.put((uid, entity, self.photo_reminder))
        else:
            await self.reply_queue.put((uid, entity, self.first_message))

    async def broadcast_loop(self):
        while True:
            tasks = []
            for gid in self.group_ids:
                ok = await check_group(self.client, gid, self.log_file)
                if ok:
                    msg = random.choice(self.group_messages)
                    tasks.append(asyncio.create_task(self.sem_broadcast(gid, msg)))
            if tasks:
                await asyncio.gather(*tasks)
            await asyncio.sleep(self.interval)

    async def sem_broadcast(self, gid, msg):
        async with self.broadcast_semaphore:
            await send_message_safe(self.client, gid, msg, self.log_file)
            await asyncio.sleep(random.randint(10, 30))

# ====== MAIN ======
async def main():
    # BOT 1 - Sleep Call
    bot1_group_messages = [
        "🌙 Call Sleep PC 🌙\nYang mau ditemenin sebelum tidur, ngobrol santai sampai ketiduran. Langsung PC ya 🤍",
        "😴 Sleep Call Yuk (PC)\nCapek seharian? Kita call pelan aja sampai mata merem. Yang mau, PC sekarang 💬",
        "🌌 Temenin Tidur via Call (PC)\nNgobrol santai sampai tidur. PC aja 🌙",
        "💤 Call Santai Sebelum Tidur (PC)\nSuara pelan, obrolan ringan, bikin adem. Langsung PC ✨",
        "🖤 Deep Talk PC\nKalau lagi capek dan butuh tempat cerita tanpa di-judge, aku siap dengerin. PC ya 💬",
        "🌧 Butuh Teman Cerita? (PC)\nNggak harus kuat sendirian. Yang mau deep talk, langsung PC 🤍",
        "🧠 Deep Talk Tengah Malam (PC)\nNgobrol jujur tentang hidup, mimpi, dan luka. PC kalau butuh 🖤",
        "🎧 Open VC PC\nBosan sendirian? Yuk VC santai, ngobrol bebas tanpa ribet. PC sekarang 🔊",
        "🎙 Voice Call Santai (PC)\nCuma mau ngobrol dan denger suara? VC yuk. Langsung PC 😄",
        "⚡ VC Cepat & Santai (PC)\nNggak jaim, nggak formal. Yang mau VC, langsung PC ya!"
    ]

    bot1 = TelegramBot(
        api_id=HARUS-ISI,
        api_hash="HARUS-ISI",
        phone_number="HARUS-ISI",
        session_name="session_bot1",
        log_file="log_telegram1.txt",
        user_state_file="user_state1.json",
        group_ids=[1
            -1001341722781, -1001689707975, -1001644239575, -1002080081522, -1001961194566, -1001764400714
        ],
        group_messages=bot1_group_messages,
        first_message="Halo ka \n\nLangsung klik bot resmi ini: @bolapelangi2_bot \nHanya Setelah klik, tekan START di bot.\n\nkirim bukti ke aku ka \nNanti aku langsung VC ka ",
        second_message="Terima kasih ka! Bukti sudah diterima. ✨\n\nAku langsung VC ya ka. Tunggu sebentar, aku siap-siap dulu ya kak. 💬\n\naku kasih waktu 5 menit,kalo dah siap info ya ka🤍",
        photo_reminder="Hai ka!\n\nJangan lupa kirim bukti foto ya ka untuk konfirmasi sudah klik START di bot.\n\nSetelah kirim foto, aku langsung VC ka.",
        interval=30*60
    )

    # BOT 2 - Open Beby
    bot2_group_messages = [
        """
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
    ]

    bot2 = TelegramBot(
        api_id=HARUS-ISI,
        api_hash="HARUS-ISI",
        phone_number="+HARUS-ISI",
        session_name="session_bot2",
        log_file="log_telegram2.txt",
        user_state_file="user_state2.json",
        group_ids=[
            -1001522258514, -1001341722781, -1001689707975,-1002481892212, -1002080081522
        ],
        group_messages=bot2_group_messages,
        first_message="Halo ka \n\nLangsung klik bot resmi ini: @bolapelangi2_bot \nHanya Setelah klik, tekan START di bot.\n\nkirim bukti ke aku ka \nNanti aku langsung VC ka ",
        second_message="Terima kasih ka! Bukti sudah diterima. ✨\n\nAku langsung VC ya ka. Tunggu sebentar, aku siap-siap dulu ya kak. 💬\n\naku kasih waktu 5 menit,kalo dah siap info ya ka🤍",
        photo_reminder="Hai ka!\n\nJangan lupa kirim bukti foto ya ka untuk konfirmasi sudah klik START di bot.\n\nSetelah kirim foto, aku langsung VC ka.",
        interval=30*60
    )

    # LOGIN BERURUTAN
    await bot1.login()
    await bot2.login()

    # START BOT SECARA ASINKRON
    await asyncio.gather(bot1.start(), bot2.start())

if __name__ == "__main__":
    asyncio.run(main())
