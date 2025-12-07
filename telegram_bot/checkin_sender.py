# telegram_bot/checkin_sender.py

from telethon.errors.rpcerrorlist import PeerFloodError


async def send_message_by_username(client, target_username, message_content):
    """Sends a message using the Telethon client via username."""
    if not target_username:
        print("    ⚠️ Skipping: Username is missing.")
        return None

    try:
        # Resolve the entity and send the message
        user_entity = await client.get_input_entity(target_username)
        message_result = await client.send_message(user_entity, message_content)
        print(f"    🎉 Success: Check-in sent to {target_username}")
        return message_result

    except PeerFloodError:
        print("    ❌ Error: Peer Flood detected. Skipping message to avoid rate limits.")
    except ValueError:
        print(f"    ❌ Error: Cannot find entity for username '{target_username}'. Check if it's correct.")
    except Exception as e:
        print(f"    ❌ An unexpected error occurred: {e}")