from __future__ import annotations

import json

from sqlalchemy.orm import Session

from backend.models.tables import AuditLog


def log_event(
    db: Session,
    *,
    actor_username: str,
    action: str,
    target: str = "",
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_username=actor_username,
            action=action,
            target=target,
            metadata_json=json.dumps(metadata or {}, sort_keys=True),
        )
    )
