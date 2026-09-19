"""Command-line interface for ARIUS.

`python -m arius` (or `python main.py`) starts an interactive REPL. Slash
commands handle sessions; everything else goes to the assistant.

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

from arius.config import AriusConfig, UserConfig, config_to_dict, load_config
from arius.core import Arius
from arius.permissions import AuthenticationError, Role, hash_passphrase

BANNER = r"""
   _   ___ ___ _   _ ___
  /_\ | _ \_ _| | | / __|   Adaptive Responsive Intelligent User System
 / _ \|   /| || |_| \__ \   로컬 개인 AI 비서
/_/ \_\_|_\___|\___/|___/
"""


def _print_reply(assistant_name: str, reply_text: str) -> None:
    print(f"\n{assistant_name} › {reply_text}\n")


def cmd_run(args: argparse.Namespace) -> int:
    arius = Arius.from_path(args.config)
    cfg = arius.config

    # Auto-login the single owner if there is exactly one user and it needs no
    # passphrase — convenient for a personal machine.
    if not args.no_autologin and len(cfg.users) == 1 and not cfg.users[0].passphrase_hash:
        try:
            arius.login(cfg.users[0].username)
        except AuthenticationError:
            pass

    print(BANNER)
    print(f"{cfg.assistant_name} 준비 완료. 백엔드: {arius.backend.name}. "
          f"현재 사용자: {arius.current_user_label}.")
    print("도움말은 '/help', 종료는 '/quit'. 로그인은 '/login <아이디>'.\n")

    while True:
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
        if line in ("/logout",):
            arius.logout()
            print(f"로그아웃했습니다. 현재 사용자: {arius.current_user_label}.")
            continue
        reply = arius.handle(line)
        _print_reply(cfg.assistant_name, reply.text)

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

    path.write_text(json.dumps(config_to_dict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n설정을 저장했습니다: {path}")
    if use_anthropic:
        print("환경 변수 ANTHROPIC_API_KEY 에 API 키를 설정한 뒤 `pip install anthropic` 하십시오.")
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
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
