"""一句话 -> 结构化请求（规则 + 关键词表，确定性、可单测）。

不引入大模型：纯规则解析，同样的输入永远得到同样的输出。

支持的表达
----------
位置：   我在西湖附近 / 在国贸周边 / 我附近 / 离我 800 米内 / 从五道口出发
城市：   杭州西湖 / 北京国贸 / 上海南京西路
类目：   咖啡、餐厅、夜宵、景点、公园、博物馆、商场、超市、亲子、自习、酒吧、茶馆、电影
约束：   半径、预算、评分门槛、营业中、避开连锁、安静、无障碍、停车、时长、含往返
交通：   步行 / 骑行 / 公交 / 驾车（缺省步行）
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

MAX_RADIUS_M = 3000
DEFAULT_RADIUS_M = 1000
WALKING_RADIUS_HINT_M = 1500


# ---------------------------------------------------------------------------
# 类目表
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CategorySpec:
    id: str
    label: str
    aliases: Tuple[str, ...]
    query_types: Optional[str]      # 召回用高德类型码（优先父类码，兼容性更好）
    search_keyword: Optional[str]   # 类型码召回为空时的兜底关键词
    typecodes: Tuple[str, ...]      # 类目匹配评分用的类型码前缀
    match_keywords: Tuple[str, ...] # POI 名称 / 标签命中即认为类目相符
    cost_band: Tuple[float, float]  # 人均消费的合理区间（用于人气分与预算提示）
    tags: Tuple[str, ...] = ()


CATEGORIES: Dict[str, CategorySpec] = {
    "coffee": CategorySpec(
        "coffee", "咖啡馆", ("咖啡", "咖啡馆", "咖啡厅", "coffee", "手冲", "咖啡店"),
        "050500", "咖啡", ("050500",), ("咖啡", "咖啡厅"), (25, 90), ("安静", "可久坐", "有插座"),
    ),
    "tea": CategorySpec(
        "tea", "茶馆", ("茶馆", "茶室", "喝茶", "奶茶", "茶饮"),
        "050600", "茶", ("050600", "050700"), ("茶",), (20, 120), ("安静", "可久坐"),
    ),
    "restaurant": CategorySpec(
        "restaurant", "餐厅", ("吃饭", "餐厅", "餐馆", "美食", "午饭", "晚饭", "中饭", "晚饭",
                              "火锅", "烧烤", "面馆", "小吃", "聚餐", "吃个饭", "吃"),
        "050100|050200|050300", "餐厅", ("050100", "050200", "050300"), ("餐厅", "菜", "火锅", "小吃"), (30, 200), ("包厢",),
    ),
    "night_snack": CategorySpec(
        "night_snack", "夜宵", ("夜宵", "宵夜", "大排档", "深夜食堂", "夜市"),
        "050300|050100", "夜宵", ("050300",), ("夜宵", "烧烤", "大排档", "粥", "深夜", "小吃"), (20, 120), ("营业到深夜",),
    ),
    "bar": CategorySpec(
        "bar", "酒吧", ("酒吧", "清吧", "小酒馆", "livehouse", "喝酒"),
        "050400", "酒吧", ("050400",), ("酒吧", "酒馆"), (50, 200), (),
    ),
    "park": CategorySpec(
        "park", "公园", ("公园", "草坪", "绿地", "散步", "遛弯", "遛娃", "晒太阳", "湖边"),
        "110101", "公园", ("110101", "110102", "110103"), ("公园", "植物园", "绿地"), (0, 60), ("晒太阳", "草坪"),
    ),
    "attraction": CategorySpec(
        "attraction", "景点", ("景点", "景区", "逛景点", "打卡", "名胜", "古迹", "旅游", "好玩的", "逛逛", "逛"),
        "110000", "景点", ("110200", "110201", "110202", "110203", "110205"), ("景区", "景点", "名胜", "博物馆"), (0, 120), ("网红", "打卡"),
    ),
    "museum": CategorySpec(
        "museum", "博物馆", ("博物馆", "美术馆", "看展", "展览", "科技馆", "纪念馆"),
        "140000", "博物馆", ("140200", "140500", "140000"), ("博物馆", "美术馆", "展览", "纪念馆"), (0, 80), ("需预约",),
    ),
    "library": CategorySpec(
        "library", "图书馆", ("图书馆", "自习室", "自习", "书房", "看书", "学习"),
        "140300", "图书馆", ("140300",), ("图书馆", "自习", "书店"), (0, 40), ("安静", "有插座"),
    ),
    "mall": CategorySpec(
        "mall", "商场", ("商场", "购物中心", "逛街", "买东西", "百货", "广场"),
        "060100", "商场", ("060100", "060101", "060102"), ("商场", "购物中心", "百货"), (0, 300), ("空调",),
    ),
    "supermarket": CategorySpec(
        "supermarket", "超市", ("超市", "便利店", "买水", "买东西"),
        "060400", "超市", ("060400", "060200"), ("超市", "便利店"), (0, 200), (),
    ),
    "kids": CategorySpec(
        "kids", "亲子", ("亲子", "遛娃", "儿童", "带娃", "游乐园", "游乐场", "小孩"),
        "080000", "亲子", ("080000", "080101", "080102"), ("亲子", "儿童", "游乐"), (50, 300), ("适合儿童",),
    ),
    "cinema": CategorySpec(
        "cinema", "电影院", ("电影", "看电影", "影院", "影城"),
        None, "电影院", ("080601", "080600"), ("电影", "影院"), (30, 120), (),
    ),
}

# 多类目意图：一句话里出现这些词时给出组合类目
MULTI_INTENTS: Dict[str, Tuple[str, ...]] = {
    "explore": ("attraction", "park", "museum", "mall"),
    "kids_trip": ("kids", "park", "museum"),
    "study": ("library", "coffee"),
    "date": ("coffee", "bar", "park"),
}

DEFAULT_CATEGORIES = ("attraction", "coffee", "restaurant")


def category_label(cat_id: str) -> str:
    spec = CATEGORIES.get(cat_id)
    return spec.label if spec else cat_id


# ---------------------------------------------------------------------------
# 城市 / 别名
# ---------------------------------------------------------------------------
CITY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "北京市": ("北京", "京"),
    "上海市": ("上海", "沪"),
    "杭州市": ("杭州",),
    "成都市": ("成都",),
    "广州市": ("广州", "羊城"),
    "深圳市": ("深圳",),
    "南京市": ("南京",),
    "西安市": ("西安",),
    "武汉市": ("武汉",),
    "长沙市": ("长沙",),
    "重庆市": ("重庆", "渝"),
    "天津市": ("天津", "津"),
    "苏州市": ("苏州",),
    "青岛市": ("青岛",),
    "厦门市": ("厦门",),
    "郑州市": ("郑州",),
    "合肥市": ("合肥",),
    "济南市": ("济南",),
    "福州市": ("福州",),
    "昆明市": ("昆明",),
}

_ALIAS_TO_CITY: Dict[str, str] = {}
for _city, _aliases in CITY_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_TO_CITY[_alias] = _city

# 城市后紧跟这些字时，通常是被路名/景点名吃掉了（如"南京西路"），不做城市推断
_STREET_SUFFIX = ("路", "街", "道", "巷", "大道", "西路", "东路", "南路", "北路")


def detect_city(text: str) -> Optional[str]:
    """从一句话里推断城市（只做保守推断，宁可交给地理编码，也不强行改城市）。"""
    if not text:
        return None
    # 1) 明确的「XX市」优先级最高
    for alias, city in sorted(_ALIAS_TO_CITY.items(), key=lambda kv: -len(kv[0])):
        if alias + "市" in text:
            return city
    # 2) 开头出现的城市别名 + 后续是地名（排除「南京西路」这类路名）
    for alias, city in sorted(_ALIAS_TO_CITY.items(), key=lambda kv: -len(kv[0])):
        idx = text.find(alias)
        if idx < 0 or idx > 4:
            continue
        rest = text[idx + len(alias):]
        rest = rest.lstrip("市 ")
        if not rest:
            return city
        if any(rest.startswith(sfx) for sfx in _STREET_SUFFIX):
            continue
        if len(rest) >= 2:
            return city
    return None


# ---------------------------------------------------------------------------
# 解析结果
# ---------------------------------------------------------------------------
@dataclass
class ParsedQuery:
    raw: str
    location_text: Optional[str] = None
    location_kind: str = "none"          # absolute / relative / city / none
    city_hint: Optional[str] = None
    city_source: str = "none"             # explicit / default / none
    categories: List[str] = field(default_factory=list)
    intent: str = "single"
    radius_m: int = DEFAULT_RADIUS_M
    max_distance_m: Optional[int] = None
    transport: str = "walking"
    budget_per_person: Optional[float] = None
    min_rating: Optional[float] = None
    require_open: bool = False
    avoid_chain: bool = False
    quiet: bool = False
    accessible: bool = False
    parking: bool = False
    duration_minutes: Optional[int] = None
    round_trip: bool = False
    time_slot: Optional[str] = None
    focus_keywords: List[str] = field(default_factory=list)  # 火锅 / 烧烤 / 夜宵 这类具体口味词
    need_clarification: bool = False
    questions: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    confidence: float = 0.3

    def to_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["category_labels"] = [category_label(c) for c in self.categories]
        return data


# ---------------------------------------------------------------------------
# 词表
# ---------------------------------------------------------------------------
_LOCATION_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"(?:我|我们)?(?:现在|目前|就)?(?:在|位于|身处)\s*(?P<place>[^\s，,。；;]{2,24}?)\s*(?:附近|周边|周围|旁边|一带)"),
    re.compile(r"(?:在|到|去|逛)\s*(?P<place>[^\s，,。；;]{2,24}?)\s*(?:附近|周边|周围|旁边|一带)"),
    re.compile(r"(?P<place>[^\s，,。；;]{2,24}?)\s*(?:附近|周边|周围|旁边|一带)"),
    re.compile(r"从\s*(?P<place>[^\s，,。；;]{2,24}?)\s*(?:出发|过去|走|开始)"),
    re.compile(r"离\s*(?P<place>[^\s，,。；;]{2,24}?)\s*(?:不远|很近|比较近|挺近)"),
    # 句末的「我在五道口」「在西湖」这类不带"附近"的说法
    re.compile(r"(?:我|我们)?(?:现在|目前)?在\s*(?P<place>[^\s，,。；;]{2,24}?)\s*(?:[，,。；;!?！？]|$)"),
)

_RELATIVE_RE = re.compile(r"我\s*(?:就|现在)?\s*(?:在)?\s*(?:附近|这边|这边儿)|我附近|我这边|当前位置|现在的位置|这儿|这里附近|离我\s*\d")

_PLACE_NOISE = ("想找", "想吃", "想看", "找个", "找家", "随便", "帮我", "请问", "推荐", "想", "要", "找", "去", "在", "的", "了", "吗", "呢")
_PLACE_REJECT = {
    "附近", "周边", "周围", "这边", "这边儿", "这儿", "这里", "外面", "家里", "公司", "路上",
    "下午", "上午", "晚上", "中午", "现在", "今天", "明天", "周末", "附近一带", "这附近",
}
for _spec in CATEGORIES.values():
    _PLACE_REJECT.add(_spec.label)
    _PLACE_REJECT.update(_spec.aliases)

_DISTANCE_RE = re.compile(r"(?:离我|附近|周围|周边|范围内|以内|\s)?\s*(\d+(?:\.\d+)?)\s*(公里|千米|km|KM|米|m|M)\s*(?:以内|之内|内|范围)?")
_DISTANCE_NEAR_RE = re.compile(r"(?:离我|从我|距离我)\s*(\d+(?:\.\d+)?)\s*(公里|千米|km|KM|米|m|M)")

_BUDGET_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"预算\s*(?:在|是|大概|约)?\s*(\d+)"),
    re.compile(r"人均\s*(?:不超过|不高于|低于|控制在|大概|约)?\s*(\d+)"),
    re.compile(r"(?:不超过|不高于|低于|控制在|最多)\s*(\d+)\s*(?:块|元|块钱)"),
    re.compile(r"(\d+)\s*(?:块|元|块钱)\s*(?:以内|以下|之内|左右)"),
)

_RATING_RE = re.compile(r"(?:评分|评分要|分数)\s*(\d(?:\.\d)?)\s*(?:分)?\s*(?:以上|及以上|\+)?")
_RATING_SUFFIX_RE = re.compile(r"(\d(?:\.\d)?)\s*分以上")

# 具体口味 / 场景词：用于「精确召回优先」与打分的额外加权
FOCUS_KEYWORDS: Tuple[str, ...] = (
    "火锅", "烧烤", "烤肉", "小龙虾", "麻辣烫", "日料", "川菜", "粤菜",
    "甜品", "披萨", "汉堡", "拉面", "面馆", "粥铺", "砂锅粥", "夜宵", "早茶",
)


def _extract_focus(text: str) -> List[str]:
    return [word for word in FOCUS_KEYWORDS if word in text][:2]


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_to_number(text: str) -> Optional[float]:
    """把「两」「三」「半」「一个半」等中文数量词转成数字。"""
    text = text.strip()
    if not text:
        return None
    if text in {"半", "半小"}:
        return 0.5
    if text.isdigit():
        return float(text)
    if text in _CN_DIGITS:
        return float(_CN_DIGITS[text])
    if text.startswith("十") and len(text) > 1 and text[1] in _CN_DIGITS:
        return 10.0 + _CN_DIGITS[text[1]]
    if text.endswith("十") and len(text) > 1 and text[0] in _CN_DIGITS:
        return _CN_DIGITS[text[0]] * 10.0
    if len(text) == 2 and text[0] in _CN_DIGITS and text[1] in _CN_DIGITS:
        return _CN_DIGITS[text[0]] * 10.0 + _CN_DIGITS[text[1]]
    return None


_DURATION_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"(?P<num>\d+(?:\.\d+)?|[一两二三四五六七八九十半]+)\s*个?\s*(?P<unit>小时|钟头|h|H)"),
    re.compile(r"(?P<num>\d+)\s*分钟"),
    re.compile(r"一个半小时"),
)


def _extract_duration(text: str) -> Tuple[Optional[int], List[str]]:
    notes: List[str] = []
    if "一个半小时" in text:
        return 90, notes
    for pattern in _DURATION_PATTERNS:
        for match in pattern.finditer(text):
            groups = match.groupdict()
            if groups.get("num") is None:
                continue
            num = _cn_to_number(groups["num"])
            if num is None:
                continue
            unit = groups.get("unit") or "分钟"
            minutes = int(round(num * 60)) if unit in ("小时", "钟头", "h", "H") else int(round(num))
            if 5 <= minutes <= 720:
                return minutes, notes
    return None, notes


_TRANSPORT_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("walking", re.compile(r"步行|走路|走着去|腿儿着|徒步|走过去|走到")),
    ("bicycling", re.compile(r"骑行|骑车|单车|自行车|共享单车")),
    ("transit", re.compile(r"公交|地铁|公共交通|坐车|巴士|轻轨|搭车|坐地铁|坐公交")),
    ("driving", re.compile(r"驾车|开车|自驾|打车|出租车|滴滴|开车去|驾车去")),
)


def _extract_transport(text: str) -> Tuple[Optional[str], Optional[int]]:
    hits: List[Tuple[int, str]] = []
    for mode, pattern in _TRANSPORT_PATTERNS:
        match = pattern.search(text)
        if match:
            hits.append((match.start(), mode))
    if not hits:
        return None, None
    hits.sort()
    return hits[0][1], hits[0][0]


def _extract_categories(text: str) -> Tuple[List[str], str]:
    hits: List[Tuple[int, str]] = []
    for cat_id, spec in CATEGORIES.items():
        for alias in spec.aliases:
            idx = text.find(alias)
            if idx >= 0:
                hits.append((idx, cat_id))
    # 多类目意图优先（"逛逛""亲子""自习"等）
    if re.search(r"逛逛|随便逛|附近逛|周边逛|有什么好玩|溜达|转转", text):
        return list(MULTI_INTENTS["explore"]), "explore"
    if re.search(r"亲子|遛娃|带娃|带孩子", text):
        return list(MULTI_INTENTS["kids_trip"]), "kids"
    if re.search(r"自习|看书学习|要学习", text):
        return list(MULTI_INTENTS["study"]), "study"
    if not hits:
        return [], "none"
    hits.sort()
    ordered: List[str] = []
    for _, cat_id in hits:
        if cat_id not in ordered:
            ordered.append(cat_id)
    # "吃"这种单字太泛，只有在没有其他类目时才生效
    if len(ordered) > 1 and "restaurant" in ordered and any(c != "restaurant" for c in ordered):
        first_other = next(i for i, c in enumerate(ordered) if c != "restaurant")
        if first_other == 0:
            ordered.remove("restaurant")
    return ordered[:3], "single" if len(ordered) <= 1 else "multi"


def _clean_place(candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return None
    text = candidate.strip(" 　,，。.、;；:：!！?？的了吗呢啊呀")
    for noise in _PLACE_NOISE:
        if text.startswith(noise) and len(text) > len(noise) + 1:
            text = text[len(noise):]
        if text.endswith(noise) and len(text) > len(noise) + 1:
            text = text[: -len(noise)]
    text = text.strip()
    if len(text) < 2 or len(text) > 20:
        return None
    if text in _PLACE_REJECT:
        return None
    for cat_id, spec in CATEGORIES.items():
        if text == spec.label or text in spec.aliases:
            return None
    return text


def _extract_location(text: str) -> Tuple[Optional[str], str, Optional[Tuple[int, int]]]:
    """返回 (地点文本, 类型, 地名在原文中的区间)。区间用于避免把地名当成类目词。"""
    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        place = _clean_place(match.group("place"))
        if place:
            start, end = match.span("place")
            return place, "absolute", (start, end)
    if _RELATIVE_RE.search(text) or "附近" in text or "周边" in text or "这边" in text:
        return None, "relative", None
    return None, "none", None


def _parse_radius(text: str, notes: List[str]) -> Tuple[int, Optional[int], bool]:
    """返回 (搜索半径, 最大距离约束, 是否被裁剪)。"""
    matched_distance: Optional[int] = None
    strong = _DISTANCE_NEAR_RE.search(text)
    candidates = []
    if strong:
        candidates.append(strong)
    for match in _DISTANCE_RE.finditer(text):
        tail = text[match.end(): match.end() + 4]
        if match.group(2) in ("公里", "千米", "km", "KM") or any(k in tail for k in ("内", "以内", "范围")):
            candidates.append(match)
    for match in candidates:
        value = float(match.group(1))
        unit = match.group(2)
        meters = value * 1000 if unit in ("公里", "千米", "km", "KM") else value
        meters_int = int(round(meters))
        if 50 <= meters_int <= 50000:
            matched_distance = meters_int if matched_distance is None else min(matched_distance, meters_int)
    radius = matched_distance if matched_distance is not None else DEFAULT_RADIUS_M
    clipped = False
    if radius > MAX_RADIUS_M:
        radius = MAX_RADIUS_M
        clipped = True
        notes.append("半径超过 3000 米上限，已按 3000 米检索")
    return int(radius), matched_distance, clipped


def _parse_budget(text: str) -> Optional[float]:
    for pattern in _BUDGET_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            value = float(match.group(1))
        except (TypeError, ValueError):
            continue
        if 1 <= value <= 5000:
            return value
    return None


def _parse_rating(text: str) -> Optional[float]:
    for pattern in (_RATING_RE, _RATING_SUFFIX_RE):
        match = pattern.search(text)
        if match:
            try:
                value = float(match.group(1))
            except (TypeError, ValueError):
                continue
            if 3.0 <= value <= 5.0:
                return value
    if re.search(r"高分|口碑好|评分高", text):
        return 4.3
    return None


_TIME_SLOTS = (
    ("早上", ("早上", "早晨", "上午")),
    ("中午", ("中午", "午饭")),
    ("下午", ("下午", "午后")),
    ("晚上", ("晚上", "今晚", "夜里", "夜间")),
    ("深夜", ("深夜", "半夜", "凌晨")),
)


def _parse_time_slot(text: str) -> Optional[str]:
    for slot, words in _TIME_SLOTS:
        if any(word in text for word in words):
            return slot
    return None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def parse(text: str, default_city: Optional[str] = None) -> ParsedQuery:
    """把一句话解析成结构化请求。对任何输入都不会抛异常。"""
    raw = (text or "").strip()
    normalized = re.sub(r"\s+", " ", raw.replace("　", " "))
    normalized = normalized.replace("，", "，").replace(",", "，")
    result = ParsedQuery(raw=raw)
    notes = result.notes

    if not normalized:
        result.need_clarification = True
        result.questions.append("想找什么地方？可以告诉我位置和想去的类型，例如「我在西湖附近想喝咖啡」。")
        return result

    # 1) 位置
    place, kind, span = _extract_location(normalized)
    result.location_text = place
    result.location_kind = kind

    # 2) 城市
    city = detect_city(normalized)
    if city:
        result.city_hint = city
        result.city_source = "explicit"
        notes.append("识别到城市：" + city)
    elif default_city:
        result.city_hint = default_city
        result.city_source = "default"

    # 3) 类目（地名区间先遮掉，避免「深圳湾公园」被当成要去的公园）
    category_text = normalized
    if span is not None:
        category_text = normalized[: span[0]] + " " * (span[1] - span[0]) + normalized[span[1]:]
    categories, intent = _extract_categories(category_text)
    if categories:
        result.categories = categories
        result.intent = intent
        if intent in ("explore", "kids", "study"):
            notes.append("多类目意图：" + "、".join(category_label(c) for c in categories))
    else:
        result.categories = list(DEFAULT_CATEGORIES)
        result.intent = "default"
        notes.append("未识别明确类目，按「景点 / 咖啡 / 餐厅」综合推荐")

    # 4) 半径与距离
    radius, max_distance, clipped = _parse_radius(normalized, notes)
    result.radius_m = radius
    result.max_distance_m = max_distance

    # 5) 预算 / 评分 / 营业 / 连锁 / 安静 / 无障碍 / 停车
    budget = _parse_budget(normalized)
    if budget is not None:
        result.budget_per_person = budget
    rating = _parse_rating(normalized)
    if rating is not None:
        result.min_rating = rating
    result.require_open = bool(re.search(r"营业中|还开着|现在开|开门|没关门|24\s*小时|现在就营业", normalized))
    result.avoid_chain = bool(re.search(r"不要连锁|避开连锁|非连锁|不是连锁|独立小店|别连锁|不去连锁", normalized))
    result.quiet = bool(re.search(r"安静|清净|人少|不吵|能看书|可以看书|适合聊天", normalized))
    result.accessible = bool(re.search(r"无障碍|轮椅|有电梯", normalized))
    result.parking = bool(re.search(r"停车|好停|有车位", normalized))
    result.round_trip = bool(re.search(r"含往返|来回|往返|算上路上", normalized))

    # 6) 时长
    duration, _ = _extract_duration(normalized)
    if duration:
        result.duration_minutes = duration

    # 7) 交通方式（默认步行；显式说"步行能到"时仍是步行）
    transport, _pos = _extract_transport(normalized)
    if transport:
        result.transport = transport
    else:
        result.transport = "walking"
        if max_distance is not None and max_distance > WALKING_RADIUS_HINT_M:
            result.transport = "transit"
            notes.append("距离超过 1.5 公里，默认改用公共交通")
        else:
            notes.append("未说交通方式，默认步行")

    # 8) 时间 + 具体口味词
    result.time_slot = _parse_time_slot(normalized)
    result.focus_keywords = _extract_focus(normalized)

    # 9) 需要澄清的情况
    if result.location_kind == "none" and result.city_hint:
        result.location_kind = "city"
        notes.append("未给出具体地点，改用城市中心检索：" + result.city_hint)
    if result.location_kind in ("none", "relative") and not result.city_hint:
        result.need_clarification = True
        result.questions.append(
            "你想在哪个位置附近找？可以说一个地名（如「西湖」「国贸」），"
            "或者提供当前坐标（--origin 经度,纬度）。"
        )

    # 10) 置信度
    score = 0.3
    if result.location_text:
        score += 0.32
    elif result.location_kind == "relative":
        score += 0.18
    if result.categories:
        score += 0.18
    if result.budget_per_person or result.min_rating or result.duration_minutes or result.require_open:
        score += 0.1
    if transport:
        score += 0.05
    result.confidence = round(min(0.95, score), 2)

    if clipped:
        result.notes.append("搜索半径已按上限裁剪")
    return result


def describe(parsed: ParsedQuery) -> str:
    """把解析结果渲染成一行中文摘要（调试 / 展示用）。"""
    bits = []
    if parsed.location_text:
        bits.append("位置「%s」" % parsed.location_text)
    elif parsed.location_kind == "relative":
        bits.append("位置「当前位置」")
    elif parsed.city_hint:
        bits.append("城市「%s」" % parsed.city_hint)
    bits.append("类目 " + "、".join(category_label(c) for c in parsed.categories))
    bits.append("半径 %d 米" % parsed.radius_m)
    bits.append("交通 " + {"walking": "步行", "bicycling": "骑行", "transit": "公交", "driving": "驾车"}.get(parsed.transport, parsed.transport))
    if parsed.budget_per_person:
        bits.append("预算 %d 元/人" % int(parsed.budget_per_person))
    if parsed.min_rating:
        bits.append("评分 ≥ %.1f" % parsed.min_rating)
    if parsed.duration_minutes:
        bits.append("停留 %d 分钟" % parsed.duration_minutes)
    if parsed.require_open:
        bits.append("要求营业中")
    return "｜".join(bits)
