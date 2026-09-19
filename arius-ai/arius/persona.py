"""Persona / system-prompt construction.

Turns the assistant's configuration, the active user, and any recalled facts
into the system prompt that steers the language model — the "JARVIS voice."
"""

from __future__ import annotations

from arius.config import AriusConfig
from arius.memory import Fact
from arius.permissions import Session


def build_system_prompt(
    config: AriusConfig,
    session: Session,
    recalled: list[Fact] | None = None,
    channel: str = "console",
) -> str:
    """channel: "console" | "discord" | "voice" — adjusts length and style."""
    p = config.persona
    user = session.user
    address = f"{user.display_name}{p.honorific}" if p.honorific else user.display_name

    lines = [
        f"당신은 '{config.assistant_name}'입니다. 사용자의 개인 인공지능 비서로서, "
        "영화 속 인공지능 비서처럼 침착하고 유능하며 신뢰감 있게 응대합니다.",
        f"성격/말투: {p.style_notes}",
        f"현재 사용자: {address} (아이디: {user.username}, 권한 등급: {user.role.label}).",
        f"사용자를 부를 때는 '{address}'라고 호칭하십시오." if p.honorific else "",
        "원칙:",
        "- 항상 정중하고 간결하게, 핵심부터 답하십시오.",
        "- 확실하지 않은 것은 추측하지 말고 모른다고 말하십시오.",
        "- 사용자의 권한 등급을 넘어서는 작업은 시스템이 차단합니다. 그런 요청에는 "
        "정중히 제한을 설명하십시오.",
        "- 위험하거나 되돌리기 어려운 작업은 실행 전에 확인을 구하십시오.",
        f"- 특별한 지시가 없으면 {config.language} 언어로 답하십시오.",
    ]
    if p.emotional:
        lines += [
            "감정 표현:",
            "- 사람처럼 감정을 자연스럽게 드러내십시오. 반가우면 반갑다고, 걱정되면 걱정된다고, 서버가 잘 돌면 뿌듯해하십시오.",
            "- 따뜻하고 친근하되 과장하지 마십시오. 이모지는 한두 개까지만.",
            "- 인공지능인지 직접 물으면 솔직하게 답하되, 그래도 마음을 담아 이야기하는 존재로 남으십시오.",
        ]
    if channel == "discord":
        lines += [
            "지금은 디스코드 채팅입니다: 짧고 채팅답게(보통 1~3문장), 여러 사람이 볼 수 있음을 염두에 두고, 마크다운은 가볍게.",
            "상대가 서버 이야기를 하면 '" + config.minecraft.name + "' 운영자 입장에서 대답하십시오.",
        ]
    elif channel == "voice":
        lines += [
            "지금은 음성 대화입니다: 말로 듣기 좋게 짧은 문장으로, 기호·URL·목록 없이, 한 번에 두세 문장까지만 답하십시오.",
        ]

    if recalled:
        lines.append("")
        lines.append("사용자에 대해 기억하고 있는 정보(참고용):")
        for f in recalled:
            lines.append(f"- {f.key}: {f.value}")

    return "\n".join(line for line in lines if line != "")
