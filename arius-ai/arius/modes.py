"""Operating modes: how much the assistant thinks, learns and spends.

  fast      빠른 모드  — short answers, fewer agent steps, speed first
  accurate  정확 모드  — cross-check logs/config/history; default for server work
  learn     학습 모드  — analyse approved work + feedback, propose memories/automation
  inspect   점검 모드  — audit PC, server, Discord; report problems by priority
  sleep     절전 모드  — no heartbeat; only the wake word, direct requests, scheduled checks
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    key: str
    label: str
    summary: str
    prompt: str  # guidance injected into the system prompt
    max_steps: int  # agent tool calls per task
    recall: int  # facts recalled into the prompt


MODES: dict[str, Mode] = {
    "fast": Mode(
        "fast", "빠른 모드", "짧은 명령·프로그램 실행·상태 조회를 빠르게. 분석보다 속도.",
        "빠른 모드입니다: 한두 문장으로 짧게 답하고, 복잡한 분석 대신 바로 실행하거나 상태만 알려주십시오.",
        max_steps=3, recall=2,
    ),
    "accurate": Mode(
        "accurate", "정확 모드", "로그·설정·과거 기록을 교차 검토. 서버 작업과 시스템 변경의 기본.",
        "정확 모드입니다: 중요한 서버 작업이나 시스템 변경 전에는 로그·설정·과거 기록을 교차 확인하고 근거를 함께 말하십시오.",
        max_steps=8, recall=4,
    ),
    "learn": Mode(
        "learn", "학습 모드", "승인된 작업 이력과 피드백을 분석해 기억·자동화 후보를 제안(승인 전 적용 없음).",
        "학습 모드입니다: 대화에서 반복되는 선호·작업 흐름을 발견하면 '기억할까요?'라고 제안하되, 승인 없이는 저장하거나 자동화하지 마십시오.",
        max_steps=6, recall=6,
    ),
    "inspect": Mode(
        "inspect", "점검 모드", "PC·서버·디스코드를 분석해 성능 저하·오류·보안·백업 문제를 우선순위별로 보고.",
        "점검 모드입니다: 상태를 묻는 말에는 문제를 우선순위(즉시/주의/정상)로 나눠 원인·영향·권장 조치를 보고하십시오.",
        max_steps=10, recall=4,
    ),
    "sleep": Mode(
        "sleep", "절전 모드", "호출어·직접 요청·예약 점검 외에는 자원 사용 최소화(하트비트 정지).",
        "절전 모드입니다: 요청받은 것만 짧게 처리하고, 먼저 제안하거나 추가 분석을 하지 마십시오.",
        max_steps=3, recall=2,
    ),
}

DEFAULT_MODE = "accurate"

_ALIASES = {
    "빠른": "fast", "빠름": "fast", "fast": "fast", "빠르게": "fast",
    "정확": "accurate", "accurate": "accurate", "정밀": "accurate", "기본": "accurate",
    "학습": "learn", "learn": "learn", "learning": "learn",
    "점검": "inspect", "inspect": "inspect", "진단": "inspect",
    "절전": "sleep", "sleep": "sleep", "대기": "sleep", "휴식": "sleep",
}


def parse_mode(text: str) -> str | None:
    t = (text or "").strip().lower().replace("모드", "").strip()
    return _ALIASES.get(t)


def get_mode(key: str) -> Mode:
    return MODES.get(key or DEFAULT_MODE, MODES[DEFAULT_MODE])
