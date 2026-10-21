class GoldAppleError(Exception):
    pass

class BlockedError(GoldAppleError):
    def __init__(self, reason: str, ip: str | None = None, request_id: str | None = None):
        self.reason = reason
        self.ip = ip
        self.request_id = request_id
        parts = [reason]
        if ip:
            parts.append(f"ip={ip}")
        if request_id:
            parts.append(f"req={request_id}")
        super().__init__(" ".join(parts))

class NotFoundError(GoldAppleError):
    pass

class TransientError(GoldAppleError):
    pass

class ParseError(GoldAppleError):
    pass
