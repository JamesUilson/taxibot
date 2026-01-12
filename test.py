from telethon import TelegramClient

API_ID = 32105054
API_HASH = "99f6f7d7c52aeab4f65686e6003c25a0"

client = TelegramClient('test_session', API_ID, API_HASH)

async def main():
    await client.start()
    print("✅ Login muvaffaqiyatli!")
    await client.send_message('me', 'Bot ishga tushdi!')
    print("✅ Test xabar yuborildi!")

client.loop.run_until_complete(main())