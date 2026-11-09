"""行前准备：高德路径规划 + 和风天气（只读、带缓存与额度护栏）。

边界：

* **只用官方接口**，不猜坐标；地理编码失败就说"查不到"，不编地点；
* **额度护栏**：同一查询缓存 6 小时；每天 ``TRAVEL_DAILY_CAP`` 次到点即停；
* **失败即降级**：接口异常/额度用尽都返回 ``status != ok``，调用方必须如实说查不到；
* 返回的时间/距离是**接口给的实时数据**，不是我们算的，所以卡片和回答里直接引用没问题，
  但必须带「数据时间」和「以出行时实际路况为准」。

高德 key 与和风 key 都从环境变量读，不落代码。
"""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

AMAP_BASE = "https://restapi.amap.com"
CACHE_TTL_ROUTE = 6 * 3600
CACHE_TTL_WEATHER = 3 * 3600
CACHE_TTL_GEO = 30 * 24 * 3600
ROUTE_MODES = {"transit": "公交/地铁", "driving": "驾车", "walking": "步行"}

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()
_dotenv_loaded = False


def _env(name: str) -> str:
    global _dotenv_loaded
    value = (os.getenv(name) or "").strip()
    if value or _dotenv_loaded:
        return value
    _dotenv_loaded = True
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
    except Exception:
        pass
    return (os.getenv(name) or "").strip()


def enabled() -> bool:
    flag = (_env("TRAVEL_ENABLED") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def daily_cap() -> int:
    try:
        return max(0, int(_env("TRAVEL_DAILY_CAP") or 300))
    except ValueError:
        return 300


def _usage_path() -> Path:
    from app import db

    return Path(db.DATA_DIR) / "travel_usage.json"


def _usage() -> dict[str, Any]:
    today = date.today().isoformat()
    try:
        raw = json.loads(_usage_path().read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    if raw.get("date") != today:
        raw = {"date": today, "count": 0}
    raw["cap"] = daily_cap()
    raw["remaining"] = max(0, daily_cap() - int(raw.get("count") or 0))
    return raw


def _bump() -> None:
    with _lock:
        used = _usage()
        used["count"] = int(used.get("count") or 0) + 1
        try:
            _usage_path().parent.mkdir(parents=True, exist_ok=True)
            _usage_path().write_text(
                json.dumps({"date": used["date"], "count": used["count"]}), encoding="utf-8")
        except Exception:
            pass


def _cache_get(key: str, ttl: float) -> dict[str, Any] | None:
    with _lock:
        hit = _cache.get(key)
        if not hit:
            return None
        stamp, value = hit
        if time.monotonic() - stamp > ttl:
            _cache.pop(key, None)
            return None
        return value


def _cache_put(key: str, value: dict[str, Any]) -> None:
    with _lock:
        if len(_cache) > 256:
            _cache.clear()
        _cache[key] = (time.monotonic(), value)


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _http_json(url: str, timeout: float, fetch: Any = None) -> dict[str, Any]:
    if fetch is not None:
        return fetch(url, timeout)
    request = urllib.request.Request(
        url, headers={"User-Agent": "TempleGuide/1.0", "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    if raw[:2] == b"\x1f\x8b":          # 和风会返回 gzip，即使只请求 identity
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _quota_blocked() -> dict[str, Any] | None:
    if not enabled():
        return {"status": "disabled", "reason": "地图/天气未启用"}
    used = _usage()
    if int(used.get("count") or 0) >= daily_cap():
        return {"status": "quota_exhausted", "reason": f"今日额度已用完（{daily_cap()} 次）", "usage": used}
    return None


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ── 地理编码 ────────────────────────────────────────────────────────────────

def geocode(address: str, city: str = "北京", *, timeout: float = 15.0,
            fetch: Any = None) -> dict[str, Any]:
    """地址 → 坐标。失败返回 status != ok（调用方不得编坐标）。"""
    blocked = _quota_blocked()
    if blocked:
        return blocked
    key = _env("AMAP_KEY")
    if not key:
        return {"status": "unconfigured", "reason": "缺少 AMAP_KEY"}
    address = (address or "").strip()
    if not address:
        return {"status": "empty", "reason": "没有地址"}
    cache_key = f"geo|{city}|{address}"
    cached = _cache_get(cache_key, CACHE_TTL_GEO)
    if cached is not None:
        return {**cached, "cached": True}

    query = urllib.parse.urlencode({"address": address, "city": city, "key": key})
    try:
        body = _http_json(f"{AMAP_BASE}/v3/geocode/geo?{query}", timeout, fetch)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": type(exc).__name__}
    _bump()
    if str(body.get("status")) != "1" or not body.get("geocodes"):
        return {"status": "not_found", "reason": str(body.get("info") or "无结果")[:80]}
    item = body["geocodes"][0]
    lng, lat = (item.get("location") or ",").split(",")[:2]
    result = {"status": "ok", "name": address, "lng": float(lng), "lat": float(lat),
              "formatted": str(item.get("formatted_address") or ""),
              "level": str(item.get("level") or ""), "source": "高德地理编码",
              "checked_at": _now_text(), "cached": False}
    _cache_put(cache_key, result)
    return result


# ── 路径规划 ────────────────────────────────────────────────────────────────

def route(origin: tuple[float, float], destination: tuple[float, float], *,
          mode: str = "transit", city: str = "北京", timeout: float = 20.0,
          fetch: Any = None) -> dict[str, Any]:
    """两点间路线。``origin``/``destination`` 是 (lng, lat)。"""
    blocked = _quota_blocked()
    if blocked:
        return blocked
    key = _env("AMAP_KEY")
    if not key:
        return {"status": "unconfigured", "reason": "缺少 AMAP_KEY"}
    mode = mode if mode in ROUTE_MODES else "transit"
    origin_text = f"{origin[0]:.5f},{origin[1]:.5f}"
    dest_text = f"{destination[0]:.5f},{destination[1]:.5f}"
    cache_key = f"route|{mode}|{origin_text}|{dest_text}"
    cached = _cache_get(cache_key, CACHE_TTL_ROUTE)
    if cached is not None:
        return {**cached, "cached": True}

    params = {"origin": origin_text, "destination": dest_text, "key": key}
    if mode == "transit":
        params.update({"city": city, "cityd": city})
        url = f"{AMAP_BASE}/v3/direction/transit/integrated"
    elif mode == "driving":
        url = f"{AMAP_BASE}/v3/direction/driving"
    else:
        url = f"{AMAP_BASE}/v3/direction/walking"
    try:
        body = _http_json(f"{url}?{urllib.parse.urlencode(params)}", timeout, fetch)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": type(exc).__name__}
    _bump()
    if str(body.get("status")) != "1":
        return {"status": "error", "reason": str(body.get("info") or "接口返回异常")[:80]}

    path = body.get("route") or {}
    distance_m = _to_int(path.get("distance"))
    options = path.get("transits") or path.get("paths") or []
    duration_s = 0
    if options:
        duration_s = _to_int(options[0].get("duration"))
    if not duration_s and path.get("duration"):
        duration_s = _to_int(path.get("duration"))
    if not distance_m and not duration_s:
        return {"status": "empty", "reason": "没有可用的路线方案"}

    result = {
        "status": "ok",
        "mode": mode,
        "mode_label": ROUTE_MODES[mode],
        "distance_km": round(distance_m / 1000, 1) if distance_m else None,
        "duration_min": max(1, round(duration_s / 60)) if duration_s else None,
        "options": len(options),
        "source": "高德路径规划",
        "checked_at": _now_text(),
        "cached": False,
        "note": "接口给的预计耗时，实际看路况；出发前请再查一次。",
    }
    _cache_put(cache_key, result)
    return result


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


# ── 天气 ────────────────────────────────────────────────────────────────────

def weather(lng: float, lat: float, *, days: int = 3, timeout: float = 15.0,
            fetch: Any = None) -> dict[str, Any]:
    """和风 3 天预报（含今天）。"""
    blocked = _quota_blocked()
    if blocked:
        return blocked
    key = _env("QWEATHER_KEY")
    host = _env("QWEATHER_HOST") or "https://devapi.qweather.com"
    if not key:
        return {"status": "unconfigured", "reason": "缺少 QWEATHER_KEY"}
    location = f"{lng:.2f},{lat:.2f}"
    days = 3 if int(days or 3) >= 3 else 1
    cache_key = f"weather|{location}|{days}"
    cached = _cache_get(cache_key, CACHE_TTL_WEATHER)
    if cached is not None:
        return {**cached, "cached": True}

    path = "/v7/weather/3d" if days >= 3 else "/v7/weather/now"
    query = urllib.parse.urlencode({"location": location, "key": key})
    try:
        body = _http_json(f"{host.rstrip('/')}{path}?{query}", timeout, fetch)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": type(exc).__name__}
    _bump()
    if str(body.get("code")) != "200":
        return {"status": "error", "reason": f"和风返回 {body.get('code')}"}

    forecasts = []
    for item in (body.get("daily") or [])[:3]:
        forecasts.append({
            "date": str(item.get("fxDate") or ""),
            "text": f"{item.get('textDay') or ''}".strip(),
            "temp_min": _to_int(item.get("tempMin")),
            "temp_max": _to_int(item.get("tempMax")),
            "wind": f"{item.get('windDirDay') or ''}{item.get('windScaleDay') or ''}级".strip(),
            "precip": item.get("precip") or "",
        })
    result = {
        "status": "ok",
        "location": location,
        "forecasts": forecasts,
        "source": "和风天气",
        "checked_at": _now_text(),
        "cached": False,
        "note": "预报会变，出发前一天再看一次。",
    }
    _cache_put(cache_key, result)
    return result


def pick_forecast(forecasts: list[dict[str, Any]], visit_date: str = "") -> dict[str, Any] | None:
    """按日期挑预报；日期超出预报范围返回 None（调用方要如实说查不到）。"""
    if not forecasts:
        return None
    text = (visit_date or "").strip().replace("/", "-")
    if not text:
        return forecasts[0]
    for target in (text, f"{date.today().year}-{text}" if len(text) <= 5 else text):
        for item in forecasts:
            if item.get("date") == target:
                return item
    try:
        wanted = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return forecasts[0]
    last = None
    for item in forecasts:
        try:
            last = datetime.strptime(str(item.get("date")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if last == wanted:
            return item
    if last is not None and wanted > last:
        return None
    if last is not None and wanted < date.today():
        return None
    return forecasts[0]
