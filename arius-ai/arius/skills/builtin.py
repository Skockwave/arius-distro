"""Built-in skills shipped with ARIUS.

They demonstrate the full range of the permission model, from a guest-safe
help listing to owner-only command execution. Add your own by subclassing
``Skill`` and registering it (see README > "새 스킬 추가하기").

Reply conventions follow the operating rules: "실행하겠습니다: …" before a
safe action, "실행 예정 / 영향 / 진행할까요?" before a confirmed one,
"완료했습니다. …" afterwards and "실행하지 않았습니다. 이유 / 다음 조치" on
refusal.
"""

from __future__ import annotations

import datetime as dt
import os
import platform
import re
import shlex
import subprocess
import time

from arius import permissions as perm
from arius import web
from arius.memory import Project
from arius.modes import MODES, get_mode, parse_mode
from arius.permissions import Role, User, hash_passphrase
from arius.privacy import looks_secret, refuse_secret_message
from arius.skills import Skill, SkillContext


def _startswith_any(text: str, prefixes: tuple[str, ...]) -> bool:
    low = text.strip().lower()
    return any(low.startswith(p) for p in prefixes)


def not_done(reason: str, next_step: str) -> str:
    return f"실행하지 않았습니다.\n이유: {reason}\n다음 조치: {next_step}"


def _tool(ctx: SkillContext, name: str, args: dict | None = None) -> str:
    """Run one agent tool directly (a human typed the command, so no autonomy gate —
    RBAC was already checked by the skill's capability)."""
    from arius.agent.tools import Refused, build_registry

    if ctx.tools is None:
        return "도구 컨텍스트가 없습니다."
    tool = build_registry().get(name)
    if tool is None:
        return f"알 수 없는 도구: {name}"
    try:
        return tool.handler(ctx.tools, args or {})
    except Refused as exc:
        return not_done(str(exc), "허용 목록·설정을 확인하거나 오너에게 요청해 주세요.")


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
        if ctx.tools is not None:
            lines.append("")
            lines.append(_tool(ctx, "system_status"))
        return "\n".join(lines)


# --- memory ---------------------------------------------------------------------


class LearnSkill(Skill):
    name = "learn"
    description = "정보를 기억하게 합니다. 예: '기억해: 내 생일은 3월 2일', '이것을 기억해: …' (권한: memory.write)"
    capability = perm.CAP_MEMORY_WRITE
    priority = 40

    _pat = re.compile(
        r"^\s*(?:/learn|이것을?\s*기억해|이거\s*기억해|기억해\s*줘|기억해|외워둬|메모)\s*[:：]?\s*(?P<body>.+)$",
        re.IGNORECASE | re.DOTALL,
    )

    def matches(self, text: str) -> bool:
        return bool(self._pat.match(text))

    def run(self, ctx: SkillContext, text: str) -> str:
        m = self._pat.match(text)
        assert m
        body = m.group("body").strip()
        if looks_secret(body):
            return refuse_secret_message()
        key, value, found = _split_kv(body)
        if not found:
            key, value = _summarize_key(body), body
        ctx.memory.learn_fact(ctx.session.user.username, key, value, source="user", confidence=1.0)
        return (
            "기억했습니다.\n"
            f"- 새로 기억한 내용: {key} → {value}\n"
            f"- 근거 및 신뢰도: {ctx.session.user.display_name}{ctx.config.persona.honorific}이 직접 알려줌 (100%, {dt.date.today()})\n"
            "- 앞으로 달라지는 동작: 관련 대화와 작업에서 이 정보를 참고합니다.\n"
            "- 사용자에게 필요한 승인: 없음\n"
            f"- 삭제 또는 수정 방법: '기억 삭제: {key}' / 다시 '기억해: {key}: 새 내용'"
        )


class ForgetSkill(Skill):
    name = "forget"
    description = "기억을 지웁니다. 예: '기억 삭제: 생일', '내 정보를 모두 잊어' (권한: memory.write)"
    capability = perm.CAP_MEMORY_WRITE
    priority = 38

    _all = re.compile(r"^\s*(?:내\s*정보(?:를)?\s*(?:모두|전부|다)\s*(?:잊어|지워|삭제)|/forgetall|모든\s*기억\s*(?:삭제|지워))", re.IGNORECASE)
    _all_yes = re.compile(r"^\s*(?:네|응|예|그래|확인)?[,\s]*(?:모두|전부|다)\s*(?:잊어|지워|삭제해?)(?:\s*줘)?\s*[.!]*$", re.IGNORECASE)
    _one = re.compile(
        r"^\s*(?:/forget|기억\s*(?:삭제|제거|지워)|이\s*기억(?:을)?\s*(?:삭제|지워)(?:해)?)\s*[:：]?\s*(?P<key>.*)$", re.IGNORECASE
    )
    _one_tail = re.compile(r"^\s*(?P<key>.+?)\s*(?:은|는|을|를)?\s*(?:기억\s*)?(?:잊어|지워|삭제해)\s*(?:줘|주세요)?\s*[.!]*$", re.IGNORECASE)
    _pending: dict[str, float] = {}
    PENDING_SECONDS = 120

    def matches(self, text: str) -> bool:
        t = text.strip()
        if self._all.match(t) or self._one.match(t) or self._all_yes.match(t):
            return True
        return bool(self._one_tail.match(t)) and "기억" in t

    def run(self, ctx: SkillContext, text: str) -> str:
        t = text.strip()
        user = ctx.session.user.username
        if self._all.match(t):
            self._pending[user] = time.monotonic()
            n = len(ctx.memory.list_facts(user))
            return (
                f"실행 예정: {ctx.session.user.display_name}{ctx.config.persona.honorific}에 대한 기억 {n}개, 학습한 웹 내용, 대화 기록을 모두 삭제\n"
                "영향: 되돌릴 수 없습니다. 호칭·선호·서버 운영 메모까지 전부 사라집니다.\n"
                "진행할까요? ('네, 모두 잊어' 라고 말씀해 주세요. 2분 안에 답이 없으면 취소됩니다.)"
            )
        if self._all_yes.match(t):
            started = self._pending.pop(user, None)
            if started is None or time.monotonic() - started > self.PENDING_SECONDS:
                return not_done("삭제 요청이 없거나 만료되었습니다.", "'내 정보를 모두 잊어' 라고 먼저 말씀해 주세요.")
            counts = ctx.memory.forget_all(user)
            return f"완료했습니다. 기억 {counts['facts']}개, 웹 학습 {counts['knowledge']}개, 대화 기록 {counts['messages']}개를 지웠습니다."
        m = self._one.match(t) or self._one_tail.match(t)
        assert m
        key = (m.group("key") or "").strip().strip("'\"")
        if key in ("", "이", "그", "이것", "그것", "방금", "마지막", "이거", "그거", "방금 거", "방금 것"):
            facts = sorted(ctx.memory.list_facts(user), key=lambda f: -f.ts)
            if not facts:
                return not_done("지울 기억이 없습니다.", "'기억 목록' 으로 확인해 주세요.")
            key = facts[0].key
        if ctx.memory.forget_fact(user, key):
            return f"완료했습니다. '{key}' 기억을 지웠습니다."
        hits = ctx.memory.recall_facts(user, key, limit=3)
        if hits:
            return not_done(f"'{key}' 라는 기억이 정확히 없습니다.", "비슷한 항목: " + ", ".join(f"'{h.key}'" for h in hits) + " — 정확한 이름으로 다시 말씀해 주세요.")
        return not_done(f"'{key}' 라는 기억이 없습니다.", "'기억 목록' 으로 이름을 확인해 주세요.")


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
        lines += [f"  • {f.key}: {f.value}  ({f.meta()})" for f in hits]
        return "\n".join(lines)


class ListFactsSkill(Skill):
    name = "facts"
    description = "기억한 모든 정보를 나열합니다. 예: '기억 목록', '네가 기억하는 내용을 보여줘' (권한: memory.read)"
    capability = perm.CAP_MEMORY_READ
    priority = 39

    _pat = re.compile(r"(^\s*(?:기억\s*목록|/facts|기억한\s*것|메모\s*목록)|기억하는\s*(?:내용|것|거)|기억하고\s*있는\s*(?:내용|것|거))", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        return bool(self._pat.search(text))

    def run(self, ctx: SkillContext, text: str) -> str:
        facts = ctx.memory.list_facts(ctx.session.user.username)
        if not facts:
            return "저장된 기억이 없습니다."
        lines = [f"저장된 기억 {len(facts)}개 (저장일 · 출처 · 신뢰도 · 마지막 확인):"]
        lines += [f"  • {f.key}: {f.value}\n      {f.meta()}" for f in facts]
        lines.append("지우려면 '기억 삭제: <항목>', 전부 지우려면 '내 정보를 모두 잊어'.")
        return "\n".join(lines)


# --- projects & users --------------------------------------------------------------


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


# --- web learning -----------------------------------------------------------------


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


# --- inspection (점검) ----------------------------------------------------------------


def inspect_server(ctx: SkillContext) -> str:
    """The seven-step server check from the operating rules, with a priority summary."""
    from arius import minecraft as mc

    tc = ctx.tools
    if tc is None:
        return "도구 컨텍스트가 없습니다."
    name = ctx.config.minecraft.name
    a = ctx.config.agent
    host, port = tc.mc_host()
    status = tc.pinger(host, port)
    snap = tc.snapshot_fn()
    lines: list[str] = [f"[{name} 점검]"]
    red: list[str] = []
    yellow: list[str] = []

    # 1. online
    if status.online:
        lines.append(f"1. 서버 온라인 상태: 🟢 온라인 ({status.version or '?'}, 응답 {status.latency_ms:.0f}ms)")
    else:
        lines.append(f"1. 서버 온라인 상태: 🔴 오프라인 — {status.error or '응답 없음'}")
        red.append("서버가 꺼져 있습니다 → '서버 시작' 으로 켤 수 있습니다.")
    # 2. players
    players = f"{status.players_online}/{status.players_max}" + (f" ({', '.join(status.player_names)})" if status.player_names else "")
    lines.append(f"2. 접속자 수: {players if status.online else '—'}")
    # 3. TPS
    tps_line = "RCON 미설정 — 'RCON 설정: <암호>' 후 확인 가능"
    if status.online:
        from arius.agent.tools import Refused

        try:
            with tc.rcon() as r:
                raw = r.command("tps")
            clean = re.sub(r"§.", "", raw)
            tail = clean.rsplit(":", 1)[-1] if ":" in clean else clean
            nums = re.findall(r"(\d+(?:\.\d+)?)", tail)
            if nums:
                tps = float(nums[0])
                mark = "🟢" if tps >= 18 else ("🟡" if tps >= 15 else "🔴")
                tps_line = f"{mark} {tps:.1f} TPS (1분)"
                if tps < 15:
                    red.append(f"TPS {tps:.1f} — 심한 렉. 플러그인/엔티티 확인 권장")
                elif tps < 18:
                    yellow.append(f"TPS {tps:.1f} — 약간의 렉")
            else:
                tps_line = raw.strip()[:80] or "(출력 없음)"
        except Refused:
            pass  # no RCON password configured: keep the "RCON 미설정" hint above
        except Exception as exc:  # RconError: RCON on but unreachable / wrong password
            tps_line = "🟡 확인 불가 — " + str(exc).splitlines()[0][:90]
            yellow.append("TPS 확인 불가 — RCON 포트·암호와 서버 재시작 여부를 확인하세요")
    lines.append(f"3. TPS: {tps_line}")
    # 4. CPU / RAM
    cpu = snap.get("cpu", {})
    mem = snap.get("memory", {})
    load = cpu.get("load_pct")
    procs = tc.process_finder()
    jvm = f", 서버 JVM {procs[0].memory_mb:.0f}MB" if procs else ""
    cpu_mark = "🔴" if (load or 0) >= a.alert_cpu_pct else ("🟡" if (load or 0) >= 80 else "🟢")
    mem_mark = "🔴" if mem.get("used_pct", 0) >= a.alert_memory_pct else ("🟡" if mem.get("used_pct", 0) >= 80 else "🟢")
    lines.append(f"4. CPU/RAM: {cpu_mark} CPU {load if load is not None else '?'}% · {mem_mark} 메모리 {mem.get('used_pct', '?')}% ({mem.get('available_mb', '?')}MB 여유{jvm})")
    if mem.get("used_pct", 0) >= a.alert_memory_pct:
        red.append(f"메모리 {mem['used_pct']}% — 상위 프로세스 확인 필요")
    if load is not None and load >= a.alert_cpu_pct:
        red.append(f"CPU 부하 {load}%")
    # 5. disk
    disk_parts = []
    for d in snap.get("disks", []):
        mark = "🔴" if d["used_pct"] >= a.alert_disk_pct else ("🟡" if d["used_pct"] >= 80 else "🟢")
        disk_parts.append(f"{mark} {d['path']} {d['free_gb']}GB 여유 ({d['used_pct']}% 사용)")
        if d["used_pct"] >= a.alert_disk_pct:
            red.append(f"디스크 {d['path']} {d['used_pct']}% — 정리 필요 (다운로드/백업 폴더 정리 제안)")
    lines.append("5. 디스크 여유 공간: " + (" · ".join(disk_parts) or "?"))
    # 6. recent errors
    sd = tc.server_dir()
    if sd:
        errs = mc.tail_log(sd, 200, r"\bERROR\b|Exception")
        n = 0 if errs.startswith(("(", "로그")) else len(errs.splitlines())
        mark = "🔴" if n >= a.alert_log_errors else ("🟡" if n else "🟢")
        last = errs.splitlines()[-1][:110] if n else ""
        lines.append(f"6. 최근 오류 로그: {mark} 최근 200줄 중 {n}건" + (f"\n   마지막: {last}" if last else ""))
        if n >= a.alert_log_errors:
            red.append(f"오류 {n}건 반복 — '서버 로그 오류' 로 원인 확인")
        elif n:
            yellow.append(f"오류 {n}건")
    else:
        lines.append("6. 최근 오류 로그: 서버 폴더 미확인 (config minecraft.server_dir)")
        yellow.append("서버 폴더를 몰라 로그·백업 점검 불가")
    # 7. backup
    latest = tc.latest_backup()
    if latest is not None:
        age_h = (time.time() - latest.stat().st_mtime) / 3600
        mark = "🟢" if age_h <= a.alert_backup_hours else "🟡"
        lines.append(f"7. 최신 백업: {mark} {latest.name} ({age_h:.1f}시간 전, {latest.stat().st_size / 1e6:.1f}MB)")
        if age_h > a.alert_backup_hours:
            yellow.append(f"백업이 {age_h:.0f}시간 전 — '서버 백업' 권장")
    else:
        lines.append("7. 최신 백업: 🟡 없음")
        yellow.append("백업이 없습니다 — '서버 백업' 권장")

    lines.append("")
    if red:
        lines.append("🔴 즉시 조치: " + " / ".join(red))
    if yellow:
        lines.append("🟡 주의: " + " / ".join(yellow))
    if not red and not yellow:
        lines.append("🟢 이상 없음. 지금은 조치할 것이 없습니다.")
    return "\n".join(lines)


def inspect_pc(ctx: SkillContext) -> str:
    tc = ctx.tools
    if tc is None:
        return "도구 컨텍스트가 없습니다."
    from arius import sysinfo

    a = ctx.config.agent
    snap = tc.snapshot_fn()
    lines = ["[PC 점검]", sysinfo.describe(snap)]
    issues = []
    mem = snap.get("memory", {})
    if mem.get("used_pct", 0) >= a.alert_memory_pct:
        issues.append(f"🔴 메모리 {mem['used_pct']}% — 원인: 프로그램 과다 / 영향: 렉 / 조치: 상위 프로세스 확인 후 종료 여부 결정")
    load = (snap.get("cpu") or {}).get("load_pct")
    if load is not None and load >= a.alert_cpu_pct:
        issues.append(f"🔴 CPU {load}% — 원인: 무거운 작업 / 영향: 전체 지연 / 조치: 작업 관리자 확인")
    for d in snap.get("disks", []):
        if d["used_pct"] >= a.alert_disk_pct:
            issues.append(f"🔴 디스크 {d['path']} {d['used_pct']}% — 영향: 저장·업데이트 실패 / 조치: 다운로드·임시 파일 정리 제안(삭제는 확인 후)")
        elif d["used_pct"] >= 80:
            issues.append(f"🟡 디스크 {d['path']} {d['used_pct']}%")
    up = snap.get("uptime_hours")
    if up and up > 24 * 14:
        issues.append(f"🟡 재부팅한 지 {up / 24:.0f}일 — 업데이트 적용·메모리 정리를 위해 재부팅 권장(승인 필요)")
    lines.append("")
    lines += issues or ["🟢 이상 없음."]
    return "\n".join(lines)


class InspectSkill(Skill):
    name = "inspect"
    description = "점검: '서버 점검해' (온라인·접속자·TPS·CPU/RAM·디스크·오류 로그·백업), 'PC 점검', '전체 점검' (권한: system.info)"
    capability = perm.CAP_SYSTEM_INFO
    priority = 32

    _server = re.compile(r"^\s*(?:마인크래프트\s*|마크\s*)?서버\s*(?:를|을)?\s*(?:점검|진단|체크)", re.IGNORECASE)
    _pc = re.compile(r"^\s*(?:pc|컴퓨터|내\s*컴퓨터|시스템|컴)\s*(?:를|을)?\s*(?:점검|진단|상태\s*점검|체크)", re.IGNORECASE)
    _all = re.compile(r"^\s*(?:전체\s*점검|점검해(?:\s*줘)?|점검\s*시작|/inspect|점검)\s*[.!~]*$", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        t = text.strip()
        return any(rx.match(t) for rx in (self._server, self._pc, self._all))

    def run(self, ctx: SkillContext, text: str) -> str:
        t = text.strip()
        if self._server.match(t):
            return inspect_server(ctx)
        if self._pc.match(t):
            return inspect_pc(ctx)
        return inspect_pc(ctx) + "\n\n" + inspect_server(ctx)


# --- Minecraft ----------------------------------------------------------------------------


class MinecraftSkill(Skill):
    name = "minecraft"
    description = ("서버 상태/로그/접속자, TPS, 화이트리스트·OP·밴 목록, 백업, 콘솔 명령, 채팅 공지, 시작/중지/재시작(확인). "
                   "예: '서버 상태', '서버 로그 오류', '서버 백업', '서버 재시작' (권한: mc.read / mc.admin)")
    capability = perm.CAP_MC_READ
    priority = 33

    _status = re.compile(r"^(?:/mc\s*(?:status)?|서버\s*(?:상태|켜져|온라인|살아)|접속자|서버\s*정보)", re.IGNORECASE)
    _log = re.compile(r"^(?:/mc\s*log|서버\s*로그)\s*(?P<pat>.*)$", re.IGNORECASE)
    _tps = re.compile(r"^(?:tps|서버\s*tps|틱\s*확인|렉\s*확인)\s*$", re.IGNORECASE)
    _players = re.compile(r"^(?:(?:서버\s*)?(?P<which>화이트\s*리스트|화이트리스트|운영자\s*(?:목록|권한)|op\s*목록|오피\s*목록|밴\s*목록|차단\s*목록|ip\s*밴)\s*(?:보여줘|확인|조회)?)\s*$", re.IGNORECASE)
    _backup = re.compile(r"^(?:서버\s*|월드\s*)?백업\s*(?:해|해줘|해\s*줘|만들어|생성|실행)?\s*[.!]*$", re.IGNORECASE)
    _backup_status = re.compile(r"^(?:백업\s*(?:상태|확인|언제|있어)|최근\s*백업|최신\s*백업)", re.IGNORECASE)
    _cmd = re.compile(r"^(?:/rcon|서버\s*명령)\s*[:：]?\s*(?P<cmd>.+)$", re.IGNORECASE)
    _say = re.compile(r"^(?:서버\s*(?:공지|채팅|말해))\s*[:：]?\s*(?P<msg>.+)$", re.IGNORECASE)
    _start = re.compile(r"^(?:서버\s*(?:시작|켜|켜줘|켜 줘|기동))", re.IGNORECASE)
    _stop_confirm = re.compile(r"^(?:서버\s*(?:중지|정지|꺼|끄기|종료)\s*확인)", re.IGNORECASE)
    _restart_confirm = re.compile(r"^(?:서버\s*재시작\s*확인)", re.IGNORECASE)
    _stop_ask = re.compile(r"^(?:서버\s*(?:중지|정지|꺼줘|꺼|끄기|종료)(?:해|해줘|해\s*줘)?)\s*[.!]*$", re.IGNORECASE)
    _restart_ask = re.compile(r"^(?:서버\s*재시작(?:해|해줘|해\s*줘)?)\s*[.!]*$", re.IGNORECASE)
    _rcon_setup = re.compile(r"^(?:RCON\s*(?:설정|켜기|활성화))\s*[:：]?\s*(?P<pw>\S+)?", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        t = text.strip()
        return any(rx.match(t) for rx in (
            self._status, self._log, self._tps, self._players, self._backup, self._backup_status, self._cmd, self._say,
            self._start, self._stop_confirm, self._restart_confirm, self._stop_ask, self._restart_ask, self._rcon_setup,
        ))

    def run(self, ctx: SkillContext, text: str) -> str:
        t = text.strip()
        admin = ctx.session.can(perm.CAP_MC_ADMIN)
        need_admin = not_done("그 작업에는 'mc.admin' 권한이 필요합니다.", "관리자 이상 계정으로 로그인해 주세요.")
        if self._status.match(t):
            return _tool(ctx, "minecraft_status")
        m = self._log.match(t)
        if m:
            pat = m.group("pat").strip()
            pattern = {"오류": "WARN|ERROR", "에러": "ERROR", "경고": "WARN", "접속": "joined|left"}.get(pat, pat)
            return _tool(ctx, "minecraft_log", {"lines": 40, "pattern": pattern})
        m = self._players.match(t)
        if m:
            w = m.group("which").lower().replace(" ", "")
            which = "whitelist" if "화이트" in w else ("ops" if ("운영자" in w or "op" in w or "오피" in w) else ("ip_bans" if "ip" in w else "bans"))
            return _tool(ctx, "minecraft_players", {"which": which})
        if self._backup_status.match(t):
            return _tool(ctx, "minecraft_backup_status")
        if not admin:
            return need_admin
        if self._tps.match(t):
            return _tool(ctx, "minecraft_command", {"command": "tps"})
        if self._backup.match(t):
            return "실행하겠습니다: 월드 저장(save-all) 후 zip 백업\n" + _tool(ctx, "minecraft_backup")
        m = self._cmd.match(t)
        if m:
            cmd = m.group("cmd")
            if ctx.tools is not None and ctx.tools.rcon_needs_confirmation(cmd) and not cmd.strip().endswith("!"):
                return (
                    f"실행 예정: 콘솔 명령 '{cmd.strip()}'\n"
                    "영향: 플레이어 권한·접속 상태가 즉시 바뀝니다.\n"
                    f"진행할까요? (진행하려면 '서버 명령: {cmd.strip()} !' 처럼 끝에 ! 를 붙여 주세요)"
                )
            return _tool(ctx, "minecraft_command", {"command": cmd.rstrip("! ")})
        m = self._say.match(t)
        if m:
            return _tool(ctx, "minecraft_say", {"message": m.group("msg")})
        if self._start.match(t):
            return "실행하겠습니다: 서버 시작\n" + _tool(ctx, "minecraft_start", {"wait": False})
        if self._stop_confirm.match(t):
            return _tool(ctx, "minecraft_stop", {"warning": "관리자가 서버를 곧 중지합니다.", "delay": 5})
        if self._restart_confirm.match(t):
            return _tool(ctx, "minecraft_restart", {"wait": False})
        if self._stop_ask.match(t) or self._restart_ask.match(t):
            return self._ask(ctx, "재시작" if self._restart_ask.match(t) else "중지")
        m = self._rcon_setup.match(t)
        if m:
            return _tool(ctx, "minecraft_enable_rcon", {"password": m.group("pw") or ""})
        return "이해하지 못했습니다."

    def _ask(self, ctx: SkillContext, what: str) -> str:
        from arius.agent.tools import restart_precheck

        if ctx.tools is None:
            return "도구 컨텍스트가 없습니다."
        pre, info = restart_precheck(ctx.tools)
        if not info["online"]:
            return f"{ctx.config.minecraft.name} 는 이미 꺼져 있습니다." + (" '서버 시작' 으로 켤 수 있습니다." if what == "재시작" else "")
        impact = "접속자가 모두 끊기고 서버가 꺼집니다." if what == "중지" else "약 2~3분간 접속이 끊깁니다. 예고 공지를 먼저 보냅니다."
        return (
            f"실행 예정: {ctx.config.minecraft.name} {what}\n{pre}\n영향: {impact}\n"
            f"진행할까요? ('서버 {what} 확인' 이라고 말씀해 주세요)"
        )


# --- Discord ----------------------------------------------------------------------------------


class DiscordSkill(Skill):
    name = "discord"
    description = "디스코드(메테노디코) 공지 초안/전송, 최근 대화. 예: '공지 초안: 오늘 22시 점검', '공지 전송: ...' (권한: discord.announce)"
    capability = perm.CAP_DISCORD_ANNOUNCE
    priority = 34

    _draft = re.compile(r"^(?:공지\s*초안|디스코드\s*초안)\s*[:：]\s*(?P<body>.+)$", re.IGNORECASE | re.DOTALL)
    _send = re.compile(r"^(?:공지\s*전송|디스코드\s*공지|디스코드\s*전송)\s*[:：]\s*(?P<body>.+)$", re.IGNORECASE | re.DOTALL)
    _recent = re.compile(r"^(?:디스코드\s*(?:최근|대화|메시지))", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        t = text.strip()
        return any(rx.match(t) for rx in (self._draft, self._send, self._recent))

    def run(self, ctx: SkillContext, text: str) -> str:
        from arius.discord import format_announcement

        t = text.strip()
        m = self._draft.match(t)
        if m:
            title, body = _split_title(m.group("body"))
            preview = format_announcement(title, body, ctx.config.minecraft.name)
            return "공지 초안입니다 (보내려면 '공지 전송: …'):\n" + preview
        m = self._send.match(t)
        if m:
            title, body = _split_title(m.group("body"))
            return _tool(ctx, "discord_announce", {"title": title, "body": body})
        if self._recent.match(t):
            return _tool(ctx, "discord_recent", {"limit": 10})
        return "이해하지 못했습니다."


def _split_title(text: str) -> tuple[str, str]:
    """'제목 | 본문' or first line as title when multi-line; else no title."""
    text = text.strip()
    if "|" in text:
        title, _, body = text.partition("|")
        return title.strip(), body.strip()
    if "\n" in text:
        title, _, body = text.partition("\n")
        return title.strip(), body.strip()
    return "", text


# --- PC control ---------------------------------------------------------------------------


class DesktopSkill(Skill):
    name = "desktop"
    description = ("PC 제어: '유튜브 열어줘', '메모장 실행해', '다운로드 폴더 열어', '창 전환: 크롬', '실행 중인 프로그램', "
                   "'프로그램 종료: notepad'(확인 필요) (권한: desktop.open / desktop.manage)")
    capability = perm.CAP_DESKTOP_OPEN
    priority = 38

    _running = re.compile(r"^\s*(?:실행\s*중인\s*(?:프로그램|프로세스|앱)|프로세스\s*목록|프로그램\s*목록|/ps)", re.IGNORECASE)
    _switch = re.compile(r"^\s*(?:창\s*전환|/window)\s*[:：]?\s*(?P<title>.+)$", re.IGNORECASE)
    _switch_tail = re.compile(r"^\s*(?P<title>.+?)\s*창(?:으로)?\s*(?:전환|바꿔|보여줘|띄워|가져와)\s*(?:줘)?\s*[.!]*$", re.IGNORECASE)
    _close_confirm = re.compile(r"^\s*(?:종료\s*확인|프로그램\s*종료\s*확인)\s*[:：]?\s*(?P<name>.+)$", re.IGNORECASE)
    _close = re.compile(r"^\s*(?:프로그램\s*종료|/kill|앱\s*종료)\s*[:：]?\s*(?P<name>.+)$", re.IGNORECASE)
    _close_tail = re.compile(r"^\s*(?P<name>.+?)\s*(?:프로그램|앱)?\s*(?:을|를)?\s*(?:종료해|종료|꺼\s*줘|닫아\s*줘|닫아)\s*(?:줘|주세요)?\s*[.!]*$", re.IGNORECASE)
    _open = re.compile(r"^\s*(?:열어|실행|켜)\s*[:：]\s*(?P<target>.+)$", re.IGNORECASE)
    _open_tail = re.compile(
        r"^\s*(?P<target>.+?)\s*(?:을|를|좀)?\s*(?:열어|실행해|실행\s*시켜|켜|띄워)\s*(?:줘|주세요|줄래|봐)?\s*[.!~]*$",
        re.IGNORECASE,
    )
    _noun_suffix = re.compile(r"\s*(?:폴더|사이트|프로그램|앱)$", re.IGNORECASE)
    _not_ours = re.compile(r"^(?:서버(?!\s*폴더)|에이전트|하트비트|디스코드\s*(?:대화|모드)|음성|마이크|학습|기억|정책|프로젝트)", re.IGNORECASE)
    _server_folder = re.compile(r"^(?:마인크래프트\s*|마크\s*)?서버\s*폴더$", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        t = text.strip()
        if self._not_ours.match(t):
            return False
        if any(rx.match(t) for rx in (self._running, self._switch, self._close_confirm, self._close, self._open)):
            return True
        return any(rx.match(t) for rx in (self._switch_tail, self._close_tail, self._open_tail))

    def run(self, ctx: SkillContext, text: str) -> str:
        t = text.strip()
        if self._running.match(t):
            return _tool(ctx, "list_processes", {"limit": 15})
        m = self._switch.match(t) or self._switch_tail.match(t)
        if m:
            return _tool(ctx, "switch_window", {"title": m.group("title").strip()})
        m = self._close_confirm.match(t)
        if m:
            if not ctx.session.can(perm.CAP_DESKTOP_MANAGE):
                return not_done("프로그램 종료에는 'desktop.manage' 권한(관리자 이상)이 필요합니다.", "관리자 계정으로 로그인해 주세요.")
            return _tool(ctx, "close_program", {"name": m.group("name").strip()})
        m = self._close.match(t) or self._close_tail.match(t)
        if m:
            name = m.group("name").strip()
            if not ctx.session.can(perm.CAP_DESKTOP_MANAGE):
                return not_done("프로그램 종료에는 'desktop.manage' 권한(관리자 이상)이 필요합니다.", "관리자 계정으로 로그인해 주세요.")
            if ctx.tools is not None and ctx.tools.desktop().is_protected(name):
                return not_done(f"'{name}' 은(는) 보호된 프로세스입니다(서버·시스템·이 비서).", "서버는 '서버 중지' 로, 시스템 프로세스는 직접 관리해 주세요.")
            return (
                f"실행 예정: '{name}' 프로그램 종료\n"
                "영향: 저장하지 않은 작업이 사라질 수 있습니다.\n"
                f"진행할까요? ('종료 확인: {name}' 이라고 말씀해 주세요)"
            )
        m = self._open.match(t) or self._open_tail.match(t)
        if m:
            return self._open_target(ctx, m.group("target").strip().strip("'\""))
        return "이해하지 못했습니다."

    def _open_target(self, ctx: SkillContext, target: str) -> str:
        from arius.desktop import is_url

        d = ctx.tools.desktop() if ctx.tools is not None else None
        if d is None:
            return "도구 컨텍스트가 없습니다."
        if self._server_folder.match(target):
            sd = ctx.tools.server_dir()
            if not sd:
                return not_done("서버 폴더를 모릅니다.", "config 의 minecraft.server_dir 를 설정해 주세요.")
            return "실행하겠습니다: 서버 폴더 열기\n" + _tool(ctx, "open_path", {"target": sd})
        trimmed = self._noun_suffix.sub("", target).strip()
        candidates = [target] + ([trimmed] if trimmed and trimmed != target else [])
        for cand in candidates:
            if is_url(cand) or d.resolve_site(cand):
                return "실행하겠습니다: 웹사이트 열기\n" + _tool(ctx, "open_url", {"target": cand})
            if d.resolve_program(cand):
                return f"실행하겠습니다: '{cand}' 실행\n" + _tool(ctx, "launch_program", {"name": cand})
            if d.resolve_folder(cand) is not None or os.path.exists(os.path.expanduser(cand)):
                return "실행하겠습니다: 폴더/파일 열기\n" + _tool(ctx, "open_path", {"target": cand})
        return not_done(
            f"'{target}' 이(가) 무엇인지 모르겠습니다 (등록된 프로그램·사이트·폴더가 아니고 경로도 아님).",
            "URL 이나 정확한 경로를 말하거나, config desktop.programs / desktop.sites / desktop.folders 에 이름을 등록해 주세요.",
        )


# --- agent, policies, modes, learning -------------------------------------------------------


class AgentSkill(Skill):
    name = "agent"
    description = "자율 에이전트에게 일을 맡깁니다. 예: '작업: 서버 로그에서 오류 찾아서 요약해줘', '/do …' (권한: agent.run)"
    capability = perm.CAP_AGENT_RUN
    priority = 36

    _pat = re.compile(r"^(?:/do\b|작업\s*[:：])\s*(?P<goal>.+)$", re.IGNORECASE | re.DOTALL)

    def matches(self, text: str) -> bool:
        return bool(self._pat.match(text.strip()))

    def run(self, ctx: SkillContext, text: str) -> str:
        m = self._pat.match(text.strip())
        assert m
        if ctx.agent is None:
            return "에이전트를 사용할 수 없습니다."
        return ctx.agent(m.group("goal"))


class PolicySkill(Skill):
    name = "policy"
    description = "에이전트 상시 정책 관리. 예: '정책 추가: 서버 꺼지면 다시 켜고 디스코드에 알려', '정책 목록', '정책 삭제 2' (권한: agent.manage)"
    capability = perm.CAP_AGENT_MANAGE
    priority = 37

    _add = re.compile(r"^정책\s*(?:추가|등록)\s*[:：]\s*(?P<text>.+)$", re.IGNORECASE | re.DOTALL)
    _list = re.compile(r"^정책\s*(?:목록|리스트|보기)", re.IGNORECASE)
    _del = re.compile(r"^정책\s*(?:삭제|제거)\s*(?P<id>\d+)", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        t = text.strip()
        return any(rx.match(t) for rx in (self._add, self._list, self._del))

    def run(self, ctx: SkillContext, text: str) -> str:
        t = text.strip()
        m = self._add.match(t)
        if m:
            pid = ctx.memory.add_policy(m.group("text"))
            return f"정책 #{pid} 을 추가했습니다: {m.group('text').strip()}"
        m = self._del.match(t)
        if m:
            return "삭제했습니다." if ctx.memory.remove_policy(int(m.group("id"))) else "해당 번호의 정책이 없습니다."
        rows = ctx.memory.list_policies()
        if not rows:
            return "등록된 정책이 없습니다. '정책 추가: …' 로 등록하십시오."
        return "상시 정책:\n" + "\n".join(f"  #{r['id']} {'✅' if r['enabled'] else '⏸'} {r['text']}" for r in rows)


class AutoAllowSkill(Skill):
    name = "auto-allow"
    description = "자율 모드에서 묻지 않고 실행할 도구 관리. 예: '자동 허용 추가: minecraft_backup', '자동 허용 목록' (권한: agent.manage)"
    capability = perm.CAP_AGENT_MANAGE
    priority = 37

    _add = re.compile(r"^자동\s*허용\s*(?:추가|등록)\s*[:：]?\s*(?P<tool>\S+)", re.IGNORECASE)
    _del = re.compile(r"^자동\s*허용\s*(?:삭제|제거|해제)\s*[:：]?\s*(?P<tool>\S+)", re.IGNORECASE)
    _list = re.compile(r"^자동\s*허용\s*(?:목록|보기|리스트)?\s*$", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        t = text.strip()
        return any(rx.match(t) for rx in (self._add, self._del, self._list))

    def run(self, ctx: SkillContext, text: str) -> str:
        from arius.agent.tools import build_registry

        t = text.strip()
        allow = ctx.config.agent.auto_allow
        m = self._add.match(t)
        if m:
            name = m.group("tool")
            tool = build_registry().get(name)
            if tool is None:
                return not_done(f"'{name}' 이라는 도구가 없습니다.", "'자동 허용 목록' 에서 도구 이름을 확인해 주세요.")
            if tool.risk == "danger":
                return not_done(
                    f"'{name}' 은(는) 서비스를 중단시키는 위험 도구라 음성/채팅으로는 자동 허용에 넣지 않습니다.",
                    "정말 필요하면 config.json 의 agent.auto_allow 에 직접 적어 주세요.",
                )
            if name in allow:
                return f"'{name}' 은(는) 이미 자동 허용 목록에 있습니다."
            allow.append(name)
            saved = _save(ctx)
            return f"완료했습니다. '{name}' 을(를) 자동 허용에 추가했습니다 (autonomous 모드에서 묻지 않고 실행).{saved}"
        m = self._del.match(t)
        if m:
            name = m.group("tool")
            if name not in allow:
                return f"'{name}' 은(는) 자동 허용 목록에 없습니다."
            allow.remove(name)
            saved = _save(ctx)
            return f"완료했습니다. '{name}' 을(를) 자동 허용에서 뺐습니다.{saved}"
        tools = build_registry()
        lines = ["자동 허용 도구 (autonomous 모드에서 확인 없이 실행):"]
        lines += [f"  ✅ {n}" for n in allow]
        others = [n for n, tl in tools.items() if tl.risk != "read" and n not in allow]
        lines.append("확인 후 실행되는 도구: " + ", ".join(others))
        lines.append("항상 확인하는 콘솔 명령: " + ", ".join(ctx.config.agent.rcon_confirm))
        return "\n".join(lines)


def _save(ctx: SkillContext) -> str:
    a = ctx.arius
    if a is None or not hasattr(a, "save_config"):
        return " (이 세션에만 적용)"
    try:
        return " config.json 에 저장했습니다." if a.save_config() else " (config 경로를 몰라 이 세션에만 적용)"
    except Exception as exc:
        return f" (config 저장 실패: {exc})"


def learning_report(ctx: SkillContext) -> str:
    """학습 모드 보고: what was learned, what the user keeps approving, what to automate."""
    mem = ctx.memory
    user = ctx.session.user.username
    facts = mem.list_facts(user)
    recent_facts = sorted(facts, key=lambda f: -f.ts)[:5]
    cands = mem.approval_candidates(3)
    approvals = mem.recent_approvals(50)
    yes = sum(1 for a in approvals if a["approved"])
    no = len(approvals) - yes
    errors = [r for r in mem.agent_log(200) if r["kind"] == "error"]
    err_counts: dict[str, int] = {}
    for r in errors:
        err_counts[r["summary"]] = err_counts.get(r["summary"], 0) + 1
    repeated = sorted(err_counts.items(), key=lambda kv: -kv[1])[:3]
    lines = ["[학습 보고]"]
    lines.append("- 새로 기억한 내용: " + ("; ".join(f"{f.key}={f.value}" for f in recent_facts) if recent_facts else "없음"))
    lines.append(f"- 근거 및 신뢰도: 최근 승인 {yes}건 / 거절 {no}건, 기억 {len(facts)}개 (출처·신뢰도는 '기억 목록' 참고)")
    if cands:
        lines.append("- 앞으로 달라지는 동작(제안): " + ", ".join(f"'{c['tool']}' 을 자동 허용 후보로 제안 ({c['yes']}회 승인)" for c in cands))
        lines.append("- 사용자에게 필요한 승인: '자동 허용 추가: <도구>' 라고 말하면 적용 (승인 전에는 계속 묻습니다)")
    else:
        lines.append("- 앞으로 달라지는 동작: 변화 없음 (3회 이상 연속 승인된 작업이 아직 없음)")
        lines.append("- 사용자에게 필요한 승인: 없음")
    if repeated:
        lines.append("- 반복된 오류: " + "; ".join(f"{s} ×{n}" for s, n in repeated) + " → 같은 오류가 반복되면 원인·이전 시도·재발 방지책을 요약합니다.")
    lines.append("- 삭제 또는 수정 방법: '기억 삭제: <항목>', '자동 허용 삭제: <도구>', '정책 삭제 <번호>'")
    return "\n".join(lines)


class ModeSkill(Skill):
    name = "mode"
    description = "운영 모드 전환: '빠른 모드', '정확 모드', '학습 모드', '점검 모드', '절전 모드', '/mode', '현재 모드' (권한: agent.run)"
    capability = perm.CAP_AGENT_RUN
    priority = 35

    _set = re.compile(r"^\s*(?:/mode\s+(?P<a>\S+)|(?P<b>빠른|빠름|정확|정밀|학습|점검|진단|절전|대기|휴식)\s*모드(?:로)?(?:\s*(?:전환|변경|켜|시작|해줘|해|가자|ㄱ))?)\s*[.!~]*$", re.IGNORECASE)
    _show = re.compile(r"^\s*(?:/mode|현재\s*모드|모드\s*(?:확인|뭐야|보기)|모드\s*목록)\s*[?？.!]*$", re.IGNORECASE)
    _report = re.compile(r"^\s*(?:학습\s*(?:보고|결과|현황|리포트))\s*[.!]*$", re.IGNORECASE)

    def matches(self, text: str) -> bool:
        t = text.strip()
        return bool(self._set.match(t) or self._show.match(t) or self._report.match(t))

    def run(self, ctx: SkillContext, text: str) -> str:
        t = text.strip()
        a = ctx.arius
        if self._report.match(t):
            return learning_report(ctx)
        m = self._set.match(t)
        if m:
            key = parse_mode(m.group("a") or m.group("b") or "")
            if key is None:
                return not_done("알 수 없는 모드입니다.", "빠른 / 정확 / 학습 / 점검 / 절전 중에서 골라 주세요.")
            if a is not None and hasattr(a, "set_mode"):
                a.set_mode(key)
            mode = get_mode(key)
            head = f"완료했습니다. {mode.label}로 전환했습니다 — {mode.summary}"
            if key == "sleep":
                head += "\n(하트비트를 멈춥니다. 호출어·직접 요청·예약 점검에만 반응합니다.)"
            if key == "inspect":
                return head + "\n\n" + inspect_pc(ctx) + "\n\n" + inspect_server(ctx)
            if key == "learn":
                return head + "\n\n" + learning_report(ctx)
            return head
        current = a.current_mode() if a is not None and hasattr(a, "current_mode") else ctx.config.agent.default_mode
        lines = [f"현재 모드: {get_mode(current).label}"]
        lines += [f"  {'▶' if k == current else '•'} {mo.label} — {mo.summary}" for k, mo in MODES.items()]
        return "\n".join(lines)


# --- shell (owner/admin) -------------------------------------------------------------------


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
        InspectSkill(),
        MinecraftSkill(),
        DiscordSkill(),
        ModeSkill(),
        AgentSkill(),
        PolicySkill(),
        AutoAllowSkill(),
        ForgetSkill(),
        DesktopSkill(),
        ListFactsSkill(),
        LearnSkill(),
        RecallSkill(),
        WebLearnSkill(),
        WebRecallSkill(),
        ProjectSkill(),
        UserAdminSkill(),
        ExecSkill(),
    ]
