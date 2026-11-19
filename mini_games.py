import re
import time
import random
import asyncio
import logging

from aiogram import Router, types, F
from aiogram.filters import Command, or_f
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as Btn

import persona
from storage import get_user, add_points, save_data
from utils import esc, safe_answer, safe_edit


class _ExtrasFallback:
    @staticmethod
    def bump(user: dict, key: str) -> None:
        """Optional extras hook; keep mini-games usable if extras is unavailable."""


try:
    import extras as extras  # type: ignore[import-not-found]
except ImportError:
    extras = _ExtrasFallback()

log = logging.getLogger("mox.mini")
mini_router = Router()

SLOT_BET = 20
DICE_BET = 10
SPORT_BET = 10

COOL: dict = {}


def cooldown(key: str, secs: int) -> int:
    """يرجع الثواني المتبقية، أو 0 ويبدأ العد من جديد."""
    now = time.time()
    left = COOL.get(key, 0) - now
    if left > 0:
        return int(left) + 1
    COOL[key] = now + secs
    return 0


async def lvl_msg(msg: types.Message, user: types.User, lvl):
    if lvl:
        await msg.answer(persona.levelup_line(user, lvl), parse_mode="HTML")


def played(u: dict):
    u["games"] = u.get("games", 0) + 1
    extras.bump(u, "games")
    save_data()


def again_kb(cb: str, label="🔁 تاني"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text=label, callback_data=cb)],
        [Btn(text="🎮 العاب", callback_data="games"), Btn(text="🏠 الرئيسية", callback_data="main_menu")],
    ])


# ==================================================================
#                          قائمة الألعاب
# ==================================================================
def games_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="🏁 سباق الأسئلة", callback_data="start_challenges"),
         Btn(text="📚 الأقسام", callback_data="cats")],
        [Btn(text="🧠 تحدي القرآن", callback_data="qq:new"),
         Btn(text="📋 مهام اليوم", callback_data="quests")],
        [Btn(text=f"🎰 سلوت ({SLOT_BET})", callback_data="g_slot"),
         Btn(text=f"🎲 نرد ضدي ({DICE_BET})", callback_data="g_dice")],
        [Btn(text="🎯 سهم", callback_data="g_sp:🎯"), Btn(text="⚽ ضربة جزاء", callback_data="g_sp:⚽"),
         Btn(text="🏀 سلة", callback_data="g_sp:🏀"), Btn(text="🎳 بولينج", callback_data="g_sp:🎳")],
        [Btn(text="✂️ حجر ورقة مقص", callback_data="g_rps"),
         Btn(text="🔢 خمن الرقم", callback_data="g_guess")],
        [Btn(text="⚡ أسرع كاتب", callback_data="g_type"),
         Btn(text="🧩 فك الكلمة", callback_data="g_word")],
        [Btn(text="🧮 حساب سريع", callback_data="g_math"),
         Btn(text="📜 كمّل المثل", callback_data="g_proverb")],
        [Btn(text="🤔 لو خيروك", callback_data="g_wyr"),
         Btn(text="😂 نكتة", callback_data="joke")],
        [Btn(text="🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])


GAMES_TEXT = (
    "🎮 <b>صالة الألعاب — MoX</b>\n\n"
    "🏁 <b>سباق الأسئلة</b> و🧠 <b>تحدي القرآن</b>: أول واحد يجاوب ياخد النقط\n"
    f"🎰 <b>سلوت</b> ({SLOT_BET}) • 🎲 <b>نرد</b> • 🎯⚽🏀🎳 <b>رياضات الحظ</b> ({SPORT_BET}): ارهن وجرب حظك\n"
    "✂️ <b>حجر ورقة مقص</b>: كسبني تاخد 10 نقط\n"
    "🔢 تخمين • ⚡ أسرع كاتب • 🧩 فك الكلمة • 🧮 حساب • 📜 كمّل المثل: ألعاب جماعية\n"
    "🤔 <b>لو خيروك</b>: تصويت يولّع الجروب 🔥\n\n"
    "💡 خلّص <b>المهام اليومية</b> وخد بونص!"
)


@mini_router.callback_query(F.data == "games")
async def games_cb(callback: types.CallbackQuery):
    await callback.answer()
    await safe_edit(callback.message, GAMES_TEXT, games_menu_kb())


@mini_router.message(or_f(Command("games"), F.text.in_(["العاب", "ألعاب", "الألعاب", "الالعاب"])))
async def games_msg(message: types.Message):
    await safe_answer(message, GAMES_TEXT, games_menu_kb())


# ==================================================================
#                              سلوت
# ==================================================================
async def play_slot(msg: types.Message, user: types.User):
    u = get_user(user)
    left = cooldown(f"slot:{user.id}", 6)
    if left:
        await msg.answer(f"⏳ اهدى يا {esc(user.first_name)}، استنى {left} ثواني! الماكينة بتسخن 😂")
        return
    if u["score"] < SLOT_BET:
        COOL.pop(f"slot:{user.id}", None)
        await msg.answer(
            f"💸 رصيدك ({u['score']}) مش كفاية للرهان ({SLOT_BET}) يا {esc(user.first_name)}!\n"
            "خد هديتك اليومية 🎁 أو العب تحدي 🔥")
        return
    add_points(user, -SLOT_BET)
    played(u)
    dice = await msg.answer_dice(emoji="🎰")
    v = dice.dice.value
    await asyncio.sleep(3.5)

    if v == 64:
        win, label = SLOT_BET * 10, "🎉🎉 <b>جاكبوووت 777!!</b> ×10"
    elif v in (1, 22, 43):
        win, label = SLOT_BET * 4, "🔥 <b>ثلاثة متشابهين!</b> ×4"
    else:
        win, label = 0, None

    if win:
        lvl = add_points(user, win, msg.chat)
        text = (f"{label}\n{persona.win_line(user)}\n"
                f"💰 كسبت <b>{win}</b> | رصيدك: <b>{u['score']}</b>")
    else:
        text = f"{persona.lose_line(user)}\n💸 خسرت <b>{SLOT_BET}</b> | رصيدك: <b>{u['score']}</b>"
        lvl = None
    await msg.answer(text, reply_markup=again_kb("g_slot", "🎰 لفة تانية"), parse_mode="HTML")
    await lvl_msg(msg, user, lvl)


@mini_router.message(or_f(Command("slot"), F.text.in_(["سلوت", "🎰"])))
async def slot_msg(message: types.Message):
    await play_slot(message, message.from_user)


@mini_router.callback_query(F.data == "g_slot")
async def slot_cb(callback: types.CallbackQuery):
    await callback.answer()
    await play_slot(callback.message, callback.from_user)


# ==================================================================
#                            نرد ضدي
# ==================================================================
async def play_dice(msg: types.Message, user: types.User):
    u = get_user(user)
    left = cooldown(f"dice:{user.id}", 6)
    if left:
        await msg.answer(f"⏳ استنى {left} ثواني يا {esc(user.first_name)}!")
        return
    if u["score"] < DICE_BET:
        COOL.pop(f"dice:{user.id}", None)
        await msg.answer(f"💸 رصيدك مش كفاية ({DICE_BET} نقط مطلوبين). خد هديتك 🎁")
        return
    add_points(user, -DICE_BET)
    played(u)
    await msg.answer(f"🎲 نردك يا <b>{esc(user.first_name)}</b> 👇", parse_mode="HTML")
    d1 = await msg.answer_dice(emoji="🎲")
    await msg.answer("🎲 ونردي أنا 👇")
    d2 = await msg.answer_dice(emoji="🎲")
    await asyncio.sleep(4)
    a, b = d1.dice.value, d2.dice.value
    lvl = None
    if a > b:
        lvl = add_points(user, DICE_BET * 2, msg.chat)
        text = f"🏆 {a} ضد {b} — {persona.win_line(user)}\n💰 كسبت <b>{DICE_BET}</b> صافي"
    elif a < b:
        text = f"😈 {a} ضد {b} — {persona.lose_line(user)}\n💸 خسرت <b>{DICE_BET}</b>"
    else:
        add_points(user, DICE_BET)
        text = f"🤝 {a} ضد {b} — {persona.tie_line(user)}\n(رجعتلك رهانك)"
    await msg.answer(text + f"\n💰 رصيدك: <b>{u['score']}</b>",
                     reply_markup=again_kb("g_dice", "🎲 جولة تانية"), parse_mode="HTML")
    await lvl_msg(msg, user, lvl)


@mini_router.message(or_f(Command("dice"), F.text.in_(["نرد", "🎲"])))
async def dice_msg(message: types.Message):
    await play_dice(message, message.from_user)


@mini_router.callback_query(F.data == "g_dice")
async def dice_cb(callback: types.CallbackQuery):
    await callback.answer()
    await play_dice(callback.message, callback.from_user)


# ==================================================================
#                    رياضات الحظ (🎯 ⚽ 🏀 🎳)
# ==================================================================
SPORTS = {
    "🎯": ("السهم", {6: 4.0, 5: 1.5}),
    "⚽": ("ضربة الجزاء", {3: 1.5, 4: 1.5, 5: 1.5}),
    "🏀": ("كورة السلة", {4: 2.5, 5: 2.5}),
    "🎳": ("البولينج", {6: 4.0, 5: 1.5}),
}


async def play_sport(msg: types.Message, user: types.User, emoji: str):
    if emoji not in SPORTS:
        return
    name, table = SPORTS[emoji]
    u = get_user(user)
    left = cooldown(f"sport:{user.id}", 5)
    if left:
        await msg.answer(f"⏳ استنى {left} ثواني يا {esc(user.first_name)}!")
        return
    if u["score"] < SPORT_BET:
        COOL.pop(f"sport:{user.id}", None)
        await msg.answer(f"💸 رصيدك مش كفاية ({SPORT_BET} نقط مطلوبين). خد هديتك 🎁")
        return
    add_points(user, -SPORT_BET)
    played(u)
    d = await msg.answer_dice(emoji=emoji)
    v = d.dice.value
    await asyncio.sleep(3.5)
    mult = table.get(v, 0)
    lvl = None
    if mult:
        ret = int(SPORT_BET * mult)
        lvl = add_points(user, ret, msg.chat)
        text = f"{persona.win_line(user)}\n🏆 {name}: رجعلك <b>{ret}</b> (صافي {ret - SPORT_BET:+d})"
    else:
        text = f"{persona.lose_line(user)}\n💸 خسرت <b>{SPORT_BET}</b>"
    await msg.answer(text + f"\n💰 رصيدك: <b>{u['score']}</b>",
                     reply_markup=again_kb(f"g_sp:{emoji}", f"{emoji} تاني"), parse_mode="HTML")
    await lvl_msg(msg, user, lvl)


@mini_router.message(F.text.in_(list(SPORTS)))
async def sport_msg(message: types.Message):
    await play_sport(message, message.from_user, message.text.strip())


@mini_router.callback_query(F.data.startswith("g_sp:"))
async def sport_cb(callback: types.CallbackQuery):
    await callback.answer()
    await play_sport(callback.message, callback.from_user, callback.data.split(":", 1)[1])


# ==================================================================
#                        حجر ورقة مقص
# ==================================================================
RPS = {"r": "🪨 حجر", "p": "📄 ورقة", "s": "✂️ مقص"}
BEATS = {"r": "s", "p": "r", "s": "p"}


def rps_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text=v, callback_data=f"rps:{k}") for k, v in RPS.items()],
        [Btn(text="🎮 العاب", callback_data="games")],
    ])


@mini_router.callback_query(F.data == "g_rps")
async def rps_start_cb(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("✂️ <b>حجر ورقة مقص</b> — اختار وكسبني ياخد 10 نقط! 😎",
                                  reply_markup=rps_kb(), parse_mode="HTML")


@mini_router.message(or_f(Command("rps"), F.text.in_(["حجر ورقة مقص", "حجر"])))
async def rps_start_msg(message: types.Message):
    await safe_answer(message, "✂️ <b>حجر ورقة مقص</b> — اختار وكسبني ياخد 10 نقط! 😎", rps_kb())


@mini_router.callback_query(F.data.startswith("rps:"))
async def rps_play(callback: types.CallbackQuery):
    me = callback.data.split(":")[1]
    played(get_user(callback.from_user))
    bot_pick = random.choice(list(RPS))
    user = callback.from_user
    lvl = None
    if me == bot_pick:
        res = persona.tie_line(user)
    elif BEATS[me] == bot_pick:
        lvl = add_points(user, 10, callback.message.chat)
        res = f"🏆 {persona.win_line(user)} (+10)"
    else:
        res = "😈 كسبتك! " + random.choice(["ادي آخرة الغرور 😂", "قولتلك أنا مش سهل 😎", "جرب تاني يا بطل... بس من غير خسارة نقط 😂"])
    await callback.answer()
    await safe_edit(
        callback.message,
        f"انت: {RPS[me]}\nأنا: {RPS[bot_pick]}\n\n{res}",
        InlineKeyboardMarkup(inline_keyboard=[
            [Btn(text="🔁 جولة تانية", callback_data="g_rps")],
            [Btn(text="🎮 العاب", callback_data="games")]]))
    await lvl_msg(callback.message, user, lvl)


# ==================================================================
#                 ألعاب جماعية: خمن الرقم / أسرع كاتب / فك الكلمة
# ==================================================================
GUESS: dict = {}   # chat_id -> {num, tries, ts}
WORDG: dict = {}   # chat_id -> {answer, points, ts, kind}
GUESS_TTL = 180
WORD_TTL = 45

PROVERBS = [
    "الصبر مفتاح الفرج", "اللي ما يعرفش يقول عدس", "الجار قبل الدار", "القرد في عين أمه غزال",
    "العجلة من الشيطان", "اللي يعيش ياما يشوف", "الباب اللي يجيلك منه الريح سده واستريح",
    "يا خبر بفلوس بكرة يبقى ببلاش", "اللي فات مات", "الصاحب ساحب", "إن كبر ابنك خاويه",
    "ضربني وبكى سبقني واشتكى", "كل تأخيرة فيها خيرة", "الإيد الواحدة ما تصقفش",
]
SCRAMBLE_WORDS = [
    "مدرسة", "كمبيوتر", "طيارة", "سيارة", "شجرة", "مكتبة", "حديقة", "اسكندرية", "موبايل",
    "تليفون", "شوكولاتة", "كشري", "فلافل", "بطيخ", "برتقال", "مستشفى", "ملعب", "مطار",
    "قطار", "هرم", "كتاب", "مفتاح", "نظارة", "فراشة", "عصفور", "تمساح", "زرافة", "صحراء",
    "مكرونة", "ملوخية", "جامعة", "صاروخ", "شاطئ", "عمارة", "ثلاجة", "غسالة",
]

_AR_NORM = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})
_TASHKEEL = re.compile(r"[\u064B-\u0652\u0640]")


def norm(s: str) -> str:
    s = _TASHKEEL.sub("", s).translate(_AR_NORM)
    return re.sub(r"\s+", "", s).lower()


async def _expire(bot, store: dict, cid: int, token: dict, ttl: int, text_fn):
    await asyncio.sleep(ttl)
    if store.get(cid) is token:
        store.pop(cid, None)
        try:
            await bot.send_message(cid, text_fn(token))
        except Exception:
            pass


async def start_guess(msg: types.Message):
    cid = msg.chat.id
    g = GUESS.get(cid)
    if g and time.time() - g["ts"] < GUESS_TTL:
        await msg.answer("🔢 فيه لعبة تخمين شغالة بالفعل! كملوا عليها 😅")
        return
    tok = {"num": random.randint(1, 100), "tries": 0, "ts": time.time()}
    GUESS[cid] = tok
    await msg.answer(
        "🔢 <b>خمن الرقم!</b>\nفكرت في رقم من <b>1 لـ 100</b> 🤫\n"
        "ابعتوا تخميناتكم، وأول واحد يجيبه ياخد نقط (كل ما قلّت المحاولات النقط أكتر)!\n"
        f"⏱️ معاكم {GUESS_TTL // 60} دقايق.", parse_mode="HTML")
    asyncio.create_task(_expire(msg.bot, GUESS, cid, tok, GUESS_TTL,
                                lambda t: f"⌛ الوقت خلص! الرقم كان {t['num']} 😂"))


async def start_word(msg: types.Message, kind: str):
    cid = msg.chat.id
    g = WORDG.get(cid)
    if g and time.time() - g["ts"] < WORD_TTL:
        await msg.answer("⚡ فيه لعبة شغالة، خلصوها الأول! 😅")
        return
    tail = lambda pts: f"\n\n💎 الجائزة: {pts} نقطة | ⏱️ {WORD_TTL} ثانية"
    if kind == "type":
        ans = random.choice(PROVERBS) if random.random() < 0.7 else "".join(
            random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        pts = 15
        text = f"⚡ <b>أسرع كاتب!</b>\nأول واحد يكتب الجملة دي بالظبط:\n\n<code>{esc(ans)}</code>" + tail(pts)
    elif kind == "math":
        op = random.choice(["+", "-", "×"])
        if op == "×":
            x, y = random.randint(3, 15), random.randint(3, 12)
            ans = str(x * y)
        elif op == "+":
            x, y = random.randint(20, 99), random.randint(20, 99)
            ans = str(x + y)
        else:
            x, y = random.randint(50, 150), random.randint(10, 49)
            ans = str(x - y)
        pts = 15
        text = f"🧮 <b>حساب سريع!</b>\nأول واحد يجاوب:\n\n<b>{x} {op} {y} = ؟</b>" + tail(pts)
    elif kind == "proverb":
        full = random.choice([p for p in PROVERBS if len(p.split()) >= 3])
        words = full.split()
        ans = words[-1]
        pts = 15
        text = (f"📜 <b>كمّل المثل!</b>\nأول واحد يكتب الكلمة الناقصة:\n\n"
                f"<b>{esc(' '.join(words[:-1]))} ... ؟</b>" + tail(pts))
    else:
        ans = random.choice(SCRAMBLE_WORDS)
        letters = list(ans)
        for _ in range(10):
            random.shuffle(letters)
            if "".join(letters) != ans:
                break
        pts = 20
        text = f"🧩 <b>فك الكلمة!</b>\nرتب الحروف دي وكوّن كلمة:\n\n<b>{' - '.join(letters)}</b>" + tail(pts)
    tok = {"answer": ans, "points": pts, "ts": time.time(), "kind": kind}
    WORDG[cid] = tok
    await msg.answer(text, parse_mode="HTML")
    asyncio.create_task(_expire(msg.bot, WORDG, cid, tok, WORD_TTL,
                                lambda t: f"⌛ الوقت خلص! الإجابة كانت: {t['answer']} 😂 محدش لحق!"))


@mini_router.message(or_f(Command("guess"), F.text.in_(["خمن", "خمن الرقم", "تخمين"])))
async def guess_msg(message: types.Message):
    await start_guess(message)


@mini_router.message(or_f(Command("type"), F.text.in_(["اسرع كاتب", "أسرع كاتب", "اكتب"])))
async def type_msg(message: types.Message):
    await start_word(message, "type")


@mini_router.message(or_f(Command("word"), F.text.in_(["فك الكلمة", "فك", "كلمة"])))
async def word_msg(message: types.Message):
    await start_word(message, "scramble")


@mini_router.message(or_f(Command("math"), F.text.in_(["حساب", "حساب سريع", "رياضيات"])))
async def math_msg(message: types.Message):
    await start_word(message, "math")


@mini_router.message(or_f(Command("proverb"), F.text.in_(["كمل المثل", "كمّل المثل", "مثل"])))
async def proverb_msg(message: types.Message):
    await start_word(message, "proverb")


@mini_router.callback_query(F.data == "g_math")
async def math_cb(callback: types.CallbackQuery):
    await callback.answer()
    await start_word(callback.message, "math")


@mini_router.callback_query(F.data == "g_proverb")
async def proverb_cb(callback: types.CallbackQuery):
    await callback.answer()
    await start_word(callback.message, "proverb")


@mini_router.callback_query(F.data == "g_guess")
async def guess_cb(callback: types.CallbackQuery):
    await callback.answer()
    await start_guess(callback.message)


@mini_router.callback_query(F.data == "g_type")
async def type_cb(callback: types.CallbackQuery):
    await callback.answer()
    await start_word(callback.message, "type")


@mini_router.callback_query(F.data == "g_word")
async def word_cb(callback: types.CallbackQuery):
    await callback.answer()
    await start_word(callback.message, "scramble")


def game_filter(message: types.Message):
    """يلتقط الرسالة فقط لو هي تخمين/إجابة للعبة شغالة، عشان ما نبلعش باقي الكلام."""
    if not message.text or not message.from_user or message.from_user.is_bot:
        return False
    t = message.text.strip()
    if t.startswith("/"):
        return False
    cid = message.chat.id
    private = message.chat.type == "private"
    now = time.time()
    w = WORDG.get(cid)
    if w and now - w["ts"] < WORD_TTL and (private or norm(t) == norm(w["answer"])):
        return True
    s = GUESS.get(cid)
    if s and now - s["ts"] < GUESS_TTL and t.isdigit():
        return True
    return False


@mini_router.message(game_filter)
async def game_answer(message: types.Message):
    cid = message.chat.id
    t = message.text.strip()
    user = message.from_user
    now = time.time()

    w = WORDG.get(cid)
    if w and now - w["ts"] < WORD_TTL:
        if norm(t) == norm(w["answer"]):
            WORDG.pop(cid, None)
            took = now - w["ts"]
            played(get_user(user))
            lvl = add_points(user, w["points"], message.chat)
            u = get_user(user)
            await message.reply(
                f"🏆 {persona.correct_line(user)}\n⚡ في {took:.1f} ثانية!\n"
                f"➕ <b>{w['points']}</b> نقطة | 💰 رصيدك: <b>{u['score']}</b>",
                parse_mode="HTML")
            await lvl_msg(message, user, lvl)
            return
        if message.chat.type == "private" and not t.isdigit():
            await message.reply("❌ لأ، جرب تاني 😅")
            return

    s = GUESS.get(cid)
    if s and t.isdigit() and now - s["ts"] < GUESS_TTL:
        n = int(t)
        s["tries"] += 1
        if n == s["num"]:
            GUESS.pop(cid, None)
            pts = max(10, 50 - 2 * (s["tries"] - 1))
            lvl = add_points(user, pts, message.chat)
            u = get_user(user)
            await message.reply(
                f"🎯 {persona.correct_line(user)}\nالرقم هو <b>{n}</b> بعد <b>{s['tries']}</b> محاولة!\n"
                f"➕ <b>{pts}</b> نقطة | 💰 رصيدك: <b>{u['score']}</b>", parse_mode="HTML")
            await lvl_msg(message, user, lvl)
        elif n < s["num"]:
            await message.reply(random.choice(["⬆️ أكبر من كده!", "⬆️ فوق شوية يا باشا", "⬆️ أعلى، لسه بدري 😂"]))
        else:
            await message.reply(random.choice(["⬇️ أصغر من كده!", "⬇️ نزّل شوية يا معلم", "⬇️ أقل، انت طيرت الرقم 😂"]))


# ==================================================================
#                           لو خيروك
# ==================================================================
WYR = [
    ("تعيش بلا إنترنت شهر", "تعيش بلا موبايل شهر"),
    ("تاكل كشري كل يوم", "تاكل فول وطعمية كل يوم"),
    ("تسافر للماضي", "تسافر للمستقبل"),
    ("تكون أذكى واحد في الدنيا وتعيش لوحدك", "تكون عادي ومعاك كل صحابك"),
    ("تنام 3 ساعات بس وتصحى نشيط", "تنام 12 ساعة وتصحى كسلان"),
    ("تكسب مليون جنيه دلوقتي", "تكسب جنيه يتضاعف كل يوم لمدة شهر"),
    ("تعرف كل لغات العالم", "تعرف تعزف كل الآلات"),
    ("الصيف طول السنة", "الشتا طول السنة"),
    ("تفقد صوتك", "تفقد قدرتك على الأكل اللي بتحبه"),
    ("تبقى مشهور ومحدش يحترمك", "تبقى مجهول والكل يحترمك"),
    ("تعيش في العاصمة الإدارية", "تعيش في وسط البلد"),
    ("تسافر في الفضاء", "تغوص في قاع المحيط"),
    ("تاكل بيتزا طول حياتك", "تاكل كباب طول حياتك"),
    ("تقدر تطير", "تقدر تبقى مش مرئي"),
    ("تحل أي امتحان بدون مذاكرة مرة واحدة", "تذاكر كل حاجة بس تنساها بعد الامتحان"),
    ("القهوة", "الشاي"),
]


async def send_wyr(msg: types.Message):
    a, b = random.choice(WYR)
    try:
        await msg.answer_poll(question="🤔 لو خيروك...", options=[a, b], is_anonymous=False)
    except Exception as e:
        log.warning("poll failed: %s", e)
        await msg.answer(f"🤔 لو خيروك:\n1️⃣ {a}\n2️⃣ {b}\nصوّتوا في الكومنتات! 😂")


@mini_router.message(or_f(Command("wyr"), F.text.in_(["لو خيروك", "لو خيروك؟"])))
async def wyr_msg(message: types.Message):
    await send_wyr(message)


@mini_router.callback_query(F.data == "g_wyr")
async def wyr_cb(callback: types.CallbackQuery):
    await callback.answer()
    await send_wyr(callback.message)