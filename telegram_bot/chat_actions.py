from contextlib import asynccontextmanager


class _NoopAction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


@asynccontextmanager
async def chat_action(client, recipient, action: str):
    """
    Safe wrapper around Telethon's chat action context.
    Falls back to a no-op if the action cannot be sent.
    """
    ctx = None
    try:
        ctx = client.action(recipient, action)
        await ctx.__aenter__()
        yield
    except Exception:
        # If sending the action fails, continue without blocking the flow.
        yield
    finally:
        if ctx:
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass
