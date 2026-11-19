"""بوابة الاشتراك الإجباري في قناة البوت."""
import os
import time
import logging
from aiogram import Router, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as Btn

from utils import esc

log = logging.getLogger("mox.gate")
gate_router = Router()

GATE_ENABLED = os.getenv("GATE_ENABLED", "1") == "1"
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)


def _parse_id(v: str):
    v = (v or "").strip()
    if not v or v == "0":
        return None
    return int(v) if v.lstrip("-").isdigit() else v     # رقم أو @username


# الاشتراكات المطلوبة: (الاسم, ID, الرابط)
REQUIRED = []
_ch = _parse_id(os.getenv("CHANNEL_ID", "-1003945976264"))
if _ch is not None:
    REQUIRED.append(("القناة", _ch, os.getenv("CHANNEL_LINK", "https://t.me/+cCFIWnW4qXIzM2Q0")))
_gr = _parse_id(os.getenv("GROUP_ID", "-1004316047539"))
if _gr is not None:
    REQUIRED.append(("الجروب", _gr, os.getenv("GROUP_LINK", "https://t.me/+wkiUwECX5slhZDM8")))

OK_STATUSES = {"member", "administrator", "creator"}
CACHE: dict = {}        # user_id -> (expires_at, ok)
PROMPTED: dict = {}     # user_id -> last prompt time
_last_err: dict = {}


async def _in_chat(bot, chat_id, user_id: int) -> bool:
    """True لو عضو. لو الفحص نفسه فشل (البوت مش أدمن/ID غلط) بنعتبره عضو عشان ما نقفلش البوت."""
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status in OK_STATUSES or (m.status == "restricted" and getattr(m, "is_member", False))
    except Exception as e:
        now = time.time()
        if now - _last_err.get(chat_id, 0) > 180:
            log.error("⚠️ فشل فحص الاشتراك في %s (%s). تأكد إن البوت أدمن هناك وإن الـ ID صح "
                      "(استخدم /checkchannel). الفحص متوقف لهذا الشات.", chat_id, e)
            _last_err[chat_id] = now
        return True


async def is_subscribed(bot, user_id: int, fresh: bool = False) -> bool:
    now = time.time()
    if not fresh:
        hit = CACHE.get(user_id)
        if hit and hit[0] > now:
            return hit[1]
    ok = True
    for _name, chat_id, _link in REQUIRED:
        if not await _in_chat(bot, chat_id, user_id):
            ok = False
            break
    CACHE[user_id] = (now + (300 if ok else 15), ok)
    return ok


def gate_text() -> str:
    names = " و".join(n for n, _, _ in REQUIRED) or "القناة"
    return ("🔒 <b>استنى يا باشا!</b>\n\n"
            f"عشان تستخدم <b>MoX Assistant</b> لازم تدخل {names} الأول 📢\n"
            "ادخل واضغط <b>تحقق</b> ✅ وهتلاقي كل حاجة مفتوحة قدامك 😎🔥")


def gate_kb() -> InlineKeyboardMarkup:
    rows = [[Btn(text=f"{'📢' if n == 'القناة' else '👥'} ادخل {n}", url=link)] for n, _, link in REQUIRED]
    rows.append([Btn(text="✅ تحقق من الاشتراك", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


class SubscriptionMiddleware(BaseMiddleware):
    """Inner middleware: بيشتغل بس لما يتلقط handler فعلي، فمابيبلعش الكلام العادي."""

    async def __call__(self, handler, event, data):
        if not GATE_ENABLED:
            return await handler(event, data)
        user = getattr(event, "from_user", None)
        if user is None or user.is_bot or user.id == OWNER_ID:
            return await handler(event, data)
        if isinstance(event, types.Message) and event.sender_chat:   # مشرف مجهول
            return await handler(event, data)

        bot = data["bot"]
        if await is_subscribed(bot, user.id):
            return await handler(event, data)

        now = time.time()
        show_prompt = now - PROMPTED.get(user.id, 0) > 45
        if isinstance(event, types.CallbackQuery):
            await event.answer("🔒 لازم تدخل القناة الأول عشان تستخدم البوت! 📢", show_alert=True)
            if show_prompt and event.message:
                PROMPTED[user.id] = now
                await event.message.answer(gate_text(), reply_markup=gate_kb(), parse_mode="HTML")
        elif show_prompt:
            PROMPTED[user.id] = now
            await event.reply(gate_text(), reply_markup=gate_kb(), parse_mode="HTML")
        return None


gate_mw = SubscriptionMiddleware()


@gate_router.callback_query(F.data == "check_sub")
async def check_sub_cb(callback: types.CallbackQuery):
    if await is_subscribed(callback.bot, callback.from_user.id, fresh=True):
        await callback.answer("✅ تمام! اتفتحلك كل حاجة 🔥")
        kb = InlineKeyboardMarkup(inline_keyboard=[[Btn(text="🏠 ادخل القائمة الرئيسية", callback_data="main_menu")]])
        try:
            await callback.message.edit_text(
                "✅ <b>تم التحقق!</b> يا أهلاً بيك في العيلة 💙\nدوس على الزرار وابدأ 👇",
                reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    else:
        await callback.answer("❌ لسه ماشتركتش في القناة! ادخل الأول وبعدين دوس تحقق 😅", show_alert=True)


@gate_router.message(Command("checkchannel"))
async def check_channel(message: types.Message):
    if OWNER_ID and message.from_user.id != OWNER_ID:
        return
    lines = []
    for name, chat_id, link in REQUIRED:
        lines.append(f"<b>{name}</b>: <code>{esc(chat_id)}</code>")
        try:
            chat = await message.bot.get_chat(chat_id)
            me = await message.bot.get_chat_member(chat_id, message.bot.id)
            mine = await message.bot.get_chat_member(chat_id, message.from_user.id)
            lines.append(f"   ✅ {esc(chat.title)} | البوت: <b>{me.status}</b> | انت: <b>{mine.status}</b>")
            if me.status not in ("administrator", "creator"):
                lines.append("   ⚠️ خلي البوت <b>أدمن</b> هناك.")
        except Exception as e:
            lines.append(f"   ❌ <code>{esc(e)}</code>\n   (تأكد من الـ ID ومن إن البوت أدمن)")
    if not lines:
        lines.append("مفيش اشتراكات مطلوبة (CHANNEL_ID / GROUP_ID فاضيين).")
    lines.append("\n💡 لمعرفة ID أي شات: اكتب /chatid جواه، أو حوّل رسالة من القناة للبوت في الخاص.")
    await message.answer("\n".join(lines), parse_mode="HTML")


@gate_router.message(Command("chatid"))
async def chat_id_cmd(message: types.Message):
    await message.reply(f"🆔 ID الشات ده: <code>{message.chat.id}</code>", parse_mode="HTML")


def _forwarded_chat(m: types.Message):
    fo = getattr(m, "forward_origin", None)
    c = getattr(fo, "chat", None) if fo else None
    return {"fchat": c} if c else False


@gate_router.message(_forwarded_chat)
async def forwarded_chat_id(message: types.Message, fchat):
    if OWNER_ID and message.from_user.id != OWNER_ID:
        return
    await message.reply(f"🆔 ID القناة/الجروب اللي حوّلت منه: <code>{fchat.id}</code>\n{esc(fchat.title or '')}",
                        parse_mode="HTML")
