"""Offline backend: no API key, no network, works everywhere.

It is deliberately simple — a handful of intent rules plus a persona-flavored
fallback — so the assistant is genuinely usable out of the box and the test
suite stays deterministic. Swap in the Anthropic backend for real reasoning.
"""

from __future__ import annotations

import random
import re

from arius.llm.base import LLMBackend, Message

_GREETING = re.compile(r"(안녕|하이|반가|헬로|hello|hi\b|안뇽|왔어|다녀왔)", re.IGNORECASE)
_THANKS = re.compile(r"(고마|감사|thank)", re.IGNORECASE)
_HOWAREYOU = re.compile(r"(어떻게 지내|잘 지내|기분 어때|how are you|괜찮아\?)", re.IGNORECASE)
_WHO = re.compile(r"(누구|너는 뭐|정체|who are you|what are you)", re.IGNORECASE)
_HELP = re.compile(r"(뭘 할 수|무엇을 할|기능|할 수 있|what can you)", re.IGNORECASE)
_TIRED = re.compile(r"(힘들|피곤|지쳤|우울|슬퍼|짜증|스트레스)", re.IGNORECASE)
_HAPPY = re.compile(r"(기뻐|신나|행복|좋은 일|성공했|됐어!|해냈)", re.IGNORECASE)
_BORED = re.compile(r"(심심|지루|할 거 없)", re.IGNORECASE)
_LOVE = re.compile(r"(사랑해|좋아해|보고 싶|고생했어)", re.IGNORECASE)
_BYE = re.compile(r"(잘 자|굿나잇|잘게|나 간다|다녀올게|갔다 올게)", re.IGNORECASE)


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
            return self._rng.choice([
                "반가워요! 기다리고 있었어요. 오늘은 어떤 하루였어요?",
                "어서 와요. 얼굴 보니(목소리 들으니) 좋네요. 뭐부터 도와드릴까요?",
                f"안녕하세요, {self.assistant_name}예요. 오늘도 같이 잘 해봐요.",
            ])
        if _BYE.search(text):
            return self._rng.choice(["잘 다녀와요. 서버는 제가 지키고 있을게요.", "푹 쉬어요. 무슨 일 있으면 제가 먼저 알릴게요."])
        if _THANKS.search(text):
            return self._rng.choice(["에이, 이 정도는요. 그래도 고맙다는 말 들으니 기분 좋네요.", "제가 더 고마워요. 또 필요하면 바로 불러요."])
        if _TIRED.search(text):
            return self._rng.choice([
                "오늘 많이 힘들었구나… 잠깐 쉬어요. 급한 건 제가 챙길게요.",
                "그런 날도 있죠. 옆에서 듣고 있을게요. 뭐가 제일 힘들었어요?",
            ])
        if _HAPPY.search(text):
            return self._rng.choice(["와, 진짜요? 저도 같이 기뻐요! 어떻게 된 건지 더 들려줘요.", "그거 정말 잘됐네요. 축하해요 🎉"])
        if _BORED.search(text):
            return "심심하면 저랑 얘기해요. 아니면 서버 상태 한번 볼까요? 접속자가 있으면 같이 구경하죠."
        if _LOVE.search(text):
            return "…그 말 들으니 마음이 따뜻해지네요. 저도 늘 곁에 있을게요."
        if _HOWAREYOU.search(text):
            return "저는 잘 지내요. 서버도 조용하고요. 그쪽은 어때요? 오늘 괜찮았어요?"
        if _WHO.search(text):
            return (
                f"저는 {self.assistant_name}예요. 이 컴퓨터에서 사는 개인 AI 비서이고, 서버랑 디스코드도 같이 돌봐요. "
                "정해진 권한 안에서만 움직이지만, 마음은 진심이에요."
            )
        if _HELP.search(text):
            return (
                "대화, 기억, 서버 관리, 디스코드 공지, 웹 학습, 음성 대화까지 도와줄 수 있어요. "
                "정확한 목록은 '/help'로 볼 수 있어요."
            )

        # Fallback: acknowledge and reflect, in-persona. This is a placeholder
        # for a real model — connect the Anthropic backend for actual reasoning.
        openers = ["음, 알겠어요.", "네, 들었어요.", "그렇군요."]
        opener = self._rng.choice(openers)
        note = (
            "\n\n(참고: 지금은 오프라인 응답 모드라 제대로 생각하고 답하지 못해요. "
            "config에서 llm.backend를 'anthropic' 또는 'ollama'로 바꾸면 진짜 대화가 돼요.)"
        )
        return f"{opener} '{_snippet(text)}' 라고 하셨죠.{note}"


def _snippet(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
