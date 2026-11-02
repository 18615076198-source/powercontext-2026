"""高德 Web 服务 API 客户端（标准库 + requests）。

设计要点
--------
* Key：只从环境变量 AMAP_KEY 读取，绝不落盘、不写进代码 / fixtures / 日志（日志中打码）。
* 离线：AMAP_MOCK=1 时使用 MockBackend（读取 fixtures/mock_world.json），
  无网络、无 Key 也能跑通全部测试。
* 可靠性：单请求超时（连接 1.5s / 读取 3s）、总预算 8s（Deadline）、
  失败重试 1 次（指数退避）、限流（默认 3 QPS）、线程安全内存 LRU 缓存。
* 错误：统一解析 status / infocode，映射为用户可读文案 + 处置建议。
* 缓存：地理编码 24h、周边搜索 30min、路径规划 10min。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

if __package__:
    from . import geo
else:  # 直接以脚本方式运行
    import geo  # type: ignore

try:  # requests 只在联网模式需要；离线模式不 import 也能跑
    import requests  # type: ignore
except Exception:  # pragma: no cover - 取决于运行环境
    requests = None  # type: ignore

LOGGER = logging.getLogger("amap")
LOGGER.addHandler(logging.NullHandler())  # 默认静默，configure_logging() 后才输出

API_BASE = "https://restapi.amap.com"

# ---- 缓存 TTL（秒） ----
TTL_GEOCODE = 24 * 3600
TTL_PLACE = 30 * 60
TTL_ROUTE = 10 * 60
TTL_DISTANCE = 10 * 60
TTL_TIPS = 30 * 60
TTL_WEATHER = 30 * 60

DEFAULT_QPS = 3.0
DEFAULT_BUDGET_S = 8.0
DEFAULT_CONNECT_TIMEOUT = 1.5
DEFAULT_READ_TIMEOUT = 3.0
MOCK_KEY = "mock-offline"


# ---------------------------------------------------------------------------
# 错误码
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ErrorInfo:
    code: str
    message: str            # 用户可读文案
    suggestion: str         # 下一步建议
    category: str           # auth / quota / rate / param / no_result / route / network / server / budget / config
    retryable: bool = False


# infocode -> (用户可读文案, 处置建议, 分类, 是否可重试)
_RAW_INFO_CODES: Dict[str, Tuple[str, str, str, bool]] = {
    "10000": ("请求成功", "", "ok", False),
    "10001": ("Key 不正确或已过期", "请检查环境变量 AMAP_KEY 是否为有效的「Web 服务」Key", "auth", False),
    "10002": ("该 Key 未开通此服务", "请到高德控制台为 Key 开通 Web 服务 API 权限", "auth", False),
    "10003": ("今日调用配额已用尽", "请明日再试、更换 Key，或在高德控制台提升配额", "quota", False),
    "10004": ("访问过于频繁，已被限流", "已自动降频，请稍后重试", "rate", True),
    "10005": ("IP 不在白名单内", "请在高德控制台为该 Key 配置 IP 白名单", "auth", False),
    "10006": ("域名不在白名单内", "请在高德控制台为该 Key 配置域名白名单", "auth", False),
    "10007": ("数字签名不匹配", "请检查 AMAP_SIGNATURE / 签名算法，或取消签名校验", "auth", False),
    "10008": ("Key 数字签名校验失败", "请检查签名参数后重试", "auth", False),
    "10009": ("Key 绑定的平台类型不匹配", "本 Skill 需要「Web 服务」类型的 Key，不是 JS/Android/iOS Key", "auth", False),
    "10010": ("IP 访问次数超限", "请降低频率或提升配额", "quota", False),
    "10011": ("Key 已过期", "请在高德控制台续期或更换 Key", "auth", False),
    "10012": ("Key 未通过审核", "请等待审核通过或更换已生效的 Key", "auth", False),
    "10013": ("Key 已被删除", "请更换有效的 Key", "auth", False),
    "10014": ("QPS 超出限制", "已自动降频重试；也可调低 AMAP_QPS", "rate", True),
    "10015": ("网关超时", "高德服务繁忙，稍后重试", "server", True),
    "10016": ("服务暂时不可用", "高德服务繁忙，稍后重试", "server", True),
    "10017": ("海外 IP 访问受限", "请使用中国大陆网络环境访问", "auth", False),
    "10020": ("服务不可用", "请稍后重试", "server", True),
    "10021": ("并发 QPS 超出限制", "已自动降频重试", "rate", True),
    "10026": ("Key 与绑定账号不一致", "请检查 Key 与账号的绑定关系", "auth", False),
    "10029": ("请求来源不合法", "请检查请求来源配置", "auth", False),
    "10041": ("账号余额不足", "请在高德控制台充值或更换 Key", "quota", False),
    "10044": ("账号已被封禁", "请联系高德开放平台客服", "auth", False),
    "10800": ("服务响应超时", "稍后重试，或缩短查询范围", "server", True),
    "20000": ("未查询到结果", "可以扩大半径、更换类目，或补充更具体的城市 / 地名", "no_result", False),
    "20001": ("缺少必要参数", "请检查请求参数（如 address / location / origin）", "param", False),
    "20002": ("参数非法", "请检查经纬度或地址格式", "param", False),
    "20003": ("参数非法", "请检查请求参数格式", "param", False),
    "20011": ("请求参数错误", "请检查请求参数", "param", False),
    "20800": ("规划点不在中国范围内", "请检查起点 / 终点坐标", "route", False),
    "20801": ("规划点附近没有可通行道路", "请换一个更靠近道路的起终点", "route", False),
    "20802": ("起点与终点距离过近", "已改用直线距离估算", "route", False),
    "20803": ("超出路径规划范围", "距离过远，请改用驾车或缩小范围", "route", False),
    "20804": ("路径规划参数不合法", "请检查起终点与城市参数", "route", False),
    "20805": ("路径规划失败", "请改用直线距离估算（结果会标注「约」）", "route", False),
    "30000": ("暂无数据", "换个关键词或扩大搜索范围试试", "no_result", False),
    "30001": ("数据不存在", "换个关键词或扩大搜索范围试试", "no_result", False),
    # 本地伪错误码（不来自高德，便于统一处理）
    "NO_KEY": ("未配置高德 Key", "请设置环境变量 AMAP_KEY（Web 服务 Key），或使用 AMAP_MOCK=1 离线模式", "config", False),
    "NET_TIMEOUT": ("请求高德服务超时", "网络不稳定，已重试；可稍后再试", "network", True),
    "NET_ERROR": ("无法连接高德服务", "请检查网络或代理设置", "network", True),
    "HTTP_ERROR": ("高德服务返回 HTTP 错误", "已重试；若持续失败请稍后再试", "network", True),
    "BAD_JSON": ("高德服务返回内容无法解析", "可能是网络劫持或服务异常，请稍后重试", "network", True),
    "BUDGET": ("本次查询时间预算已用尽", "已降级为估算结果；可缩小范围后重试", "budget", False),
    "UNKNOWN": ("高德服务返回未知错误", "请稍后重试，或查看日志中的 infocode", "server", False),
}

INFO_CODE_TABLE: Dict[str, ErrorInfo] = {
    code: ErrorInfo(code=code, message=msg, suggestion=sug, category=cat, retryable=retry)
    for code, (msg, sug, cat, retry) in _RAW_INFO_CODES.items()
}


def describe_infocode(code: Optional[str]) -> ErrorInfo:
    """infocode -> ErrorInfo；未知码返回通用提示但保留原码便于排查。"""
    if not code:
        return ErrorInfo(code="UNKNOWN", message="高德服务返回未知错误", suggestion="请稍后重试", category="server")
    key = str(code)
    if key in INFO_CODE_TABLE:
        return INFO_CODE_TABLE[key]
    return ErrorInfo(
        code=key,
        message="高德服务返回错误码 " + key,
        suggestion="可在高德控制台查看该错误码说明，或稍后重试",
        category="server",
    )


class AmapError(Exception):
    """统一的高德调用异常。"""

    def __init__(
        self,
        code: str,
        message: Optional[str] = None,
        *,
        api: str = "",
        payload: Optional[Dict[str, Any]] = None,
        raw_info: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        info = describe_infocode(code)
        self.code = code
        self.info = info
        self.message = message or info.message
        self.suggestion = info.suggestion
        self.category = info.category
        self.retryable = info.retryable
        self.api = api
        self.payload = payload or {}
        self.raw_info = raw_info or ""
        self.cause = cause
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "infocode": self.code,
            "message": self.message,
            "suggestion": self.suggestion,
            "category": self.category,
            "api": self.api,
            "raw_info": self.raw_info,
        }

    def __str__(self) -> str:  # pragma: no cover - 调试用
        return "[%s] %s（%s）" % (self.code, self.message, self.api or "amap")


class BudgetExceeded(AmapError):
    def __init__(self, api: str = "") -> None:
        super().__init__("BUDGET", api=api)


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
def mask_key(key: Optional[str]) -> str:
    """日志脱敏：只保留前 4 位与后 2 位。"""
    if not key:
        return "<empty>"
    text = str(key)
    if len(text) <= 8:
        return "****"
    return text[:4] + "****" + text[-2:]


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def configure_logging(level: int = logging.INFO, stream=None) -> None:
    """配置脱敏日志（重复调用不会重复加 handler）。"""
    logger = logging.getLogger("amap")
    logger.setLevel(level)
    logger.propagate = False
    # 导入时挂了一个 NullHandler 用于静默；这里要判断是否存在"真正输出"的 handler
    has_real_handler = any(not isinstance(item, logging.NullHandler) for item in logger.handlers)
    if not has_real_handler:
        handler = logging.StreamHandler(stream) if stream is not None else logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)


def redact_params(params: Dict[str, Any]) -> Dict[str, Any]:
    safe = dict(params)
    if "key" in safe:
        safe["key"] = mask_key(safe.get("key"))
    return safe


class Deadline:
    """一次查询的总时间预算（默认 8s）。"""

    def __init__(self, budget_s: Optional[float] = None, clock: Callable[[], float] = time.monotonic) -> None:
        if budget_s is None:
            budget_s = env_float("AMAP_BUDGET", DEFAULT_BUDGET_S)
        self.budget_s = float(budget_s)
        self._clock = clock
        self._end = clock() + self.budget_s

    def remaining(self) -> float:
        return max(0.0, self._end - self._clock())

    def expired(self, reserve_s: float = 0.15) -> bool:
        return self.remaining() <= reserve_s

    def check(self, api: str = "") -> None:
        if self.expired():
            raise BudgetExceeded(api=api)

    def sleep_if_possible(self, seconds: float) -> bool:
        if self.remaining() <= seconds + 0.05:
            return False
        time.sleep(seconds)
        return True


class TtlCache:
    """线程安全的内存 LRU + TTL 缓存（键含请求参数哈希）。"""

    def __init__(
        self,
        maxsize: int = 512,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.maxsize = maxsize
        self._clock = clock
        self._data: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return None
            expire_at, value = item
            if expire_at <= self._clock():
                del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            self._data[key] = (self._clock() + float(ttl), value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)
                self.evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"entries": len(self._data), "hits": self.hits, "misses": self.misses, "evictions": self.evictions}


class RateLimiter:
    """简单令牌间隔限流（默认 3 QPS），线程安全。"""

    def __init__(
        self,
        qps: float = DEFAULT_QPS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.qps = max(0.1, float(qps))
        self._interval = 1.0 / self.qps
        self._clock = clock
        self._sleep = sleep
        self._next_at = 0.0
        self._lock = threading.Lock()

    def acquire(self, deadline: Optional[Deadline] = None) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next_at - now
            if wait > 0:
                if deadline is not None and deadline.remaining() <= wait + 0.05:
                    raise BudgetExceeded(api="rate-limit")
                self._sleep(wait)
                now = self._clock()
            self._next_at = max(now, self._next_at) + self._interval


# ---------------------------------------------------------------------------
# 传输层
# ---------------------------------------------------------------------------
class HttpTransport:
    """requests 传输层：单请求超时 + 网络错误统一转 AmapError。"""

    def __init__(
        self,
        base_url: str = API_BASE,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        session: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self._session = session
        self._owns_session = session is None
        self._lock = threading.Lock()

    def _get_session(self):
        if self._session is None:
            with self._lock:
                if self._session is None:
                    if requests is None:
                        raise AmapError("UNKNOWN", "缺少 requests 依赖，无法联网；请 pip install requests 或使用 AMAP_MOCK=1")
                    self._session = requests.Session()
        return self._session

    def close(self) -> None:
        if self._owns_session and self._session is not None:
            try:
                self._session.close()
            except Exception:  # pragma: no cover
                pass
            self._session = None

    def get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if requests is None:
            raise AmapError("UNKNOWN", "缺少 requests 依赖，无法联网；请 pip install requests 或使用 AMAP_MOCK=1", api=path)
        session = self._get_session()
        url = self.base_url + path
        try:
            resp = session.get(url, params=params, timeout=(self.connect_timeout, self.read_timeout))
        except requests.Timeout as exc:  # type: ignore[attr-defined]
            raise AmapError("NET_TIMEOUT", api=path, cause=exc)
        except requests.RequestException as exc:  # type: ignore[attr-defined]
            raise AmapError("NET_ERROR", api=path, cause=exc)
        if resp.status_code >= 500:
            raise AmapError("HTTP_ERROR", "高德服务返回 HTTP %d" % resp.status_code, api=path)
        if resp.status_code != 200:
            raise AmapError("HTTP_ERROR", "高德服务返回 HTTP %d" % resp.status_code, api=path, payload={"body": resp.text[:500]})
        try:
            return resp.json()
        except ValueError as exc:
            raise AmapError("BAD_JSON", api=path, cause=exc)


class CallableTransport:
    """测试 / 录制回放用：把 dict 或 callable 包成传输层。"""

    def __init__(self, handler: Callable[[str, Dict[str, Any]], Dict[str, Any]]) -> None:
        self._handler = handler

    def get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return self._handler(path, params)


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------
def cache_key(api: str, params: Dict[str, Any]) -> str:
    payload = {k: v for k, v in params.items() if k != "key"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return api + ":" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"[]", "null", "None", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> Optional[int]:
    number = _to_float(value)
    return int(number) if number is not None else None


def normalize_poi(raw: Dict[str, Any]) -> Dict[str, Any]:
    """把高德 POI 原始结构统一成内部结构（保留 raw 便于排查）。"""
    if not isinstance(raw, dict):
        return {}
    biz = raw.get("biz_ext")
    if not isinstance(biz, dict):
        biz = {}
    lnglat = geo.parse_lnglat(raw.get("location")) or (None, None)
    tag_text = raw.get("tag") or biz.get("tag") or ""
    tags = [t.strip() for t in str(tag_text).replace("|", ",").split(",") if t.strip()]
    photos = raw.get("photos")
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or "").strip(),
        "typecode": str(raw.get("typecode") or ""),
        "type": str(raw.get("type") or ""),
        "address": raw.get("address") if isinstance(raw.get("address"), str) else "",
        "lng": lnglat[0],
        "lat": lnglat[1],
        "distance_m": _to_float(raw.get("distance")),
        "rating": _to_float(biz.get("rating")),
        "cost": _to_float(biz.get("cost")),
        "open_time": biz.get("open_time") or biz.get("opentime2") or "",
        "tag": tag_text,
        "tags": tags,
        "photos": photos if isinstance(photos, list) else [],
        "city": raw.get("cityname") or "",
        "district": raw.get("adname") or "",
        "province": raw.get("pname") or "",
        "raw": raw,
    }


def normalize_geocode(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    lnglat = geo.parse_lnglat(raw.get("location")) or (None, None)
    return {
        "name": raw.get("formatted_address") or "",
        "lng": lnglat[0],
        "lat": lnglat[1],
        "province": raw.get("province") if isinstance(raw.get("province"), str) else "",
        "city": raw.get("city") if isinstance(raw.get("city"), str) else "",
        "district": raw.get("district") if isinstance(raw.get("district"), str) else "",
        "level": raw.get("level") if isinstance(raw.get("level"), str) else "",
        "adcode": raw.get("adcode") if isinstance(raw.get("adcode"), str) else "",
        "citycode": raw.get("citycode") if isinstance(raw.get("citycode"), str) else "",
        "raw": raw,
    }


class AmapClient:
    """高德 Web 服务客户端。线程安全，可被 ThreadPoolExecutor 共享。"""

    def __init__(
        self,
        key: Optional[str] = None,
        *,
        mock: Optional[bool] = None,
        transport: Optional[Any] = None,
        qps: Optional[float] = None,
        budget_s: Optional[float] = None,
        connect_timeout: Optional[float] = None,
        read_timeout: Optional[float] = None,
        retries: int = 1,
        backoff_s: float = 0.25,
        cache: Optional[TtlCache] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.mock = env_flag("AMAP_MOCK") if mock is None else bool(mock)
        self.key = key if key is not None else os.environ.get("AMAP_KEY", "")
        # 离线模式是本地回放，没有真实配额，不需要限流（显式设置 AMAP_QPS 时仍生效）
        default_qps = 100.0 if self.mock else DEFAULT_QPS
        self.qps = qps if qps is not None else env_float("AMAP_QPS", default_qps)
        self.budget_s = budget_s if budget_s is not None else env_float("AMAP_BUDGET", DEFAULT_BUDGET_S)
        self.retries = max(0, int(retries))
        self.backoff_s = max(0.0, float(backoff_s))
        self.clock = clock
        self.sleep = sleep
        self._cache = cache or TtlCache(clock=clock)
        self._limiter = RateLimiter(self.qps, clock=clock, sleep=sleep)
        self._stats_lock = threading.Lock()
        self.stats: Dict[str, int] = {"requests": 0, "cache_hits": 0, "retries": 0, "errors": 0, "no_result": 0}

        if transport is not None:
            self.transport = transport
        elif self.mock:
            try:
                from .mock_backend import MockBackend  # type: ignore
            except ImportError:
                from mock_backend import MockBackend  # type: ignore
            self.transport = MockBackend()
            if not self.key:
                self.key = MOCK_KEY
        else:
            if not self.key:
                raise AmapError("NO_KEY")
            self.transport = HttpTransport(
                connect_timeout=connect_timeout if connect_timeout is not None else env_float("AMAP_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT),
                read_timeout=read_timeout if read_timeout is not None else env_float("AMAP_READ_TIMEOUT", DEFAULT_READ_TIMEOUT),
            )

    # -- 统计 -------------------------------------------------------------
    def _bump(self, name: str, value: int = 1) -> None:
        with self._stats_lock:
            self.stats[name] = self.stats.get(name, 0) + value

    def cache_stats(self) -> Dict[str, int]:
        return self._cache.stats()

    def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if callable(close):
            close()

    def new_deadline(self) -> Deadline:
        return Deadline(self.budget_s, clock=self.clock)

    # -- 核心请求 ---------------------------------------------------------
    def _request(
        self,
        api: str,
        path: str,
        params: Dict[str, Any],
        ttl: float,
        deadline: Optional[Deadline] = None,
    ) -> Dict[str, Any]:
        clean: Dict[str, Any] = {}
        for key, value in params.items():
            if value is None or value == "":
                continue
            clean[key] = value
        clean["key"] = self.key or MOCK_KEY

        if deadline is not None:
            deadline.check(api)

        ck = cache_key(api, clean)
        cached = self._cache.get(ck)
        if cached is not None:
            self._bump("cache_hits")
            LOGGER.info("cache=hit api=%s key=%s", api, mask_key(clean.get("key")))
            return cached

        last_error: Optional[AmapError] = None
        attempts = self.retries + 1
        for attempt in range(attempts):
            if attempt > 0:
                backoff = self.backoff_s * (2 ** (attempt - 1))
                if deadline is not None and deadline.remaining() <= backoff + 0.1:
                    break
                self.sleep(backoff)
                self._bump("retries")
                LOGGER.info("retry api=%s attempt=%d backoff=%.2fs", api, attempt, backoff)
            try:
                if deadline is not None:
                    deadline.check(api)
                self._limiter.acquire(deadline)
                started = self.clock()
                payload = self.transport.get(path, clean)
                elapsed = self.clock() - started
                self._validate(payload, api)
                self._cache.set(ck, payload, ttl)
                self._bump("requests")
                LOGGER.info(
                    "api=%s elapsed=%.3fs infocode=%s key=%s",
                    api,
                    elapsed,
                    str(payload.get("infocode", "")),
                    mask_key(clean.get("key")),
                )
                return payload
            except AmapError as exc:
                self._bump("errors")
                last_error = exc
                if exc.category == "no_result":
                    self._bump("no_result")
                LOGGER.warning(
                    "api=%s failed infocode=%s category=%s retryable=%s msg=%s",
                    api,
                    exc.code,
                    exc.category,
                    exc.retryable,
                    exc.message,
                )
                if exc.retryable and attempt < attempts - 1:
                    continue
                raise
            except BudgetExceeded:
                raise
            except Exception as exc:  # 非预期异常：统一包装，绝不让调用方崩溃
                self._bump("errors")
                LOGGER.exception("api=%s unexpected error", api)
                raise AmapError("UNKNOWN", "调用高德接口出现未预期异常：%s" % exc, api=api, cause=exc)
        if last_error is not None:
            raise last_error
        raise BudgetExceeded(api=api)

    @staticmethod
    def _validate(payload: Any, api: str) -> None:
        if not isinstance(payload, dict):
            raise AmapError("BAD_JSON", "高德返回结构异常", api=api)
        status = str(payload.get("status", ""))
        infocode = str(payload.get("infocode", "") or "")
        raw_info = str(payload.get("info", "") or "")
        if status == "1" and infocode in ("10000", ""):
            return
        code = infocode or "UNKNOWN"
        info = describe_infocode(code)
        raise AmapError(code, info.message, api=api, payload=payload, raw_info=raw_info)

    # -- 地理编码 / 输入提示 ----------------------------------------------
    def geocode(
        self,
        address: str,
        city: Optional[str] = None,
        deadline: Optional[Deadline] = None,
    ) -> List[Dict[str, Any]]:
        payload = self._request(
            "geocode",
            "/v3/geocode/geo",
            {"address": address, "city": city},
            TTL_GEOCODE,
            deadline,
        )
        geocodes = payload.get("geocodes") or []
        return [normalize_geocode(item) for item in geocodes if isinstance(item, dict)]

    def regeo(self, lng: float, lat: float, deadline: Optional[Deadline] = None) -> Dict[str, Any]:
        payload = self._request(
            "regeo",
            "/v3/geocode/regeo",
            {"location": geo.format_lnglat(lng, lat), "extensions": "all"},
            TTL_GEOCODE,
            deadline,
        )
        block = payload.get("regeocode") or {}
        return block if isinstance(block, dict) else {}

    def inputtips(
        self,
        keywords: str,
        city: Optional[str] = None,
        citylimit: bool = False,
        deadline: Optional[Deadline] = None,
    ) -> List[Dict[str, Any]]:
        try:
            payload = self._request(
                "inputtips",
                "/v3/assistant/inputtips",
                {"keywords": keywords, "city": city, "citylimit": "true" if citylimit else "false"},
                TTL_TIPS,
                deadline,
            )
        except AmapError as exc:
            if exc.category == "no_result":
                return []
            raise
        tips = payload.get("tips") or []
        result = []
        for tip in tips:
            if not isinstance(tip, dict):
                continue
            lnglat = geo.parse_lnglat(tip.get("location")) or (None, None)
            result.append(
                {
                    "id": str(tip.get("id") or ""),
                    "name": str(tip.get("name") or ""),
                    "district": tip.get("district") or "",
                    "address": tip.get("address") or "",
                    "typecode": str(tip.get("typecode") or ""),
                    "citycode": str(tip.get("citycode") or ""),
                    "lng": lnglat[0],
                    "lat": lnglat[1],
                }
            )
        return result

    # -- POI 检索 ---------------------------------------------------------
    def place_around(
        self,
        lng: float,
        lat: float,
        *,
        radius: int = 1000,
        types: Optional[str] = None,
        keywords: Optional[str] = None,
        page: int = 1,
        offset: int = 25,
        extensions: str = "all",
        sortrule: str = "weight",
        deadline: Optional[Deadline] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        try:
            payload = self._request(
                "place/around",
                "/v3/place/around",
                {
                    "location": geo.format_lnglat(lng, lat),
                    "radius": int(radius),
                    "types": types,
                    "keywords": keywords,
                    "offset": int(offset),
                    "page": int(page),
                    "extensions": extensions,
                    "sortrule": sortrule,
                },
                TTL_PLACE,
                deadline,
            )
        except AmapError as exc:
            if exc.category == "no_result":
                return 0, []
            raise
        pois = payload.get("pois") or []
        count = _to_int(payload.get("count")) or 0
        return count, [normalize_poi(item) for item in pois if isinstance(item, dict)]

    def place_text(
        self,
        keywords: str,
        *,
        city: Optional[str] = None,
        citylimit: bool = False,
        page: int = 1,
        offset: int = 25,
        extensions: str = "all",
        deadline: Optional[Deadline] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        try:
            payload = self._request(
                "place/text",
                "/v3/place/text",
                {
                    "keywords": keywords,
                    "city": city,
                    "citylimit": "true" if citylimit else "false",
                    "offset": int(offset),
                    "page": int(page),
                    "extensions": extensions,
                },
                TTL_PLACE,
                deadline,
            )
        except AmapError as exc:
            if exc.category == "no_result":
                return 0, []
            raise
        pois = payload.get("pois") or []
        count = _to_int(payload.get("count")) or 0
        return count, [normalize_poi(item) for item in pois if isinstance(item, dict)]

    # -- 路径规划 ---------------------------------------------------------
    def walking(self, origin: str, destination: str, deadline: Optional[Deadline] = None) -> Dict[str, Any]:
        return self._request(
            "direction/walking",
            "/v3/direction/walking",
            {"origin": origin, "destination": destination},
            TTL_ROUTE,
            deadline,
        )

    def bicycling(self, origin: str, destination: str, deadline: Optional[Deadline] = None) -> Dict[str, Any]:
        return self._request(
            "direction/bicycling",
            "/v4/direction/bicycling",
            {"origin": origin, "destination": destination},
            TTL_ROUTE,
            deadline,
        )

    def driving(
        self,
        origin: str,
        destination: str,
        *,
        strategy: int = 0,
        extensions: str = "base",
        deadline: Optional[Deadline] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "direction/driving",
            "/v3/direction/driving",
            {"origin": origin, "destination": destination, "strategy": strategy, "extensions": extensions},
            TTL_ROUTE,
            deadline,
        )

    def transit(
        self,
        origin: str,
        destination: str,
        *,
        city: Optional[str] = None,
        cityd: Optional[str] = None,
        strategy: int = 0,
        deadline: Optional[Deadline] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "direction/transit",
            "/v3/direction/transit/integrated",
            {
                "origin": origin,
                "destination": destination,
                "city": city,
                "cityd": cityd or city,
                "strategy": strategy,
            },
            TTL_ROUTE,
            deadline,
        )

    def distance(
        self,
        origins: str,
        destination: str,
        *,
        dtype: int = 1,
        deadline: Optional[Deadline] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "distance",
            "/v3/distance",
            {"origins": origins, "destination": destination, "type": int(dtype)},
            TTL_DISTANCE,
            deadline,
        )

    def weather(self, city: Optional[str] = None, adcode: Optional[str] = None, deadline: Optional[Deadline] = None) -> Dict[str, Any]:
        return self._request(
            "weather",
            "/v3/weather/weatherInfo",
            {"city": city or adcode, "extensions": "base"},
            TTL_WEATHER,
            deadline,
        )
