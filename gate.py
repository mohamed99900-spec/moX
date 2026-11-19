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
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/+cCFIWnW4qXIzM2Q0")
_raw_id = os.getenv("CHANNEL_ID", "-1003945976264").strip()
CHANNEL_ID = int(_raw_id) if _raw_id.lstrip("-").isdigit() else _raw_id   # رقم أو @username
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

OK_STATUSES = {"member", "administrator", "creator"}
CACHE: dict = {}        # user_id -> (expires_at, ok)
PROMPTED: dict = {}     # user_id -> last prompt time
_last_err = 0.0


async def is_subscribed(bot, user_id: int, fresh: bool = False) -> bool:
    global _last_err
    now = time.time()
    if not fresh:
        hit = CACHE.get(user_id)
        if hit and hit[0] > now:
            return hit[1]
    try:
        m = await bot.get_chat_member(CHANNEL_ID, user_id)
        ok = m.status in OK_STATUSES or (m.status == "restricted" and getattr(m, "is_member", False))
        CACHE[user_id] = (now + (300 if ok else 15), ok)
        return ok
    except Exception as e:
        # لو البوت مش أدمن في القناة أو الـ ID غلط: منقفلش البوت على الناس كلها
        if now - _last_err > 120:
            log.error("⚠️ فشل فحص الاشتراك (%s). تأكد إن البوت أدمن في القناة وإن CHANNEL_ID صح. "
                      "الفحص متوقف مؤقتاً.", e)
            _last_err = now
        return True


def gate_text() -> str:
    return ("🔒 <b>استنى يا باشا!</b>\n\n"
            "عشان تستخدم <b>MoX Assistant</b> لازم تدخل قناتي الأول 📢\n"
            "ادخل القناة وبعدين دوس <b>تحقق</b> ✅ وهتلاقي كل حاجة مفتوحة قدامك 😎🔥")


def gate_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="📢 ادخل القناة", url=CHANNEL_LINK)],
        [Btn(text="✅ تحقق من الاشتراك", callback_data="check_sub")],
    ])


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
    lines = [f"CHANNEL_ID = <code>{esc(CHANNEL_ID)}</code>", f"الرابط = {esc(CHANNEL_LINK)}"]
    try:
        chat = await message.bot.get_chat(CHANNEL_ID)
        lines.append(f"✅ القناة موجودة: <b>{esc(chat.title)}</b>")
        me = await message.bot.get_chat_member(CHANNEL_ID, message.bot.id)
        lines.append(f"حالة البوت في القناة: <b>{me.status}</b>")
        if me.status not in ("administrator", "creator"):
            lines.append("⚠️ لازم تخلي البوت <b>أدمن</b> في القناة عشان يقدر يفحص الأعضاء.")
        mine = await message.bot.get_chat_member(CHANNEL_ID, message.from_user.id)
        lines.append(f"حالتك انت: <b>{mine.status}</b>")
    except Exception as e:
        lines.append(f"❌ خطأ: <code>{esc(e)}</code>\nتأكد من CHANNEL_ID ومن إن البوت أدمن في القناة.")
    await message.answer("\n".join(lines), parse_mode="HTML")