import uuid

import pytest

from app.auth.principal import READ, WRITE, Principal


def principal(*scopes: str) -> Principal:
    return Principal(user_id=uuid.uuid4(), scopes=frozenset(scopes), via="pat")


@pytest.mark.parametrize(
    ("scopes", "asked", "expected"),
    [
        ((READ,), READ, True),
        ((READ,), WRITE, False),
        ((WRITE,), WRITE, True),
        ((WRITE,), READ, True),  # write implies read
        ((), READ, False),
        ((), WRITE, False),
    ],
)
def test_has(scopes: tuple[str, ...], asked: str, expected: bool) -> None:
    assert principal(*scopes).has(asked) is expected
