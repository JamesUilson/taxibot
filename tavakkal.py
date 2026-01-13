import asyncio
from telethon import TelegramClient
from telethon.errors import SessionRevokedError, AuthKeyUnregisteredError

api_id = 37865153
api_hash = "8f8fbd11e173c2fbd113345430bb83b8"


async def main():
    client = TelegramClient("userbot", api_id, api_hash)  # userbot.session ishlatiladi

    try:
        await client.connect()

        if not await client.is_user_authorized():
            print("❌ Session server tomonidan bekor qilingan.")
            return

        me = await client.get_me()
        print("✅ Ulandi:", me.username, me.id)

    except SessionRevokedError:
        print("❌ Session Telegram tomonidan revoke qilingan.")
    except AuthKeyUnregisteredError:
        print("❌ Session auth_key serverda yo‘q.")
    except Exception as e:
        print("❌ Xato:", e)
    finally:
        await client.disconnect()

asyncio.run(main())
