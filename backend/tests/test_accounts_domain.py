import pytest

from domain.accounts import (
    Role,
    check_new_password,
    generate_password,
    hash_password,
    validate_membership,
    verify_password,
)


def test_hashes_verify_and_are_salted() -> None:
    a, b = hash_password("a long enough pass"), hash_password("a long enough pass")
    assert a != b
    assert verify_password("a long enough pass", a) and not verify_password("wrong", a)
    assert not verify_password("x", "not-a-hash") and not verify_password("x", "md5$1$2$3$4$5")


def test_generated_passwords_are_long_and_different() -> None:
    first, second = generate_password(), generate_password()
    assert len(first) >= 16 and first != second


@pytest.mark.parametrize(
    ("role", "tenant", "groups"),
    [
        (Role.USER, "t1", ("eng",)),
        (Role.USER, "t1", ("eng", "hr")),
        (Role.GROUP_ADMIN, "t1", ("hr",)),
        (Role.TENANT_ADMIN, "t1", ()),
        (Role.PLATFORM_ADMIN, None, ()),
    ],
)
def test_valid_shapes(role: Role, tenant: str | None, groups: tuple[str, ...]) -> None:
    validate_membership(role, tenant, groups)


@pytest.mark.parametrize(
    ("role", "tenant", "groups"),
    [
        (Role.USER, "t1", ()),
        (Role.USER, None, ("eng",)),
        (Role.GROUP_ADMIN, "t1", ("eng", "hr")),
        (Role.TENANT_ADMIN, "t1", ("eng",)),
        (Role.PLATFORM_ADMIN, "t1", ()),
        (Role.USER, "bad tenant!", ("eng",)),
    ],
)
def test_invalid_shapes(role: Role, tenant: str | None, groups: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        validate_membership(role, tenant, groups)


def test_password_rules() -> None:
    check_new_password("a long enough pass", "alice")
    for bad in ("short", "x" * 129, "my alice password"):
        with pytest.raises(ValueError):
            check_new_password(bad, "alice")

            