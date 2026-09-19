"""Secret detection and redaction.

The operating rules say passwords, API keys, tokens, financial data and
national ID numbers must never be spoken aloud, written to logs, or stored in
long-term memory. This module is the single place that decides what "looks
like a secret" so every entry point (memory, logs, voice) agrees.
"""

from __future__ import annotations

import re

SECRET_NOTE = "[비밀 정보 생략]"

# Labels that usually precede a secret value ("비밀번호: hunter2", "api key = ...").
_LABEL_SRC = (
    r"(?:비밀\s*번호|비번|패스워드|암호\s*(?=[:：=는은])|password|passwd|pwd\s*(?=[:：=])|"
    r"api[\s_-]*key|apikey|secret|token|토큰|인증\s*키|비밀\s*키|private\s*key|rcon\s*(?:설정|암호|password)|"
    r"계좌\s*번호|카드\s*번호|cvc|cvv|주민\s*(?:등록)?\s*번호)"
)
_LABEL = re.compile(_LABEL_SRC, re.IGNORECASE)
_LABEL_VALUE = re.compile(
    rf"(?P<label>{_LABEL_SRC})(?P<sep>[\"'\s]*[:：=]?[\"'\s]*(?:는|은|이|가)?\s*)(?P<val>(?!\[비밀)[^\s:：=\"']\S*)",
    re.IGNORECASE,
)
# Values that are secrets on their own.
_VALUE = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[abp]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|"
    r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]{20,}|"
    r"\b[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27,}\b|"  # Discord bot token
    r"\b\d{6}-[1-4]\d{6}\b|"  # 주민등록번호
    r"\b(?:\d{4}[ -]){3}\d{4}\b|\b\d{15,16}\b|"  # card number (grouped or contiguous; timestamps are 14 digits)
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)


def looks_secret(text: str) -> bool:
    """True when the text carries something that must not be stored or spoken."""
    if not text:
        return False
    if _VALUE.search(text):
        return True
    return bool(_LABEL.search(text))


def redact(text: str) -> str:
    """Replace secret-looking values with a marker. Labelled lines lose their value part."""
    if not text or not looks_secret(text):
        return text
    out = _VALUE.sub(SECRET_NOTE, text)
    # "비밀번호: abc" -> "비밀번호: [비밀 정보 생략]"
    return _LABEL_VALUE.sub(lambda m: f"{m.group('label')}{m.group('sep')}{SECRET_NOTE}", out)


def refuse_secret_message() -> str:
    return (
        "실행하지 않았습니다.\n"
        "이유: 비밀번호·API 키·토큰·금융 정보처럼 보이는 내용은 장기 기억이나 로그에 저장하지 않습니다.\n"
        "다음 조치: 비밀 값은 환경 변수(예: ANTHROPIC_API_KEY, ARIUS_DISCORD_TOKEN)나 config 에 직접 넣어 주세요. "
        "값 자체가 아닌 '어디에 있는지'는 기억할 수 있습니다."
    )
