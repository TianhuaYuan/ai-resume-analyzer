from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.exceptions import AppException
from services.resume_service import set_resume_status


@pytest.mark.asyncio
async def test_resume_state_transition_records_event():
    db = AsyncMock()
    resume = SimpleNamespace(id=10, status="ready", status_message=None)

    await set_resume_status(db, resume, "draft", reason="用户继续编辑")

    assert resume.status == "draft"
    assert resume.status_message == "用户继续编辑"
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_resume_state_transition_rejects_unknown_path():
    db = AsyncMock()
    resume = SimpleNamespace(id=10, status="expired", status_message=None)

    with pytest.raises(AppException) as exc_info:
        await set_resume_status(db, resume, "ready")

    assert exc_info.value.status_code == 409
    db.add.assert_not_called()
