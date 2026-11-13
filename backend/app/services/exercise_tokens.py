"""训记→Garmin 动作映射用的静态词表与部位→category 映射。

纯数据模块：只导出常量，不做 I/O、不访问 DB/网络。
不负责候选打分或落库（见 exercise_mapping_candidates / V6-7）。
"""
from __future__ import annotations

from garminconnect import exercises as _garmin_exercises

# 部位 → Garmin category 候选子集（第 1 级窄化）。
# 「其他」用空 list 表示不窄化（全目录搜索）。
# 已剔除 CATEGORIES 中不存在的 CABLE / LAT_PULLDOWN / LEG_PRESS。
PART_TO_GARMIN_CATEGORIES: dict[str, list[str]] = {
    "胸": [
        "BENCH_PRESS",
        "FLYE",
        "PUSH_UP",
        "PLYO",
        "SUSPENSION",
    ],
    "背": [
        "ROW",
        "PULL_UP",
        "SHRUG",
        "OLYMPIC_LIFT",
        "SUSPENSION",
    ],
    "腿": [
        "SQUAT",
        "DEADLIFT",
        "LUNGE",
        "LEG_CURL",
        "LEG_RAISE",
        "HIP_RAISE",
        "PLYO",
        "SLED",
        "CALF_RAISE",
        "HIP_STABILITY",
        "HIP_SWING",
    ],
    "肩": [
        "SHOULDER_PRESS",
        "LATERAL_RAISE",
        "SHOULDER_STABILITY",
        "FLYE",
        "SHRUG",
    ],
    "臂": [
        "TRICEPS_EXTENSION",
        "CURL",
        "PUSH_UP",
    ],
    "核心": [
        "CORE",
        "CRUNCH",
        "PLANK",
        "SIT_UP",
        "TOTAL_BODY",
        "CHOP",
    ],
    "有氧": [
        "RUN",
        "RUN_INDOOR",
        "INDOOR_BIKE",
        "STAIR_STEPPER",
        "CARDIO",
        "ELLIPTICAL",
    ],
    "其他": [],
}

_UNKNOWN = {
    c for cats in PART_TO_GARMIN_CATEGORIES.values() for c in cats
} - set(_garmin_exercises.CATEGORIES)
assert not _UNKNOWN, f"PART_TO_GARMIN_CATEGORIES 含无效 category: {_UNKNOWN}"

# 器械专属 Garmin 分类：不按部位归属，但器械词命中时必须进候选池。
# 键是 EQUIPMENT_TOKENS 的**值**（英文词根），不是中文。
EQUIPMENT_TO_GARMIN_CATEGORY: dict[str, str] = {
    "suspension": "SUSPENSION",
    "ring": "SUSPENSION",  # 吊环在 Garmin 归 SUSPENSION
    "banded": "BANDED_EXERCISES",
    "sled": "SLED",
    "tire": "TIRE",
    "sandbag": "SANDBAG",
    "battle rope": "BATTLE_ROPE",
    "kettlebell": "HIP_SWING",  # 壶铃摆荡
}

_UNKNOWN_EQ = set(EQUIPMENT_TO_GARMIN_CATEGORY.values()) - set(
    _garmin_exercises.CATEGORIES
)
assert not _UNKNOWN_EQ, f"EQUIPMENT_TO_GARMIN_CATEGORY 含无效 category: {_UNKNOWN_EQ}"

# 器械中文 → Garmin 英文词根（空串 = 无器械前缀 / 自重）。
EQUIPMENT_TOKENS: dict[str, str] = {
    "史密斯机": "smith machine",
    "史密斯": "smith machine",
    "悍马机": "machine",
    "悍马": "machine",
    "弹力带": "banded",
    "弹力绳": "banded",
    "泡沫轴": "foam roller",
    "瑞士球": "stability ball",
    "药球": "medicine ball",
    "哑铃": "dumbbell",
    "杠铃": "barbell",
    "壶铃": "kettlebell",
    "绳索": "cable",
    "龙门": "cable",
    "器械": "machine",
    "吊环": "ring",
    "悬吊": "suspension",
    "TRX": "suspension",
    "自重": "",
    "徒手": "",
    "战绳": "battle rope",
    "雪橇": "sled",
    "轮胎": "tire",
    "沙袋": "sandbag",
}

# 姿态中文 → Garmin 英文词。
POSTURE_TOKENS: dict[str, str] = {
    "上斜": "incline",
    "下斜": "decline",
    "坐姿": "seated",
    "站姿": "standing",
    "俯卧": "prone",
    "仰卧": "supine",
    "跪姿": "kneeling",
    "俯身": "bent over",
    "单腿": "single leg",
    "单手": "single arm",
    "单臂": "single arm",
    "单边": "single arm",
    "侧躺": "side lying",
    "半跪": "half kneeling",
    "负重": "weighted",
    "反向": "reverse",
    "宽距": "wide grip",
    "窄距": "close grip",
}

# 动作模式中文 → Garmin 英文动作词（匹配时按键长降序）。
MOVEMENT_TOKENS: dict[str, str] = {
    "罗马尼亚硬拉": "romanian deadlift",
    "引体向上": "pull up",
    "平板支撑": "plank",
    "腿弯举": "leg curl",
    "侧平举": "lateral raise",
    "前平举": "front raise",
    "臀推": "hip thrust",
    "背伸展": "back extension",
    "箭步蹲": "lunge",
    "俯卧撑": "push up",
    "臂屈伸": "extension",
    "卧推": "bench press",
    "飞鸟": "fly",
    "夹胸": "fly",
    "深蹲": "squat",
    "硬拉": "deadlift",
    "腿举": "leg press",
    "箭步": "lunge",
    "划船": "row",
    "下拉": "pulldown",
    "引体": "pull up",
    "推举": "shoulder press",
    "推肩": "shoulder press",
    "平举": "raise",
    "弯举": "curl",
    "下压": "press down",
    "卷腹": "crunch",
    "转体": "twist",
    "抬腿": "leg raise",
    "提踵": "calf raise",
    "耸肩": "shrug",
    "挺身": "back extension",
    "三头肌": "triceps",
    "二头肌": "biceps",
    "推胸": "chest press",
    "抓举": "snatch",
    "挺举": "clean and jerk",
    "臀桥": "bridge",
    "开合跳": "jumping jack",
    "波比": "burpee",
    # —— V6-2 实测 empty 样本补齐（词表基于 1091 个动作名的真实词频与 Garmin 目录术语）——
    # 臀/髋（Garmin 归 HIP_RAISE / HIP_STABILITY / HIP_SWING）
    "臀冲": "hip thrust",
    "臀外展": "abduction",
    "外展": "abduction",
    "内收": "adduction",
    "蚌式": "clam",
    "驴踢": "fire hydrant",
    "摆荡": "swing",
    "髋绕环": "hip circle",
    "死虫": "dead bug",
    # 腿
    "上凳": "step up",
    "台阶": "step up",
    "侧踢": "side kick",
    "后踢": "kickback",
    "早安式": "good morning",
    # 核心（Garmin 有 CHOP / PLANK / SIT_UP）
    "仰卧起坐": "sit up",
    "侧支撑": "side plank",
    "悬垂举腿": "hanging leg raise",
    "木劈": "chop",
    "伐木": "woodchop",
    "爬行": "crawl",
    "熊爬": "bear crawl",
    # 臂
    "锤式弯举": "hammer curl",
    "集中弯举": "concentration curl",
    "颈弯举": "neck",
    "头后仰": "neck",
    # 肩/胸
    "前伸手": "front raise",
    "上斜推": "incline bench press",
    # 背
    "面拉": "face pull",
    # 举重/功能性（Garmin 有 OLYMPIC_LIFT / SLED / TIRE / BATTLE_ROPE / CARRY）
    "高翻": "clean",
    "推雪橇": "sled push",
    "翻轮胎": "tire flip",
    "战绳": "battle rope",
    "农夫行走": "farmer",
    "农夫": "farmer",
    # —— V6-9c：为 219 个无候选动作补充的词（每条都已在 Garmin 目录验证有命中）——
    "保加利亚蹲": "bulgarian split squat",
    "土耳其起身": "turkish get up",
    "保加利亚": "bulgarian split squat",
    "单腿屈伸": "leg extension",
    "小腿屈伸": "calf",
    "手臂上抬": "raise",
    "直腿上举": "leg raise",
    "站立提膝": "knee raise",
    "螃蟹行走": "lateral walk",
    "青蛙后蹬": "kickback",
    "髋部上抬": "hip raise",
    "髋部环绕": "hip circle",
    "体前屈": "forward bend",
    "倒立撑": "handstand push up",
    "健腹轮": "rollout",
    "分腿蹲": "split squat",
    "剪刀式": "scissor",
    "剪刀腿": "scissor",
    "大剪刀": "scissor",
    "滑冰式": "skater",
    "漫步机": "elliptical",
    "爬楼梯": "stair",
    "相扑蹲": "sumo squat",
    "砸药球": "medicine ball slam",
    "肩绕圈": "shoulder circle",
    "腹斜肌": "oblique",
    "腹肌轮": "rollout",
    "腿屈伸": "leg extension",
    "蝴蝶式": "butterfly",
    "螃式走": "lateral walk",
    "超人式": "superman",
    "髋上抬": "hip raise",
    "髋后伸": "hip extension",
    "上步": "step up",
    "侧压": "side lunge",
    "侧屈": "side bend",
    "侧转": "rotation",
    "倒蹬": "leg press",
    "前蹲": "front squat",
    "后压": "reverse lunge",
    "后蹬": "kickback",
    "外旋": "external rotation",
    "尺蠖": "inchworm",
    "开合": "clamshell",
    "弓步": "lunge",
    "快走": "walk",
    "悬垂": "hang",
    "扩胸": "fly",
    "扭转": "twist",
    "拉穿": "pull through",
    "拳击": "punch",
    "提拉": "upright row",
    "提腿": "leg raise",
    "提膝": "knee raise",
    "提髋": "hip raise",
    "摆腿": "leg swing",
    "旋转": "rotation",
    "早安": "good morning",
    "滚轮": "rollout",
    "猫式": "cat cow",
    "环绕": "circle",
    "画圆": "circle",
    "画圈": "circle",
    "箱式": "box",
    "绕圈": "circle",
    "翻举": "clean",
    "肩胛": "scapular",
    "蛙式": "frog",
    "跨步": "step",
    "转髋": "rotation",
    "顶胯": "hip thrust",
    "颈部": "neck",
    "风车": "windmill",
    "髋推": "hip thrust",
    # —— V6-9f：错配修复词（每条已在 Garmin 目录验证有命中；坐姿划船/seated row 因
    # 目录均为 seated+中间词+row，_norm 后无连续 seatedrow，0 命中故不收录）——
    "手腕弯举": "wrist curl",
    "环抱弯举": "hammer curl",
    "俯身划船": "bent over row",
    "髋外展": "hip abduction",
    "髋内收": "hip adduction",
}

# 按键长降序，供 extract_tokens / 测试断言长键优先。
MOVEMENT_KEYS_BY_LENGTH: list[str] = sorted(
    MOVEMENT_TOKENS.keys(), key=len, reverse=True
)

# 有氧/非力量分类：力量动作的候选池必须排除。
# 注意：Garmin 的 Rowing Machine 挂在 category=ROW、exercise=INDOOR_ROW，
# INDOOR_ROW 不是 CATEGORIES 成员，故不进本集合；候选池另行按 exercise 排除。
CARDIO_ONLY_CATEGORIES: frozenset[str] = frozenset({
    "RUN",
    "RUN_INDOOR",
    "BIKE_OUTDOOR",
    "ELLIPTICAL",
    "STAIR_STEPPER",
    "CARDIO",
    "LADDER",
    "FLOOR_CLIMB",
})

_UNKNOWN_CARDIO = CARDIO_ONLY_CATEGORIES - set(_garmin_exercises.CATEGORIES)
assert not _UNKNOWN_CARDIO, (
    f"CARDIO_ONLY_CATEGORIES 含无效 category: {_UNKNOWN_CARDIO}"
)

# 同名词根在不同部位含义不同：候选名必须含该部位的锚词，否则视为错配
PART_ANCHORED_MOVEMENTS: dict[str, dict[str, tuple[str, ...]]] = {
    # 动作中文关键词 -> {部位: 候选名必须包含的任一英文锚词}
    "外展": {"腿": ("leg", "hip"), "肩": ("shoulder",), "臂": ("shoulder", "arm")},
    "内收": {"腿": ("leg", "hip"), "肩": ("shoulder",), "臂": ("shoulder", "arm")},
}

# 中文名里没有限定词时，候选名里出现这些词就判为错配
MOVEMENT_NAME_EXCLUDES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # (中文必须含, 中文必须"不含"才生效, 候选名禁止出现的词)
    ("弯举", "腿", ("hamstring",)),
    ("弯举", "手腕", ("wrist",)),
)

# 候选名里出现「中文没要求」的限定词时的扣分规则。
# 每项 = (候选名里要检查的英文写法, 中文名里必须出现的任一关键词)
# 只收特异性限定词；不要把 dumbbell/barbell/cable 等器械词放进来——
# 中文没写器械通常是「不限定器材」，不是「不是该器材」。
QUALIFIER_CONSISTENCY: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("single", "one-arm", "one arm", "one-leg", "one leg"), ("单",)),
    (("alternating",), ("交替", "左右")),
    (("behind-the-back", "behind the back"), ("背后",)),
    (("reverse",), ("反",)),
    (("leaning",), ("斜身",)),
    (("side-lying", "side lying"), ("侧躺", "侧卧")),
    (("seated",), ("坐",)),
    (("standing",), ("站", "立")),
    (("kneeling",), ("跪",)),
    (("prone",), ("俯卧")),
    (("supine",), ("仰卧")),
    (("incline",), ("上斜",)),
    (("decline",), ("下斜",)),
    (("crossover",), ("夹胸",)),
)

QUALIFIER_MISSING_PENALTY = 20   # 每个「不该有」的限定词扣多少分
QUALIFIER_PENALTY_CAP = 40       # 单条候选最多扣多少分

# 同一中文动作在 Garmin 里可能有两种英文命名，匹配时都要试。
MOVEMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "fly": ("crossover",),   # 夹胸：Cable Crossover 不含 "fly"，只靠 fly 永远找不到
}

CARDIO_KEYWORDS: tuple[str, ...] = (
    "跑步",
    "跑",
    "骑",
    "单车",
    "泳",
    "椭圆",
    "划船机",
    "跳绳",
    "登山",
    "徒步",
    "爬坡",
    "有氧",
    "波比",
    "滑雪",
    "登山机",
    "风扇车",
)

FLEXIBILITY_KEYWORDS: tuple[str, ...] = (
    "拉伸",
    "放松",
    "伸展",
    "筋膜",
    "泡沫轴",
    "瑜伽",
    "活动度",
    "开肩",
    "开髋",
)
