from unittest.mock import MagicMock

from app.database.session import session_scope


def test_session_scope_commits_and_closes() -> None:
    session = MagicMock()
    factory = MagicMock(return_value=session)

    with session_scope(factory) as with_value:
        assert with_value is session

    session.commit.assert_called_once_with()
    session.close.assert_called_once_with()


def test_session_scope_rolls_back_on_error() -> None:
    session = MagicMock()
    factory = MagicMock(return_value=session)
    try:
        with session_scope(factory):
            raise RuntimeError("failure")
    except RuntimeError:
        pass

    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
