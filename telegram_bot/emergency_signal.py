
def has_emergency_signal(event, text):
    t = (text or "").lower()
    if any(k in t for k in ["help", "emergency", "urgent", "bleeding", "chest", "breath", "pain", "911"]):
        return True
    if getattr(event.message, 'media', None):
        m = event.message.media
        if getattr(m, 'photo', None) is not None:
            return True
        if getattr(getattr(m, 'document', None), 'voice', False):
            return True
    return False
