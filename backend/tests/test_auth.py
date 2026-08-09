from app.auth import Security
from app.config import Settings
from app.storage import SecretsStore


def _security(tmp_path, access_code: str = "", jwt_secret: str = "") -> Security:
    s = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        access_code=access_code,
        jwt_secret=jwt_secret,
    )
    return Security(SecretsStore(s.data_dir), s)


def test_env_access_code_hashed(tmp_path):
    sec = _security(tmp_path, access_code="abc123")
    assert sec.verify_access_code("abc123") is True
    assert sec.verify_access_code("wrong") is False
    # 明文不落盘
    text = (tmp_path / "data" / "secrets.json").read_text(encoding="utf-8")
    assert "abc123" not in text


def test_empty_access_code_disables_auth(tmp_path):
    """未设置访问码 = 免认证模式：auth_enabled 为 False，不再生成随机码。"""
    sec = _security(tmp_path)
    assert sec.auth_enabled is False
    assert sec.verify_access_code("anything") is False


def test_token_roundtrip(tmp_path):
    sec = _security(tmp_path, jwt_secret="fixed-secret-0123456789abcdefghijklmnopqrstuv")
    token = sec.create_token()
    assert sec.verify_token(token) is True
    assert sec.verify_token(token + "x") is False
    assert sec.verify_token("") is False


def test_env_jwt_secret_takes_precedence(tmp_path):
    sec = _security(tmp_path, jwt_secret="env-secret-0123456789abcdefghijklmnopqrstuv")
    assert sec.secrets.jwt_secret == "env-secret-0123456789abcdefghijklmnopqrstuv"
    # 不同 secret 无法互验
    other = _security(tmp_path, jwt_secret="other-secret-0123456789abcdefghijklmnopqrstuv")
    assert not other.verify_token(sec.create_token())
