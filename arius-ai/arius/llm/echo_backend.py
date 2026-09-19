"""Offline backend: no API key, no network, works everywhere.

It is deliberately simple — a handful of intent rules plus a persona-flavored
fallback — so the assistant is genuinely usable out of the box and the test
suite stays deterministic. Swap in the Anthropic backend for real reasoning.
"""

from __future__ import annotations

import random
import re

from arius.llm.base import LLMBackend, Message

_GREETING = re.compile(r"(안녕|하이|반가|헬로|hello|hi\b|안뇽)", re.IGNORECASE)
_THANKS = re.compile(r"(고마|감사|thank)", re.IGNORECASE)
_HOWAREYOU = re.compile(r"(어떻게 지내|잘 지내|기분|how are you)", re.IGNORECASE)
_WHO = re.compile(r"(누구|너는 뭐|정체|who are you|what are you)", re.IGNORECASE)
_HELP = re.compile(r"(뭘 할 수|무엇을 할|기능|할 수 있|what can you)", re.IGNORECASE)


class EchoBackend(LLMBackend):
    name = "echo"

    def __init__(self, assistant_name: str = "ARIUS", honorific: str = "님") -> None:
        self.assistant_name = assistant_name
        self.honorific = honorific
        self._rng = random.Random(7)

    def generate(self, system: str, messages: list[Message]) -> str:
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        text = last.strip()
        if not text:
            return f"네, 말씀하십시오. {self.assistant_name}는 대기 중입니다."

        if _GREETING.search(text):
            return f"안녕하십니까. {self.assistant_name}입니다. 무엇을 도와드릴까요?"
        if _THANKS.search(text):
            return "천만에요. 더 필요하신 일이 있으면 언제든 말씀하십시오."
        if _HOWAREYOU.search(text):
            return "시스템은 안정적으로 가동 중입니다. 지시를 기다리고 있습니다."
        if _WHO.search(text):
            return (
                f"저는 {self.assistant_name}, 로컬에서 동작하는 개인 인공지능 비서입니다. "
                "권한 등급에 따라 통제되며, 지시하신 범위 안에서만 움직입니다."
            )
        if _HELP.search(text):
            return (
                "대화, 기억/학습, 시스템 정보 조회, 프로젝트 관리, 명령 실행 등을 지원합니다. "
                "정확한 목록은 '도움말' 또는 '/help'로 확인하실 수 있습니다."
            )

        # Fallback: acknowledge and reflect, in-persona. This is a placeholder
        # for a real model — connect the Anthropic backend for actual reasoning.
        openers = [
            "확인했습니다.",
            "알겠습니다.",
            "말씀 잘 들었습니다.",
        ]
        opener = self._rng.choice(openers)
        note = (
            "\n\n(참고: 현재 오프라인 응답 모드입니다. 실제 추론을 원하시면 "
            "config에서 llm.backend를 'anthropic'으로 바꾸고 API 키를 설정하십시오.)"
        )
        return f"{opener} '{_snippet(text)}' 요청으로 이해했습니다.{note}"


def _snippet(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
