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
    "颈弯举": "neck curl",
    "头后仰": "neck extension",
    # 肩/胸
    "前伸手": "front raise",
    "上斜推": "incline press",
    # 背
    "面拉": "face pull",
    # 举重/功能性（Garmin 有 OLYMPIC_LIFT / SLED / TIRE / BATTLE_ROPE / CARRY）
    "高翻": "clean",
    "推雪橇": "sled push",
    "翻轮胎": "tire flip",
    "战绳": "battle rope",
    "农夫行走": "farmer carry",
    "农夫": "farmer carry",
}

# 按键长降序，供 extract_tokens / 测试断言长键优先。
MOVEMENT_KEYS_BY_LENGTH: list[str] = sorted(
    MOVEMENT_TOKENS.keys(), key=len, reverse=True
)

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
