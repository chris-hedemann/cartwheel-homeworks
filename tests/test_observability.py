from __future__ import annotations

from fastapi import HTTPException
import pytest

from server import app as server_app


def test_false_role_claim(world: dict) -> None:
    session_claim = server_app.SessionCreate(user_id=1, role="merchant")

    with pytest.raises(HTTPException) as exc:
        server_app.create_session(session_claim)
    assert exc.value.status_code == 403


def test_impersonate_session_token(world: dict) -> None:
    session_01 = server_app.create_session(
        server_app.SessionCreate(user_id=1, role="shopper")
    )

    session_02 = server_app.create_session(
        server_app.SessionCreate(user_id=2, role="shopper")
    )

    with pytest.raises(HTTPException) as exc:
        server_app._authorize(session_id=session_01["session_id"],
                              authorization=f"Bearer {session_02['token']}")
    assert exc.value.status_code == 403

