import asyncio
import os
from getpass import getpass

from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, Unauthorized
from pyrogram.raw import functions, types

import config

API_ID = config.API_ID
API_HASH = config.API_HASH

SESSION_NAME = "interactive_call_session"
SESSION_FILE = f"{SESSION_NAME}.session"


async def interactive_login(app: Client):
    await app.connect()

    # Check if session file exists and is valid; do not delete it automatically.
    if os.path.exists(SESSION_FILE):
        try:
            me = await app.get_me()
            if me:
                print(f"✅ Already logged in as @{me.username or me.first_name} (id={me.id}) using {SESSION_FILE}")
                return
        except Unauthorized:
            print("⚠️ Existing session appears invalid (AUTH_KEY_UNREGISTERED). Not deleting the file.")
            print("   Please re-login manually if calls fail.")
            return
    else:
        print("📝 No existing session found. Starting fresh login to create one...")

    # Interactive sign-in
    phone = input("Enter phone number (e.g. +998901234567): ").strip()
    sent = await app.send_code(phone)
    code = input("Enter the OTP code you received: ").strip()

    try:
        await app.sign_in(
            phone_number=phone,
            phone_code_hash=sent.phone_code_hash,
            phone_code=code
        )
    except SessionPasswordNeeded:
        pwd = getpass("Enter your 2FA password: ")
        await app.check_password(pwd)

    me = await app.get_me()
    print(f"✅ Logged in successfully as @{me.username or me.first_name} (id={me.id})")


async def make_call(app: Client, username: str):
    """Make a voice call to a user"""
    try:
        # Resolve the username to get user info
        print(f"🔍 Looking up user {username}...")
        user = await app.get_users(username)

        if not user:
            print(f"❌ User {username} not found")
            return

        print(f"📞 Calling {user.first_name} (@{user.username})...")

        # Generate random ID for the call
        import random
        random_id = random.randint(1, 2 ** 31 - 1)

        # Generate encryption key hash (simplified version)
        import hashlib
        g_a_hash = hashlib.sha256(os.urandom(256)).digest()

        # Create call protocol
        protocol = types.PhoneCallProtocol(
            min_layer=65,
            max_layer=92,
            udp_p2p=True,
            udp_reflector=True,
            library_versions=["2.4.4"]
        )

        # Request the call using raw API
        result = await app.invoke(
            functions.phone.RequestCall(
                user_id=await app.resolve_peer(user.id),
                random_id=random_id,
                g_a_hash=g_a_hash,
                protocol=protocol,
                video=False  # Audio call only
            )
        )

        print(f"✅ Call initiated!")
        print(f"   Phone call object: {result}")
        print("   Waiting for user to accept...")

        return result

    except Exception as e:
        print(f"❌ Failed to start call: {e}")
        import traceback
        traceback.print_exc()


async def main():
    app = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH)
    try:
        await interactive_login(app)

        # Now make the call
        target_username = input("\nEnter username to call (e.g. erkinov_wiz or @erkinov_wiz): ").strip()
        if not target_username.startswith('@'):
            target_username = '@' + target_username

        call = await make_call(app, target_username)

        if call:
            print("\n📞 Call is active. Press Ctrl+C to end...")
            try:
                while True:
                    await asyncio.sleep(100)
            except KeyboardInterrupt:
                print("\n📴 Ending call...")

    finally:
        await app.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
