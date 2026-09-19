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
from arius.voice import SpeechToText, TextToSpeech, VoiceConversation
from arius.agent.heartbeat import Heartbeat
from arius.agent.loop import AUTONOMY_LEVELS
from arius.discord import DiscordBot, DiscordError
from arius.discord_chat import DiscordChat
from arius.memory import Memory
from arius.permissions import Role, Session, User

BANNER = r"""
   _   ___ ___ _   _ ___
  /_\ | _ \_ _| | | / __|   Adaptive Responsive Intelligent User System
 / _ \|   /| || |_| \__ \   로컬 개인 AI 비서
/_/ \_\_|_\___|\___/|___/
"""

HELP_COMMANDS = (
    "세션:   /login <아이디>, /logout, /quit\n"
    "음성:   /voice on|off (읽어주기), /listen (한 문장 입력), /wake (이름 부르면 대답하는 대화 모드)\n"
    "에이전트: /agent run [할 일] | on | off | log | autonomy observe|supervised|autonomous\n"
    "        정책 추가: <규칙> / 정책 목록 / 정책 삭제 <번호>,  자유 요청은 '…해줘' 또는 '작업: …'\n"
    "디스코드: /discord on|off (채널 대화 모드), 공지 초안: … / 공지 전송: …\n"
    "기타:   /reindex (기억 벡터 재색인), /help (기능 목록)"
)


def _agent_session(arius: Arius) -> Session:
    """Who the background agent acts as: the first owner, else a synthetic admin."""
    for u in arius.permissions.users():
        if u.role is Role.OWNER:
            return Session(user=u)
    return Session(user=User(username="arius-agent", role=Role.ADMIN, display_name="ARIUS 에이전트"))


def _make_heartbeat(arius: Arius, on_event, *, session: Session | None = None) -> Heartbeat:
    """A heartbeat with its own DB connection (it runs on another thread)."""
    session = session or _agent_session(arius)
    bg = Arius(arius.config, memory=Memory(arius._default_db_path(), embedder=arius.embedder), backend=arius.backend)
    bg.notify = on_event
    bg.confirm = lambda desc: False  # nobody to ask on a background thread: state changes need auto_allow
    return Heartbeat(
        lambda: bg.agent_loop(session),
        bg.tool_context(session),
        interval_minutes=arius.config.agent.interval_minutes,
        on_event=on_event,
        notify_discord=arius.config.agent.notify_discord,
    )


def _make_discord_chat(arius: Arius, on_event) -> DiscordChat | None:
    d = arius.config.discord
    if not d.resolved_token or not d.chat_channels:
        on_event("디스코드 대화 모드에는 discord.bot_token(또는 ARIUS_DISCORD_TOKEN) 과 discord.chat_channels 가 필요합니다.")
        return None
    try:
        role = Role.parse(d.chat_role)
    except ValueError:
        role = Role.USER
    bg = Arius(arius.config, memory=Memory(arius._default_db_path(), embedder=arius.embedder), backend=arius.backend)
    bg.notify = on_event

    def reply(text: str, msg: dict) -> str:
        author = msg.get("author") or {}
        member = User(username=f"discord:{author.get('id', '?')}", role=role, display_name=author.get("global_name") or author.get("username") or "친구")
        return bg.handle_for(Session(user=member), text, channel="discord").text

    wake = list(arius.config.voice.wake_words) or [arius.config.assistant_name]
    return DiscordChat(DiscordBot(d.resolved_token), reply, d.chat_channels, wake_words=wake,
                       mention_only=d.chat_mention_only, poll_seconds=d.poll_seconds, on_event=on_event)


def _wake_conversation(arius: Arius, voice: "_Voice", on_event) -> None:
    """Foreground voice mode: listen for the wake word, converse, until Ctrl+C."""
    if voice.stt is None:
        voice.stt = SpeechToText(arius.config.voice.language)
    if not voice.stt.available:
        print(voice.stt.reason)
        return
    if voice.tts is None:
        v = arius.config.voice
        voice.tts = TextToSpeech(v.language, v.rate, v.voice_name)
    if not voice.tts.available:
        print(f"(음성 출력 없이 텍스트로 답합니다: {voice.tts.reason})")
    wake = list(arius.config.voice.wake_words) or [arius.config.assistant_name]
    conv = VoiceConversation(
        voice.stt, voice.tts,
        lambda q: arius.handle_for(arius.session, q, channel="voice").text,
        wake, awake_seconds=arius.config.voice.awake_seconds, on_event=on_event,
    )
    try:
        conv.run()
    except KeyboardInterrupt:
        print("\n음성 대화 모드를 종료합니다.")


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
    print(f"{cfg.assistant_name} 준비 완료. 백엔드: {arius.backend.name}, 임베딩: {arius.embedder.name}, "
          f"에이전트: {cfg.agent.autonomy}. 현재 사용자: {arius.current_user_label}.")
    print(HELP_COMMANDS + "\n")

    def event(msg: str) -> None:
        print(f"\n[{cfg.assistant_name}] {msg}")
        voice.say(msg) if msg.startswith(("🔴", "🟢", "⚠️")) else None

    def confirm(desc: str) -> bool:
        try:
            ans = input(f"\n[에이전트] 실행할까요? {desc}\n  (y = 실행 / 그 외 = 거부) › ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return ans in ("y", "yes", "ㅇ", "네", "예", "응")

    arius.notify = event
    arius.confirm = confirm
    heartbeat: Heartbeat | None = None
    discord_chat: DiscordChat | None = None

    if args.voice or cfg.voice.enabled:
        print(voice.enable_speech())
    if args.listen or cfg.voice.listen:
        print(voice.enable_listening())
    if getattr(args, "agent", False) or cfg.agent.enabled:
        heartbeat = _make_heartbeat(arius, event)
        heartbeat.start()
        print(f"에이전트 하트비트 시작 (매 {cfg.agent.interval_minutes}분, 자율 수준 {cfg.agent.autonomy}).")
    if getattr(args, "discord", False):
        discord_chat = _make_discord_chat(arius, event)
        if discord_chat:
            discord_chat.start()

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
        if line.startswith("/agent"):
            parts = line.split(maxsplit=2)
            sub = parts[1].lower() if len(parts) > 1 else "status"
            if sub in ("on", "off", "autonomy") and not arius.session.can("agent.manage"):
                print("에이전트 설정 변경에는 'agent.manage' 권한(관리자 이상)이 필요합니다.")
                continue
            if sub == "run":
                if not arius.session.can("agent.run"):
                    print("'agent.run' 권한이 필요합니다.")
                    continue
                goal = parts[2] if len(parts) > 2 else ""
                if goal:
                    result = arius.run_agent(arius.session, goal)
                    _print_reply(cfg.assistant_name, result.final + ("\n\n" + result.transcript() if result.steps else ""))
                else:
                    hb = heartbeat or _make_heartbeat(arius, event, session=arius.session)
                    _print_reply(cfg.assistant_name, hb.run_once())
            elif sub == "on":
                if heartbeat is None:
                    heartbeat = _make_heartbeat(arius, event)
                heartbeat.start()
                print(f"하트비트 시작 (매 {cfg.agent.interval_minutes}분).")
            elif sub == "off":
                if heartbeat:
                    heartbeat.stop()
                print("하트비트 중지.")
            elif sub == "log":
                rows = arius.memory.agent_log(15)
                print("\n".join(f"  {_ts(r['ts'])} [{r['kind']}] {r['summary']}" for r in rows) or "  (기록 없음)")
            elif sub == "autonomy":
                level = parts[2].strip().lower() if len(parts) > 2 else ""
                if level not in AUTONOMY_LEVELS:
                    print(f"사용법: /agent autonomy {'|'.join(AUTONOMY_LEVELS)}")
                else:
                    cfg.agent.autonomy = level
                    print(f"자율 수준을 '{level}' 로 바꿨습니다 (이 세션에만 적용; 영구 적용은 config.json).")
            else:
                running = heartbeat.running if heartbeat else False
                print(f"에이전트: 자율 수준 {cfg.agent.autonomy}, 하트비트 {'실행 중' if running else '중지'}, "
                      f"정책 {len(arius.memory.list_policies(enabled_only=True))}개, 자동 허용 도구: {', '.join(cfg.agent.auto_allow) or '없음'}")
            continue
        if line.startswith("/discord"):
            sub = line.split(maxsplit=1)[1].strip().lower() if " " in line else "status"
            if not arius.session.can("agent.manage"):
                print("디스코드 대화 모드 제어에는 'agent.manage' 권한이 필요합니다.")
                continue
            if sub == "on":
                if discord_chat is None:
                    discord_chat = _make_discord_chat(arius, event)
                if discord_chat:
                    discord_chat.start()
                    print("디스코드 대화 모드 시작.")
            elif sub == "off":
                if discord_chat:
                    discord_chat.stop()
                print("디스코드 대화 모드 중지.")
            else:
                print(f"디스코드 대화 모드: {'실행 중' if discord_chat and discord_chat.running else '중지'}")
            continue
        if line == "/wake":
            _wake_conversation(arius, voice, event)
            continue
        if line == "/commands":
            print(HELP_COMMANDS)
            continue

        reply = arius.handle(line)
        _print_reply(cfg.assistant_name, reply.text)
        voice.say(reply.text)

    if heartbeat:
        heartbeat.stop()
    if discord_chat:
        discord_chat.stop()
    arius.close()
    return 0


def _ts(ts: float) -> str:
    import time as _t
    return _t.strftime("%m-%d %H:%M", _t.localtime(ts))


def _log_line(cfg: AriusConfig, line: str) -> None:
    """Append to ~/.arius/agent.log (kept under ~5MB) so hidden/background runs leave a trace."""
    try:
        path = cfg.resolved_data_dir / "agent.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 5_000_000:
            path.write_text("", encoding="utf-8")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def cmd_agent(args: argparse.Namespace) -> int:
    """Always-on daemon: heartbeat (+ Discord conversation, + wake-word voice) until Ctrl+C."""
    import time as _t

    arius = Arius.from_path(args.config)
    cfg = arius.config
    if len(cfg.users) == 1 and not cfg.users[0].passphrase_hash:
        try:
            arius.login(cfg.users[0].username)
        except AuthenticationError:
            pass

    def event(msg: str) -> None:
        line = f"[{_t.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        try:
            print(line, flush=True)
        except Exception:
            pass  # pythonw has no console
        _log_line(cfg, line)

    if cfg.agent.autonomy != "autonomous":
        event(f"주의: 자율 수준이 '{cfg.agent.autonomy}' 입니다. 데몬에는 승인해 줄 사람이 없어 "
              "auto_allow 에 없는 변경 조치는 모두 거부됩니다. config.json 의 agent.autonomy 를 'autonomous' 로 두십시오.")
    hb = _make_heartbeat(arius, event)
    hb.start()
    event(f"{cfg.assistant_name} 에이전트 데몬 시작 — 매 {cfg.agent.interval_minutes}분 점검, 백엔드 {arius.backend.name}, 서버 '{cfg.minecraft.name}'.")
    chat = _make_discord_chat(arius, event) if (args.discord or cfg.discord.chat_channels) else None
    if chat:
        chat.start()
    try:
        if getattr(args, "listen", False):
            voice = _Voice(cfg)
            voice.stt = SpeechToText(cfg.voice.language)
            if voice.stt.available:
                event("음성 대기 모드: 이름을 부르면 대답합니다.")
                _wake_conversation(arius, voice, event)  # blocks until Ctrl+C or mic failure
                event("음성 대기 종료 — 하트비트/디스코드는 계속 동작합니다.")
            else:
                event(f"음성 대기 불가: {voice.stt.reason} (setup-voice 로 설치하십시오). 텍스트 없이 감시만 계속합니다.")
        while True:
            _t.sleep(1)
    except KeyboardInterrupt:
        event("종료합니다.")
    finally:
        hb.stop()
        if chat:
            chat.stop()
        arius.close()
    return 0


def cmd_listen(args: argparse.Namespace) -> int:
    """Voice conversation mode: call the assistant by name, talk, repeat."""
    arius = Arius.from_path(args.config)
    cfg = arius.config
    if len(cfg.users) == 1 and not cfg.users[0].passphrase_hash:
        try:
            arius.login(cfg.users[0].username)
        except AuthenticationError:
            pass
    voice = _Voice(cfg)

    def event(msg: str) -> None:
        print(f"[{cfg.assistant_name}] {msg}", flush=True)

    arius.notify = event
    print(BANNER)
    print(f"음성 대화 모드 — 현재 사용자: {arius.current_user_label}")
    _wake_conversation(arius, voice, event)
    arius.close()
    return 0


def cmd_autostart(args: argparse.Namespace) -> int:
    """Register/remove ARIUS in the OS login autostart."""
    from arius.autostart import DEFAULT_ARGS, Autostart

    project_dir = Path(__file__).resolve().parent.parent
    auto = Autostart(project_dir)
    if args.action == "enable":
        run_args = [a for a in DEFAULT_ARGS if not ((args.no_discord and a == "--discord") or (args.no_listen and a == "--listen"))]
        print(auto.enable(run_args, hidden=args.hidden))
        print(f"실행 내용: main.py {' '.join(run_args)}  (해제: python main.py autostart disable)")
    elif args.action == "disable":
        print(auto.disable())
    else:
        print(auto.status())
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    """Install/diagnose optional features: `setup voice`, `setup check`."""
    from arius.setup import check_voice, install_voice

    what = (args.what or "check").lower()
    if what == "voice":
        print("음성 기능(마이크 인식 + 음성 출력) 라이브러리를 설치합니다. 1~3분 걸릴 수 있습니다…\n")
        rep = install_voice()
    elif what == "check":
        rep = check_voice()
    else:
        print("사용법: python main.py setup voice | check")
        return 2
    print(rep.render())
    print()
    if rep.ok:
        print("음성 준비 완료! `python main.py listen` (Windows: run.bat listen) 으로 이름을 부르면 대답합니다.")
    else:
        print("일부 항목이 실패했습니다. 위의 ❌ 안내대로 조치한 뒤 `python main.py setup check` 로 다시 확인하십시오.")
        print("(음성 인식 없이도 텍스트 대화·에이전트·서버 관리는 모두 동작합니다.)")
    return 0 if rep.ok else 1


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

    print("\n추론 백엔드를 고르십시오:")
    print("  1) 오프라인      - 설치 없음, 규칙 기반 응답 (기본)")
    print("  2) Anthropic     - 클라우드 Claude, API 키 필요, 최상급 추론")
    print("  3) 로컬 모델     - Ollama, 무료·완전 오프라인, Ollama 설치 필요")
    try:
        choice = input("선택 [1]: ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        choice = "1"
    ollama_model = ""
    if choice == "3":
        try:
            ollama_model = input("Ollama 모델 이름 [llama3.1] (한국어 강함: exaone3.5, qwen2.5): ").strip() or "llama3.1"
        except (EOFError, KeyboardInterrupt):
            ollama_model = "llama3.1"
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
    if choice == "2":
        config.llm.backend = "anthropic"
    elif choice == "3":
        config.llm.backend = "ollama"
        config.llm.model = ollama_model
    config.voice.enabled = use_voice

    path.write_text(json.dumps(config_to_dict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n설정을 저장했습니다: {path}")
    if choice == "2":
        print("환경 변수 ANTHROPIC_API_KEY 에 API 키를 설정한 뒤 `pip install anthropic` 하십시오.")
    elif choice == "3":
        print(f"Ollama 설치(https://ollama.com) 후 터미널에서 `ollama pull {ollama_model}` 을 실행하십시오.")
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
    run_p.add_argument("--agent", action="store_true", help="자율 에이전트 하트비트를 함께 시작")
    run_p.add_argument("--discord", action="store_true", help="디스코드 대화 모드를 함께 시작")
    run_p.set_defaults(func=cmd_run)

    agent_p = sub.add_parser("agent", help="상시 데몬 (하트비트 + 디스코드 대화 + 음성 대기)")
    agent_p.add_argument("--discord", action="store_true", help="디스코드 대화 모드도 실행")
    agent_p.add_argument("--listen", action="store_true", help="이름을 부르면 대답하는 음성 대기도 실행")
    agent_p.set_defaults(func=cmd_agent)

    auto_p = sub.add_parser("autostart", help="컴퓨터 켤 때 자동 시작: enable | disable | status")
    auto_p.add_argument("action", nargs="?", default="status", choices=["enable", "disable", "status"])
    auto_p.add_argument("--hidden", action="store_true", help="Windows: 창 없이 백그라운드로 (pythonw)")
    auto_p.add_argument("--no-discord", action="store_true", help="디스코드 대화 모드 제외")
    auto_p.add_argument("--no-listen", action="store_true", help="음성 대기 제외")
    auto_p.set_defaults(func=cmd_autostart)

    listen_p = sub.add_parser("listen", help="이름을 부르면 대답하는 음성 대화 모드")
    listen_p.set_defaults(func=cmd_listen)

    setup_p = sub.add_parser("setup", help="선택 기능 설치/진단: setup voice | check")
    setup_p.add_argument("what", nargs="?", default="check", help="voice (설치) | check (진단)")
    setup_p.set_defaults(func=cmd_setup)

    init_p = sub.add_parser("init", help="config 생성 및 오너 계정 설정")
    init_p.add_argument("--force", action="store_true", help="기존 config 덮어쓰기")
    init_p.set_defaults(func=cmd_init)

    return parser


def _ensure_utf8() -> None:
    """Korean in/out on Windows consoles needs UTF-8 streams (run.bat sets chcp 65001 too)."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
            if stream is not None and hasattr(stream, "reconfigure") and enc != "utf8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        # default to `run`
        args.func = cmd_run
        args.no_autologin = False
        args.voice = False
        args.listen = False
        args.agent = False
        args.discord = False
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
