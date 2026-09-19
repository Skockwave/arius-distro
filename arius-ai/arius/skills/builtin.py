"""Built-in skills shipped with ARIUS.

They demonstrate the full range of the permission model, from a guest-safe
help listing to owner-only command execution. Add your own by subclassing
``Skill`` and registering it (see README > "새 스킬 추가하기").
"""

from __future__ import annotations

import datetime as dt
import os
import platform
import re
import shlex
import subprocess

from arius import permissions as perm
from arius import web
from arius.memory import Project
from arius.permissions import Role, User, hash_passphrase
from arius.skills import Skill, SkillContext


def _startswith_any(text: str, prefixes: tuple[str, ...]) -> bool:
    low = text.strip().lower()
    return any(low.startswith(p) for p in prefixes)


class HelpSkill(Skill):
    name = "help"
    description = "사용 가능한 기능과 명령을 안내합니다."
    capability = perm.CAP_CHAT
    priority = 10

    def matches(self, text: str) -> bool:
        return _startswith_any(text, ("/help", "도움말", "명령어", "도움", "help"))

    def run(self, ctx: SkillContext, text: str) -> str:
        skills = ctx.registry.available_for(ctx.session)
        lines = [
            f"[{ctx.config.assistant_name}] 현재 등급({ctx.session.role.label})에서 사용 가능한 기능:",
        ]
        for s in skills:
            lines.append(f"  • {s.name} — {s.description}")
        lines.append("")
        lines.append("그 외의 말은 자유 대화로 처리됩니다. 로그인: '/login <아이디>'.")
        return "\n".join(lines)


class WhoAmISkill(Skill):
    name = "whoami"
    description = "현재 로그인한 사용자와 권한을 보여줍니다."
    capability = perm.CAP_CHAT
    priority = 11

    def matches(self, text: str) -> bool:
        return _startswith_any(text, ("/whoami", "내 권한", "나 누구", "whoami", "내 등급"))

    def run(self, ctx: SkillContext, text: str) -> str:
        u = ctx.session.user
        caps = sorted(ctx.session.capabilities)
        cap_str = "모든 권한(*)" if perm.WILDCARD in caps else ", ".join(caps)
        return (
            f"사용자: {u.display_name} (아이디 {u.username})\n"
            f"권한 등급: {u.role.label} ({u.role.name})\n"
            f"보유 권한: {cap_str}"
        )


class TimeSkill(Skill):
    name = "time"
    description = "현재 날짜와 시간을 알려줍니다."
    capability = perm.CAP_CHAT
    priority = 20

    def matches(self, text: str) -> bool:
        low = text.strip().lower()
        return any(k in low for k in ("몇 시", "지금 시간", "오늘 날짜", "today", "what time"))

    def run(self, ctx: SkillContext, text: str) -> str:
        now = dt.datetime.now()
        return now.strftime("현재 시각은 %Y-%m-%d %H:%M:%S 입니다.")


class SystemInfoSkill(Skill):
    name = "system-info"
    description = "운영체제/CPU 등 시스템 정보를 조회합니다. (권한: system.info)"
    capability = perm.CAP_SYSTEM_INFO
    priority = 30

    def matches(self, text: str) -> bool:
        low = text.strip().lower()
        return any(k in low for k in ("시스템 정보", "사양", "cpu", "os 정보", "system info", "spec"))

    def run(self, ctx: SkillContext, text: str) -> str:
        info = {
            "OS": f"{platform.system()} {platform.release()}",
            "머신": platform.machine(),
            "프로세서": platform.processor() or "unknown",
            "CPU 코어": os.cpu_count(),
            "Python": platform.python_version(),
        }
        lines = ["시스템 정보:"]
        lines += [f"  • {k}: {v}" for k, v in info.items()]
        return "\n".join(lines)


class LearnSkill(Skill):
    name = "learn"
    description = "정보를 기억하게 합니다. 예: '기억해: 내 생일은 3월 2일' (권한: memory.write)"
    capability = perm.CAP_MEMORY_WRITE
    priority = 40

    _pat = re.compile(r"^\s*(?:/learn|기억해|외워둬|메모)\s*[:：]?\s*(?P<body>.+)$", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        return bool(self._pat.match(text))

    def run(self, ctx: SkillContext, text: str) -> str:
        m = self._pat.match(text)
        assert m
        body = m.group("body").strip()
        key, value, found = _split_kv(body)
        if not found:
            key, value = _summarize_key(body), body
        ctx.memory.learn_fact(ctx.session.user.username, key, value)
        return f"기억했습니다. ('{key}' → '{value}')"


class RecallSkill(Skill):
    name = "recall"
    description = "기억한 정보를 떠올립니다. 예: '내 생일 기억나?' (권한: memory.read)"
    capability = perm.CAP_MEMORY_READ
    priority = 41

    _pat = re.compile(r"(기억나|기억하니|기억해\?|떠올려|/recall|뭐였|기억 중)", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        return bool(self._pat.search(text))

    def run(self, ctx: SkillContext, text: str) -> str:
        username = ctx.session.user.username
        query = re.sub(r"(기억나|기억하니|기억해|떠올려|/recall|뭐였|기억 중|\?)", " ", text)
        hits = ctx.memory.recall_facts(username, query)
        if not hits:
            all_facts = ctx.memory.list_facts(username)
            if not all_facts:
                return "아직 기억하고 있는 정보가 없습니다."
            return "관련된 기억을 찾지 못했습니다. 전체 목록은 '기억 목록'으로 확인하십시오."
        lines = ["기억하고 있는 내용입니다:"]
        lines += [f"  • {f.key}: {f.value}" for f in hits]
        return "\n".join(lines)


class ListFactsSkill(Skill):
    name = "facts"
    description = "기억한 모든 정보를 나열합니다. (권한: memory.read)"
    capability = perm.CAP_MEMORY_READ
    priority = 42

    def matches(self, text: str) -> bool:
        return _startswith_any(text, ("기억 목록", "/facts", "기억한 것", "메모 목록"))

    def run(self, ctx: SkillContext, text: str) -> str:
        facts = ctx.memory.list_facts(ctx.session.user.username)
        if not facts:
            return "저장된 기억이 없습니다."
        lines = ["저장된 기억 목록:"]
        lines += [f"  • {f.key}: {f.value}" for f in facts]
        return "\n".join(lines)


class ProjectSkill(Skill):
    name = "project"
    description = "프로젝트를 만들고 상태를 관리합니다. 예: '프로젝트 생성 슈트' (권한: project.manage)"
    capability = perm.CAP_PROJECT_MANAGE
    priority = 50

    _create = re.compile(r"(?:프로젝트\s*(?:생성|만들|추가)|/project\s+new)\s+(?P<name>.+)", re.IGNORECASE)
    _list = re.compile(r"(?:프로젝트\s*(?:목록|리스트)|/project\s+list|/projects)", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        return bool(self._create.search(text) or self._list.search(text))

    def run(self, ctx: SkillContext, text: str) -> str:
        if self._list.search(text):
            projects = ctx.memory.list_projects()
            if not projects:
                return "등록된 프로젝트가 없습니다."
            lines = ["프로젝트 목록:"]
            lines += [f"  • {p.name} [{p.status}] (소유자: {p.owner})" for p in projects]
            return "\n".join(lines)
        m = self._create.search(text)
        assert m
        name = m.group("name").strip().strip("'\"")
        existing = ctx.memory.get_project(name)
        if existing:
            return f"이미 존재하는 프로젝트입니다: '{name}' (상태: {existing.status})."
        ctx.memory.upsert_project(
            Project(name=name, owner=ctx.session.user.username, status="active")
        )
        return (
            f"'{name}' 프로젝트를 생성했습니다. 소유자는 {ctx.session.user.display_name}"
            f"{ctx.config.persona.honorific}입니다. 진행 상황을 이 프로젝트에 기록해 두겠습니다."
        )


class UserAdminSkill(Skill):
    name = "user-admin"
    description = "사용자를 추가하거나 권한을 변경합니다. (권한: user.manage / 오너)"
    capability = perm.CAP_USER_MANAGE
    priority = 60

    _add = re.compile(r"(?:사용자\s*추가|/adduser)\s+(?P<name>\S+)(?:\s+(?P<role>\S+))?", re.IGNORECASE)
    _role = re.compile(r"(?:권한\s*변경|/setrole)\s+(?P<name>\S+)\s+(?P<role>\S+)", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        return bool(self._add.search(text) or self._role.search(text))

    def run(self, ctx: SkillContext, text: str) -> str:
        m = self._add.search(text)
        if m:
            username = m.group("name")
            role = Role.parse(m.group("role") or "user")
            try:
                ctx.permissions.add_user(User(username=username, role=role))
            except ValueError as exc:
                return str(exc)
            return f"사용자 '{username}'을(를) {role.label} 등급으로 추가했습니다."
        m = self._role.search(text)
        assert m
        try:
            role = Role.parse(m.group("role"))
            ctx.permissions.set_role(m.group("name"), role)
        except ValueError as exc:
            return str(exc)
        return f"'{m.group('name')}'의 권한을 {role.label}(으)로 변경했습니다."


class WebLearnSkill(Skill):
    """Fetch a web page and store its readable text as learned knowledge.

    A *bounded reader*, not a whole-internet crawler: it learns the page(s)
    you point it at. Say '크롬' in the request to render with Chromium.
    """

    name = "web-learn"
    description = "웹 페이지(URL)를 읽어 학습합니다. 예: '학습해: https://...' (권한: web.learn)"
    capability = perm.CAP_WEB_LEARN
    priority = 45

    _pat = re.compile(r"^\s*(?:/weblearn|학습해|웹\s*학습|인터넷\s*학습|크롬으로?\s*학습해?)\s*[:：]?\s*(?P<body>.+)$", re.IGNORECASE)

    def __init__(self, fetcher=None) -> None:
        # fetcher(url, backend) -> WebPage; injectable for tests.
        self._fetch = fetcher or (lambda url, backend: web.fetch(url, backend=backend))

    def matches(self, text: str) -> bool:
        return bool(self._pat.match(text))

    def run(self, ctx: SkillContext, text: str) -> str:
        m = self._pat.match(text)
        assert m
        body = m.group("body").strip()
        url = web.extract_first_url(body)
        if not url:
            return (
                "학습할 웹 주소(URL)를 함께 알려주십시오. 예: '학습해: https://example.com'.\n"
                "(참고: '인터넷의 모든 것'을 한 번에 학습할 수는 없습니다. 원하는 페이지나 주제의 "
                "링크를 주시면 그 내용을 읽어 기억하겠습니다.)"
            )
        backend = "chrome" if re.search(r"크롬|chrome", text, re.IGNORECASE) else "urllib"
        try:
            page = self._fetch(url, backend)
        except Exception as exc:
            return f"'{url}' 학습에 실패했습니다: {exc}"
        if not page.text.strip():
            return f"'{page.title}'({url})에서 읽을 수 있는 본문을 찾지 못했습니다."
        ctx.memory.add_knowledge(ctx.session.user.username, page.url, page.title, page.text)
        return (
            f"학습 완료: '{page.title}'\n"
            f"  • 출처: {url}\n"
            f"  • 분량: 약 {page.length:,}자 (백엔드: {backend})\n"
            f"  • 요약: {page.summary()}\n"
            "이제 '웹에서 …찾아줘' 또는 '…배운 것 있어?'로 회상할 수 있습니다."
        )


class WebRecallSkill(Skill):
    name = "web-recall"
    description = "학습한 웹 내용을 검색/회상합니다. 예: '웹에서 포지 설치 찾아줘' (권한: web.read)"
    capability = perm.CAP_WEB_READ
    priority = 46

    _pat = re.compile(r"(웹에서|웹\s*검색|인터넷에서|배운\s*것|학습한\s*내용|/websearch|/webrecall)", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        return bool(self._pat.search(text))

    def run(self, ctx: SkillContext, text: str) -> str:
        username = ctx.session.user.username
        query = self._pat.sub(" ", text)
        query = re.sub(r"(찾아줘|알려줘|있어\??|뭐였|검색해줘|해줘)", " ", query).strip()
        hits = ctx.memory.search_knowledge(username, query or text)
        if not hits:
            total = len(ctx.memory.list_knowledge(username))
            if total == 0:
                return "아직 웹에서 학습한 내용이 없습니다. '학습해: <URL>'로 먼저 학습시켜 주십시오."
            return "학습한 내용 중 관련된 것을 찾지 못했습니다. 다른 키워드로 시도해 보십시오."
        lines = ["학습한 웹 내용에서 찾았습니다:"]
        for k in hits:
            lines.append(f"  • {k.title} — {k.snippet()}\n    ({k.url})")
        return "\n".join(lines)


class ExecSkill(Skill):
    """Run a shell command. Highest-privilege skill; gated by system.exec."""

    name = "exec"
    description = "셸 명령을 실행합니다. 위험하므로 오너/관리자만 사용. (권한: system.exec)"
    capability = perm.CAP_SYSTEM_EXEC
    priority = 70

    _pat = re.compile(r"^\s*(?:/exec|명령\s*실행|실행해)\s*[:：]?\s*(?P<cmd>.+)$", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        return bool(self._pat.match(text))

    def run(self, ctx: SkillContext, text: str) -> str:
        m = self._pat.match(text)
        assert m
        cmd = m.group("cmd").strip()
        if not cmd:
            return "실행할 명령이 비어 있습니다."
        # Windows: go through cmd.exe so builtins like `dir`/`echo` work and paths
        # keep their backslashes. POSIX: argv list, no shell.
        if os.name == "nt":
            run_args: list[str] | str = cmd
            use_shell = True
        else:
            try:
                run_args = shlex.split(cmd)
            except ValueError as exc:
                return f"명령을 해석할 수 없습니다: {exc}"
            if not run_args:
                return "실행할 명령이 비어 있습니다."
            use_shell = False
        try:
            proc = subprocess.run(
                run_args,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=20,
                shell=use_shell,
            )
        except FileNotFoundError:
            return f"명령을 찾을 수 없습니다: {cmd.split()[0]}"
        except subprocess.TimeoutExpired:
            return "명령이 20초 제한을 초과하여 중단했습니다."
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        parts = [f"실행: {cmd}", f"종료 코드: {proc.returncode}"]
        if out:
            parts.append("표준 출력:\n" + _truncate(out))
        if err:
            parts.append("표준 오류:\n" + _truncate(err))
        return "\n".join(parts)


# --- helpers ----------------------------------------------------------------


def _split_kv(body: str) -> tuple[str, str, bool]:
    for sep in ("는 ", "은 ", "=", ":", "→"):
        if sep in body:
            key, _, value = body.partition(sep)
            return key.strip(), value.strip(), True
    return body, "", False


def _summarize_key(body: str) -> str:
    words = body.split()
    return " ".join(words[:4]) if words else body[:16]


def _truncate(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…(생략됨)"


def default_skills() -> list[Skill]:
    """The standard skill set registered by the assistant."""
    return [
        HelpSkill(),
        WhoAmISkill(),
        TimeSkill(),
        SystemInfoSkill(),
        LearnSkill(),
        RecallSkill(),
        ListFactsSkill(),
        WebLearnSkill(),
        WebRecallSkill(),
        ProjectSkill(),
        UserAdminSkill(),
        ExecSkill(),
    ]
