import os
import json
import copy
import logging
from datetime import datetime, timezone
from aiogram import types

log = logging.getLogger("mox.storage")

DATA_FILE = os.getenv("DATA_FILE", "scores.json")
DATA: dict = {"users": {}, "groups": {}, "adhan": {}, "audio": {}}

LEVELS = [
    (0, "مبتدئ", "🌱"), (100, "هاوي", "🌿"), (300, "محترف", "🔥"),
    (700, "خبير", "💎"), (1500, "أسطورة", "👑"), (3000, "عبقري", "🧠"),
]

USER_DEFAULTS = {
    "name": "لاعب", "score": 0, "correct": 0, "wrong": 0, "streak": 0,
    "best_streak": 0, "answered": [], "last_daily": "", "daily_streak": 0,
    "wins": 0, "games": 0, "quest": {}, "titles": [], "title": "",
    "last_spin": 0, "bookmark": 1, "week": {"id": "", "pts": 0},
}


def level_of(score: int):
    cur = LEVELS[0]
    for lv in LEVELS:
        if score >= lv[0]:
            cur = lv
    nxt = next((lv for lv in LEVELS if lv[0] > score), None)
    return cur, nxt


def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if "users" not in raw:  # ملف قديم (قبل نظام الجروبات)
            raw = {"users": raw, "groups": {}}
    except Exception:
        raw = {"users": {}, "groups": {}}
    raw.setdefault("groups", {})
    raw.setdefault("adhan", {})
    raw.setdefault("audio", {})
    DATA.clear()
    DATA.update(raw)


def save_data():
    try:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(DATA, f, ensure_ascii=False)
        os.replace(tmp, DATA_FILE)
    except Exception as e:
        log.error("تعذر حفظ البيانات: %s", e)


load_data()


def get_user(user: types.User) -> dict:
    uid = str(user.id)
    u = DATA["users"].setdefault(uid, {})
    for k, v in USER_DEFAULTS.items():
        if k not in u:
            u[k] = copy.deepcopy(v)
    u["name"] = user.first_name or "لاعب"
    return u


def peek_user(uid: int):
    """قراءة بدون إنشاء سجل جديد."""
    return DATA["users"].get(str(uid))


def week_id() -> str:
    return datetime.now(timezone.utc).strftime("%G-W%V")


def add_points(user: types.User, pts: int, chat: types.Chat = None):
    """يضيف/يخصم نقاط. يرجع المستوى الجديد لو اللاعب طلع مستوى."""
    u = get_user(user)
    old = level_of(u["score"])[0]
    u["score"] = max(0, u["score"] + pts)
    if pts > 0:
        w = u.get("week") or {}
        if w.get("id") != week_id():
            w = {"id": week_id(), "pts": 0}
        w["pts"] += pts
        u["week"] = w

    if pts > 0 and chat is not None and chat.type in ("group", "supergroup"):
        g = DATA["groups"].setdefault(str(chat.id), {"title": chat.title or "جروب", "scores": {}})
        g["title"] = chat.title or g.get("title", "جروب")
        e = g["scores"].setdefault(str(user.id), {"name": u["name"], "score": 0})
        e["name"] = u["name"]
        e["score"] += pts

    save_data()
    new = level_of(u["score"])[0]
    return new if new[0] > old[0] else None


# ---------------- المتصدرين ----------------
def top_global(n=10):
    rows = [(uid, u) for uid, u in DATA["users"].items() if u.get("score", 0) > 0]
    rows.sort(key=lambda kv: kv[1]["score"], reverse=True)
    return rows[:n], rows


def top_group(chat_id: int, n=10):
    g = DATA["groups"].get(str(chat_id))
    if not g:
        return [], []
    rows = [(uid, e) for uid, e in g["scores"].items() if e["score"] > 0]
    rows.sort(key=lambda kv: kv[1]["score"], reverse=True)
    return rows[:n], rows


def top_groups(n=10):
    rows = []
    for cid, g in DATA["groups"].items():
        total = sum(e["score"] for e in g["scores"].values())
        if total > 0:
            rows.append((cid, g.get("title", "جروب"), total, len(g["scores"])))
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows[:n], rows


def rank_in(rows, uid: int):
    for i, (u, _) in enumerate(rows):
        if u == str(uid):
            return i + 1
    return None


def title_of(uid) -> str:
    return DATA["users"].get(str(uid), {}).get("title", "") or ""


def top_week(n=10):
    wk = week_id()
    rows = [(uid, u) for uid, u in DATA["users"].items()
            if (u.get("week") or {}).get("id") == wk and u["week"]["pts"] > 0]
    rows.sort(key=lambda kv: kv[1]["week"]["pts"], reverse=True)
    return rows[:n], rows


# ---- كاش ملفات الصوت (file_id) عشان الإرسال المرة الجاية يبقى فوري ----
def audio_get(key: str):
    return DATA["audio"].get(key)


def audio_put(key: str, ids: list):
    DATA["audio"][key] = ids
    save_data()
