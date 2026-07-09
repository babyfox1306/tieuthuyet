"""Sub-niche keywords and platform settings."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_HTML_DIR = DATA_DIR / "raw_html"
OUTPUT_DIR = ROOT / "output"
DB_PATH = DATA_DIR / "recon.db"

NINEROUTER_BASE_URL = "http://localhost:20128/v1"
NINEROUTER_MODEL = "kr/claude-sonnet-4.5"

TOP_N = 20
MIN_DELAY_SEC = 2.0
MAX_DELAY_SEC = 5.0
AMAZON_MIN_DELAY_SEC = 3.0
MAX_WORKERS = 2

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

# id -> (label, amazon_keyword, webnovel_kw, goodnovel_kw, royalroad_tags, vella_kw)
SUB_NICHES: dict[int, dict] = {
    1: {
        "label": "Xianxia / cultivation",
        "amazon": "xianxia cultivation romance kindle",
        "webnovel": "xianxia",
        "goodnovel": "xianxia",
        "royalroad": ["cultivation", "xianxia"],
        "vella": "xianxia cultivation",
    },
    2: {
        "label": "Wuxia",
        "amazon": "wuxia martial arts romance kindle",
        "webnovel": "wuxia",
        "goodnovel": "wuxia",
        "royalroad": ["martial arts", "wuxia"],
        "vella": "wuxia martial arts",
    },
    3: {
        "label": "K-pop idol romance (fictional)",
        "amazon": "kpop idol romance fiction kindle",
        "webnovel": "kpop idol romance",
        "goodnovel": "kpop romance",
        "royalroad": ["romance"],
        "vella": "kpop idol romance",
    },
    4: {
        "label": "K-drama romance",
        "amazon": "korean drama romance CEO contract marriage kindle",
        "webnovel": "ceo romance",
        "goodnovel": "ceo romance",
        "royalroad": ["romance"],
        "vella": "korean romance CEO",
    },
    5: {
        "label": "Dark academia Seoul/Tokyo",
        "amazon": "dark academia tokyo seoul romance kindle",
        "webnovel": "dark academia",
        "goodnovel": "dark academia",
        "royalroad": ["school life", "romance"],
        "vella": "dark academia romance",
    },
    6: {
        "label": "Romantasy Asian mythology",
        "amazon": "romantasy chinese mythology dokkaebi youkai kindle",
        "webnovel": "chinese mythology romance",
        "goodnovel": "mythology romance",
        "royalroad": ["mythos"],
        "vella": "asian mythology romance",
    },
    7: {
        "label": "Vietnamese mythology fantasy",
        "amazon": "vietnamese mythology fantasy kindle",
        "webnovel": "vietnamese fantasy",
        "goodnovel": "vietnamese romance",
        "royalroad": ["mythos"],
        "vella": "vietnamese fantasy",
    },
    8: {
        "label": "Mafia romance",
        "amazon": "mafia romance kindle",
        "webnovel": "mafia romance",
        "goodnovel": "mafia romance",
        "royalroad": ["crime"],
        "vella": "mafia romance",
    },
    9: {
        "label": "Dark romance / why choose",
        "amazon": "dark romance why choose kindle",
        "webnovel": "dark romance",
        "goodnovel": "dark romance",
        "royalroad": ["romance"],
        "vella": "dark romance",
    },
    10: {
        "label": "Reverse harem",
        "amazon": "reverse harem romance kindle",
        "webnovel": "reverse harem",
        "goodnovel": "reverse harem",
        "royalroad": ["harem"],
        "vella": "reverse harem",
    },
    11: {
        "label": "Omegaverse",
        "amazon": "omegaverse romance kindle",
        "webnovel": "omegaverse",
        "goodnovel": "omegaverse",
        "royalroad": ["romance"],
        "vella": "omegaverse",
    },
    12: {
        "label": "Monster / alien romance",
        "amazon": "monster romance alien romance kindle",
        "webnovel": "monster romance",
        "goodnovel": "monster romance",
        "royalroad": ["romance"],
        "vella": "monster romance",
    },
    13: {
        "label": "Stepbrother / forbidden romance",
        "amazon": "forbidden romance stepbrother adult kindle",
        "webnovel": "forbidden romance",
        "goodnovel": "forbidden love",
        "royalroad": ["romance"],
        "vella": "forbidden romance",
    },
    14: {
        "label": "Bully romance",
        "amazon": "bully romance college kindle",
        "webnovel": "bully romance",
        "goodnovel": "bully romance",
        "royalroad": ["school life"],
        "vella": "bully romance",
    },
    15: {
        "label": "Billionaire romance Asian setting",
        "amazon": "billionaire romance asian setting kindle",
        "webnovel": "billionaire romance",
        "goodnovel": "billionaire romance",
        "royalroad": ["romance"],
        "vella": "billionaire asian romance",
    },
}

PLATFORMS = ["amazon", "webnovel", "goodnovel", "royalroad", "vella"]
