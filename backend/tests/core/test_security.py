from flinq.core.security import hash_password, verify_password


def test_hash_and_verify_round_trip() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong password", h) is False


def test_hash_is_unique_per_call() -> None:
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2  # argon2 uses random salt
    assert verify_password("same", h1) is True
    assert verify_password("same", h2) is True


def test_verify_rejects_invalid_hash() -> None:
    assert verify_password("anything", "$argon2id$invalid") is False
