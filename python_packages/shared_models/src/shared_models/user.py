from datetime import datetime

from pydantic import BaseModel


class UserResponse(BaseModel):
    id: str
    github_user_id: int
    github_username: str
    github_avatar_url: str | None
    email: str
    display_name: str | None
    created_at: datetime
    last_signed_in_at: datetime
