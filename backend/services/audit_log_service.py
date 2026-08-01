"""审计日志服务：异步写入关键安全操作日志。"""

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def write_audit_log(
    db: AsyncSession,
    *,
    user_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> AuditLog | None:
    """写入一条审计日志。

    异常时仅记录 warning，不阻断主流程（审计失败不应导致业务操作失败）。
    """
    try:
        log = AuditLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip=ip,
            created_at=datetime.now(timezone.utc),
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        return log
    except Exception:
        logger.warning("审计日志写入失败: user_id=%s action=%s", user_id, action, exc_info=True)
        await db.rollback()
        return None
