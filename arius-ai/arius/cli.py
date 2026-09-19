"""Command-line interface for ARIUS.

`python -m arius` (or `python main.py`) starts an interactive REPL. Slash
commands handle sessions and voice; everything else goes to the assistant.

Subcommands:
  run   (default) - start the interactive assistant
  init            - scaffold a config file and create the owner account
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from arius.config import AriusConfig, UserConfig, config_to_dict
from arius.core import Arius
from arius.permissions import AuthenticationError, hash_passphrase
from arius.voice import SpeechToText, TextToSpeech

BANNER = r"""
   _   ___ ___ _   _ ___
  /_\ | _ \_ _| | | / __|   Adaptive Responsive Intelligent User System
 / _ \|   /| || |_| \__ \   로컬 개인 AI 비서
/_/ \_\_|_\___|\___/|___/
"""

HELP_COMMANDS = (
    "세션: /login <아이디>, /logout, /quit\n"
    "음성: /voice on|off (답변 읽어주기), /listen (마이크로 한 문장 입력)\n"
    "기타: /reindex (기억 벡터 재색인), /help (기능 목록)"
)


def _print_reply(assistant_name: str, reply_text: str) -> None:
    print(f"\n{assistant_name} › {reply_text}\n")


class _Voice:
    """Lazy holder for TTS/STT so the REPL can toggle them at runtime."""

    def __init__(self, cfg: AriusConfig) -> None:
        self.cfg = cfg
        self.tts: TextToSpeech | None = None
        self.stt: SpeechToText | None = None
        self.speaking = False
        self.listening = False

    def enable_speech(self) -> str:
        if self.tts is None:
            v = self.cfg.voice
            self.tts = TextToSpeech(v.language, v.rate, v.voice_name)
        if not self.tts.available:
            self.speaking = False
            return f"음성 출력을 켤 수 없습니다: {self.tts.reason}"
        self.speaking = True
        return f"음성 출력을 켰습니다. (엔진: {self.tts.backend})"

    def disable_speech(self) -> str:
        self.speaking = False
        return "음성 출력을 껐습니다."

    def enable_listening(self) -> str:
        if self.stt is None:
            self.stt = SpeechToText(self.cfg.voice.language)
        if not self.stt.available:
            self.listening = False
            return f"음성 입력을 켤 수 없습니다: {self.stt.reason}"
        self.listening = True
        return "음성 입력을 켰습니다. 말씀하시면 받아 적겠습니다."

    def say(self, text: str) -> None:
        if self.speaking and self.tts is not None:
            self.tts.speak(text)

    def hear_once(self) -> str | None:
        """One utterance from the mic, or None (with a printed reason) if unavailable."""
        if self.stt is None:
            self.stt = SpeechToText(self.cfg.voice.language)
        if not self.stt.available:
            print(self.stt.reason)
            return None
        print("🎤 듣는 중… (말씀하십시오)")
        heard = self.stt.listen()
        if heard is None:
            if self.stt.reason:
                print(self.stt.reason)
            else:
                print("아무 소리도 듣지 못했습니다.")
            return None
        if heard == "":
            print("잘 알아듣지 못했습니다. 다시 말씀해 주십시오.")
            return None
        return heard


def cmd_run(args: argparse.Namespace) -> int:
    arius = Arius.from_path(args.config)
    cfg = arius.config
    voice = _Voice(cfg)

    # Auto-login the single owner if there is exactly one user and it needs no
    # passphrase — convenient for a personal machine.
    if not args.no_autologin and len(cfg.users) == 1 and not cfg.users[0].passphrase_hash:
        try:
            arius.login(cfg.users[0].username)
        except AuthenticationError:
            pass

    print(BANNER)
    print(f"{cfg.assistant_name} 준비 완료. 백엔드: {arius.backend.name}, 임베딩: {arius.embedder.name}. "
          f"현재 사용자: {arius.current_user_label}.")
    print(HELP_COMMANDS + "\n")

    if args.voice or cfg.voice.enabled:
        print(voice.enable_speech())
    if args.listen or cfg.voice.listen:
        print(voice.enable_listening())

    while True:
        line: str | None = None
        if voice.listening:
            line = voice.hear_once()
            if line:
                print(f"{arius.session.user.display_name} › {line}")
        if line is None:
            try:
                line = input(f"{arius.session.user.display_name} › ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n" + f"{cfg.assistant_name}를 종료합니다. 안녕히 가십시오.")
                break
        if not line:
            continue
        if line in ("/quit", "/exit", "종료"):
            print(f"{cfg.assistant_name}를 종료합니다. 안녕히 가십시오.")
            break
        if line.startswith("/login"):
            _handle_login(arius, line)
            continue
        if line == "/logout":
            arius.logout()
            print(f"로그아웃했습니다. 현재 사용자: {arius.current_user_label}.")
            continue
        if line.startswith("/voice"):
            arg = line.split(maxsplit=1)[1].strip().lower() if " " in line else ""
            if arg in ("off", "끄기", "0"):
                print(voice.disable_speech())
            elif arg in ("on", "켜기", "1", ""):
                print(voice.enable_speech())
            else:
                print("사용법: /voice on|off")
            continue
        if line == "/listen":
            heard = voice.hear_once()
            if not heard:
                continue
            print(f"{arius.session.user.display_name} › {heard}")
            line = heard
        if line == "/reindex":
            n = arius.memory.reindex()
            print(f"기억 벡터를 재색인했습니다: {n}개 항목 (임베딩: {arius.embedder.name})")
            continue
        if line == "/commands":
            print(HELP_COMMANDS)
            continue

        reply = arius.handle(line)
        _print_reply(cfg.assistant_name, reply.text)
        voice.say(reply.text)

    arius.close()
    return 0


def _handle_login(arius: Arius, line: str) -> None:
    parts = line.split()
    if len(parts) < 2:
        print("사용법: /login <아이디>")
        return
    username = parts[1]
    user = arius.permissions.get(username)
    if user is None:
        print(f"등록되지 않은 사용자입니다: {username}")
        return
    passphrase = None
    if user.requires_passphrase:
        try:
            passphrase = getpass.getpass("암호: ")
        except (EOFError, KeyboardInterrupt):
            print("\n로그인을 취소했습니다.")
            return
    try:
        arius.login(username, passphrase)
    except AuthenticationError as exc:
        print(f"로그인 실패: {exc}")
        return
    print(f"환영합니다, {arius.current_user_label}.")


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.config or "config.json")
    if path.exists() and not args.force:
        print(f"이미 config가 존재합니다: {path} (덮어쓰려면 --force)")
        return 1

    print("ARIUS 초기 설정을 시작합니다.\n")
    assistant_name = input("비서 이름 [ARIUS]: ").strip() or "ARIUS"
    owner_username = input("오너 아이디 [owner]: ").strip() or "owner"
    owner_display = input(f"오너 표시 이름 [{owner_username}]: ").strip() or owner_username

    passphrase_hash = ""
    if _yes_no("오너 계정에 암호를 설정할까요?", default=True):
        while True:
            p1 = getpass.getpass("암호: ")
            p2 = getpass.getpass("암호 확인: ")
            if p1 and p1 == p2:
                passphrase_hash = hash_passphrase(p1)
                break
            print("암호가 비어 있거나 일치하지 않습니다. 다시 입력하십시오.")

    use_anthropic = _yes_no("실제 추론을 위해 Anthropic Claude 백엔드를 쓰시겠습니까?", default=False)
    use_voice = _yes_no("답변을 음성으로 읽어줄까요? (TTS)", default=False)

    config = AriusConfig(
        assistant_name=assistant_name,
        users=[
            UserConfig(
                username=owner_username,
                role="owner",
                display_name=owner_display,
                passphrase_hash=passphrase_hash,
            )
        ],
        default_user="guest",
    )
    if use_anthropic:
        config.llm.backend = "anthropic"
    config.voice.enabled = use_voice

    path.write_text(json.dumps(config_to_dict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n설정을 저장했습니다: {path}")
    if use_anthropic:
        print("환경 변수 ANTHROPIC_API_KEY 에 API 키를 설정한 뒤 `pip install anthropic` 하십시오.")
    if use_voice:
        print("음성 출력 품질을 높이려면 `pip install pyttsx3` 를 권장합니다 (없어도 OS 음성으로 동작).")
    print("이제 `python main.py` 로 시작할 수 있습니다.")
    return 0


def _yes_no(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    try:
        ans = input(prompt + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if not ans:
        return default
    return ans in ("y", "yes", "예", "네", "ㅇ")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arius", description="ARIUS 로컬 AI 비서")
    parser.add_argument("-c", "--config", help="config 파일 경로")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="대화형 비서 실행 (기본값)")
    run_p.add_argument("--no-autologin", action="store_true", help="단일 오너 자동 로그인 비활성화")
    run_p.add_argument("--voice", action="store_true", help="답변을 음성으로 읽어주기 (TTS)")
    run_p.add_argument("--listen", action="store_true", help="마이크로 입력 받기 (STT)")
    run_p.set_defaults(func=cmd_run)

    init_p = sub.add_parser("init", help="config 생성 및 오너 계정 설정")
    init_p.add_argument("--force", action="store_true", help="기존 config 덮어쓰기")
    init_p.set_defaults(func=cmd_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        # default to `run`
        args.func = cmd_run
        args.no_autologin = False
        args.voice = False
        args.listen = False
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
