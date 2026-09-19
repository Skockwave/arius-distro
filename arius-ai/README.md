# ARIUS — 로컬 개인 AI 비서

> **A**daptive **R**esponsive **I**ntelligent **U**ser **S**ystem
> 영화 속 인공지능 비서(예: 자비스)처럼 대화하고, 기억하고, **권한 등급에 따라 통제되는** 개인용 AI 시스템입니다.
> 내 컴퓨터에서 직접 돌아갑니다.

---

## 이게 뭔가요 (그리고 무엇이 현실적인가요)

요청하신 목표를 실제로 만들 수 있는 것과, 아직은 공상과학인 것으로 나눠 솔직하게 정리했습니다.

| 목표 | 이 프로젝트가 실제로 제공하는 것 |
|------|-------------------------------|
| **"자비스처럼 대화"** | ✅ 정중하고 유능한 페르소나로 대화. 클라우드(Claude) **또는 내 PC의 로컬 모델(Ollama)** 로 진짜 추론, 둘 다 없어도 오프라인으로 동작 |
| **"권한에 따라 통제"** | ✅ **RBAC(역할 기반 접근 제어)** — 오너/관리자/운영자/사용자/게스트 5단계. 각 기능마다 필요한 권한이 있고, 등급이 낮으면 시스템이 차단 |
| **"고난이도의 학습"** | ✅ 영구 기억 + **의미 기반 회상(임베딩 유사도)** + **웹 학습**. 가르친 사실뿐 아니라 **웹 페이지(URL)를 읽어 본문을 수집·저장**하고 회상. 크롬(Chromium) 렌더링 옵션 지원. (⚠️ 개인 PC에서 모델을 처음부터 훈련시키는 것은 비현실적 — 아래 "학습의 진실" 참고) |
| **"슈트 제작"** | ⚠️ 소프트웨어는 물리적 슈트를 만들 수 없습니다. 대신 **프로젝트 관리 기능**으로 '슈트' 프로젝트의 계획·기록·진행을 도와줍니다 (아이언맨의 자비스도 실제로는 CAD/제어 소프트웨어였습니다) |
| **"말하는" 자비스 (음성)** | ✅ 답변을 **음성으로 읽어주고**(TTS), **마이크로 듣습니다**(STT). 라이브러리가 없어도 OS 내장 음성으로 동작하고, 아무것도 없으면 조용히 텍스트로 폴백 |

즉, 이 저장소는 **진짜로 실행되는 개인 AI 비서의 뼈대**입니다. 추가 설치 없이 바로 켜지고, API 키를 넣으면 실제 대형 언어 모델로 똑똑해집니다.

---

## 내 컴퓨터에 설치하기

핵심 기능은 **파이썬 표준 라이브러리만으로** 동작합니다. 필요한 건 **Python 3.10 이상** 하나뿐입니다.

### 1) 코드 받기

- **ZIP**: GitHub 저장소 페이지에서 브랜치 선택 → 초록색 **Code** → **Download ZIP** → 압축 해제 → 그 안의 `arius-ai` 폴더를 씁니다.
- **git**:
  ```bash
  git clone https://github.com/Skockwave/arius-distro.git
  cd arius-distro/arius-ai
  ```
  (아직 `main`에 합쳐지기 전이라면 `git clone -b claude/high-performance-ai-system-ibqiwl …`)

### 2) Windows — 더블클릭 두 번

1. Python이 없다면 https://www.python.org/downloads/ 에서 설치. 설치 화면 맨 아래 **"Add python.exe to PATH" 체크 필수**.
2. `arius-ai` 폴더의 **`install.bat` 더블클릭** → Python 확인 → 가상환경(.venv) 생성 → 선택 기능 설치 여부 → 오너 계정·백엔드 설정(`init`).
3. 이후에는 **`run.bat` 더블클릭**으로 실행. 바탕화면 바로가기: `run.bat` 우클릭 → 보내기 → 바탕 화면(바로 가기 만들기).

`run.bat`은 콘솔을 UTF-8로 맞춰 주므로 **한글이 깨지지 않습니다.** 음성으로 실행하려면 바로가기의 "대상" 끝에 ` run --voice` 를 붙이십시오.

### 3) macOS / Linux — 명령 두 줄

```bash
bash install.sh     # Python 확인 → .venv → 선택 기능 → init
./run.sh            # 실행 (음성: ./run.sh run --voice)
```

### 4) 직접 실행 (스크립트 없이)

```bash
cd arius-ai
python main.py init     # 설정과 오너 계정 생성 (대화형)
python main.py          # 실행
```

### 5) 선택 — 더 똑똑하게

| 원하는 것 | 할 일 |
|---|---|
| 진짜 추론 (클라우드) | `pip install anthropic` + 환경변수 `ANTHROPIC_API_KEY` + `init`에서 2번 |
| 진짜 추론 (완전 오프라인) | https://ollama.com 설치 → `ollama pull exaone3.5` → `init`에서 3번 |
| 말하는 자비스 | `pip install pyttsx3` (없어도 OS 내장 음성으로 동작) |
| 마이크 입력 | `pip install SpeechRecognition pyaudio` |

### 문제가 생기면

- **`python`을 찾을 수 없음** → Python 설치 시 "Add to PATH"를 안 켠 경우. 재설치하거나 `install.bat`이 `py` 런처를 자동으로 찾습니다.
- **한글이 깨짐** → `run.bat` / `run.sh`로 실행하십시오(UTF-8 자동 설정). 직접 실행 시엔 Windows에서 `chcp 65001` 후 실행.
- **`/exec` 명령이 Windows에서 안 됨** → `dir`, `echo` 같은 cmd 내장 명령도 지원합니다. 오너/관리자 등급인지 `/whoami`로 확인하십시오.
- **가상환경 생성 실패(Ubuntu)** → `sudo apt install python3-venv` 후 재실행. 실패해도 시스템 Python으로 계속 동작합니다.

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
ARIUS › 죄송하지만 그 작업에는 'system.exec' 권한이 필요합니다.
        현재 게스트님의 등급은 '게스트'이라 실행할 수 없습니다.
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
| `기억해: 내 생일은 3월 2일` | 사실을 학습(저장) | memory.write |
| `내 생일 기억나?` | 저장한 사실 회상 | memory.read |
| `기억 목록` | 저장한 모든 사실 나열 | memory.read |
| `학습해: https://...` / `크롬으로 학습해: https://...` | 웹 페이지를 읽어 학습 | web.learn |
| `웹에서 포지 설치 찾아줘` | 학습한 웹 내용 회상 | web.read |
| `프로젝트 생성 슈트` / `프로젝트 목록` | 프로젝트 관리 | project.manage |
| `사용자 추가 friend user` / `권한 변경 friend admin` | 계정 관리 | user.manage |
| `/exec echo hi`, `명령 실행: ls` | 셸 명령 실행 (위험) | system.exec |
| 그 외 아무 말 | 자유 대화(LLM) | chat |

세션 명령: `/login <아이디>`, `/logout`, `/quit`. 음성: `/voice on|off`, `/listen`. 기타: `/reindex`(기억 벡터 재색인).

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

키가 없거나 패키지가 없으면 자동으로 오프라인 모드로 **안전하게 되돌아갑니다** (비서는 계속 동작).

### 또는 로컬 모델로 (Ollama — 무료, 완전 오프라인, API 키 없음)

1. https://ollama.com 에서 Ollama 설치 (Windows/macOS/Linux)
2. 모델 받기 — 터미널에서:
   ```bash
   ollama pull llama3.1      # 범용 기본값 (약 4.7GB)
   ollama pull exaone3.5     # 한국어에 강함 (LG AI연구원)
   ollama pull qwen2.5       # 한국어 포함 다국어 우수
   ```
3. `config.json`:
   ```json
   "llm": { "backend": "ollama", "model": "exaone3.5" }
   ```
   (`python main.py init` 에서 "3) 로컬 모델"을 고르면 자동으로 설정됩니다.)

추가 파이썬 패키지는 필요 없습니다 — `localhost:11434` 로 직접 통신합니다. 서버가 꺼져 있거나 모델을 안 받았으면 **무엇을 하면 되는지 알려주고** 오프라인 모드로 계속 동작합니다:

```
ARIUS › ... (알림: 요청하신 백엔드를 쓸 수 없어 오프라인 모드로 답했습니다 —
        모델 'exaone3.5'이(가) 준비되어 있지 않습니다. 터미널에서 `ollama pull exaone3.5` 을 실행하십시오.)
```

임베딩도 로컬 신경망으로 바꾸려면 `ollama pull bge-m3` 후 `"embeddings": { "backend": "ollama" }` 로 두고 `/reindex` — 이러면 **대화·기억·회상 전부가 내 PC 안에서만** 돌아갑니다.

---

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
├── install.bat / run.bat    # Windows 설치·실행 (더블클릭)
├── install.sh  / run.sh     # macOS·Linux 설치·실행
├── config.example.json      # 설정 예시
├── arius/
│   ├── core.py              # 오케스트레이터: 권한검사 → 스킬 라우팅 → LLM
│   ├── permissions.py       # ★ RBAC: 등급·권한·인증·세션
│   ├── memory.py            # SQLite 기억/학습/프로젝트/웹지식 저장소
│   ├── web.py               # 웹 페이지 수집·본문 추출 (urllib / 크롬)
│   ├── embeddings.py        # 임베딩(해싱 / sentence-transformers / ollama) + 문단 분할
│   ├── ollama.py            # 로컬 Ollama HTTP 클라이언트 (표준 라이브러리)
│   ├── voice.py             # 음성 출력(TTS)·음성 입력(STT), 전부 선택형
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

---

## 안전 & 주의

- `system.exec` 는 **실제 셸 명령을 실행**합니다. 오너/관리자에게만 부여하고, 신뢰할 수 없는 사람에게 그 등급을 주지 마십시오.
- `config.json` 과 `*.db` 에는 개인 정보·암호 해시가 담길 수 있어 `.gitignore` 처리되어 있습니다. 공개 저장소에 올리지 마십시오.
- 이 비서는 당신의 컴퓨터에서, 당신이 준 권한 안에서만 동작합니다.

---

## 로드맵 아이디어

- [x] 웹 학습 (URL/크롬 수집 → 저장 → 회상)
- [x] 음성 입출력 (STT/TTS) — "말하는" 자비스
- [x] 임베딩 기반 의미 회상 (기억·웹 지식 유사도 검색, 문단 단위)
- [x] 로컬 모델 백엔드(Ollama) — 완전 오프라인 추론 + 로컬 임베딩
- [ ] LoRA 미세조정 워크플로 (로컬 모델 위에)
- [ ] 스마트홈/기기 제어 스킬 (권한으로 통제)
- [ ] 웹/파일 도구 스킬

MIT 라이선스.
