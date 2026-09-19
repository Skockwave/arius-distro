import pytest

from arius import permissions as perm
from arius.permissions import (
    AuthenticationError,
    PermissionManager,
    Role,
    User,
    hash_passphrase,
    role_has_capability,
    verify_passphrase,
)


def test_role_ordering_and_parse():
    assert Role.OWNER > Role.ADMIN > Role.OPERATOR > Role.USER > Role.GUEST
    assert Role.parse("owner") is Role.OWNER
    assert Role.parse("ADMIN") is Role.ADMIN
    assert Role.parse(Role.USER) is Role.USER
    with pytest.raises(ValueError):
        Role.parse("emperor")


def test_owner_has_wildcard_everything():
    assert role_has_capability(Role.OWNER, perm.CAP_SYSTEM_EXEC)
    assert role_has_capability(Role.OWNER, "anything.at.all")


def test_guest_is_chat_only():
    assert role_has_capability(Role.GUEST, perm.CAP_CHAT)
    assert not role_has_capability(Role.GUEST, perm.CAP_MEMORY_WRITE)
    assert not role_has_capability(Role.GUEST, perm.CAP_SYSTEM_EXEC)


def test_user_cannot_exec_but_can_remember():
    assert role_has_capability(Role.USER, perm.CAP_MEMORY_WRITE)
    assert not role_has_capability(Role.USER, perm.CAP_SYSTEM_EXEC)
    assert not role_has_capability(Role.USER, perm.CAP_USER_MANAGE)


def test_passphrase_roundtrip():
    stored = hash_passphrase("s3cret!")
    assert verify_passphrase("s3cret!", stored)
    assert not verify_passphrase("wrong", stored)
    assert not verify_passphrase("s3cret!", "garbage")


def test_authenticate_success_and_failure():
    pm = PermissionManager(
        [
            User("owner", Role.OWNER, passphrase_hash=hash_passphrase("pw")),
            User("kid", Role.GUEST),
        ]
    )
    sess = pm.authenticate("owner", "pw")
    assert sess.role is Role.OWNER
    assert sess.can(perm.CAP_SYSTEM_EXEC)

    # no passphrase set -> logs in freely
    guestish = pm.authenticate("kid")
    assert guestish.role is Role.GUEST

    with pytest.raises(AuthenticationError):
        pm.authenticate("owner", "nope")
    with pytest.raises(AuthenticationError):
        pm.authenticate("ghost")


def test_require_raises_access_denied():
    pm = PermissionManager([User("kid", Role.GUEST)])
    sess = pm.authenticate("kid")
    with pytest.raises(perm.AccessDenied):
        pm.require(sess, perm.CAP_SYSTEM_EXEC)
