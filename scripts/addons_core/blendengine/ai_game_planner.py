# SPDX-License-Identifier: GPL-2.0-or-later
#
# AI Game Creator: turn a plain-language game idea into a game spec.
#
# Two planners share one output format (see ``ai_game_spec``):
#
# * ``plan_with_claude`` asks Claude for a spec through the official Anthropic
#   Python SDK, using structured outputs so the reply is guaranteed JSON.
# * ``plan_offline`` is a deterministic keyword planner that understands
#   Uzbek, English, and Russian. It needs no network or API key, and it is
#   the automatic fallback whenever Claude is unavailable.
#
# Nothing here touches ``bpy``: the Claude call runs on a worker thread and
# the result is handed to ``ai_game_builder`` on Blender's main thread.

import json
import os
import random
import re

from . import ai_game_spec as spec_lib


DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
EFFORT_LEVELS = ("low", "medium", "high")
MAX_PROMPT_CHARS = 4000

PROVIDER_AUTO = "AUTO"
PROVIDER_CLAUDE = "CLAUDE"
PROVIDER_OFFLINE = "OFFLINE"


class PlannerError(Exception):
    """A planner failure with a message that is safe to show to the user."""


class PlanResult:
    def __init__(self, spec, source, warnings=None):
        self.spec = spec
        self.source = source
        self.warnings = list(warnings or [])


# ---------------------------------------------------------------------------
# Text helpers.
# ---------------------------------------------------------------------------

_APOSTROPHES = re.compile(r"[‘’ʻʼ`´]")


def normalize_text(text):
    text = (text or "")[:MAX_PROMPT_CHARS]
    text = _APOSTROPHES.sub("'", text)
    return text.lower()


def _pattern(keyword):
    exact = keyword.endswith("$")
    word = re.escape(keyword.rstrip("$"))
    suffix = r"(?![\w'])" if exact else ""
    return re.compile(r"(?<![\w'])" + word + suffix)


_PATTERN_CACHE = {}


def _has(text, keyword):
    pattern = _PATTERN_CACHE.get(keyword)
    if pattern is None:
        pattern = _PATTERN_CACHE[keyword] = _pattern(keyword)
    return pattern.search(text) is not None


def _has_any(text, keywords):
    return any(_has(text, keyword) for keyword in keywords)


def _score(text, keywords):
    return sum(1 for keyword in keywords if _has(text, keyword))


NUMBER_WORDS = {
    # English
    "one": 1, "a pair of": 2, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "dozen": 12, "a dozen": 12,
    # Uzbek
    "bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "tort": 4, "besh": 5, "olti": 6, "yetti": 7,
    "sakkiz": 8, "to'qqiz": 9, "toqqiz": 9, "o'n": 10, "yigirma": 20, "o'ttiz": 30,
    # Russian
    "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "двадцать": 20,
}

_NUMBER_TOKEN = r"(\d{1,3}|" + "|".join(re.escape(w) for w in sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"


def _to_number(token):
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def _count_before(text, keywords):
    """Find "10 zombies", "10 ta zombi", "5 big robots" style counts."""
    for keyword in keywords:
        word = re.escape(keyword.rstrip("$"))
        pattern = re.compile(
            r"(?<![\w'])" + _NUMBER_TOKEN + r"\s+(?:ta\s+|x\s+|шт\.?\s+)?(?:[\w'-]+\s+)?" + word)
        match = pattern.search(text)
        if match:
            value = _to_number(match.group(1))
            if value is not None:
                return value
    # "Zombilar 14 ta bo'lsin", "zombies: 14" -- the number after the noun.
    for keyword in keywords:
        word = re.escape(keyword.rstrip("$"))
        pattern = re.compile(r"(?<![\w'])" + word + r"[\w'-]*(?:\s+|\s*[:=]\s*)" + _NUMBER_TOKEN
                             + r"(?:\s+ta\b|\s*шт|\s*x\b|\s*(?=[,.;!?]|$))")
        match = pattern.search(text)
        if match:
            value = _to_number(match.group(1))
            if value is not None:
                return value
    return None


def _matching_group(groups, archetype):
    """The existing enemy group made from an archetype (names may be localized)."""
    names = {archetype["name"].casefold()}
    names.update(table[archetype["name"]].casefold() for table in LOCAL_NAMES.values() if archetype["name"] in table)
    for group in groups:
        if group["name"].casefold() in names or (group["shape"], group["color"]) == (archetype["shape"], archetype["color"]):
            return group
    return None


def _seconds(text):
    match = re.search(r"(\d{1,4})\s*(?:-\s*)?(minutes?|mins?|daqiqa|minut|минут\w*)", text)
    if match:
        return int(match.group(1)) * 60
    match = re.search(r"(\d{1,4})\s*(?:-\s*)?(seconds?|secs?|s\b|soniya|sekund|секунд\w*|сек\b)", text)
    if match:
        return int(match.group(1))
    return None


def detect_language(text):
    if re.search(r"[а-яё]", text):
        return "ru"
    uzbek_markers = (
        "o'", "g'", "o'yin", " va ", " bilan ", " qil", " ta ", "lar", "yarat", "kerak",
        "o'rmon", "dushman", "tanga", "yig'", "qahramon", "sakra", "chiqish",
    )
    padded = " %s " % text
    if sum(1 for marker in uzbek_markers if marker in padded) >= 2:
        return "uz"
    return "en"


# ---------------------------------------------------------------------------
# Keyword tables (Uzbek, English, Russian).
# ---------------------------------------------------------------------------

THEME_KEYWORDS = {
    "FOREST": ["forest", "jungle", "woods", "o'rmon", "orman", "changalzor", "daraxt", "лес", "джунгл", "чащ"],
    "DESERT": ["desert", "sand", "dune", "pyramid", "egypt", "cho'l", "chol$", "sahro", "qum$", "qumli",
               "piramida", "пустын", "песок", "песк", "пирамид"],
    "SNOW": ["snow", "ice", "icy", "frozen", "winter", "arctic", "polar", "qor$", "qorli", "qorda", "muz$",
             "muzli", "muzlagan", "qish$", "qishki", "снег", "снеж", "лёд", "лед$", "ледян", "зим", "аркти"],
    "NEON_CITY": ["city", "cyber", "neon", "street", "urban", "downtown", "shahar", "shahr", "ko'cha", "kiber",
                  "город", "неон", "кибер", "улиц"],
    "SPACE": ["space", "planet", "galaxy", "asteroid", "moon$", "mars", "spaceship", "space station", "kosmos",
              "kosmik", "sayyora", "galaktika", "asteroid", "космос", "космич", "планет", "галакт", "луна", "марс"],
    "DUNGEON": ["dungeon", "cave", "castle", "crypt", "catacomb", "underground", "g'or", "gor$", "zindon", "qasr",
                "qal'a", "yerosti", "подзем", "пещер", "замок", "замк", "склеп", "темниц"],
    "ISLAND": ["island", "beach", "ocean", "sea$", "tropical", "orol", "dengiz", "okean", "sohil", "plyaj",
               "остров", "море", "пляж", "океан", "тропи"],
    "VOLCANO": ["volcano", "volcanic", "lava", "magma", "inferno", "hell", "vulqon", "vulkan", "olovli",
                "вулкан", "лава", "магма", "огнен", "ад$"],
    "CANDY": ["candy", "sweet", "cake", "chocolate", "dessert", "shirinlik", "konfet", "tort$", "shokolad",
              "конфет", "сладк", "торт", "шоколад"],
    "GRASSLAND": ["field", "meadow", "farm", "village", "hills", "dala", "qishloq", "o'tloq", "yaylov", "ferma",
                  "поле", "деревн", "ферм", "луг"],
}

ENEMY_KEYWORDS = {
    "zombie": ["zombie", "zombi", "зомби", "undead", "o'liklar"],
    "robot": ["robot", "mech", "android", "робот", "мех$"],
    "drone": ["drone", "dron", "дрон"],
    "slime": ["slime", "blob", "shilimshiq", "слизн", "слайм"],
    "monster": ["monster", "creature", "beast", "demon", "maxluq", "yirtqich", "monstr", "jin$", "jinlar", "dev$",
                "devlar", "монстр", "чудовищ", "демон", "тварь", "твар"],
    "alien": ["alien", "o'zga sayyoralik", "o'zga sayyora", "elmon", "пришел", "инопланет"],
    "ghost": ["ghost", "spirit", "phantom", "arvoh", "ruh$", "ruhlar", "призрак", "привидени"],
    "skeleton": ["skeleton", "skelet", "скелет"],
    "wolf": ["wolf", "wolves", "bo'ri", "волк", "волч"],
    "spider": ["spider", "o'rgimchak", "паук"],
    "scorpion": ["scorpion", "chayon", "скорпион"],
    "yeti": ["yeti", "snowman", "йети"],
    "pirate": ["pirate", "qaroqchi", "пират"],
    "ninja": ["ninja", "ниндзя"],
    "soldier": ["soldier", "guard", "askar", "soqchi", "qo'riqchi", "солдат", "охранник", "страж"],
    "dragon": ["dragon", "ajdar", "ajdaho", "ajdarho", "дракон"],
}

GENERIC_ENEMY_KEYWORDS = ["enemy", "enemies", "foe", "villain", "dushman", "raqib", "yov$", "враг", "противник"]
BOSS_KEYWORDS = ["boss", "bosh dushman", "босс"]
NO_ENEMY_KEYWORDS = ["no enemies", "without enemies", "peaceful", "dushmansiz", "dushman yo'q", "tinch",
                     "без врагов", "мирн"]

COLLECTIBLE_KEYWORDS = {
    "coin": ["coin", "gold", "money", "tanga", "oltin", "pul$", "монет", "золот"],
    "gem": ["gem", "diamond", "crystal", "jewel", "olmos", "kristall", "kristal", "javohir", "gavhar",
            "алмаз", "кристалл", "драгоцен", "самоцвет"],
    "star": ["star", "yulduz", "звезд", "звёзд"],
    "orb": ["orb", "energy", "battery", "power cell", "energiya", "batareya", "sfera", "энерг", "батаре", "сфер"],
    "key": ["key", "keys", "kalit", "ключ"],
    "crate": ["treasure", "chest", "loot", "xazina", "sandiq", "boylik", "сокровищ", "сундук", "клад"],
    "fruit": ["fruit", "apple", "berry", "meva", "olma", "фрукт", "яблок", "ягод"],
}

HAZARD_KEYWORDS = {
    "LAVA": ["lava", "magma", "fire pit", "лава", "магма"],
    "SPIKES": ["spike", "thorn", "tikan", "шип"],
    "POISON": ["poison", "acid", "toxic", "swamp", "zahar", "kislota", "botqoq", "яд$", "ядов", "кислот", "токсич", "болот"],
    "LASER": ["laser", "lazer", "лазер"],
}
TRAP_KEYWORDS = ["trap", "tuzoq", "qopqon", "ловушк", "капкан"]
GENERIC_HAZARD_KEYWORDS = ["hazard", "danger", "obstacle", "xavf", "to'siq", "опасн", "препятстви"]

PROP_KEYWORDS = {
    "TREE": ["tree", "daraxt", "дерев"],
    "PINE": ["pine", "spruce", "archa", "qarag'ay", "ёлк", "елк", "сосн"],
    "PALM": ["palm", "palma", "пальм"],
    "ROCK": ["rock", "stone", "boulder", "tosh", "qoya", "камн", "камен", "скал"],
    "CACTUS": ["cactus", "cacti", "kaktus", "кактус"],
    "BUILDING": ["building", "skyscraper", "tower", "house", "bino", "uy$", "uylar", "minora", "osmono'par",
                 "здани", "небоскр", "башн", "дом$", "дома$"],
    "CRYSTAL": ["crystal", "kristall", "кристалл"],
    "PILLAR": ["pillar", "column", "ruin", "ustun", "xaroba", "колонн", "руин"],
    "CRATE": ["crate", "box", "barrel", "yashik", "quti", "bochka", "ящик", "коробк", "бочк"],
    "LAMP": ["lamp", "lantern", "street light", "chiroq", "fonar", "фонар", "ламп"],
    "MUSHROOM": ["mushroom", "qo'ziqorin", "гриб"],
}

GOAL_KEYWORDS = {
    "SURVIVE": ["survive", "survival", "last for", "hold out", "omon qol", "yashab qol", "chidab", "bardosh",
                "выжи", "продерж", "выстоя"],
    "DEFEAT_ALL": ["defeat", "kill", "destroy", "eliminate", "shoot all", "clear the", "beat all",
                   "yo'q qil", "o'ldir", "yeng", "mag'lub", "qirib", "otib tashla", "убей", "убить", "уничтож",
                   "победи", "зачист"],
    "REACH_EXIT": ["exit", "portal", "escape", "finish line", "reach the", "get to", "goal flag", "door",
                   "chiqish", "qochib chiq", "qutul", "portal", "eshik", "marra", "yetib bor", "yeting", "выход", "портал",
                   "сбеж", "финиш", "добер", "дойд"],
    "COLLECT_ALL": ["collect", "gather", "find all", "pick up", "yig'", "to'pla", "terib", "top$", "toping",
                    "собер", "собир", "найди", "найти"],
}

TWO_D_KEYWORDS = ["2d", "2-d", "side scroll", "side-scroll", "sidescroll", "platformer", "platformer",
                  "yon tomondan", "ikki o'lchov", "платформер", "2д", "двухмер"]
THREE_D_KEYWORDS = ["3d", "3-d", "uch o'lchov", "3д", "трехмер", "трёхмер"]
FIRST_PERSON_KEYWORDS = ["first person", "first-person", "fps", "birinchi shaxs", "от первого лица", "шутер от первого"]
TOP_DOWN_KEYWORDS = ["top down", "top-down", "topdown", "isometric", "bird's eye", "yuqoridan", "сверху", "изометр"]
THIRD_PERSON_KEYWORDS = ["third person", "third-person", "uchinchi shaxs", "от третьего лица"]
SHOOT_KEYWORDS = ["shoot", "shooter", "gun", "blaster", "rifle", "weapon", "laser gun", "otish", "otadigan",
                  "qurol", "miltiq", "avtomat", "стрел", "шутер", "оружи", "пистолет", "бластер"]
NO_JUMP_KEYWORDS = ["no jump", "without jump", "sakramasdan", "sakrashsiz", "без прыж"]
EASY_KEYWORDS = ["easy", "kids", "child", "casual", "relaxing", "oson", "yengil", "bolalar", "лёгк", "легк",
                 "просто", "детск"]
HARD_KEYWORDS = ["hard", "difficult", "challenging", "hardcore", "brutal", "qiyin", "murakkab", "сложн", "хардкор"]
NIGHT_KEYWORDS = ["night", "dark", "midnight", "moonlight", "tun$", "tunda", "tungi", "kechasi", "qorong'i",
                  "ночь", "ночн", "темн", "тёмн"]
SUNSET_KEYWORDS = ["sunset", "dusk", "evening", "sunrise", "kun botishi", "shom", "oqshom", "закат", "вечер", "рассвет"]
DAY_KEYWORDS = ["daytime", "sunny", "morning", "kunduz", "quyoshli", "ertalab", "днём", "днем", "солнечн", "утр"]
BIG_KEYWORDS = ["huge", "big world", "large", "open world", "katta", "ulkan", "keng", "огромн", "больш", "открытый мир"]
SMALL_KEYWORDS = ["tiny", "small arena", "compact", "kichik", "ixcham", "маленьк", "небольш"]
MORE_KEYWORDS = ["more", "extra", "ko'proq", "yana", "больше", "добавь", "add "]
ADD_KEYWORDS = ["add", "also", "plus", "qo'sh", "qo'shib", "qo'shing", "добавь", "добавить", "ещё", "еще"]
FEWER_KEYWORDS = ["fewer", "less", "kamroq", "kamaytir", "меньше", "убери"]
FASTER_KEYWORDS = ["faster", "speed up", "quicker", "tezroq", "tezlashtir", "быстрее"]
SLOWER_KEYWORDS = ["slower", "sekinroq", "медленнее"]
PLAYER_SHAPE_KEYWORDS = {
    "ROBOT": ["play as a robot", "robot hero", "robot qahramon", "robot bo'lib", "играть за робота"],
    "SPHERE": ["ball", "rolling", "sphere hero", "to'p$", "dumalab", "мяч", "шар$", "шарик"],
    "CUBE": ["cube hero", "block hero", "kub$", "kubik", "куб$", "кубик"],
}

THEME_TITLES = {
    "en": {
        "FOREST": "Forest", "DESERT": "Desert", "SNOW": "Frozen", "NEON_CITY": "Neon", "SPACE": "Star",
        "DUNGEON": "Dungeon", "ISLAND": "Island", "VOLCANO": "Volcano", "CANDY": "Candy", "GRASSLAND": "Meadow",
    },
    "uz": {
        "FOREST": "O'rmon", "DESERT": "Sahro", "SNOW": "Muzli o'lka", "NEON_CITY": "Neon shahar",
        "SPACE": "Koinot", "DUNGEON": "Zindon", "ISLAND": "Orol", "VOLCANO": "Vulqon", "CANDY": "Shirinlik o'lkasi",
        "GRASSLAND": "Yaylov",
    },
    "ru": {
        "FOREST": "Лесной", "DESERT": "Пустынный", "SNOW": "Ледяной", "NEON_CITY": "Неоновый", "SPACE": "Звёздный",
        "DUNGEON": "Подземный", "ISLAND": "Островной", "VOLCANO": "Вулканический", "CANDY": "Сладкий",
        "GRASSLAND": "Луговой",
    },
}

GOAL_TITLES = {
    "en": {"COLLECT_ALL": "Rush", "REACH_EXIT": "Escape", "DEFEAT_ALL": "Showdown", "SURVIVE": "Survival"},
    "uz": {"COLLECT_ALL": "xazinasi", "REACH_EXIT": "dan qochish", "DEFEAT_ALL": "jangi", "SURVIVE": "da omon qolish"},
    "ru": {"COLLECT_ALL": "забег", "REACH_EXIT": "побег", "DEFEAT_ALL": "бой", "SURVIVE": "выживание"},
}

MESSAGES = {
    "en": {"intro": "Good luck, %s!", "win": "Victory! You beat %s.", "lose": "Game over. Try again!"},
    "uz": {"intro": "Omad, %s!", "win": "G'alaba! Siz %s o'yinini yutdingiz.", "lose": "O'yin tugadi. Yana urinib ko'ring!"},
    "ru": {"intro": "Удачи, %s!", "win": "Победа! Вы прошли «%s».", "lose": "Игра окончена. Попробуйте ещё раз!"},
}

HERO_NAMES = {"en": "Hero", "uz": "Qahramon", "ru": "Герой"}

LOCAL_NAMES = {
    "uz": {
        "Coin": "Tanga", "Gem": "Olmos", "Star": "Yulduz", "Energy Cell": "Energiya", "Key": "Kalit",
        "Treasure": "Xazina", "Fruit": "Meva", "Zombie": "Zombi", "Drone": "Dron", "Slime": "Shilimshiq",
        "Monster": "Maxluq", "Alien": "O'zga sayyoralik", "Ghost": "Arvoh", "Skeleton": "Skelet", "Wolf": "Bo'ri",
        "Spider": "O'rgimchak", "Scorpion": "Chayon", "Pirate": "Qaroqchi", "Guard": "Soqchi", "Dragon": "Ajdar",
        "Lava Pool": "Lava ko'li", "Spike Trap": "Tikanli tuzoq", "Poison Pool": "Zaharli ko'lmak",
        "Laser Fence": "Lazer to'sig'i", "Hero": "Qahramon",
    },
    "ru": {
        "Coin": "Монета", "Gem": "Кристалл", "Star": "Звезда", "Energy Cell": "Энергоячейка", "Key": "Ключ",
        "Treasure": "Сокровище", "Fruit": "Фрукт", "Zombie": "Зомби", "Robot": "Робот", "Drone": "Дрон",
        "Slime": "Слизень", "Monster": "Монстр", "Alien": "Пришелец", "Ghost": "Призрак", "Skeleton": "Скелет",
        "Wolf": "Волк", "Spider": "Паук", "Scorpion": "Скорпион", "Yeti": "Йети", "Pirate": "Пират",
        "Ninja": "Ниндзя", "Guard": "Страж", "Dragon": "Дракон", "Boss": "Босс", "Lava Pool": "Лавовое озеро",
        "Spike Trap": "Шипы", "Poison Pool": "Ядовитая лужа", "Laser Fence": "Лазерный барьер", "Hero": "Герой",
    },
}


def _localize(spec, lang):
    table = LOCAL_NAMES.get(lang)
    if not table:
        return
    for key in ("enemies", "collectibles", "hazards"):
        for group in spec[key]:
            group["name"] = table.get(group["name"], group["name"])
    spec["player"]["name"] = table.get(spec["player"]["name"], spec["player"]["name"])

NOTES = {
    "en": {
        "offline": "Built by the offline planner from keywords in your idea. Add a Claude API key for richer designs.",
        "controls": "WASD move · Space jump · Shift sprint · F / left mouse attack · Esc stop.",
        "hazard": "%s hurt the player: each touch costs %d health.",
        "boss": "A boss guards the arena. Hit it repeatedly with F to bring it down.",
    },
    "uz": {
        "offline": "Oflayn rejalashtiruvchi g'oyangizdagi kalit so'zlardan yaratdi. Boyroq dizayn uchun Claude API kalitini qo'shing.",
        "controls": "WASD — yurish · Space — sakrash · Shift — yugurish · F / sichqoncha — hujum · Esc — to'xtatish.",
        "hazard": "%s xavfli: har tegishda %d sog'liq kamayadi.",
        "boss": "Arenani boss qo'riqlaydi. Uni F bilan bir necha marta urib yenging.",
    },
    "ru": {
        "offline": "Создано офлайн-планировщиком по ключевым словам. Добавьте ключ Claude API для более богатого дизайна.",
        "controls": "WASD — движение · Space — прыжок · Shift — бег · F / ЛКМ — атака · Esc — стоп.",
        "hazard": "%s опасны: каждое касание отнимает %d здоровья.",
        "boss": "Арену охраняет босс. Бейте его клавишей F, пока он не падёт.",
    },
}


def _quoted_title(raw_prompt):
    match = re.search(r"[\"«“]([^\"»”]{3,60})[\"»”]", raw_prompt or "")
    if match:
        return match.group(1).strip()
    return None


def _difficulty_scale(difficulty):
    return {"EASY": 0.65, "NORMAL": 1.0, "HARD": 1.45}[difficulty]


def plan_offline(prompt, base_spec=None, seed=None):
    """Build a spec from keywords. With ``base_spec`` the prompt is treated as
    a change request: only the attributes it mentions are modified."""
    text = normalize_text(prompt)
    lang = detect_language(text)
    refining = base_spec is not None
    if refining:
        spec, _ = spec_lib.normalize_spec(spec_lib.copy_spec(base_spec))
    else:
        spec = spec_lib.default_spec()
    notes = []

    # Theme. In a change request, words that also name a hazard ("add lava")
    # must not move the whole game to another world.
    hazard_words = {word for words in HAZARD_KEYWORDS.values() for word in words}
    theme_scores = {
        theme: _score(text, [w for w in words if not (refining and w in hazard_words)])
        for theme, words in THEME_KEYWORDS.items()
    }
    best_theme = max(theme_scores, key=lambda key: theme_scores[key])
    theme_changed = theme_scores[best_theme] > 0
    if theme_changed:
        theme = best_theme
    elif refining:
        theme = spec["world"]["theme"]
    else:
        theme = "NEON_CITY" if _has_any(text, SHOOT_KEYWORDS) else "FOREST"
    preset = spec_lib.THEME_PRESETS[theme]
    if theme_changed or not refining:
        spec["world"].update({
            "theme": theme,
            "time_of_day": preset["time"],
            "hilliness": preset["hilliness"],
            "ground_color": preset["ground"],
            "sky_color": preset["sky"],
            "accent_color": preset["accent"],
        })
        spec["props"] = [{"kind": kind, "count": count} for kind, count in preset["props"]]

    # Dimension and camera.
    if _has_any(text, TWO_D_KEYWORDS):
        spec["dimension"], spec["camera"] = "2D", "SIDE_VIEW"
    elif _has_any(text, THREE_D_KEYWORDS) and spec["dimension"] == "2D":
        spec["dimension"], spec["camera"] = "3D", "THIRD_PERSON"
    if spec["dimension"] == "3D":
        if _has_any(text, TOP_DOWN_KEYWORDS):
            spec["camera"] = "TOP_DOWN"
        elif _has_any(text, FIRST_PERSON_KEYWORDS):
            spec["camera"] = "FIRST_PERSON"
        elif _has_any(text, THIRD_PERSON_KEYWORDS):
            spec["camera"] = "THIRD_PERSON"
        elif not refining and _has_any(text, ["shooter", "шутер"]):
            spec["camera"] = "FIRST_PERSON"

    # Difficulty.
    if _has_any(text, EASY_KEYWORDS):
        spec["difficulty"] = "EASY"
    elif _has_any(text, HARD_KEYWORDS):
        spec["difficulty"] = "HARD"
    scale = _difficulty_scale(spec["difficulty"])

    # Time of day and size.
    if _has_any(text, NIGHT_KEYWORDS):
        spec["world"]["time_of_day"] = "NIGHT"
    elif _has_any(text, SUNSET_KEYWORDS):
        spec["world"]["time_of_day"] = "SUNSET"
    elif _has_any(text, DAY_KEYWORDS):
        spec["world"]["time_of_day"] = "DAY"
    if _has_any(text, BIG_KEYWORDS):
        spec["world"]["size"] = 84.0
    elif _has_any(text, SMALL_KEYWORDS):
        spec["world"]["size"] = 30.0

    # Player.
    if _has_any(text, SHOOT_KEYWORDS):
        spec["player"]["can_shoot"] = True
    if _has_any(text, NO_JUMP_KEYWORDS):
        spec["player"]["jump_force"] = 0.0
    for shape, words in PLAYER_SHAPE_KEYWORDS.items():
        if _has_any(text, words):
            spec["player"]["shape"] = shape
            break
    else:
        if not refining and theme == "SPACE":
            spec["player"]["shape"] = "ROBOT"
    if not refining:
        spec["player"]["name"] = HERO_NAMES[lang]

    # Enemies.
    more = _has_any(text, MORE_KEYWORDS)
    fewer = _has_any(text, FEWER_KEYWORDS)
    mentioned_enemies = [key for key, words in ENEMY_KEYWORDS.items() if _has_any(text, words)]
    base_enemy_count = max(1, int(round(4 * scale)))
    if _has_any(text, NO_ENEMY_KEYWORDS):
        spec["enemies"] = []
    elif mentioned_enemies and refining and not theme_changed and all(
            _matching_group(spec["enemies"], spec_lib.ENEMY_ARCHETYPES.get(key, {"name": "", "shape": "", "color": ""}))
            for key in mentioned_enemies):
        # "Zombies: 14, slower" while changing a game keeps the same zombies
        # (name, look, behavior) and only adjusts what was asked for.
        for key in mentioned_enemies:
            group = _matching_group(spec["enemies"], spec_lib.ENEMY_ARCHETYPES[key])
            count = _count_before(text, ENEMY_KEYWORDS[key])
            if count:
                group["count"] = count
            elif more or fewer:
                group["count"] = max(1, int(round(group["count"] * (1.6 if more else 0.6))))
    elif mentioned_enemies:
        groups = []
        for key in mentioned_enemies[:spec_lib.MAX_ENEMY_GROUPS]:
            count = _count_before(text, ENEMY_KEYWORDS[key])
            if key == "dragon":
                count = count or 1
            group = spec_lib.enemy_from_archetype(key, count or base_enemy_count)
            group["speed"] = round(group["speed"] * (0.85 + 0.15 * scale), 2)
            groups.append(group)
        if refining and not theme_changed and more:
            spec["enemies"] = (spec["enemies"] + groups)[:spec_lib.MAX_ENEMY_GROUPS]
        else:
            spec["enemies"] = groups
    elif _has_any(text, GENERIC_ENEMY_KEYWORDS) or not refining or theme_changed:
        count = _count_before(text, GENERIC_ENEMY_KEYWORDS)
        if refining and spec["enemies"] and not theme_changed:
            factor = 1.6 if more else 0.6 if fewer else 1.0
            for group in spec["enemies"]:
                group["count"] = max(1, int(round(group["count"] * factor)))
        else:
            spec["enemies"] = [spec_lib.enemy_from_archetype(preset["enemy"], count or base_enemy_count)]
    if _has_any(text, BOSS_KEYWORDS) and not any(g["behavior"] == "ENEMY_BOSS" for g in spec["enemies"]):
        spec["enemies"] = (spec["enemies"] + [spec_lib.enemy_from_archetype("boss", 1)])[:spec_lib.MAX_ENEMY_GROUPS]
    if any(g["behavior"] == "ENEMY_BOSS" for g in spec["enemies"]):
        notes.append(NOTES[lang]["boss"])
    if _has_any(text, FASTER_KEYWORDS):
        for group in spec["enemies"]:
            group["speed"] = round(group["speed"] * 1.35, 2)
        spec["player"]["walk_speed"] = min(15.0, spec["player"]["walk_speed"] * 1.2)
        spec["player"]["run_speed"] = min(25.0, spec["player"]["run_speed"] * 1.2)
    elif _has_any(text, SLOWER_KEYWORDS):
        for group in spec["enemies"]:
            group["speed"] = round(group["speed"] * 0.7, 2)

    # Collectibles.
    mentioned_pickups = [key for key, words in COLLECTIBLE_KEYWORDS.items() if _has_any(text, words)]
    # "crystal" is both a pickup and a prop; prefer the pickup reading.
    base_pickups = int(round(10 * (1.15 if scale > 1 else 1.0)))
    if mentioned_pickups:
        groups = []
        for key in mentioned_pickups[:spec_lib.MAX_COLLECTIBLE_GROUPS]:
            count = _count_before(text, COLLECTIBLE_KEYWORDS[key])
            default = 3 if key == "key" else base_pickups
            groups.append(spec_lib.collectible_from_archetype(key, count or default))
        spec["collectibles"] = groups
    elif not refining or theme_changed:
        spec["collectibles"] = [spec_lib.collectible_from_archetype(preset["collectible"], base_pickups)]

    # Hazards.
    mentioned_hazards = [kind for kind, words in HAZARD_KEYWORDS.items() if _has_any(text, words)]
    if not mentioned_hazards and _has_any(text, TRAP_KEYWORDS):
        mentioned_hazards = ["SPIKES"]
    hazard_count = max(1, int(round(3 * scale)))
    hazard_damage = round(15 * scale)
    if mentioned_hazards:
        groups = [
            {"name": spec_lib.HAZARD_NAMES[kind], "count": _count_before(text, HAZARD_KEYWORDS[kind]) or hazard_count,
             "kind": kind, "damage": hazard_damage}
            for kind in mentioned_hazards[:spec_lib.MAX_HAZARD_GROUPS]
        ]
        if refining and not theme_changed and _has_any(text, ADD_KEYWORDS + MORE_KEYWORDS):
            # "add lava" keeps the hazards the game already has.
            kept = [h for h in spec["hazards"] if h["kind"] not in mentioned_hazards]
            groups = (kept + groups)[-spec_lib.MAX_HAZARD_GROUPS:]
        spec["hazards"] = groups
    elif _has_any(text, GENERIC_HAZARD_KEYWORDS) or not refining or theme_changed:
        kind = preset["hazard"]
        spec["hazards"] = [{"name": spec_lib.HAZARD_NAMES[kind], "count": hazard_count, "kind": kind, "damage": hazard_damage}]

    # Extra scenery the user asked for.
    for kind, words in PROP_KEYWORDS.items():
        if kind == "CRYSTAL" and "gem" in mentioned_pickups:
            continue
        if _has_any(text, words):
            count = _count_before(text, words) or 8
            existing = next((p for p in spec["props"] if p["kind"] == kind), None)
            if existing:
                existing["count"] = max(existing["count"], count)
            elif len(spec["props"]) < spec_lib.MAX_PROP_GROUPS:
                spec["props"].append({"kind": kind, "count": count})

    if spec["dimension"] == "2D" and (not refining or spec["platforms"] < 4):
        spec["platforms"] = 8 if scale >= 1 else 6
    if spec["difficulty"] == "EASY":
        spec["health_pickups"] = 3
    elif spec["difficulty"] == "HARD":
        spec["health_pickups"] = 1
        spec["player"]["max_health"] = 80.0

    # Goal.
    goal_scores = {goal: _has_any(text, words) for goal, words in GOAL_KEYWORDS.items()}
    goal = next((g for g in ("SURVIVE", "DEFEAT_ALL", "REACH_EXIT", "COLLECT_ALL") if goal_scores[g]), None)
    seconds = _seconds(text)
    if goal is None:
        if refining:
            goal = spec["goal"]["type"]
        elif spec["dimension"] == "2D":
            goal = "REACH_EXIT"
        elif spec["player"]["can_shoot"] and spec["enemies"]:
            goal = "DEFEAT_ALL"
        else:
            goal = "COLLECT_ALL"
    if goal != spec["goal"]["type"] or not refining:
        spec["goal"]["description"] = ""
    spec["goal"]["type"] = goal
    pickup_total = spec_lib.total_count(spec["collectibles"])
    if goal == "COLLECT_ALL":
        spec["goal"]["target_count"] = pickup_total
    elif goal == "REACH_EXIT":
        wants_pickups = goal_scores["COLLECT_ALL"] or bool(mentioned_pickups)
        if wants_pickups:
            spec["goal"]["target_count"] = pickup_total
        elif not refining:
            spec["goal"]["target_count"] = 0
    if goal == "SURVIVE":
        spec["goal"]["time_limit_seconds"] = float(seconds or (90 if scale > 1 else 60))
    elif seconds:
        spec["goal"]["time_limit_seconds"] = float(seconds)
    elif not refining:
        spec["goal"]["time_limit_seconds"] = 0.0

    # Text.
    _localize(spec, lang)
    title = _quoted_title(prompt)
    if title:
        spec["title"] = title
    elif not refining or theme_changed:
        spec["title"] = _make_title(lang, theme, goal, spec)
    spec["tagline"] = spec_lib.clean_text(prompt, spec["tagline"]) if not refining else spec["tagline"]
    if not refining or theme_changed:
        spec["messages"] = {
            "intro": MESSAGES[lang]["intro"] % spec["player"]["name"],
            "win": MESSAGES[lang]["win"] % spec["title"],
            "lose": MESSAGES[lang]["lose"],
        }

    if seed is not None:
        spec["seed"] = seed
    normalized, warnings = spec_lib.normalize_spec(spec)
    normalized["goal"]["description"] = spec_lib.describe_goal(normalized, lang) if not spec["goal"]["description"] else normalized["goal"]["description"]
    if not refining or not normalized["design_notes"]:
        design = [NOTES[lang]["offline"], normalized["goal"]["description"] + "."]
        if normalized["hazards"]:
            hazard = normalized["hazards"][0]
            design.append(NOTES[lang]["hazard"] % (hazard["name"], int(hazard["damage"])))
        design.extend(notes[:1])
        design.append(NOTES[lang]["controls"])
        normalized["design_notes"] = design[:spec_lib.MAX_DESIGN_NOTES]
    if seed is None and not refining:
        normalized["seed"] = spec_lib.stable_seed(text) % (2 ** 31)
    return normalized, warnings


def _make_title(lang, theme, goal, spec):
    theme_word = THEME_TITLES[lang][theme]
    goal_word = GOAL_TITLES[lang][goal]
    enemy = spec["enemies"][0]["name"] if spec["enemies"] else ""
    if lang == "uz":
        return "%s %s" % (theme_word, goal_word) if not goal_word.startswith("d") else "%s%s" % (theme_word, goal_word)
    if lang == "ru":
        return "%s %s" % (theme_word, goal_word)
    if enemy and goal in ("DEFEAT_ALL", "SURVIVE", "REACH_EXIT"):
        return "%s %s %s" % (theme_word, enemy, goal_word)
    collectible = spec["collectibles"][0]["name"] if spec["collectibles"] else ""
    return "%s %s %s" % (theme_word, collectible, goal_word) if collectible else "%s %s" % (theme_word, goal_word)


# ---------------------------------------------------------------------------
# Claude planner.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the game designer inside BlendEngine, a beginner-friendly game engine built on Blender. \
A creator describes a game idea; you answer with a game spec that the engine turns into a playable level.

What the engine can build:
- A square arena (or, for 2D games, a side-view run along the X axis) with a themed ground, sky, lighting, and scenery props.
- One player with WASD movement, Space to jump, Shift to sprint, and F / left mouse to attack. If can_shoot is true the attack is a ranged shot.
- Enemy groups that patrol, follow, attack, guard, or flee. ENEMY_BOSS is a single large tough enemy.
- Pickups that add score, health pickups, and damaging hazard zones.
- Floating platforms to jump between (the main structure of a 2D game).
- One win condition: collect pickups, reach an exit portal (optionally after collecting pickups), defeat every enemy, or survive for a time. Any goal may add a time limit.

Everything is built from simple procedural shapes, so choose shapes, colors, and counts that read clearly from a distance. \
Make the game fun and fair: give the player room to move, keep enemy damage and speed beatable, and make sure the goal is reachable \
(DEFEAT_ALL needs enemies and can_shoot; COLLECT_ALL needs pickups). Stay within the ranges given in the schema; keep total objects modest, \
especially when the target platform is a phone or the web.

Write every player-facing string (title, tagline, names, goal description, messages, design notes) in the same language as the creator's request. \
Design notes are for the creator: two to four short sentences on what you built and how to play it."""


def credentials_available(api_key=""):
    """Best-effort check that a Claude credential exists without calling the API."""
    if api_key:
        return True
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if os.environ.get(name):
            return True
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.isdir(os.path.join(config_home, "anthropic"))


_SDK_CHECK = {"available": None}


def sdk_available(refresh=False):
    """Whether the official ``anthropic`` package can be imported (cached,
    because UI panels ask on every redraw)."""
    if refresh or _SDK_CHECK["available"] is None:
        try:
            import anthropic  # noqa: F401
            _SDK_CHECK["available"] = True
        except Exception:
            _SDK_CHECK["available"] = False
    return _SDK_CHECK["available"]


def _import_sdk():
    try:
        import anthropic
    except Exception as ex:
        raise PlannerError(
            "The Anthropic Python SDK is not installed in Blender's Python. "
            "Use Preferences > Add-ons > BlendEngine > Install Claude SDK. (%s)" % ex)
    return anthropic


def build_user_message(prompt, base_spec=None, platform=""):
    lines = []
    if platform:
        lines.append("Target platform: %s" % platform.title())
    if base_spec is not None:
        current = {k: v for k, v in base_spec.items() if k not in ("seed", "version")}
        lines.append("Current game spec:")
        lines.append(json.dumps(current, ensure_ascii=False))
        lines.append("")
        lines.append("Change request: %s" % prompt.strip()[:MAX_PROMPT_CHARS])
        lines.append("Return the complete updated spec. Keep everything the change request does not mention.")
    else:
        lines.append("Game idea: %s" % prompt.strip()[:MAX_PROMPT_CHARS])
    return "\n".join(lines)


def _response_text(response):
    for block in response.content:
        if getattr(block, "type", "") == "text":
            return block.text
    return ""


def plan_with_claude(prompt, api_key="", model=DEFAULT_MODEL, effort=DEFAULT_EFFORT, base_spec=None,
                     platform="", client=None, timeout=180.0):
    anthropic = _import_sdk()
    effort = effort if effort in EFFORT_LEVELS else DEFAULT_EFFORT
    if client is None:
        options = {"timeout": timeout}
        if api_key:
            options["api_key"] = api_key
        try:
            client = anthropic.Anthropic(**options)
        except anthropic.AnthropicError as ex:
            raise PlannerError("Claude is not configured: %s" % ex)

    try:
        response = client.beta.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=16000,
            # If a safety classifier declines, the API retries on the model
            # Anthropic recommends for that category instead of failing.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_message(prompt, base_spec, platform)}],
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": spec_lib.SPEC_JSON_SCHEMA},
            },
        )
    except anthropic.AuthenticationError:
        raise PlannerError("Claude rejected the API key. Check it in the BlendEngine add-on preferences.")
    except anthropic.PermissionDeniedError:
        raise PlannerError("This API key is not allowed to use %s." % model)
    except anthropic.NotFoundError:
        raise PlannerError("Model %s was not found. Check the model name in the add-on preferences." % model)
    except anthropic.RateLimitError:
        raise PlannerError("Claude is rate limited right now. Wait a moment and try again.")
    except anthropic.BadRequestError as ex:
        raise PlannerError("Claude could not process the request: %s" % getattr(ex, "message", ex))
    except anthropic.APIStatusError as ex:
        raise PlannerError("Claude returned an error (HTTP %s). Try again shortly." % getattr(ex, "status_code", "?"))
    except anthropic.APIConnectionError:
        raise PlannerError("Could not reach the Claude API. Check the internet connection.")
    except anthropic.AnthropicError as ex:
        raise PlannerError("Claude request failed: %s" % ex)
    except TypeError as ex:
        if "authentication" in str(ex).lower():
            raise PlannerError(
                "No Anthropic API key found. Add one in the BlendEngine add-on preferences "
                "or set the ANTHROPIC_API_KEY environment variable.")
        raise PlannerError("The installed Anthropic SDK is too old for this add-on; reinstall it from the preferences. (%s)" % ex)

    if response.stop_reason == "refusal":
        raise PlannerError("Claude declined to design this game. Try rephrasing the idea.")
    if response.stop_reason == "max_tokens":
        raise PlannerError("Claude's answer was cut off. Try a shorter or simpler idea.")
    text = _response_text(response)
    try:
        raw = json.loads(text)
    except ValueError:
        raise PlannerError("Claude returned a spec that was not valid JSON.")

    if base_spec is not None and "seed" in base_spec:
        raw["seed"] = base_spec["seed"]
    spec, warnings = spec_lib.normalize_spec(raw)
    return spec, warnings


# ---------------------------------------------------------------------------
# Entry point used by the operators and the command-line tool.
# ---------------------------------------------------------------------------

def generate_spec(prompt, provider=PROVIDER_AUTO, api_key="", model=DEFAULT_MODEL, effort=DEFAULT_EFFORT,
                  base_spec=None, platform="", seed=None, client=None):
    prompt = (prompt or "").strip()
    if not prompt:
        raise PlannerError("Describe the game you want first.")

    use_claude = provider == PROVIDER_CLAUDE or (
        provider == PROVIDER_AUTO and (client is not None or (sdk_available() and credentials_available(api_key))))

    if use_claude:
        try:
            spec, warnings = plan_with_claude(
                prompt, api_key=api_key, model=model, effort=effort, base_spec=base_spec,
                platform=platform, client=client)
            if seed is not None:
                spec["seed"] = seed
            return PlanResult(spec, "claude", warnings)
        except PlannerError as ex:
            if provider == PROVIDER_CLAUDE:
                raise
            fallback_warning = "Claude unavailable, used the offline planner: %s" % ex
        spec, warnings = plan_offline(prompt, base_spec=base_spec, seed=seed)
        return PlanResult(spec, "offline", [fallback_warning] + warnings)

    spec, warnings = plan_offline(prompt, base_spec=base_spec, seed=seed)
    return PlanResult(spec, "offline", warnings)


def random_seed():
    return random.randint(1, 2 ** 31 - 1)
