"""Cross-platform machine snapshot for the agent, standard library only."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _run(args: list[str], timeout: float = 10.0) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def memory_info() -> dict:
    """total/available in MB, best effort per OS."""
    try:
        if sys.platform.startswith("linux"):
            info = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                k, _, v = line.partition(":")
                info[k.strip()] = int(v.strip().split()[0]) // 1024
            total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
        elif sys.platform == "darwin":
            total = int(_run(["sysctl", "-n", "hw.memsize"]).strip() or 0) // (1024 * 1024)
            page = 4096
            free_pages = 0
            for line in _run(["vm_stat"]).splitlines():
                if "page size of" in line:
                    page = int("".join(ch for ch in line if ch.isdigit()) or 4096)
                if line.startswith(("Pages free", "Pages inactive", "Pages speculative")):
                    free_pages += int(line.split(":")[1].strip().rstrip("."))
            avail = free_pages * page // (1024 * 1024)
        elif sys.platform == "win32":
            out = _run(["powershell", "-NoProfile", "-Command",
                        "$o=Get-CimInstance Win32_OperatingSystem; '{0} {1}' -f $o.TotalVisibleMemorySize,$o.FreePhysicalMemory"])
            t, f = (out.split() + ["0", "0"])[:2]
            total, avail = int(float(t)) // 1024, int(float(f)) // 1024
        else:
            total = avail = 0
    except (OSError, ValueError):
        total = avail = 0
    used_pct = round(100 * (1 - avail / total), 1) if total else 0.0
    return {"total_mb": total, "available_mb": avail, "used_pct": used_pct}


def cpu_info() -> dict:
    cores = os.cpu_count() or 1
    load_pct = None
    try:
        if hasattr(os, "getloadavg"):
            load1 = os.getloadavg()[0]
            load_pct = round(100 * load1 / cores, 1)
        elif sys.platform == "win32":
            out = _run(["powershell", "-NoProfile", "-Command",
                        "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"])
            load_pct = float(out.strip() or 0)
    except (OSError, ValueError):
        pass
    return {"cores": cores, "load_pct": load_pct}


def disk_info(paths: list[str] | None = None) -> list[dict]:
    targets = paths or [str(Path.home()), os.environ.get("SystemDrive", "C:") + "\\" if sys.platform == "win32" else "/"]
    out = []
    seen = set()
    for p in targets:
        try:
            usage = shutil.disk_usage(p)
            anchor = Path(p).anchor or p
            if anchor in seen:
                continue
            seen.add(anchor)
            out.append({"path": p, "total_gb": round(usage.total / 1e9, 1), "free_gb": round(usage.free / 1e9, 1),
                        "used_pct": round(100 * usage.used / usage.total, 1) if usage.total else 0.0})
        except OSError:
            continue
    return out


def top_processes(limit: int = 6) -> list[dict]:
    procs: list[dict] = []
    try:
        if sys.platform == "win32":
            out = _run(["powershell", "-NoProfile", "-Command",
                        f"Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First {limit} | "
                        "ForEach-Object { '{0}|{1}|{2}' -f $_.Id, [math]::Round($_.WorkingSet64/1MB), $_.ProcessName }"])
            for line in out.splitlines():
                pid, mem, name = (line.split("|", 2) + ["", ""])[:3]
                if pid.strip().isdigit():
                    procs.append({"pid": int(pid), "mem_mb": float(mem or 0), "name": name.strip()})
        else:
            args = ["ps", "-Aceo", "pid=,rss=,comm=", "-r"] if sys.platform == "darwin" else ["ps", "-eo", "pid=,rss=,comm=", "--sort=-rss"]
            for line in _run(args).splitlines()[:limit]:
                bits = line.split(None, 2)
                if len(bits) == 3 and bits[0].isdigit():
                    procs.append({"pid": int(bits[0]), "mem_mb": round(int(bits[1]) / 1024, 1), "name": bits[2]})
    except (OSError, ValueError):
        pass
    return procs[:limit]


def uptime_hours() -> float | None:
    try:
        if sys.platform.startswith("linux"):
            return round(float(Path("/proc/uptime").read_text().split()[0]) / 3600, 1)
        if sys.platform == "darwin":
            out = _run(["sysctl", "-n", "kern.boottime"])
            sec = int(out.split("sec =")[1].split(",")[0])
            return round((time.time() - sec) / 3600, 1)
        if sys.platform == "win32":
            out = _run(["powershell", "-NoProfile", "-Command",
                        "((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalHours"])
            return round(float(out.strip()), 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def snapshot(disk_paths: list[str] | None = None) -> dict:
    return {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": cpu_info(),
        "memory": memory_info(),
        "disks": disk_info(disk_paths),
        "uptime_hours": uptime_hours(),
        "top_processes": top_processes(),
    }


def describe(snap: dict) -> str:
    cpu = snap.get("cpu", {})
    mem = snap.get("memory", {})
    lines = [f"[{snap.get('time')}] {snap.get('os')}  가동 {snap.get('uptime_hours') or '?'}시간"]
    load = cpu.get("load_pct")
    lines.append(f"CPU: {cpu.get('cores')}코어, 부하 {load if load is not None else '?'}%")
    lines.append(f"메모리: {mem.get('used_pct')}% 사용 ({mem.get('available_mb')}MB 여유 / {mem.get('total_mb')}MB)")
    for d in snap.get("disks", []):
        lines.append(f"디스크 {d['path']}: {d['used_pct']}% 사용, {d['free_gb']}GB 여유")
    tops = snap.get("top_processes") or []
    if tops:
        lines.append("상위 프로세스: " + ", ".join(f"{p['name']}({p['mem_mb']:.0f}MB)" for p in tops))
    return "\n".join(lines)
