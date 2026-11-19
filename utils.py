import html
import logging
from aiogram import types
from aiogram.exceptions import TelegramBadRequest

log = logging.getLogger("mox")


def esc(text) -> str:
    """تهريب النصوص لاستخدامها داخل HTML."""
    return html.escape(str(text))


def _trim(text: str) -> str:
    return text if len(text) <= 4000 else text[:3990] + "…"


async def safe_edit(msg: types.Message, text: str, kb=None, parse_mode="HTML"):
    """تعديل رسالة بدون ما البوت يقع لو فيه خطأ تنسيق أو الرسالة لم تتغير."""
    text = _trim(text)
    try:
        return await msg.edit_text(text, reply_markup=kb, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "not modified" in err:
            return msg
        if "parse" in err or "entities" in err:
            try:
                return await msg.edit_text(text, reply_markup=kb, parse_mode=None)
            except TelegramBadRequest as e2:
                log.warning("edit failed: %s", e2)
                return msg
        log.warning("edit failed: %s", e)
        return msg


async def safe_answer(msg: types.Message, text: str, kb=None, parse_mode="HTML"):
    """إرسال رسالة جديدة مع نفس الحماية."""
    text = _trim(text)
    try:
        return await msg.answer(text, reply_markup=kb, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if "parse" in str(e).lower() or "entities" in str(e).lower():
            return await msg.answer(text, reply_markup=kb, parse_mode=None)
        raise


async def show(target, text: str, kb=None, parse_mode="HTML"):
    """لو target ضغطة زر -> يعدل الرسالة، لو رسالة -> يرد برسالة جديدة."""
    if isinstance(target, types.CallbackQuery):
        return await safe_edit(target.message, text, kb, parse_mode)
    return await safe_answer(target, text, kb, parse_mode)