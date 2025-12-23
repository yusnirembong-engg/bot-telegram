from telethon import TelegramClient, events, errors
from telethon.errors import SessionPasswordNeededError
import asyncio, random, json, os
from datetime import datetime
import psutil

# ================== LOGIN ==================
async def login_telegram():
    api_id = int(input("Masukkan API ID      : "))
    api_hash = input("Masukkan API HASH    : ")
    phone = input("Masukkan No Telegram : ")

    session_name = f"session_{phone.replace('+','')}"
    client = TelegramClient(session_name, api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        await client.send_code_request(phone)
        print("OTP dikirim ke Telegram")

        code = input("Masukkan OTP/Token   : ")
        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            pw = input("Password 2FA        : ")
            await client.sign_in(password=pw)

    print("LOGIN SUKSES\n")
    return client

# ================== KONFIG TEKS ==================
def input_messages():
    total = int(input("Berapa variasi teks broadcast? : "))
    msgs = []
    for i in range(total):
        print(f"Teks ke-{i+1}:")
        msgs.append(input("> "))
    return msgs

# ================== AUTO REPLY SETTING ==================
def input_auto_reply():
    print("\n--- SET AUTO REPLY PRIVATE ---")
    first = input("Pesan pertama user baru:\n> ")
    second = input("\nPesan setelah kirim foto:\n> ")
    reminder = input("\nPesan reminder (belum kirim foto):\n> ")
    return first, second, reminder

# ================== LOG ==================
def log(text):
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{t} - {text}")
    with open("log_telegram.txt", "a", encoding="utf-8") as f:
        f.write(f"{t} - {text}\n")

# ================== HANDLER PRIVATE ==================
user_state = {}

async def setup_private_handler(client, FIRST, SECOND, REMINDER):
    @client.on(events.NewMessage)
    async def handler(event):
        if not event.is_private:
            return

        uid = str(event.sender_id)
        if uid not in user_state:
            user_state[uid] = "wait_photo"
            await client.send_message(uid, FIRST)
            return

        if event.photo:
            user_state[uid] = "done"
            await client.send_message(uid, SECOND)
        else:
            if user_state[uid] == "wait_photo":
                await client.send_message(uid, REMINDER)

# ================== BROADCAST ==================
async def broadcast_loop(client, groups, messages):
    while True:
        for gid in groups:
            try:
                await client.send_message(gid, random.choice(messages))
                log(f"Broadcast OK -> {gid}")
                await asyncio.sleep(random.randint(10, 30))
            except errors.FloodWaitError as e:
                log(f"FloodWait {e.seconds}s")
                await asyncio.sleep(e.seconds + 5)
            except Exception as e:
                log(f"Error {gid}: {e}")
        log("Selesai broadcast, tunggu 30 menit\n")
        await asyncio.sleep(1800)

# ================== MAIN ==================
async def main():
    client = await login_telegram()

    GROUP_IDS = input("Masukkan ID grup (pisahkan koma):\n> ")
    GROUP_IDS = [int(x.strip()) for x in GROUP_IDS.split(",")]

    messages = input_messages()
    FIRST, SECOND, REMINDER = input_auto_reply()

    await setup_private_handler(client, FIRST, SECOND, REMINDER)

    await broadcast_loop(client, GROUP_IDS, messages)

asyncio.run(main())
