"""مهام يومية + شارات + متجر ألقاب — عشان اللعب يبقى إدمان 😎🔥"""
from datetime import datetime, timezone

from aiogram import Router, types, F
from aiogram.filters import Command, or_f
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as Btn

import persona
from storage import get_user, add_points, save_data, DATA
from utils import esc, show, safe_answer

extras_router = Router()

# ------------------------------------------------------------------
# المهام اليومية
# ------------------------------------------------------------------
QUESTS = [
    ("correct", "جاوب 5 أسئلة صح", 5, 30),
    ("games", "العب 3 ألعاب (سلوت/نرد/تخمين...)", 3, 30),
    ("daily", "خد هديتك اليومية", 1, 20),
    ("wins", "اكسب سباق أسئلة في جروب", 1, 40),
    ("quran", "اقرأ 3 صفحات من المصحف 📖", 3, 25),
]
ALL_BONUS = 60


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def quest_state(u: dict) -> dict:
    q = u.get("quest") or {}
    if q.get("date") != today():
        q = {"date": today(), "claimed": []}
        u["quest"] = q
    return q


def bump(u: dict, key: str, n: int = 1):
    """يزوّد عداد مهمة. بيتنادى من باقي الملفات (بدون save، الحفظ بيتم مع النقاط)."""
    q = quest_state(u)
    q[key] = q.get(key, 0) + n


# ------------------------------------------------------------------
# الشارات (بتتحسب من الإحصائيات)
# ------------------------------------------------------------------
BADGES = [
    ("🥉", "أول دم", lambda u: u["correct"] >= 1),
    ("🎯", "قناص", lambda u: u["correct"] >= 50),
    ("🧠", "موسوعة", lambda u: u["correct"] >= 200),
    ("🔥", "ولّعتها", lambda u: u["best_streak"] >= 5),
    ("⚡", "برق", lambda u: u["best_streak"] >= 10),
    ("🏁", "سبّاق", lambda u: u["wins"] >= 10),
    ("👑", "ملك السباق", lambda u: u["wins"] >= 50),
    ("💰", "غني", lambda u: u["score"] >= 1000),
    ("💎", "مليونير النقط", lambda u: u["score"] >= 5000),
    ("📆", "ملتزم", lambda u: u.get("daily_streak", 0) >= 7),
    ("🎰", "مقامر", lambda u: u.get("games", 0) >= 25),
]


def badges_text(u: dict) -> str:
    got = [f"{e} {n}" for e, n, c in BADGES if c(u)]
    return " • ".join(got) if got else "لسه مفيش — العب وهتجيبهم! 💪"


# ------------------------------------------------------------------
# عرض المهام
# ------------------------------------------------------------------
def quests_view(u: dict):
    q = quest_state(u)
    lines = ["📋 <b>مهام النهارده</b>\n"]
    rows, ready = [], 0
    all_done = True
    for key, label, goal, reward in QUESTS:
        prog = min(q.get(key, 0), goal)
        claimed = key in q["claimed"]
        done = prog >= goal
        all_done &= done
        bar = "🟩" * prog + "⬜" * (goal - prog) if goal <= 6 else f"{prog}/{goal}"
        status = "✅ استلمت" if claimed else ("🎁 جاهزة!" if done else f"{prog}/{goal}")
        lines.append(f"{'✅' if done else '▫️'} {label}\n   {bar} — {status} (+{reward})")
        if done and not claimed:
            ready += 1
    bonus_claimed = "all" in q["claimed"]
    lines.append(f"\n🏆 خلّص كل المهام = بونص <b>+{ALL_BONUS}</b> نقطة"
                 + (" ✅" if bonus_claimed else ""))
    if ready or (all_done and not bonus_claimed):
        rows.append([Btn(text="🎁 استلم الجوايز", callback_data="qc")])
    rows.append([Btn(text="🔥 تحدي", callback_data="start_challenges"), Btn(text="🎮 العاب", callback_data="games")])
    rows.append([Btn(text="🏠 الرئيسية", callback_data="main_menu")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@extras_router.callback_query(F.data == "quests")
async def quests_cb(callback: types.CallbackQuery):
    await callback.answer()
    u = get_user(callback.from_user)
    text, kb = quests_view(u)
    save_data()
    await show(callback, text, kb)


@extras_router.message(or_f(Command("quests"), F.text.in_(["مهام", "المهام", "مهامي", "مهام اليوم"])))
async def quests_msg(message: types.Message):
    u = get_user(message.from_user)
    text, kb = quests_view(u)
    save_data()
    await safe_answer(message, text, kb)


@extras_router.callback_query(F.data == "qc")
async def claim_cb(callback: types.CallbackQuery):
    u = get_user(callback.from_user)
    q = quest_state(u)
    total, done_all = 0, True
    for key, label, goal, reward in QUESTS:
        done = q.get(key, 0) >= goal
        done_all &= done
        if done and key not in q["claimed"]:
            q["claimed"].append(key)
            total += reward
    if done_all and "all" not in q["claimed"]:
        q["claimed"].append("all")
        total += ALL_BONUS
    if total <= 0:
        await callback.answer("مفيش جوايز جاهزة دلوقتي 😅", show_alert=True)
        return
    lvl = add_points(callback.from_user, total, callback.message.chat)
    await callback.answer(f"🎁 +{total} نقطة!")
    text, kb = quests_view(u)
    extra = f"\n\n🎉 استلمت <b>{total}</b> نقطة! رصيدك: <b>{u['score']}</b>"
    if lvl:
        extra += "\n\n" + persona.levelup_line(callback.from_user, lvl)
    await show(callback, text + extra, kb)


# ------------------------------------------------------------------
# 💸 تحويل نقاط بين الأعضاء (بالرد على رسالة): تحويل 50
# ------------------------------------------------------------------
import re as _re

TRANSFER_RE = _re.compile(r"^(?:تحويل|حول|اهدي|اهداء|ابعت)\s+(\d{1,5})$")
TRANSFER_FEE = 0.05


def transfer_filter(m: types.Message):
    t = (m.text or "").strip()
    mt = TRANSFER_RE.match(t)
    r = m.reply_to_message
    if not mt or not r or not r.from_user or not m.from_user:
        return False
    return {"amount": int(mt.group(1))}


@extras_router.message(transfer_filter)
async def transfer_points(message: types.Message, amount: int):
    sender, target = message.from_user, message.reply_to_message.from_user
    if target.is_bot or target.id == sender.id:
        await message.reply("😂 مينفعش تحوّل لنفسك ولا للبوت يا باشا!")
        return
    if amount < 10:
        await message.reply("⚠️ أقل مبلغ للتحويل 10 نقط.")
        return
    u = get_user(sender)
    if u["score"] < amount:
        await message.reply(f"💸 رصيدك ({u['score']}) مش كفاية يا {esc(sender.first_name)}!")
        return
    fee = max(1, int(amount * TRANSFER_FEE))
    add_points(sender, -amount)
    lvl = add_points(target, amount - fee, message.chat)
    await message.reply(
        f"💸 <b>{esc(sender.first_name)}</b> حوّل <b>{amount}</b> نقطة لـ <b>{esc(target.first_name)}</b>\n"
        f"🧾 رسوم التحويل ({int(TRANSFER_FEE * 100)}%): {fee} | وصله: <b>{amount - fee}</b> 🎁\n"
        f"💰 رصيدك دلوقتي: <b>{u['score']}</b>", parse_mode="HTML")
    if lvl:
        await message.answer(persona.levelup_line(target, lvl), parse_mode="HTML")


# ------------------------------------------------------------------
# متجر الألقاب
# ------------------------------------------------------------------
TITLES = [
    ("باشا", 150), ("وحش الجروب", 300), ("ملك الكويز", 600), ("أمير الألعاب", 800),
    ("الزعيم", 1200), ("أسطورة مصر", 2500), ("إمبراطور النقط", 6000),
]


def shop_view(u: dict):
    owned = u.get("titles", [])
    lines = [f"🛒 <b>متجر الألقاب</b>\n💰 رصيدك: <b>{u['score']}</b>\n"
             f"🏷️ لقبك الحالي: <b>{esc(u['title']) if u.get('title') else 'مفيش'}</b>\n"]
    rows = []
    for i, (name, price) in enumerate(TITLES):
        if name in owned:
            mark = "✅ معاك" + (" (لابسه)" if u.get("title") == name else "")
            lines.append(f"• {name} — {mark}")
            rows.append([Btn(text=f"👑 البس «{name}»", callback_data=f"se:{i}")])
        else:
            lines.append(f"• {name} — 💰 {price}")
            rows.append([Btn(text=f"🛒 اشتري «{name}» ({price})", callback_data=f"sb:{i}")])
    if u.get("title"):
        rows.append([Btn(text="🚫 شيل اللقب", callback_data="se:-1")])
    rows.append([Btn(text="🏠 الرئيسية", callback_data="main_menu")])
    lines.append("\nاللقب بيظهر جنب اسمك في المتصدرين 😎")
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@extras_router.callback_query(F.data == "shop")
async def shop_cb(callback: types.CallbackQuery):
    await callback.answer()
    text, kb = shop_view(get_user(callback.from_user))
    await show(callback, text, kb)


@extras_router.message(or_f(Command("shop"), F.text.in_(["المتجر", "متجر", "الألقاب", "القابي"])))
async def shop_msg(message: types.Message):
    text, kb = shop_view(get_user(message.from_user))
    await safe_answer(message, text, kb)


@extras_router.callback_query(F.data.startswith("sb:"))
async def buy_cb(callback: types.CallbackQuery):
    i = int(callback.data.split(":")[1])
    name, price = TITLES[i]
    u = get_user(callback.from_user)
    if name in u["titles"]:
        await callback.answer("عندك اللقب ده بالفعل 😉", show_alert=True)
        return
    if u["score"] < price:
        await callback.answer(f"💸 رصيدك ({u['score']}) مش كفاية! محتاج {price - u['score']} نقطة كمان.", show_alert=True)
        return
    add_points(callback.from_user, -price)
    u["titles"].append(name)
    u["title"] = name
    save_data()
    await callback.answer(f"🎉 مبروك لقب «{name}»!", show_alert=True)
    text, kb = shop_view(u)
    await show(callback, text, kb)


@extras_router.callback_query(F.data.startswith("se:"))
async def equip_cb(callback: types.CallbackQuery):
    i = int(callback.data.split(":")[1])
    u = get_user(callback.from_user)
    if i == -1:
        u["title"] = ""
    elif 0 <= i < len(TITLES) and TITLES[i][0] in u["titles"]:
        u["title"] = TITLES[i][0]
    save_data()
    await callback.answer("✅")
    text, kb = shop_view(u)
    await show(callback, text, kb)
