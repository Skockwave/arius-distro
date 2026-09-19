# ARIUS — 로컬 개인 AI 비서

> **A**daptive **R**esponsive **I**ntelligent **U**ser **S**ystem
> 영화 속 인공지능 비서(예: 자비스)처럼 대화하고, 기억하고, **권한 등급에 따라 통제되는** 개인용 AI 시스템입니다.
> 내 컴퓨터에서 직접 돌아갑니다. 비서의 이름(호출어)은 `config.json` 의 `assistant_name` 으로 정합니다 — 예시 설정은 **"자비스"** 입니다.

---

## 이게 뭔가요 (그리고 무엇이 현실적인가요)

요청하신 목표를 실제로 만들 수 있는 것과, 아직은 공상과학인 것으로 나눠 솔직하게 정리했습니다.

| 목표 | 이 프로젝트가 실제로 제공하는 것 |
|------|-------------------------------|
| **"자비스처럼 대화"** | ✅ 정중하고 유능한 페르소나로 대화. 클라우드(Claude) **또는 내 PC의 로컬 모델(Ollama)** 로 진짜 추론, 둘 다 없어도 오프라인으로 동작 |
| **"권한에 따라 통제"** | ✅ **RBAC(역할 기반 접근 제어)** — 오너/관리자/운영자/사용자/게스트 5단계. 각 기능마다 필요한 권한이 있고, 등급이 낮으면 시스템이 차단 |
| **"고난이도의 학습"** | ✅ 영구 기억 + **의미 기반 회상(임베딩 유사도)** + **웹 학습**. 가르친 사실뿐 아니라 **웹 페이지(URL)를 읽어 본문을 수집·저장**하고 회상. 크롬(Chromium) 렌더링 옵션 지원. (⚠️ 개인 PC에서 모델을 처음부터 훈련시키는 것은 비현실적 — 아래 "학습의 진실" 참고) |
| **"슈트 제작"** | ⚠️ 소프트웨어는 물리적 슈트를 만들 수 없습니다. 대신 **프로젝트 관리 기능**으로 '슈트' 프로젝트의 계획·기록·진행을 도와줍니다 (아이언맨의 자비스도 실제로는 CAD/제어 소프트웨어였습니다) |
| **"말하는" 자비스 (음성)** | ✅ 답변을 **음성으로 읽어주고**(TTS), **마이크로 듣습니다**(STT). **이름을 부르면 대답하는 대화 모드**(`listen`) 포함. 라이브러리가 없어도 OS 내장 음성으로 동작 |
| **"스스로 생각해서 관리"** | ✅ **자율 에이전트** — 컴퓨터·서버 상태를 관찰하고, 상시 정책을 읽고, LLM이 도구를 골라 조치. 3단계 자율 수준 + 확인 게이트 + 도구 허용 목록으로 **안전 경계** 안에서만 |
| **마인크래프트 서버 관리** | ✅ 로컬 Bukkit/Spigot/Paper 서버(예: 메테노서버) 상태·접속자·TPS·로그·화이트리스트/OP/밴 목록·**월드 백업**·RCON 콘솔·시작/재시작(사전 점검+예고), 죽으면 자동 복구(정책), **7단계 점검** |
| **디스코드(메테노디코)** | ✅ 공지 게시(웹훅/봇) + **채널에서 사람처럼 감정을 담아 대화**하는 봇 모드 |
| **PC 제어** | ✅ 프로그램 실행·종료(확인)·창 전환·파일/폴더/웹사이트 열기·실행 중 프로그램·CPU/RAM/디스크 점검. 삭제·설치·설정 변경은 **하지 않음** |
| **운영 규칙** | ✅ 고정된 응답 형식(실행하겠습니다 / 실행 예정·영향·진행할까요? / 완료했습니다 / 실행하지 않았습니다·이유·다음 조치), 확인 필수 작업 목록, 비밀 정보 차단, 5가지 운영 모드 — 아래 "운영 규칙" |

즉, 이 저장소는 **진짜로 실행되는 개인 AI 비서의 뼈대**입니다. 추가 설치 없이 바로 켜지고, API 키를 넣으면 실제 대형 언어 모델로 똑똑해집니다.

---

## 내 컴퓨터에 설치하기

핵심 기능은 **파이썬 표준 라이브러리만으로** 동작합니다. 필요한 건 **Python 3.10 이상** 하나뿐입니다.

### 가장 쉬운 방법 — 한 줄 자동 설치

**Windows** — 시작 메뉴에서 *PowerShell* 을 열고 아래 한 줄을 붙여넣기 → Enter:

```powershell
irm https://raw.githubusercontent.com/Skockwave/arius-distro/main/arius-ai/bootstrap.ps1 | iex
```

**macOS / Linux** — 터미널에서:

```bash
curl -fsSL https://raw.githubusercontent.com/Skockwave/arius-distro/main/arius-ai/bootstrap.sh | bash
```

이 한 줄이 **Python 확인(Windows는 없으면 winget으로 자동 설치) → 코드 다운로드 → Windows는 `바탕 화면\ARIUS`, macOS/Linux는 `~/ARIUS`에 복사 → 설치 → 오너 계정 설정 → 바탕 화면 바로가기(Windows)** 까지 전부 처리합니다. 설치 위치를 바꾸려면 앞에 `$env:ARIUS_DIR="D:\ARIUS"; ` 를 붙이십시오. 다시 실행해도 안전합니다(설정과 가상환경 보존).
아직 `main`에 합쳐지기 전이라면 URL의 `main`을 `claude/high-performance-ai-system-ibqiwl`로 바꾸십시오. 스크립트는 `main`에 코드가 없으면 그 브랜치를 자동으로 시도합니다.

### 직접 하려면

#### 1) 코드 받기

- **ZIP**: GitHub 저장소 페이지에서 브랜치 선택 → 초록색 **Code** → **Download ZIP** → 압축 해제 → 그 안의 `arius-ai` 폴더를 씁니다.
- **git**:
  ```bash
  git clone https://github.com/Skockwave/arius-distro.git
  cd arius-distro/arius-ai
  ```
  (아직 `main`에 합쳐지기 전이라면 `git clone -b claude/high-performance-ai-system-ibqiwl …`)

#### 2) Windows — 더블클릭 두 번

1. Python이 없다면 https://www.python.org/downloads/ 에서 설치. 설치 화면 맨 아래 **"Add python.exe to PATH" 체크 필수**.
2. `arius-ai` 폴더의 **`install.bat` 더블클릭** → Python 확인 → 가상환경(.venv) 생성 → 선택 기능 설치 여부 → 오너 계정·백엔드 설정(`init`).
3. 이후에는 **`run.bat` 더블클릭**으로 실행. 바탕화면 바로가기: `run.bat` 우클릭 → 보내기 → 바탕 화면(바로 가기 만들기).

`run.bat`은 콘솔을 UTF-8로 맞춰 주므로 **한글이 깨지지 않습니다.** 음성으로 실행하려면 바로가기의 "대상" 끝에 ` run --voice` 를 붙이십시오.

#### 3) macOS / Linux — 명령 두 줄

```bash
bash install.sh     # Python 확인 → .venv → 선택 기능 → init
./run.sh            # 실행 (음성: ./run.sh run --voice)
```

#### 4) 직접 실행 (스크립트 없이)

```bash
cd arius-ai
python main.py init     # 설정과 오너 계정 생성 (대화형)
python main.py          # 실행
```

#### 5) 선택 — 더 똑똑하게

| 원하는 것 | 할 일 |
|---|---|
| 진짜 추론 (클라우드) | `pip install anthropic` + 환경변수 `ANTHROPIC_API_KEY` + `init`에서 2번 |
| 진짜 추론 (완전 오프라인) | https://ollama.com 설치 → `ollama pull exaone3.5` → `init`에서 3번 |
| 말하는 자비스 + 마이크 | **`setup-voice.bat` 더블클릭** (또는 `python main.py setup voice`) — 설치와 마이크 점검까지 한 번에 |

### 문제가 생기면

- **`python`을 찾을 수 없음** → Python 설치 시 "Add to PATH"를 안 켠 경우. 재설치하거나 `install.bat`이 `py` 런처를 자동으로 찾습니다.
- **한글이 깨짐** → `run.bat` / `run.sh`로 실행하십시오(UTF-8 자동 설정). 직접 실행 시엔 Windows에서 `chcp 65001` 후 실행.
- **`/exec` 명령이 Windows에서 안 됨** → `dir`, `echo` 같은 cmd 내장 명령도 지원합니다. 오너/관리자 등급인지 `/whoami`로 확인하십시오.
- **가상환경 생성 실패(Ubuntu)** → `sudo apt install python3-venv` 후 재실행. 실패해도 시스템 Python으로 계속 동작합니다.
- **시작하면 "게스트"로 뜸** → 오너 계정에 암호가 걸려 있어 시작 시 암호 입력에서 Enter 를 친 경우입니다. `/login <아이디>` 로 로그인하거나, 암호를 없애 자동 로그인하려면 **`run.bat passwd --clear`** (`python main.py passwd --clear`).
- **답변에 "(참고: 지금은 오프라인 응답 모드…)" 가 붙음** → 실제 언어 모델이 연결되지 않은 상태입니다. 로컬 모델은 Ollama 설치 → `ollama pull exaone3.5` → **`run.bat backend ollama exaone3.5`**, 클라우드는 API 키 저장 후 **`run.bat backend anthropic`**. 이 명령이 config 를 고치고 무엇이 빠졌는지 바로 알려줍니다. (`backend: ollama` 인데 모델이 `claude-…` 로 남아 있어도 이 명령이 정리합니다.)

`init` 없이 바로 체험만 하려면 예제 설정을 복사하세요:

```bash
cp config.example.json config.json
python main.py
```

실행하면 이렇게 대화할 수 있습니다:

```
게스트 › 안녕
ARIUS › 안녕하십니까. ARIUS입니다. 무엇을 도와드릴까요?

게스트 › /login owner
환영합니다, 오너 (오너).

오너 › 기억해: 내 취미는 슈트 제작
ARIUS › 기억했습니다. ('내 취미' → '슈트 제작')

오너 › 프로젝트 생성 아이언슈트
ARIUS › '아이언슈트' 프로젝트를 생성했습니다. ...
```

---

## 권한(RBAC)으로 통제하기 — 핵심 기능

AI가 "권한에 따라 통제된다"는 요구를 이렇게 구현했습니다.

### 5단계 권한 등급

| 등급 | 설명 | 가진 권한 |
|------|------|----------|
| `owner` (오너) | 최고 관리자 | **전부** (`*`) |
| `admin` (관리자) | 시스템 관리 | 대화·기억·시스템정보·**명령실행**·프로젝트 |
| `operator` (운영자) | 운영 담당 | 대화·기억·시스템정보·프로젝트 |
| `user` (사용자) | 일반 사용자 | 대화·기억·프로젝트 조회 |
| `guest` (게스트) | 손님 | **대화만** |

### 작동 방식

1. 모든 스킬(기능)은 필요한 **권한(capability)** 을 선언합니다. 예: 명령 실행 스킬 → `system.exec`.
2. 사용자는 `/login <아이디>` 로 로그인하고, 계정에 설정된 등급을 부여받습니다.
3. 요청이 들어오면 코어(`core.py`)가 **현재 세션의 등급이 그 권한을 가졌는지** 확인합니다.
4. 없으면 실행을 막고 정중히 거절합니다:

```
게스트 › /exec rm -rf /
자비스 › 실행하지 않았습니다.
        이유: 'system.exec' 권한이 필요한데, 게스트님의 현재 등급은 '게스트'입니다.
        다음 조치: 권한이 있는 계정으로 로그인하거나('/login <아이디>') 오너에게 권한 상향을 요청해 주세요.
```

암호는 평문으로 저장되지 않습니다 — **PBKDF2-HMAC-SHA256**(20만 회 반복)으로 해시됩니다.

### 권한 표 (capability)

| capability | 의미 | guest | user | operator | admin | owner |
|------------|------|:---:|:---:|:---:|:---:|:---:|
| `chat` | 대화 | ● | ● | ● | ● | ● |
| `memory.read` / `memory.write` | 기억 조회/저장 | | ● | ● | ● | ● |
| `project.read` / `project.manage` | 프로젝트 | 조회 | 조회 | ● | ● | ● |
| `system.info` | 시스템 정보 조회 | | | ● | ● | ● |
| `web.read` | 학습한 웹 내용 회상 | | ● | ● | ● | ● |
| `web.learn` | **웹 페이지 학습(수집)** | | | ● | ● | ● |
| `mc.read` | 서버 상태/로그 조회 | | ● | ● | ● | ● |
| `mc.admin` | 서버 콘솔 명령·시작/중지 | | | | ● | ● |
| `discord.read` / `discord.announce` | 디스코드 읽기 / 공지 | | | ● | ● | ● |
| `files.read` | 서버 폴더 파일 읽기 | | | ● | ● | ● |
| `agent.run` / `agent.manage` | 에이전트에게 일 맡기기·모드 전환 / 정책·자동 허용 관리 | | | 실행 | ● | ● |
| `desktop.open` | 프로그램 실행, 파일·폴더·웹사이트 열기, 창 전환 | | | ● | ● | ● |
| `desktop.manage` | **프로그램 종료** (항상 확인) | | | | ● | ● |
| `system.exec` | **셸 명령 실행** | | | | ● | ● |
| `user.manage` | 사용자/권한 관리 | | | | | ● |

---

## 기본 명령·기능

| 입력 예시 | 하는 일 | 필요 권한 |
|-----------|--------|----------|
| `/help`, `도움말` | 현재 등급에서 쓸 수 있는 기능 목록 | chat |
| `/whoami`, `내 권한` | 내 계정·등급·권한 표시 | chat |
| `지금 몇 시야?` | 현재 시각 | chat |
| `시스템 정보` | OS·CPU 등 | system.info |
| `기억해: 내 생일은 3월 2일`, `이것을 기억해: …` | 사실을 학습(저장) — 저장일·출처·신뢰도 기록, 비밀번호/키/토큰은 거부 | memory.write |
| `내 생일 기억나?` | 저장한 사실 회상 | memory.read |
| `기억 목록`, `네가 기억하는 내용을 보여줘` | 저장한 모든 사실 + 메타데이터 | memory.read |
| `기억 삭제: 생일`, `내 정보를 모두 잊어` | 기억 삭제 (전체 삭제는 '네, 모두 잊어' 재확인) | memory.write |
| `서버 점검해`, `PC 점검`, `전체 점검` | 7단계 점검 보고(온라인·접속자·TPS·CPU/RAM·디스크·오류·백업), 우선순위 요약 | system.info |
| `빠른 모드` / `정확 모드` / `학습 모드` / `점검 모드` / `절전 모드`, `현재 모드`, `학습 보고` | 운영 모드 전환·학습 보고 | agent.run |
| `유튜브 열어줘`, `메모장 실행해`, `다운로드 폴더 열어`, `창 전환: 크롬`, `실행 중인 프로그램` | PC 제어 | desktop.open |
| `notepad 종료해` → `종료 확인: notepad` | 프로그램 종료 (2단계 확인, 보호 프로세스 제외) | desktop.manage |
| `자동 허용 목록`, `자동 허용 추가: minecraft_backup` | 자율 모드에서 묻지 않을 도구 관리 (위험 도구는 거부) | agent.manage |
| `학습해: https://...` / `크롬으로 학습해: https://...` | 웹 페이지를 읽어 학습 | web.learn |
| `웹에서 포지 설치 찾아줘` | 학습한 웹 내용 회상 | web.read |
| `프로젝트 생성 슈트` / `프로젝트 목록` | 프로젝트 관리 | project.manage |
| `사용자 추가 friend user` / `권한 변경 friend admin` | 계정 관리 | user.manage |
| `/exec echo hi`, `명령 실행: ls` | 셸 명령 실행 (위험) | system.exec |
| 그 외 아무 말 | 자유 대화(LLM) | chat |

세션 명령: `/login <아이디>`, `/logout`, `/quit`. 음성: `/voice on|off`, `/listen`, `/wake`. 모드: `/mode`. 에이전트: `/agent run|on|off|log|autonomy`, `정책 추가/목록/삭제`. 디스코드: `/discord on|off`. 기타: `/reindex`.

터미널 명령(`run.bat …` 또는 `python main.py …`): `init`(설정 생성), `passwd [--clear]`(암호 설정/제거), `backend ollama|anthropic|echo [모델]`(추론 백엔드 전환+점검), `setup voice|check`, `listen`, `agent`, `autostart enable|disable|status`.

---

## 진짜 추론 켜기 (Claude 연결)

기본은 **오프라인 모드**(규칙 기반, 네트워크 불필요)라 바로 켜집니다. 실제 대형 언어 모델의 추론을 원하면:

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."   # Windows: set ANTHROPIC_API_KEY=...
```

`config.json` 에서 백엔드를 바꿉니다:

```json
"llm": { "backend": "anthropic", "model": "claude-sonnet-5" }
```

키가 없거나 패키지가 없으면 자동으로 오프라인 모드로 **안전하게 되돌아갑니다** (비서는 계속 동작). 전환과 점검을 한 번에: `run.bat backend anthropic` (키는 환경 변수 `ANTHROPIC_API_KEY` 에만 두고 config 나 대화에 넣지 마십시오).

### 또는 로컬 모델로 (Ollama — 무료, 완전 오프라인, API 키 없음)

1. https://ollama.com 에서 Ollama 설치 (Windows/macOS/Linux)
2. 모델 받기 — 터미널에서:
   ```bash
   ollama pull llama3.1      # 범용 기본값 (약 4.7GB)
   ollama pull exaone3.5     # 한국어에 강함 (LG AI연구원)
   ollama pull qwen2.5       # 한국어 포함 다국어 우수
   ```
3. 한 줄로 전환 + 점검:
   ```
   run.bat backend ollama exaone3.5        # macOS/Linux: python main.py backend ollama exaone3.5
   ```
   config 의 `"llm": { "backend": "ollama", "model": "exaone3.5" }` 를 써 주고, Ollama 서버 연결과 모델 준비 여부를 ✅/⚠️ 로 알려줍니다. (`python main.py init` 에서 "3) 로컬 모델"을 골라도 됩니다.)
   메모리가 8GB 면 `exaone3.5:2.4b` 나 `qwen2.5:3b` 처럼 작은 태그를 권장합니다.

추가 파이썬 패키지는 필요 없습니다 — `localhost:11434` 로 직접 통신합니다. 서버가 꺼져 있거나 모델을 안 받았으면 **무엇을 하면 되는지 알려주고** 오프라인 모드로 계속 동작합니다:

```
ARIUS › ... (알림: 요청하신 백엔드를 쓸 수 없어 오프라인 모드로 답했습니다 —
        모델 'exaone3.5'이(가) 준비되어 있지 않습니다. 터미널에서 `ollama pull exaone3.5` 을 실행하십시오.)
```

임베딩도 로컬 신경망으로 바꾸려면 `ollama pull bge-m3` 후 `"embeddings": { "backend": "ollama" }` 로 두고 `/reindex` — 이러면 **대화·기억·회상 전부가 내 PC 안에서만** 돌아갑니다.

---

## 자율 에이전트 — 스스로 생각해서 관리하기

ARIUS는 정해진 스케줄을 도는 게 아니라, **관찰 → 생각 → 행동** 루프로 움직입니다.

```
오너 › 서버 로그에서 오류 찾아서 문제 있으면 디스코드에 알려줘
[ARIUS] minecraft_log 실행: [12:01] [Server thread/WARN]: Can't keep up! …
[ARIUS] discord_announce 실행: 디스코드(웹훅) 전송 완료 …
ARIUS › 최근 로그에 "Can't keep up" 경고가 6회 있어 TPS 저하가 의심됩니다. 운영 채널에 요약을 올렸습니다.
```

- **자유 요청**: "…해줘", "…봐줘", `작업: …`, `/do …` 로 말하면 에이전트가 도구를 골라 처리합니다 (실제 LLM 필요: Claude 또는 Ollama).
- **상시 정책**: `정책 추가: 서버 꺼지면 다시 켜고 디스코드에 공지해` 처럼 자연어 규칙을 등록하면, **하트비트**(기본 10분)마다 AI가 상태를 보고 정책이 요구하는 조치만 합니다. `/agent run` 으로 지금 바로 점검, `/agent on` 으로 백그라운드 시작, `/agent log` 로 기록 확인.
- **상시 데몬**: `python main.py agent --discord --listen` 으로 REPL 없이 24시간 — 하트비트 + 디스코드 대화 + 음성 대기를 한 프로세스로. 컴퓨터 켤 때 자동 시작은 아래 "컴퓨터를 켜면 자동으로 시작하기".
- LLM이 없어도(오프라인) "디스크 N% / 메모리 N% / 서버 꺼지면 …" 같은 단순 정책은 **규칙 엔진**이 처리합니다.

### 안전 경계 (일부러 이렇게 만들었습니다)

| 층 | 무엇을 막나 |
|---|---|
| **도구 자체** | 에이전트에게는 **임의 셸 명령 실행, 파일 쓰기/삭제 도구가 없습니다.** 할 수 있는 건 서버 상태/로그 읽기, 허용 목록 안의 콘솔 명령, 서버 시작/중지/재시작, 디스코드 공지, 기억뿐 |
| **RCON 허용 목록** | `agent.rcon_allow` 에 있는 명령만 (`list, tps, save-all, say, whitelist, kick, ban, op …`). `stop / reload / give / execute` 는 목록 밖 → 거부 |
| **항상 확인하는 명령** | `agent.rcon_confirm` (`kick, ban, op, deop, whitelist remove …`) 은 자율 수준·자동 허용과 무관하게 **매번 사람에게 묻습니다** (데몬처럼 물을 사람이 없으면 거부). 사람이 직접 칠 때는 `서버 명령: kick 철수 !` 처럼 `!` 로 확정 |
| **읽기 범위** | 파일은 서버 폴더와 `agent.read_paths` 안에서만 읽기 |
| **자율 수준** | `observe` 읽기만 / `supervised`(기본) 변경은 매번 y/n 확인 / `autonomous` 는 `agent.auto_allow` 에 적은 도구만 자동, 서버 중지·재시작은 목록에 없으면 항상 확인 |
| **RBAC** | 에이전트도 로그인한 사람의 등급을 넘지 못함 (게스트는 관찰조차 불가) |

`config.json` 예:
```json
"agent": { "autonomy": "autonomous", "interval_minutes": 10,
           "policies": ["서버가 꺼지면 다시 켜고 디스코드에 공지해", "디스크 85% 넘으면 알려줘"],
           "auto_allow": ["discord_announce", "minecraft_say", "minecraft_command", "minecraft_start"] }
```
> "컴퓨터를 직접 만져서 자동으로"라는 요청에 대해: 위 경계 안에서는 완전 자동입니다. 경계 밖(임의 명령·파일 삭제)은 **일부러** 열지 않았습니다 — 모델의 실수 한 번이 컴퓨터를 망가뜨릴 수 있기 때문입니다. 필요한 콘솔 명령은 `rcon_allow` 에, 읽을 폴더는 `read_paths` 에 추가하면 됩니다.

## 마인크래프트 서버 관리 (로컬 Bukkit/Spigot/Paper)

서버 이름·주소·폴더는 `config.json` 의 `minecraft` 에 둡니다 (`"name": "메테노서버"`, `"host": "localhost"`, `"server_dir": "C:/서버폴더"`). 폴더를 비워 두면 **실행 중인 서버 JVM에서 자동 감지**를 시도합니다.

| 말하면 | 하는 일 | 권한 |
|---|---|---|
| `서버 상태` | 온라인/접속자/버전/MOTD + 로컬 프로세스·폴더 | mc.read |
| `서버 점검해` | 7단계 점검: 온라인 → 접속자 → TPS → CPU/RAM → 디스크 → 최근 오류 → 최신 백업, 🔴즉시/🟡주의/🟢정상 요약 | system.info |
| `서버 로그 오류` / `서버 로그 접속` | latest.log 끝부분을 패턴으로 필터 | mc.read |
| `화이트리스트` / `운영자 목록` / `밴 목록` | whitelist.json / ops.json / banned-players.json 조회 (RCON 불필요) | mc.read |
| `백업 상태` | 최근 zip 백업의 시각·크기 (`alert_backup_hours` 초과 시 주의) | mc.read |
| `서버 백업` | `save-all` 후 월드 3개 폴더를 `backups/world-날짜.zip` 으로 (기존 백업은 절대 지우지 않음) | mc.admin |
| `tps` / `서버 명령: list` / `whitelist add 철수` | RCON 콘솔 명령 (허용 목록) | mc.admin |
| `서버 명령: kick 철수` → `… !` | 킥·밴·OP·화이트리스트 제거는 **실행 예정/영향** 을 보여주고 `!` 로 확정 | mc.admin |
| `서버 공지: 10분 후 점검` | 서버 채팅 `say` | mc.admin |
| `서버 시작` | 꺼진 서버를 start.bat/start.sh 로 시작 | mc.admin |
| `서버 재시작` / `서버 중지` | **사전 점검**(접속자 수·예상 중단 시간·최근 백업·공지 필요) 을 보여주고 확인 요청 | mc.admin |
| `서버 재시작 확인` / `서버 중지 확인` | 예고("서버가 약 5분 후 재시작됩니다. 안전한 곳으로 이동해 주세요.") → 대기(`restart_notice_seconds`, 접속자 없으면 10초) → 중지 → 시작. 긴 예고는 백그라운드로 진행하고 끝나면 알림 | mc.admin |
| `RCON 설정 <암호>` | server.properties 에 RCON 켜기(백업 생성, 재시작 필요) | mc.admin |

**RCON 준비**: `server.properties` 에 `enable-rcon=true`, `rcon.port=25575`, `rcon.password=암호` → 서버 재시작 → `config.json` 의 `minecraft.rcon_password`(또는 환경변수 `ARIUS_RCON_PASSWORD`)에 같은 암호. `RCON 설정 <암호>` 라고 말하면 ARIUS가 파일 수정까지 해 줍니다.

## 디스코드 — 공지와 대화

**공지(웹훅, 가장 쉬움)**: 채널 설정 → 연동 → 웹훅 만들기 → URL을 `discord.webhook_url`(또는 환경변수 `ARIUS_DISCORD_WEBHOOK`)에. 그러면 `공지 초안: 제목 | 본문` 으로 미리 보고 `공지 전송: …` 으로 게시합니다. 에이전트 정책의 "디스코드에 공지해"도 이 경로를 씁니다.

**대화 모드(봇)**: 사람처럼 감정을 담아 채널에서 이야기합니다.
1. https://discord.com/developers/applications 에서 앱 → Bot → 토큰 발급, **MESSAGE CONTENT INTENT** 켜기, 서버에 초대(메시지 보기/보내기 권한)
2. `config.json`: `"bot_token"`(또는 환경변수 `ARIUS_DISCORD_TOKEN`), `"chat_channels": ["채널ID"]`, `"channel_id": "공지채널ID"`
3. `python main.py run --discord` 또는 REPL에서 `/discord on`, 데몬은 `python main.py agent --discord`

- 기본은 **@멘션하거나 이름(웨이크워드)을 부를 때만** 대답합니다 (`chat_mention_only`). 모든 메시지에 답하게 하려면 `false`.
- 디스코드 멤버는 `chat_role`(기본 `user`) 등급으로 대화합니다 — 서버 상태는 물어볼 수 있지만 관리 명령은 못 합니다.
- 감정 표현은 `persona.emotional` (기본 켜짐). 웹소켓 없이 REST 폴링(기본 4초)이라 추가 패키지가 필요 없습니다.

## 이름을 부르면 대답하는 음성 대화

이어폰/헤드셋 마이크를 연결하고:
```bash
python main.py listen        # 또는 REPL에서 /wake
```
"**아리우스**" 또는 "**자비스**"(`voice.wake_words`)라고 부르면 "네, 듣고 있어요"라고 답하고, 이어지는 말에 음성으로 대답합니다. 한 번 대답한 뒤 `awake_seconds`(기본 20초) 동안은 이름 없이 계속 대화됩니다. 띄어쓰기·문장부호가 달라도("아리 우스!") 인식합니다. 인식은 Google 웹 음성(무료, 인터넷 필요)을 씁니다.

### 마이크·음성 라이브러리 설치 (더블클릭 한 번)

| OS | 방법 |
|---|---|
| Windows | `setup-voice.bat` 더블클릭 (또는 `run.bat setup voice`) |
| macOS / Linux | `bash setup-voice.sh` (macOS는 Homebrew로 PortAudio까지 자동) |
| 아무 OS | `python main.py setup voice` — 설치 후 진단까지, `python main.py setup check` — 진단만 |

설치기는 **SpeechRecognition(인식) + sounddevice(마이크) + pyttsx3(음성 출력)** 를 가상환경에 넣고, 각 항목을 ✅/❌ 로 보여 주며 **마이크 장치 목록**까지 확인합니다. `install.bat` / `install.sh` 도 기본으로 이 설치를 포함합니다(엔터만 치면 됨).

마이크는 **PyAudio 없이** 동작합니다. `sounddevice` 는 PortAudio 를 내장한 미리 빌드된 패키지라 Windows/macOS 어떤 Python 버전에서도 컴파일 없이 설치됩니다(PyAudio 는 Python 버전에 맞는 휠이 없으면 빌드 실패가 잦아서 선택 사항으로 내렸습니다).

❌ 가 나오면 이렇게 하십시오:
- **마이크 입력 라이브러리** — Linux 만 시스템 라이브러리가 필요: `sudo apt install libportaudio2`. Windows/macOS 는 `setup-voice` 재실행.
- **음성 출력 엔진 없음** — Windows/macOS 는 OS 내장 음성을 쓰므로 거의 없음. Linux: `sudo apt install espeak-ng`.
- **마이크 목록 0개** — 이어폰/헤드셋을 꽂고, Windows 설정 → 개인정보 → 마이크 → "데스크톱 앱이 마이크에 액세스" 허용.

## 컴퓨터를 켜면 자동으로 시작하기

한 번 등록하면 로그인할 때마다 ARIUS가 **서버 감시(하트비트) + 디스코드 대화 + 이름 부르면 대답(음성)** 을 한 프로세스로 켭니다.

| OS | 방법 |
|---|---|
| Windows | **`setup-autostart.bat` 더블클릭** → 시작프로그램에 등록 (창 없이 백그라운드로 할지 물어봄) |
| macOS / Linux | `bash setup-autostart.sh` → LaunchAgent / autostart 등록 |
| 아무 OS | `python main.py autostart enable` (옵션: `--hidden`, `--no-discord`, `--no-listen`) · `status` · `disable` |

`install.bat` / `install.sh` 도 마지막에 "자동 시작할까요?"를 물어봅니다(Enter = 예). 실행 기록은 `~/.arius/agent.log` 에 남습니다(창 없이 돌릴 때도 확인 가능).

> 자동 시작 시 자율 수준이 `supervised` 면 확인해 줄 사람이 없어 **변경 조치는 `auto_allow` 목록만** 실행됩니다. 무인 운영을 원하면 `config.json` 의 `agent.autonomy` 를 `"autonomous"` 로 두십시오 — 그래도 서버 중지/재시작 같은 위험 조치는 목록에 없으면 실행하지 않습니다.

## 감정이 있는 대화 (콘솔·음성·디스코드 모두)

ARIUS는 일만 처리하고 끝내지 않습니다. 반가우면 반갑다고, 걱정되면 걱정된다고 말하고, 지쳐 보이면 먼저 안부를 묻습니다.

```
형 › 다녀왔어
ARIUS › 어서 와요. 목소리 들으니 좋네요. 오늘은 어떤 하루였어요?
형 › 오늘 너무 힘들다
ARIUS › 오늘 많이 힘들었구나… 잠깐 쉬어요. 급한 건 제가 챙길게요.
```

| 설정 (`config.json` › `persona`) | 의미 |
|---|---|
| `"tone": "friendly"` (기본) | 친근한 존댓말(해요체) |
| `"tone": "casual"` | 편한 반말, 오래된 친구처럼 |
| `"tone": "formal"` | 정중한 합니다체 |
| `"emotional": true` | 감정 표현 켜기 (끄면 비서 모드) |
| `"honorific": "님"` | 부르는 호칭 (`""` 로 두면 이름만) |

- **기분(mood)**: 사건에 따라 기분이 바뀌고 모든 채널에서 일관되게 드러납니다 — 서버가 꺼지면 "걱정", 다시 살아나면 "안도와 기쁨". 오너와의 관계("가장 가까운 사람")도 페르소나에 들어갑니다.
- **진짜 감정 대화는 LLM(Claude/Ollama) 연결 시** 풍부해집니다. 오프라인 모드도 인사·고마움·힘듦·기쁨·심심함 같은 말엔 따뜻하게 반응하지만, 정해진 답 안에서만 그렇습니다.
- 인공지능이냐고 직접 물으면 솔직하게 답합니다 — 감정 표현은 흉내가 아니라 대화 방식이고, 그 사실을 숨기지 않습니다.

## 웹 학습 (인터넷에서 배우기)

ARIUS는 **웹 페이지를 읽어 그 내용을 학습(수집·저장)**하고, 나중에 검색해 회상할 수 있습니다.

```
운영자 › 학습해: https://docs.minecraftforge.net/en/1.20.1/gettingstarted/
ARIUS › 학습 완료: 'Getting Started with Forge'
        • 출처: https://docs.minecraftforge.net/...
        • 분량: 약 8,300자 (백엔드: urllib)
        • 요약: Forge 개발 환경 설정은 ...

운영자 › 웹에서 forge 설정 찾아줘
ARIUS › 학습한 웹 내용에서 찾았습니다:
        • Getting Started with Forge — Forge 개발 환경 설정은 ...
```

- **크롬(Chromium) 렌더링**: 자바스크립트로 그려지는 페이지는 `크롬으로 학습해: <URL>` 처럼 말하면 Playwright+Chromium으로 읽습니다.
  먼저 설치: `pip install playwright && playwright install chromium`.
- 기본 백엔드(`urllib`)는 추가 설치 없이 동작하며, 정적 페이지에 적합합니다.
- 권한: 수집(`web.learn`)은 **운영자 이상**, 회상(`web.read`)은 **사용자 이상**.

> ⚠️ **"인터넷의 모든 것"에 대하여**: 어떤 프로그램도 인터넷 전체를 학습할 수는 없습니다(무한한 양, robots.txt·이용약관·저작권 등 법적 제약). ARIUS의 웹 학습은 **당신이 지정한 페이지/주제를 읽는 "경계가 있는 리더"**이지, 무단으로 전체를 긁는 크롤러가 아닙니다. 필요한 링크를 주시면 그 내용을 확실히 배웁니다. (수집 대상 사이트의 이용약관과 robots.txt를 존중해 주세요.)

## 음성으로 대화하기 (말하는 자비스)

```bash
python main.py run --voice            # 답변을 음성으로 읽어줌
python main.py run --voice --listen   # 마이크로 듣고, 음성으로 답함
```

REPL 안에서도 `/voice on|off` 로 켜고 끄고, `/listen` 으로 한 문장을 마이크로 입력할 수 있습니다.
`config.json` 의 `voice.enabled` / `voice.listen` 을 `true` 로 두면 항상 켜집니다.

| 기능 | 권장 설치 | 없을 때 |
|------|----------|--------|
| 음성 출력(TTS) | `pip install pyttsx3` | OS 내장 음성 사용 — macOS `say`, Windows System.Speech, Linux `espeak-ng` — 그것도 없으면 텍스트만 출력 |
| 음성 입력(STT) | `pip install SpeechRecognition pyaudio` | `/listen` 시 설치 안내만 출력, 키보드 입력으로 계속 |

- 한국어 음성은 `voice.language = "ko-KR"`(기본값), 선호 목소리는 `voice.voice_name` 에 이름 일부(예: `"Yuna"`)를 적습니다.
- 읽어줄 때는 URL·불릿·괄호 안내문을 자동으로 걷어내고 최대 400자까지만 말합니다.

## 의미 기반 회상 (임베딩 유사도 검색)

기억과 웹 지식은 저장될 때 **벡터(임베딩)** 로도 색인됩니다. 그래서 정확한 단어가 없어도 **뜻이 비슷하면** 찾습니다.

```
오너 › 기억해: 취미는 슈트 제작
오너 › 슈트 만드는 거 뭐였지 기억나?      ← "제작"이라는 단어가 없어도
ARIUS › 기억하고 있는 내용입니다:
        • 취미: 슈트 제작
```

긴 웹 문서는 **문단 단위로 쪼개 색인**되어, 질문과 가장 가까운 문단을 골라 보여줍니다(예: 위키 전체를 학습해도 "레드스톤 신호" 질문에는 레드스톤 문단만).

| 백엔드 | 설치 | 특징 |
|--------|------|------|
| `hashing` (기본) | 없음 | 문자 n-gram 해싱. 오프라인, 즉시 동작, 한국어 어형 변화(설치/설치법/설치하기)에 강함 |
| `sentence-transformers` | `pip install sentence-transformers` | 신경망 다국어 임베딩. 더 똑똑하지만 첫 실행 시 모델 다운로드(수백 MB) |
| `ollama` | `ollama pull bge-m3` (파이썬 패키지 불필요) | 로컬 Ollama가 서빙하는 신경망 임베딩. `bge-m3` 는 한국어 포함 다국어에 강함 |

`config.json` 에서 `embeddings.backend` 를 바꾸고 REPL에서 `/reindex` 를 실행하면 기존 기억이 새 임베딩으로 재색인됩니다. 백엔드를 쓸 수 없으면 자동으로 `hashing` 으로 돌아갑니다.

## 로컬 모델이란? (Ollama 등)

지금 ARIUS의 "진짜 추론"은 **클라우드 API(Claude)** 를 호출합니다 — 인터넷과 API 키가 필요하고, 사용량만큼 비용이 듭니다.
**로컬 모델**은 언어 모델 자체를 **내 컴퓨터에서 직접 실행**하는 방식입니다. 대표 도구는 **Ollama**, **LM Studio**, **llama.cpp** 이고, 모델은 Llama 3, Qwen, Gemma, EXAONE(한국어) 같은 공개 모델을 씁니다.

| | 클라우드(Claude) | 로컬 모델(Ollama 등) |
|---|---|---|
| 인터넷 | 필요 | **불필요** (완전 오프라인) |
| 비용 | 사용량 과금 | **무료** (전기세만) |
| 개인정보 | 외부 서버로 전송 | **내 PC 밖으로 안 나감** |
| 똑똑함 | 최상급 | 모델·PC 사양에 따라 다름 (보통 클라우드보다 낮음) |
| 요구 사양 | 없음 | RAM 8GB↑, GPU 있으면 훨씬 빠름 (7~8B 모델 기준) |

"내 컴퓨터에서 도는 자비스"라는 목표에는 로컬 모델이 잘 맞습니다. **ARIUS는 Ollama 백엔드를 내장**하고 있어 설정 한 줄(`"backend": "ollama"`)로 전환됩니다 — 설치 방법은 위 "진짜 추론 켜기 › 로컬 모델로" 를 보십시오. 실제 성능은 모델과 PC 사양에 달려 있으니, 8GB RAM이면 7~8B 모델, 16GB 이상이면 14B급을 권합니다.

## "학습"의 진실 (고난이도 학습에 대해)

개인 컴퓨터에서 할 수 있는 "학습"은 세 층위입니다. 이 프로젝트는 **1·2층을 구현**하고, 3층으로 가는 자리를 비워 두었습니다.

1. **기억/회상 (구현됨)** — 사용자가 가르친 사실을 SQLite에 영구 저장하고, 다음 대화에서 관련 내용을 자동으로 프롬프트에 넣어 줍니다. 실제로 가장 실용적인 "학습"입니다.
2. **웹 학습 + 의미 기반 검색(RAG) (구현됨)** — `web.py` 로 웹 페이지를 읽어 `knowledge` 저장소에 담고, `embeddings.py` 로 문단을 벡터화해 `search_knowledge()` 가 **뜻이 가까운 문단**을 찾습니다. 기본은 무설치 해싱 임베딩, 원하면 `sentence-transformers` 신경망 임베딩으로 교체할 수 있습니다.
3. **모델 미세조정/훈련 (의도적으로 미포함)** — LLM을 처음부터 훈련하려면 수천 장의 GPU가 필요합니다. 개인 PC에서는 비현실적입니다. 현실적 대안은 (a) 위의 RAG, (b) **로컬 모델(Ollama, 내장됨)** 위에 LoRA 미세조정을 얹는 것입니다. 미세조정한 모델을 `ollama create` 로 등록하면 ARIUS가 그대로 씁니다.

솔직히 말씀드리면, "영화 속 자비스"는 아직 어떤 소프트웨어로도 완전히 만들 수 없습니다. 하지만 여기서 시작해 **실제로 유용한 비서**로 키워 나갈 수 있습니다.

---

## 구조

```
arius-ai/
├── main.py                  # 진입점 (python main.py)
├── bootstrap.ps1 / .sh      # 한 줄 자동 설치 (다운로드부터 바로가기까지)
├── install.bat / run.bat    # Windows 설치·실행 (더블클릭)
├── setup-voice.bat / .sh    # 마이크·음성 라이브러리 설치 + 진단 (더블클릭)
├── setup-autostart.bat/.sh  # 컴퓨터 켤 때 자동 시작 등록 (더블클릭)
├── install.sh  / run.sh     # macOS·Linux 설치·실행
├── config.example.json      # 설정 예시
├── arius/
│   ├── core.py              # 오케스트레이터: 권한검사 → 스킬 라우팅 → LLM
│   ├── permissions.py       # ★ RBAC: 등급·권한·인증·세션
│   ├── memory.py            # SQLite 기억/학습/프로젝트/웹지식 저장소
│   ├── web.py               # 웹 페이지 수집·본문 추출 (urllib / 크롬)
│   ├── embeddings.py        # 임베딩(해싱 / sentence-transformers / ollama) + 문단 분할
│   ├── ollama.py            # 로컬 Ollama HTTP 클라이언트 (표준 라이브러리)
│   ├── voice.py             # 음성 출력(TTS)·입력(STT) + 웨이크워드 대화
│   ├── mic.py               # PyAudio 없는 마이크 캡처 (sounddevice + 음성 구간 감지)
│   ├── setup.py             # 선택 기능 설치·진단 (setup voice / check)
│   ├── autostart.py         # 로그인 자동 시작 (시작프로그램 / LaunchAgent / autostart)
│   ├── minecraft.py         # 서버 핑, RCON, 로컬 서버 프로세스/로그/시작
│   ├── discord.py           # 웹훅·봇 REST 클라이언트
│   ├── discord_chat.py      # 채널 대화 모드 (폴링)
│   ├── sysinfo.py           # CPU/메모리/디스크/프로세스 스냅샷
│   ├── agent/               # 자율 에이전트: tools(도구·허용 목록) / loop(생각-행동) / heartbeat(정기 점검)
│   ├── persona.py           # 자비스 스타일 시스템 프롬프트 생성
│   ├── config.py            # 설정 로딩(JSON, 선택적 YAML)
│   ├── cli.py               # 대화형 REPL + `init`
│   ├── llm/                 # LLM 백엔드 (echo 오프라인 / anthropic 클라우드 / ollama 로컬)
│   └── skills/              # 확장형 기능들 (도움말·기억·시스템·프로젝트·실행…)
└── tests/                   # pytest 스위트
```

---

## 새 스킬 추가하기

`Skill` 을 상속하고 등록만 하면 됩니다:

```python
from arius.skills import Skill, SkillContext
from arius import permissions as perm

class WeatherSkill(Skill):
    name = "weather"
    description = "날씨를 알려줍니다."
    capability = perm.CAP_CHAT           # 필요한 권한
    priority = 25                        # 낮을수록 먼저 검사

    def matches(self, text: str) -> bool:
        return "날씨" in text

    def run(self, ctx: SkillContext, text: str) -> str:
        return "오늘은 맑습니다."        # 실제로는 API 호출 등
```

`arius/skills/builtin.py` 의 `default_skills()` 목록에 추가하면 끝입니다. 권한은 자동으로 강제됩니다.

---

## 테스트

```bash
pip install pytest
python -m pytest -q
```

GitHub Actions(`.github/workflows/ci.yml`)가 `arius-ai/` 를 건드리는 모든 푸시와 PR에서 같은 테스트를 Python 3.10 / 3.11 / 3.12 로 자동 실행하고, ruff 로 문법 오류·미정의 이름을 검사합니다.

---

## 운영 규칙 (자비스 사양)

이 비서는 아래 규칙을 **시스템 프롬프트(`arius/persona.py`)와 코드 양쪽에서** 지킵니다. LLM이 없어도 스킬 응답은 같은 형식을 씁니다.

### 대화 원칙과 응답 형식

- 항상 한국어, 친절하되 짧게. 호출어("자비스")를 들으면 **"네, 말씀하세요."**, 못 알아들으면 추측 실행 대신 **"잘 듣지 못했습니다. 다시 말씀해 주시겠어요?"**
- 연결되지 않은 기능·권한 없는 작업은 실행한 척하지 않습니다.

| 상황 | 형식 |
|---|---|
| 안전한 작업 전 | `실행하겠습니다: [작업 내용]` |
| 확인이 필요한 작업 전 | `실행 예정: [작업]` / `영향: [예상 결과·위험]` / `진행할까요?` |
| 작업 후 | `완료했습니다. [핵심 결과]` |
| 오류·거부 | `실행하지 않았습니다.` / `이유: [원인]` / `다음 조치: [안전한 해결 방법]` |

### 반드시 확인을 받는 작업

- **PC**: 파일·폴더 삭제(휴지통 우선), 프로그램 설치·제거, 시스템/레지스트리/보안 설정 변경, 관리자 권한 실행, 재부팅·종료·절전, 계정·비밀번호·권한 변경, 외부 메시지 전송, 결제, 자동화 스크립트 실행, 외부 업로드, **프로그램 종료**. 이 중 대부분은 아예 도구가 없어 **할 수 없고**, 프로그램 종료만 2단계 확인으로 가능합니다.
- **마인크래프트 서버**: 중지·재시작, 월드/설정/모드/플러그인 삭제·교체(도구 없음), 버전 변경(도구 없음), 킥·밴·화이트리스트 제거, OP 부여·회수, 공개/네트워크 설정 변경(도구 없음).
- **디스코드(메테노디코)**: 계정·데이터 삭제, 권한 변경, 공개 설정, 비용 발생, 서비스 중지·재시작, 중요 설정 변경 — 현재 디스코드 도구는 공지·최근 메시지 읽기뿐이라 이런 작업은 하지 않습니다.
- 재시작 전 사전 점검: **접속자 수 · 예상 중단 시간 · 최근 백업 · 공지 필요 여부** 를 먼저 보여줍니다.

> "메테노디코"는 메테노서버의 디스코드로 해석했습니다. 다른 프로그램/서비스를 뜻한다면 정확한 이름·접속 방식·허용 명령을 알려주면 그에 맞는 스킬을 추가할 수 있습니다.

### 장기 기억 규칙

- 저장하는 것: 호칭·말투 선호, 자주 쓰는 프로그램·작업, 서버 구성, 반복 오류와 해결 결과, "기억해"라고 명시한 정보, 자주 승인·거절한 작업 방식.
- **저장하지 않는 것**: 비밀번호, API 키, 인증 토큰, 금융 정보, 주민번호, 개인 파일 원문. `arius/privacy.py` 가 패턴을 감지해 **기억·대화 로그·데몬 로그·음성 출력 모두에서 가립니다.**
- 모든 기억에 **저장 날짜 · 출처(사용자/에이전트/시스템) · 신뢰도 · 마지막 확인 날짜** 가 붙고 `기억 목록` 에 표시됩니다.
- 명령: `이것을 기억해: …`, `기억 삭제: …`, `네가 기억하는 내용을 보여줘`, `내 정보를 모두 잊어`(→ `네, 모두 잊어` 재확인).
- 학습 후 보고 형식: 새로 기억한 내용 / 근거 및 신뢰도 / 앞으로 달라지는 동작 / 사용자에게 필요한 승인 / 삭제 또는 수정 방법.

### 행동 학습 (승인 이력)

에이전트가 확인을 구한 결과(승인/거절)를 기록합니다. 같은 도구가 **3번 연속 승인**되면 "'자동 허용 추가: <도구>' 라고 말하면 다음부터 묻지 않겠다"고 **제안만** 하고, 승인 없이는 바꾸지 않습니다. 서버 중지·재시작·프로그램 종료 같은 위험 도구는 음성/채팅으로 자동 허용에 넣을 수 없습니다(config 직접 편집만). `학습 보고` 또는 `학습 모드` 로 현황을 봅니다.

### 운영 모드

| 모드 | 말하기 | 동작 |
|---|---|---|
| 빠른 | `빠른 모드` | 짧은 답, 에이전트 3단계, 최근 대화 4개만 참고 |
| 정확 (기본) | `정확 모드` | 로그·설정·과거 기록 교차 검토, 서버 작업 기본 |
| 학습 | `학습 모드` | 승인 이력·반복 오류 분석 → 기억/자동화 후보 제안 (즉시 학습 보고) |
| 점검 | `점검 모드` | 즉시 PC + 서버 전체 점검, 문제를 우선순위별로 보고 |
| 절전 | `절전 모드` | 하트비트 정지, 호출어·직접 요청·예약 점검에만 반응 |

모드는 기억에 저장되어 재시작 후에도 유지됩니다 (`/mode`, `현재 모드`).

### 자동 상태 감시 (하트비트 내장 알림)

정책이 없어도 하트비트마다 **디스크 ≥ 90% · 메모리 ≥ 92% · CPU ≥ 95% · 서버 로그 오류 5건 이상 반복 · 백업 48시간 초과/없음** 을 감지해 **원인 → 영향 → 권장 조치** 로 알립니다. 같은 문제는 처음 한 번만 알리고, 해소되면 다시 감시합니다. 임계값은 `agent.alert_*`.

### PC 제어 (`desktop`)

- 실행: 내장 이름(메모장, 계산기, 그림판, 탐색기, 터미널, 크롬, 엣지, 디스코드, 스팀 …) + `desktop.programs` 에 등록한 것만. 등록되지 않은 프로그램은 "실행하지 않았습니다"로 안내.
- 열기: URL, 내장 사이트(유튜브, 구글, 네이버, 깃허브 …)와 `desktop.sites`, 폴더(다운로드/문서/바탕화면 …)와 `desktop.folders`, 실제 경로. `allow_any_url: false` 면 등록된 사이트만.
- 종료: `X 종료해` → 영향 안내 → `종료 확인: X`. `protected_processes`(java, explorer, python …)는 절대 종료하지 않음. 강제 종료(`/F`)는 기본 아님.
- 창 전환: Windows `AppActivate`, macOS `osascript`, Linux `wmctrl`.
- 삭제·설치·레지스트리·보안 설정·재부팅 도구는 **없습니다.** 정리는 "제안"만 합니다.

### 모델 개선·재학습

비서는 승인 없이 자신의 모델·프롬프트·자동화·설정을 바꾸지 않습니다. 개선이 필요하면 먼저 **개선 기능 / 필요한 데이터 / 예상 향상 / 필요한 자원과 시간 / 비용 / 보안·개인정보 위험 / 백업·되돌리기 / 테스트 방법과 성공 기준** 을 보고하도록 프롬프트에 고정되어 있습니다. (실제 재학습 파이프라인은 로드맵 — "학습의 진실" 참고.)

---

## 안전 & 주의

- `system.exec` 는 **실제 셸 명령을 실행**합니다. 오너/관리자가 직접 칠 때만 쓰이며, **자율 에이전트는 이 기능에 접근할 수 없습니다.** 신뢰할 수 없는 사람에게 그 등급을 주지 마십시오.
- RCON 암호·디스코드 토큰·웹훅 URL은 환경변수(`ARIUS_RCON_PASSWORD`, `ARIUS_DISCORD_TOKEN`, `ARIUS_DISCORD_WEBHOOK`)에 두는 것을 권장합니다.
- `config.json` 과 `*.db` 에는 개인 정보·암호 해시가 담길 수 있어 `.gitignore` 처리되어 있습니다. 공개 저장소에 올리지 마십시오.
- 이 비서는 당신의 컴퓨터에서, 당신이 준 권한 안에서만 동작합니다.

---

## 로드맵 아이디어

- [x] 웹 학습 (URL/크롬 수집 → 저장 → 회상)
- [x] 음성 입출력 (STT/TTS) — "말하는" 자비스
- [x] 임베딩 기반 의미 회상 (기억·웹 지식 유사도 검색, 문단 단위)
- [x] 로컬 모델 백엔드(Ollama) — 완전 오프라인 추론 + 로컬 임베딩
- [x] 자율 에이전트(관찰→생각→행동, 정책, 하트비트, 안전 경계)
- [x] 마인크래프트 서버 관리(핑·RCON·로그·시작/재시작) + 디스코드 공지/대화 봇
- [x] 이름을 부르면 대답하는 음성 대화
- [x] 감정이 있는 대화 (말투 옵션, 기분 상태, 오너 관계)
- [x] 운영 규칙: 고정 응답 형식, 확인 필수 작업, 비밀 정보 차단, 기억 메타데이터, 운영 모드, 승인 학습
- [x] PC 제어(실행·종료·창 전환·열기), 서버 점검 7단계, 월드 백업, 화이트리스트/OP/밴 조회, 재시작 사전 점검
- [ ] 디스코드 게이트웨이(실시간 이벤트·음성 채널) — 현재는 REST 폴링
- [ ] 오프라인 웨이크워드 엔진(Porcupine/Vosk) — 현재는 STT 전사 기반
- [ ] LoRA 미세조정 워크플로 (로컬 모델 위에)
- [ ] 스마트홈/기기 제어 스킬 (권한으로 통제)
- [ ] 웹/파일 도구 스킬

MIT 라이선스.
