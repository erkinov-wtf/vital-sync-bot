from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any

from models.utils import parse_date


@dataclass
class User:
    ID: str
    PhoneNumber: str
    FirstName: str
    LastName: str
    Role: str
    Gender: str
    IsActive: bool
    TelegramUsername: str
    LastLoginAt: Optional[datetime]
    CreatedAt: datetime
    UpdatedAt: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        return cls(
            ID=data["ID"],
            PhoneNumber=data["PhoneNumber"],
            FirstName=data["FirstName"],
            LastName=data["LastName"],
            Role=data["Role"],
            Gender=data["Gender"],
            IsActive=data["IsActive"],
            TelegramUsername=data.get("TelegramUsername", ""),
            LastLoginAt=parse_date(data.get("LastLoginAt")),
            CreatedAt=parse_date(data.get("CreatedAt")),
            UpdatedAt=parse_date(data.get("UpdatedAt")),
        )