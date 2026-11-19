import os
import json
import math
import time
import random
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, types, F
from aiogram.filters import Command, or_f
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as Btn

import persona
import extras
from storage import (
    DATA, get_user, add_points, save_data, level_of,
    top_global, top_group, top_groups, top_week, rank_in, title_of,
)
from utils import esc, show, safe_edit

log = logging.getLogger("mox.games")
games_router = Router()

CHALLENGES_FILE = os.getenv("CHALLENGES_FILE", "challenges.json")
RACE_SECONDS = 25


def load_challenges():
    try:
        with open(CHALLENGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error("تعذر تحميل الأسئلة: %s", e)
        return []


CHALLENGES = load_challenges()
CATEGORIES = sorted({c["category"] for c in CHALLENGES})
BY_ID = {c["id"]: c for c in CHALLENGES}


def is_group(chat: types.Chat) -> bool:
    return chat.type in ("group", "supergroup")


def difficulty(points: int) -> str:
    if points <= 10:
        return "🟢 سهل"
    if points <= 15:
        return "🟡 متوسط"
    if points <= 20:
        return "🟠 صعب"
    return "🔴 خبراء"


def pick_challenge(user: dict, cat_idx: int = -1):
    if not CHALLENGES:
        return None
    pool = CHALLENGES
    if 0 <= cat_idx < len(CATEGORIES):
        pool = [c for c in CHALLENGES if c["category"] == CATEGORIES[cat_idx]]
    unseen = [c for c in pool if c["id"] not in user["answered"]]
    if not unseen:
        ids = {c["id"] for c in pool}
        user["answered"] = [i for i in user["answered"] if i not in ids]
        unseen = pool
    return random.choice(unseen)


def next_cb(cat_idx: int) -> str:
    return "start_challenges" if cat_idx < 0 else f"cat:{cat_idx}"


def question_text(q: dict, extra: str = "") -> str:
    return (
        f"🔥 <b>تحدي جديد | {esc(q['category'])}</b>\n"
        f"📊 المستوى: {difficulty(q['points'])}\n"
        f"💎 الجائزة: <b>{q['points']} نقطة</b>\n{extra}\n"
        f"❓ <b>{esc(q['question'])}</b>"
    )


# ==================================================================
#                       تحدي فردي (الخاص)
# ==================================================================
def solo_keyboard(q, order, hint_used, cat_idx):
    rows = [[Btn(text=f"🔹 {q['options'][i]}",
                 callback_data=f"ans:{q['id']}:{i}:{hint_used}:{cat_idx}")] for i in order]
    tools = []
    if not hint_used:
        tools.append(Btn(text="💡 تلميح (نصف الجائزة)", callback_data=f"hint:{q['id']}:{cat_idx}"))
    tools.append(Btn(text="⏭️ تخطي", callback_data=next_cb(cat_idx)))
    rows.append(tools)
    rows.append([Btn(text="🏆 المتصدرين", callback_data="lb"),
                 Btn(text="🏠 الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ==================================================================
#                   سباق الأسئلة (الجروبات)
# ==================================================================
RACES: dict = {}   # (chat_id, message_id) -> dict


def race_keyboard(q, order):
    rows = [[Btn(text=f"🔹 {q['options'][i]}", callback_data=f"race:{q['id']}:{i}")] for i in order]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def race_timeout(msg: types.Message, key):
    await asyncio.sleep(RACE_SECONDS)
    race = RACES.get(key)
    if not race or race["done"]:
        RACES.pop(key, None)
        return
    race["done"] = True
    q = race["q"]
    await safe_edit(
        msg,
        f"⏰ <b>الوقت خلص!</b> محدش جاوب صح 😂\n\n"
        f"✔️ الإجابة كانت: <b>{esc(q['options'][q['answer']])}</b>\n"
        f"يا جماعة فين التركيز؟ 😅",
        InlineKeyboardMarkup(inline_keyboard=[
            [Btn(text="🏁 سؤال جديد", callback_data="start_challenges"),
             Btn(text="🏆 المتصدرين", callback_data="lb")]
        ]))
    RACES.pop(key, None)


async def send_race(target, user_obj: types.User):
    msg = target.message if isinstance(target, types.CallbackQuery) else target
    q = random.choice(CHALLENGES)
    order = list(range(4))
    random.shuffle(order)
    extra = f"⏱️ معاكم <b>{RACE_SECONDS} ثانية</b> — أول واحد يجاوب صح ياخد الجائزة! 🏁\n"
    sent = await msg.answer(question_text(q, extra), reply_markup=race_keyboard(q, order), parse_mode="HTML")
    key = (sent.chat.id, sent.message_id)
    RACES[key] = {"q": q, "done": False, "wrong": set(), "ts": time.time()}
    asyncio.create_task(race_timeout(sent, key))


@games_router.callback_query(F.data.startswith("race:"))
async def race_answer(callback: types.CallbackQuery):
    _, qid, chosen = callback.data.split(":")
    key = (callback.message.chat.id, callback.message.message_id)
    race = RACES.get(key)
    if not race or race["done"]:
        await callback.answer("⌛ السؤال ده خلص أو حد سبقك!", show_alert=True)
        return
    user = callback.from_user
    if user.id in race["wrong"]:
        await callback.answer("جاوبت غلط قبل كده، سيب غيرك يجرب 😂", show_alert=True)
        return

    q = race["q"]
    u = get_user(user)
    if int(chosen) != q["answer"]:
        race["wrong"].add(user.id)
        u["wrong"] += 1
        u["streak"] = 0
        save_data()
        await callback.answer("❌ غلط! " + random.choice(["اتحسب عليك 😂", "ركز شوية!", "قرّبت... لأ بعيد 😅"]),
                              show_alert=True)
        return

    race["done"] = True
    elapsed = time.time() - race["ts"]
    speed_bonus = 5 if elapsed <= 8 else 0
    u["correct"] += 1
    u["wins"] += 1
    extras.bump(u, "correct")
    extras.bump(u, "wins")
    u["streak"] += 1
    u["best_streak"] = max(u["best_streak"], u["streak"])
    streak_bonus = min(u["streak"] - 2, 5) * 5 if u["streak"] >= 3 else 0
    gained = q["points"] + speed_bonus + streak_bonus
    levelup = add_points(user, gained, callback.message.chat)
    await callback.answer("🎉 صح!")

    lines = [
        f"🏁 {persona.correct_line(user)}\n",
        f"✔️ الإجابة: <b>{esc(q['options'][q['answer']])}</b>",
        f"⚡ جاوب في <b>{elapsed:.1f}</b> ثانية",
        f"➕ كسب: <b>{q['points']}</b> نقطة"
        + (f" + <b>{speed_bonus}</b> سرعة" if speed_bonus else "")
        + (f" + <b>{streak_bonus}</b> سلسلة 🔥" if streak_bonus else ""),
        f"💰 رصيده: <b>{u['score']}</b> نقطة",
    ]
    if levelup:
        lines.append("\n" + persona.levelup_line(user, levelup))
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        Btn(text="🏁 سؤال جديد", callback_data="start_challenges"),
        Btn(text="🏆 المتصدرين", callback_data="lb"),
    ]])
    await safe_edit(callback.message, "\n".join(lines), kb)


# ==================================================================
#                       نقطة بدء التحديات
# ==================================================================
async def send_challenge(target, user_obj: types.User, cat_idx: int = -1):
    chat = target.message.chat if isinstance(target, types.CallbackQuery) else target.chat
    if not CHALLENGES:
        await show(target, "⚠️ لا توجد أسئلة متاحة حالياً.")
        return
    if is_group(chat):
        await send_race(target, user_obj)
        return
    user = get_user(user_obj)
    q = pick_challenge(user, cat_idx)
    order = list(range(4))
    random.shuffle(order)
    await show(target, question_text(q), solo_keyboard(q, order, 0, cat_idx))


@games_router.callback_query(F.data.in_(["start_challenges", "start_games"]))
async def start_challenge_cb(callback: types.CallbackQuery):
    await callback.answer()
    await send_challenge(callback, callback.from_user, -1)


@games_router.message(or_f(Command("challenge"), Command("race"),
                           F.text.in_(["تحدي", "لغز", "سؤال", "سباق", "challenge"])))
async def start_challenge_msg(message: types.Message):
    await send_challenge(message, message.from_user, -1)


@games_router.callback_query(F.data == "cats")
async def categories_menu(callback: types.CallbackQuery):
    await callback.answer()
    rows, row = [], []
    for i, cat in enumerate(CATEGORIES):
        n = sum(1 for c in CHALLENGES if c["category"] == cat)
        row.append(Btn(text=f"{cat} ({n})", callback_data=f"cat:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Btn(text="🎲 عشوائي من كل الأقسام", callback_data="start_challenges")])
    rows.append([Btn(text="🏠 القائمة الرئيسية", callback_data="main_menu")])
    await show(callback, f"📚 <b>اختر القسم</b> (الأسئلة: {len(CHALLENGES)}):",
               InlineKeyboardMarkup(inline_keyboard=rows))


@games_router.callback_query(F.data.startswith("cat:"))
async def category_challenge(callback: types.CallbackQuery):
    await callback.answer()
    await send_challenge(callback, callback.from_user, int(callback.data.split(":")[1]))


@games_router.callback_query(F.data.startswith("hint:"))
async def hint_cb(callback: types.CallbackQuery):
    _, qid, cat = callback.data.split(":")
    q = BY_ID.get(int(qid))
    if not q:
        await callback.answer("⚠️ انتهت صلاحية السؤال.", show_alert=True)
        return
    wrong = [i for i in range(4) if i != q["answer"]]
    keep = [q["answer"], random.choice(wrong)]
    random.shuffle(keep)
    try:
        await callback.message.edit_reply_markup(reply_markup=solo_keyboard(q, keep, 1, int(cat)))
    except Exception:
        pass
    await callback.answer("💡 شلت إجابتين غلط! (الجائزة بقت نصف القيمة)")


@games_router.callback_query(F.data.startswith("ans:"))
async def check_answer_cb(callback: types.CallbackQuery):
    try:
        _, qid, chosen, hint, cat = callback.data.split(":")
        qid, chosen, hint, cat = int(qid), int(chosen), int(hint), int(cat)
    except ValueError:
        await callback.answer("⚠️ زر قديم.", show_alert=True)
        return
    q = BY_ID.get(qid)
    if not q:
        await callback.answer("⚠️ انتهت صلاحية هذا السؤال.", show_alert=True)
        return

    user_obj = callback.from_user
    user = get_user(user_obj)
    correct_text = esc(q["options"][q["answer"]])
    already = qid in user["answered"]
    if not already:
        user["answered"].append(qid)
    levelup = None

    if chosen == q["answer"]:
        base = math.ceil(q["points"] / 2) if hint else q["points"]
        user["correct"] += 1
        extras.bump(user, "correct")
        user["streak"] += 1
        user["best_streak"] = max(user["best_streak"], user["streak"])
        bonus = min(user["streak"] - 2, 5) * 5 if user["streak"] >= 3 else 0
        gained = 0 if already else base + bonus
        if gained:
            levelup = add_points(user_obj, gained, callback.message.chat)
        lines = [f"✅ {persona.correct_line(user_obj)}\n", f"✔️ الإجابة: <b>{correct_text}</b>"]
        if already:
            lines.append("ℹ️ جاوبت السؤال ده قبل كده، مفيش نقط زيادة 😉")
        else:
            lines.append(f"➕ كسبت: <b>{base}</b> نقطة" + (" (بعد التلميح)" if hint else ""))
            if bonus:
                lines.append(f"🔥 سلسلة {user['streak']} إجابات ورا بعض: <b>+{bonus}</b>")
    else:
        lost = user["streak"]
        user["wrong"] += 1
        user["streak"] = 0
        lines = [f"{persona.wrong_line(user_obj)}\n", f"✔️ الإجابة الصحيحة: <b>{correct_text}</b>"]
        if lost >= 3:
            lines.append(f"💔 السلسلة بتاعتك ({lost}) راحت... البقاء لله 😂")
    save_data()

    lvl = level_of(user["score"])[0]
    lines.append(f"💰 رصيدك: <b>{user['score']}</b> نقطة | {lvl[2]} {lvl[1]}")
    if levelup:
        lines.append("\n" + persona.levelup_line(user_obj, levelup))
    await callback.answer()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="➡️ التحدي التالي", callback_data=next_cb(cat))],
        [Btn(text="🏆 المتصدرين", callback_data="lb"), Btn(text="📊 إحصائياتي", callback_data="my_stats")],
        [Btn(text="🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])
    await safe_edit(callback.message, "\n".join(lines), kb)


# ==================================================================
#                          المتصدرين
# ==================================================================
MEDALS = ["🥇", "🥈", "🥉"]


def lb_keyboard(tab: str):
    def b(label, t):
        return Btn(text=("• " if t == tab else "") + label, callback_data=f"lb:{t}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [b("🌍 العالم", "g"), b("🏘️ الجروب", "c")],
        [b("📅 الأسبوع", "w"), b("🏰 الجروبات", "t")],
        [Btn(text="🔥 العب", callback_data="start_challenges"), Btn(text="🏠 الرئيسية", callback_data="main_menu")],
    ])


def _t(uid) -> str:
    t = title_of(uid)
    return f" «{esc(t)}»" if t else ""


def fmt_row(i, name, score, extra=""):
    medal = MEDALS[i] if i < 3 else f"{i + 1}."
    return f"{medal} <b>{esc(name)}</b>{extra} — <code>{score}</code>\n"


async def render_lb(target, user_obj: types.User, chat: types.Chat, tab: str):
    text = ""
    if tab == "c" and not is_group(chat):
        tab = "g"
    if tab == "c":
        top, allrows = top_group(chat.id)
        text = f"🏘️ <b>أبطال جروب {esc(chat.title or '')}</b>\n\n"
        if not top:
            text += "لسه محدش كسب نقط هنا! اكتب <b>تحدي</b> وكن الأول 🔥"
        for i, (uid, e) in enumerate(top):
            lvl = level_of(DATA["users"].get(uid, {}).get("score", 0))[0]
            text += fmt_row(i, e["name"], e["score"], f" {lvl[2]}" + _t(uid))
        pos = rank_in(allrows, user_obj.id)
        if pos and pos > 10:
            text += f"\n📍 ترتيبك في الجروب: <b>#{pos}</b>"
    elif tab == "w":
        top, allrows = top_week()
        text = "📅 <b>متصدري الأسبوع</b> (بيتصفّر كل أسبوع — الكل عنده فرصة!) 🔥\n\n"
        if not top:
            text += "الأسبوع لسه بادئ! العب واكسب نقط وكن أول واحد 🏁"
        for i, (uid, u) in enumerate(top):
            lvl = level_of(u["score"])[0]
            text += fmt_row(i, u["name"], u["week"]["pts"], f" {lvl[2]}" + _t(uid))
        pos = rank_in(allrows, user_obj.id)
        if pos:
            text += f"\n📍 ترتيبك هذا الأسبوع: <b>#{pos}</b>"
    elif tab == "t":
        top, _ = top_groups()
        text = "🏰 <b>أقوى الجروبات (مجموع نقط الأعضاء)</b>\n\n"
        if not top:
            text += "لسه مفيش جروبات متصدرة! ضيف البوت لجروبك والعبوا 🔥"
        for i, (cid, title, total, members) in enumerate(top):
            medal = MEDALS[i] if i < 3 else f"{i + 1}."
            here = " 👈 جروبك" if str(chat.id) == cid else ""
            text += f"{medal} <b>{esc(title)}</b> — <code>{total}</code> ({members} لاعب){here}\n"
    else:
        top, allrows = top_global()
        text = "🌍 <b>أبطال العالم — MoX Assistant (أعلى 10)</b>\n\n"
        if not top:
            text += "لسه محدش جمع نقط! كن أول واحد 🔥"
        for i, (uid, u) in enumerate(top):
            lvl = level_of(u["score"])[0]
            text += fmt_row(i, u["name"], u["score"], f" {lvl[2]}" + _t(uid))
        pos = rank_in(allrows, user_obj.id)
        if pos and pos > 10:
            text += f"\n📍 ترتيبك العالمي: <b>#{pos}</b>"
    await show(target, text, lb_keyboard(tab))


@games_router.callback_query(F.data.in_(["lb", "leaderboard"]) | F.data.startswith("lb:"))
async def lb_cb(callback: types.CallbackQuery):
    await callback.answer()
    chat = callback.message.chat
    if ":" in callback.data:
        tab = callback.data.split(":")[1]
    else:
        tab = "c" if is_group(chat) else "g"
    await render_lb(callback, callback.from_user, chat, tab)


@games_router.message(or_f(Command("top"), F.text.in_(["المتصدرين", "الترتيب", "top"])))
async def lb_msg(message: types.Message):
    tab = "c" if is_group(message.chat) else "g"
    await render_lb(message, message.from_user, message.chat, tab)


@games_router.message(or_f(Command("world"), F.text.in_(["متصدري العالم", "الترتيب العالمي"])))
async def lb_world(message: types.Message):
    await render_lb(message, message.from_user, message.chat, "g")


@games_router.message(or_f(Command("groups"), F.text.in_(["الجروبات", "متصدري الجروبات"])))
async def lb_groups(message: types.Message):
    await render_lb(message, message.from_user, message.chat, "t")


# ==================================================================
#                          إحصائياتي
# ==================================================================
async def render_stats(target, user_obj: types.User, chat: types.Chat):
    u = get_user(user_obj)
    cur, nxt = level_of(u["score"])
    total = u["correct"] + u["wrong"]
    acc = round(u["correct"] * 100 / total) if total else 0
    _, allrows = top_global(10 ** 6)
    grank = rank_in(allrows, user_obj.id)

    text = (
        f"📊 <b>إحصائيات {esc(u['name'])}</b>\n\n"
        f"🎖️ المستوى: {cur[2]} <b>{cur[1]}</b>"
        + (f" | 🏷️ «{esc(u['title'])}»" if u.get("title") else "") + "\n"
        f"💰 النقاط: <b>{u['score']}</b>\n"
        f"🌍 ترتيبك العالمي: <b>{('#' + str(grank)) if grank else '—'}</b>\n"
    )
    if is_group(chat):
        _, grows = top_group(chat.id, 10 ** 6)
        gr = rank_in(grows, user_obj.id)
        text += f"🏘️ ترتيبك في الجروب: <b>{('#' + str(gr)) if gr else '—'}</b>\n"
    text += (
        f"✅ صح: <b>{u['correct']}</b> | ❌ غلط: <b>{u['wrong']}</b> | 🎯 دقة: <b>{acc}%</b>\n"
        f"🏁 انتصارات في السباق: <b>{u['wins']}</b>\n"
        f"🔥 السلسلة: <b>{u['streak']}</b> | أفضل سلسلة: <b>{u['best_streak']}</b>\n"
    )
    text += f"\n🏅 <b>الشارات:</b> {extras.badges_text(u)}\n"
    if nxt:
        text += f"\n⬆️ باقي <b>{nxt[0] - u['score']}</b> نقطة وتبقى {nxt[2]} {nxt[1]}"
    else:
        text += "\n👑 وصلت لأعلى مستوى! انت عبقري بجد."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="🔥 تحدي جديد", callback_data="start_challenges"),
         Btn(text="🎁 هدية يومية", callback_data="daily")],
        [Btn(text="📋 المهام", callback_data="quests"), Btn(text="🛒 المتجر", callback_data="shop")],
        [Btn(text="🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])
    await show(target, text, kb)


@games_router.callback_query(F.data == "my_stats")
async def stats_cb(callback: types.CallbackQuery):
    await callback.answer()
    await render_stats(callback, callback.from_user, callback.message.chat)


@games_router.message(or_f(Command("me"), F.text.in_(["نقاطي", "احصائياتي", "إحصائياتي", "ترتيبي"])))
async def stats_msg(message: types.Message):
    await render_stats(message, message.from_user, message.chat)


# ==================================================================
#                          الهدية اليومية
# ==================================================================
async def claim_daily(target, user_obj: types.User, chat: types.Chat):
    u = get_user(user_obj)
    today = datetime.now(timezone.utc).date()
    last = u.get("last_daily", "")
    if last == today.isoformat():
        msg = "🎁 خدت هديتك النهارده يا طماع! ارجع بكرة 😂"
        if isinstance(target, types.CallbackQuery):
            await target.answer(msg, show_alert=True)
        else:
            await show(target, msg)
        return

    yesterday = (today - timedelta(days=1)).isoformat()
    u["daily_streak"] = u.get("daily_streak", 0) + 1 if last == yesterday else 1
    base = random.choice([20, 30, 40, 50, 75, 100])
    streak_bonus = min(u["daily_streak"], 10) * 5
    u["last_daily"] = today.isoformat()
    extras.bump(u, "daily")
    levelup = add_points(user_obj, base + streak_bonus, chat)

    text = (
        f"🎁 <b>هديتك اليومية</b> {persona.call(user_obj)}!\n\n"
        f"💎 الهدية: <b>{base}</b> نقطة\n"
        f"📆 مكافأة {u['daily_streak']} يوم ورا بعض: <b>+{streak_bonus}</b>\n"
        f"💰 رصيدك: <b>{u['score']}</b> نقطة"
    )
    if levelup:
        text += "\n\n" + persona.levelup_line(user_obj, levelup)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="🔥 ابدأ التحدي", callback_data="start_challenges"),
         Btn(text="🎰 جرب حظك", callback_data="g_slot")],
        [Btn(text="🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])
    if isinstance(target, types.CallbackQuery):
        await target.answer("🎁 مبروك!")
    await show(target, text, kb)


@games_router.callback_query(F.data == "daily")
async def daily_cb(callback: types.CallbackQuery):
    await claim_daily(callback, callback.from_user, callback.message.chat)


@games_router.message(or_f(Command("daily"), F.text.in_(["هدية", "الهدية", "هديتي"])))
async def daily_msg(message: types.Message):
    await claim_daily(message, message.from_user, message.chat)
