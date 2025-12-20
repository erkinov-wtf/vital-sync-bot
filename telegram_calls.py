import os
import random
import hashlib

from pyrogram import Client
from pyrogram.raw import functions, types


async def make_call(app: Client, username: str):
    """
    Make a voice call to a user using a started Pyrogram client.
    Returns the raw PhoneCall object on success.
    """
    try:
        # Resolve the username to get user info
        handle = username if username.startswith("@") else f"@{username}"
        print(f"🔍 Looking up user {handle}...")
        user = await app.get_users(handle)

        if not user:
            print(f"❌ User {handle} not found")
            return

        print(f"📞 Calling {user.first_name} (@{user.username})...")

        # Generate random ID for the call
        random_id = random.randint(1, 2 ** 31 - 1)

        # Generate encryption key hash (simplified version)
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
