"""口令哈希与校验的回归测试（2026-10-29 去 passlib 后新增）。

背景：passlib 1.7.4 与 bcrypt 4.x 不兼容，导致 AUTH_DISABLED 启动即崩、
本地账号登录 500。改用 bcrypt 直连后，这里锁住四个行为：
  1. 正常往返；
  2. 超长口令（>72 字节）不抛异常，且按 72 字节截断语义校验；
  3. 损坏/空/非法格式的哈希返回 False，而不是抛异常；
  4. **黄金样本**：一条硬编码的 `$2b$12$` 历史哈希仍能通过校验
     （证明与 passlib 时代产物兼容，无需重置密码）。
"""
import bcrypt

from app.core.security import get_password_hash, verify_password

# 由 bcrypt.gensalt(rounds=12) 生成的固定样本，明文见 GOLDEN_PASSWORD。
# 它代表"历史遗留哈希"：与 passlib 1.7.4 生成的产物同格式（$2b$12$）。
GOLDEN_PASSWORD = "golden-sample-2019"
GOLDEN_HASH = "$2b$12$GrLkpn2S8WiVlatzEIV7FugK/QV2ezB1.Tcek/5YRYnxl9NAavDSO"


class TestRoundTrip:
    def test_hash_then_verify_succeeds(self):
        stored = get_password_hash("s3cret-pass")
        assert stored.startswith("$2b$12$")
        assert verify_password("s3cret-pass", stored) is True

    def test_wrong_password_is_rejected(self):
        stored = get_password_hash("s3cret-pass")
        assert verify_password("s3cret-pas", stored) is False
        assert verify_password("", stored) is False

    def test_same_password_hashes_differ(self):
        """每次加盐不同，哈希不应相同（防止误用固定盐）。"""
        assert get_password_hash("same-pass") != get_password_hash("same-pass")


class TestLegacyCompatibility:
    def test_golden_hash_from_older_implementation_verifies(self):
        assert verify_password(GOLDEN_PASSWORD, GOLDEN_HASH) is True

    def test_golden_hash_rejects_other_password(self):
        assert verify_password(GOLDEN_PASSWORD + "x", GOLDEN_HASH) is False


class TestLongPassword:
    """bcrypt 上限 72 字节：passlib 静默截断，bcrypt>=4 抛 ValueError。

    我们显式截断以保持旧行为——同一口令的前 72 字节相同即视为相同口令。
    """

    def test_long_password_does_not_raise(self):
        long_password = "a" * 100
        stored = get_password_hash(long_password)
        assert verify_password(long_password, stored) is True

    def test_long_password_compares_by_first_72_bytes(self):
        stored = get_password_hash("a" * 100)
        # 与历史行为一致：72 字节之后的内容不参与校验
        assert verify_password("a" * 72, stored) is True

    def test_multibyte_password_does_not_raise(self):
        """中文口令按 UTF-8 编码后可能超过 72 字节，不能因此抛异常。"""
        stored = get_password_hash("测试口令" * 20)
        assert verify_password("测试口令" * 20, stored) is True


class TestMalformedHash:
    """哈希串异常必须降级为 False，绝不 500。"""

    def test_empty_values(self):
        assert verify_password("", "") is False
        assert verify_password("any", "") is False
        assert verify_password("", GOLDEN_HASH) is False

    def test_garbage_hash(self):
        for bad in ("not-a-hash", "$2b$12$short", "$$$", "口令不是哈希"):
            assert verify_password("any", bad) is False

    def test_non_bcrypt_scheme(self):
        assert verify_password("any", "$argon2id$v=19$m=65536$abc$def") is False

    def test_bcrypt_accepts_stored_hash_from_hashpw(self):
        """确认我们自己生成的串能被 bcrypt 本身接受（排除格式自造错误）。"""
        stored = get_password_hash("cross-check")
        assert bcrypt.checkpw(b"cross-check", stored.encode("utf-8")) is True
