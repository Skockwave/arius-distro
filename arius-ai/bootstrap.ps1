# ARIUS one-line installer for Windows.
#
#   PowerShell에 붙여넣기:
#   irm https://raw.githubusercontent.com/Skockwave/arius-distro/main/arius-ai/bootstrap.ps1 | iex
#
# 하는 일: Python 확인(없으면 winget으로 설치) -> 코드 ZIP 다운로드 -> 바탕 화면\ARIUS 에 복사
#          -> install.bat 실행 -> 바탕화면 "ARIUS" 바로가기 생성.
# 다시 실행해도 안전합니다: config.json 과 .venv 는 보존됩니다.
# 환경변수: ARIUS_DIR (설치 폴더), ARIUS_BRANCH (브랜치 강제), ARIUS_ARCHIVE_URL (ZIP 주소 강제)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Repo     = "Skockwave/arius-distro"
# 기본 설치 위치: 바탕 화면\ARIUS (눈에 잘 띄도록). 바꾸려면 $env:ARIUS_DIR 설정.
$Dest     = if ($env:ARIUS_DIR) { $env:ARIUS_DIR } else { Join-Path ([Environment]::GetFolderPath("Desktop")) "ARIUS" }
$Branches = @()
if ($env:ARIUS_BRANCH) { $Branches += $env:ARIUS_BRANCH }
$Branches += @("main", "claude/high-performance-ai-system-ibqiwl")

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  ARIUS 자동 설치 (Windows)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

function Test-Python {
    foreach ($cmd in @(@("py", "-3"), @("python"))) {
        try {
            $exe = $cmd[0]; $args = @(); if ($cmd.Length -gt 1) { $args = $cmd[1..($cmd.Length - 1)] }
            if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
            & $exe @args -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $true }
        } catch {}
    }
    return $false
}

# --- 1) Python -------------------------------------------------------------
if (Test-Python) {
    Write-Host "[1/4] Python 3.10+ 확인됨." -ForegroundColor Green
} else {
    Write-Host "[1/4] Python 3.10+ 가 없습니다." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "      winget 으로 Python 3.12 를 설치합니다 (1~2분)..."
        winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements `
            --override "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0"
        # refresh PATH for this session
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        if (-not (Test-Python)) {
            Write-Host "      Python 설치는 됐지만 이 창에서 아직 인식되지 않습니다. PowerShell 을 닫고 다시 열어 같은 명령을 한 번 더 실행하십시오." -ForegroundColor Yellow
            exit 1
        }
        Write-Host "      Python 설치 완료." -ForegroundColor Green
    } else {
        Write-Host "      https://www.python.org/downloads/ 에서 Python 3.10+ 를 설치하십시오 ('Add python.exe to PATH' 체크)." -ForegroundColor Yellow
        Write-Host "      설치 후 이 명령을 다시 실행하십시오."
        Start-Process "https://www.python.org/downloads/"
        exit 1
    }
}

# --- 2) Download -----------------------------------------------------------
$tmpRoot = Join-Path $env:TEMP ("arius-bootstrap-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
$srcAi = $null
$urls = @()
if ($env:ARIUS_ARCHIVE_URL) { $urls += $env:ARIUS_ARCHIVE_URL }
foreach ($b in $Branches) { $urls += "https://github.com/$Repo/archive/refs/heads/$b.zip" }

foreach ($url in $urls) {
    try {
        Write-Host "[2/4] 다운로드: $url"
        $zip = Join-Path $tmpRoot "src.zip"
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        $ex = Join-Path $tmpRoot "x"
        Remove-Item -Recurse -Force $ex -ErrorAction SilentlyContinue
        Expand-Archive -Path $zip -DestinationPath $ex -Force
        $found = Get-ChildItem -Path $ex -Recurse -Filter "main.py" | Where-Object { $_.Directory.Name -eq "arius-ai" } | Select-Object -First 1
        if ($found) { $srcAi = $found.Directory.FullName; break }
        Write-Host "      이 브랜치에는 arius-ai 가 없습니다. 다음 후보를 시도합니다." -ForegroundColor Yellow
    } catch {
        Write-Host "      실패: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}
if (-not $srcAi) { Write-Host "코드를 내려받지 못했습니다. 인터넷 연결을 확인하십시오." -ForegroundColor Red; exit 1 }

# --- 3) Copy (preserve config.json / .venv on re-run) ------------------------
Write-Host "[3/4] 설치 폴더: $Dest"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
robocopy $srcAi $Dest /E /NFL /NDL /NJH /NJS /NC /NS /NP /XF config.json /XD .venv .pytest_cache __pycache__ | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Host "파일 복사에 실패했습니다 (robocopy $LASTEXITCODE)." -ForegroundColor Red; exit 1 }
Remove-Item -Recurse -Force $tmpRoot -ErrorAction SilentlyContinue

# --- 4) Install + shortcut ---------------------------------------------------
Write-Host "[4/4] 설치 스크립트를 실행합니다 (질문에 답해 주십시오)..."
Push-Location $Dest
try { & cmd.exe /c "install.bat" } finally { Pop-Location }

try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path $desktop "ARIUS.lnk"))
    $lnk.TargetPath = Join-Path $Dest "run.bat"
    $lnk.WorkingDirectory = $Dest
    $lnk.Description = "ARIUS 로컬 AI 비서"
    $lnk.Save()
    Write-Host ""
    Write-Host "바탕화면에 'ARIUS' 바로가기를 만들었습니다. 더블클릭하면 실행됩니다." -ForegroundColor Green
} catch {
    Write-Host "바로가기 생성은 건너뛰었습니다. $Dest\run.bat 을 더블클릭해 실행하십시오." -ForegroundColor Yellow
}
Write-Host "설치 폴더: $Dest"
