import os
import re
import random
from datetime import datetime, timedelta, timezone

from aiogram import Router, types, F
from aiogram.filters import Command, or_f
from aiogram.types import ChatPermissions

from utils import esc

admin_router = Router()

ANTI_LINKS = os.getenv("ANTI_LINKS", "1") == "1"          # حذف الروابط
ANTI_MENTIONS = os.getenv("ANTI_MENTIONS", "0") == "1"    # حذف المعرفات @username
MAX_WARNS = 3
WARNS: dict = {}  # (chat_id, user_id) -> عدد التحذيرات

WELCOMES = [
    "🎉 يا أهلاً يا أهلاً بـ <b>{n}</b>! نورت الجروب يا باشا ✨ اكتب <b>تحدي</b> وورّينا شطارتك 🔥",
    "👋 <b>{n}</b> وصل! جهزوا الشاي والكراسي 😂 اكتب <b>العاب</b> وابدأ تجمع نقط 🎮",
    "🔥 نورتنا يا <b>{n}</b>! الدخول بالسلامة والخروج بالنقط 😎 اكتب <b>هدية</b> وخد هديتك",
    "🥳 أهلاً يا <b>{n}</b>! احنا هنا عيلة واحدة... وبنلعب كتير. اكتب <b>تحدي</b> 😂",
]

LINK_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/)", re.I)
MENTION_RE = re.compile(r"@\w{4,}")


def trig(cmds, words):
    """يقبل الأمر بالإنجليزي (/ban أو /ban@botname) أو الكلمة العربية."""
    return or_f(Command(*cmds), F.text.in_(words))


def full_perms() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True, can_send_audios=True, can_send_documents=True,
        can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
        can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
        can_add_web_page_previews=True, can_invite_users=True,
    )


async def is_admin_id(bot, chat_id: int, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


async def is_user_admin(message: types.Message) -> bool:
    if message.chat.type == "private":
        return False
    # مشرف مجهول (Anonymous Admin)
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True
    if not message.from_user:
        return False
    return await is_admin_id(message.bot, message.chat.id, message.from_user.id)


async def get_target(message: types.Message):
    """يرجع (العضو المستهدف) أو None مع رسالة خطأ مناسبة."""
    if not await is_user_admin(message):
        return None
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("⚠️ رد على رسالة العضو الأول يا باشا 😅")
        return None
    target = message.reply_to_message.from_user
    if target.is_bot and target.id == message.bot.id:
        return None
    if await is_admin_id(message.bot, message.chat.id, target.id):
        await message.reply("⚠️ ده مشرف يا معلم، مقدرش أقرب منه 😂")
        return None
    return target


# --- 1. حظر ---
@admin_router.message(trig(["ban"], ["حظر", "ban"]))
async def ban_user(message: types.Message):
    target = await get_target(message)
    if not target:
        return
    try:
        await message.bot.ban_chat_member(message.chat.id, target.id)
        await message.reply(f"🚫 <b>{esc(target.full_name)}</b> اتحظر نهائياً... مع السلامة يا حبيبي 👋😂", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ لم أتمكن من الحظر. تأكد أنني مشرف ولدي الصلاحية.\n({e})")


# --- 2. إلغاء الحظر ---
@admin_router.message(trig(["unban"], ["الغاء الحظر", "إلغاء الحظر", "فك الحظر", "unban"]))
async def unban_user(message: types.Message):
    if not await is_user_admin(message):
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("⚠️ يرجى الرد على رسالة العضو لفك الحظر عنه.")
        return
    target = message.reply_to_message.from_user
    try:
        await message.bot.unban_chat_member(message.chat.id, target.id, only_if_banned=True)
        await message.reply(f"✅ <b>{esc(target.full_name)}</b> اتفك حظره... المرة دي اتلم بقى 😏", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ حدث خطأ: {e}")


# --- 3. طرد ---
@admin_router.message(trig(["kick"], ["طرد", "kick"]))
async def kick_user(message: types.Message):
    target = await get_target(message)
    if not target:
        return
    try:
        await message.bot.ban_chat_member(message.chat.id, target.id)
        await message.bot.unban_chat_member(message.chat.id, target.id)
        await message.reply(f"👢 <b>{esc(target.full_name)}</b> اتشال من الجروب (يقدر يرجع بالرابط لو اتأدب) 😂", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ لم أتمكن من الطرد: {e}")


# --- 4. كتم (مع مدة اختيارية بالدقائق: كتم 30) ---
@admin_router.message(or_f(Command("mute"), F.text.in_(["كتم", "mute"]), F.text.regexp(r"^(كتم|mute)\s+\d+$")))
async def mute_user(message: types.Message):
    target = await get_target(message)
    if not target:
        return
    nums = re.findall(r"\d+", message.text or "")
    minutes = int(nums[0]) if nums else 0
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes) if minutes else None
    try:
        await message.bot.restrict_chat_member(
            message.chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        dur = f"لمدة {minutes} دقيقة" if minutes else "حتى فك الكتم"
        await message.reply(f"🔇 <b>{esc(target.full_name)}</b> اتكتم {dur}... ريّح ودنينا شوية 😂", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ لم أتمكن من الكتم: {e}")


# --- 5. إلغاء الكتم ---
@admin_router.message(trig(["unmute"], ["الغاء الكتم", "إلغاء الكتم", "فك الكتم", "unmute"]))
async def unmute_user(message: types.Message):
    if not await is_user_admin(message):
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("⚠️ يرجى الرد على رسالة العضو لفك الكتم عنه.")
        return
    target = message.reply_to_message.from_user
    try:
        await message.bot.restrict_chat_member(message.chat.id, target.id, permissions=full_perms())
        await message.reply(f"🔊 <b>{esc(target.full_name)}</b> رجع يتكلم... اتفضل يا حبيبي بس بأدب 😏", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ حدث خطأ: {e}")


# --- 6. قفل / فتح الدردشة ---
@admin_router.message(trig(["lock"], ["قفل الشات", "قفل الجروب", "lock"]))
async def lock_chat(message: types.Message):
    if not await is_user_admin(message):
        return
    try:
        await message.bot.set_chat_permissions(message.chat.id, ChatPermissions(can_send_messages=False))
        await message.reply("🔒 <b>الشات اتقفل بأمر المشرفين</b> — كله يهدى ويشرب شاي ☕", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ تأكد من صلاحيات البوت: {e}")


@admin_router.message(trig(["unlock"], ["فتح الشات", "فتح الجروب", "unlock"]))
async def unlock_chat(message: types.Message):
    if not await is_user_admin(message):
        return
    try:
        await message.bot.set_chat_permissions(message.chat.id, full_perms())
        await message.reply("🔓 <b>الشات اتفتح!</b> اتفضلوا يا جماعة والكلام بحساب 😎", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ تأكد من صلاحيات البوت: {e}")


# --- 7. تثبيت / حذف رسالة ---
@admin_router.message(trig(["pin"], ["تثبيت", "pin"]))
async def pin_message(message: types.Message):
    if not await is_user_admin(message) or not message.reply_to_message:
        return
    try:
        await message.bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id)
        await message.reply("📌 اتثبتت يا باشا!")
    except Exception as e:
        await message.reply(f"❌ تعذر التثبيت: {e}")


@admin_router.message(trig(["del"], ["حذف", "مسح", "del"]))
async def delete_message(message: types.Message):
    if not await is_user_admin(message) or not message.reply_to_message:
        return
    try:
        await message.reply_to_message.delete()
        await message.delete()
    except Exception as e:
        await message.reply(f"❌ تعذر الحذف: {e}")


# --- 8. نظام التحذيرات (3 تحذيرات = كتم 24 ساعة) ---
@admin_router.message(trig(["warn"], ["تحذير", "warn"]))
async def warn_user(message: types.Message):
    target = await get_target(message)
    if not target:
        return
    key = (message.chat.id, target.id)
    WARNS[key] = WARNS.get(key, 0) + 1
    count = WARNS[key]
    if count >= MAX_WARNS:
        WARNS[key] = 0
        try:
            await message.bot.restrict_chat_member(
                message.chat.id, target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now(timezone.utc) + timedelta(hours=24),
            )
            await message.reply(
                f"⛔ <b>{esc(target.full_name)}</b> خد {MAX_WARNS} إنذارات واتكتم 24 ساعة... خد إجازة يا صاحبي 😂",
                parse_mode="HTML")
        except Exception as e:
            await message.reply(f"❌ لم أتمكن من الكتم: {e}")
    else:
        await message.reply(
            f"⚠️ إنذار لـ <b>{esc(target.full_name)}</b> ({count}/{MAX_WARNS}) — ركز يا معلم، الكارت الأحمر قرب 🟥😂", parse_mode="HTML")


@admin_router.message(trig(["unwarn"], ["الغاء التحذير", "مسح التحذيرات", "unwarn"]))
async def unwarn_user(message: types.Message):
    if not await is_user_admin(message) or not message.reply_to_message:
        return
    target = message.reply_to_message.from_user
    WARNS[(message.chat.id, target.id)] = 0
    await message.reply(f"✅ اتمسحت إنذارات <b>{esc(target.full_name)}</b>... صفحة جديدة 😎", parse_mode="HTML")


# --- 9. الترحيب بالأعضاء الجدد ---
@admin_router.message(F.new_chat_members)
async def welcome_new_members(message: types.Message):
    for user in message.new_chat_members:
        if user.is_bot:
            continue
        await message.answer(
            random.choice(WELCOMES).format(n=esc(user.full_name)),
            parse_mode="HTML",
        )


# --- 10. منع الروابط من غير المشرفين ---
def _has_link(message: types.Message) -> bool:
    if message.chat.type not in ("group", "supergroup") or not message.text:
        return False
    if not (ANTI_LINKS or ANTI_MENTIONS):
        return False
    if ANTI_LINKS:
        if LINK_RE.search(message.text):
            return True
        if any(e.type in ("url", "text_link") for e in (message.entities or [])):
            return True
    if ANTI_MENTIONS and MENTION_RE.search(message.text):
        return True
    return False


@admin_router.message(_has_link)
async def anti_links(message: types.Message):
    if await is_user_admin(message):
        return
    try:
        await message.delete()
        await message.answer(
            f"🚫 ياعم <b>{esc(message.from_user.first_name)}</b>، ممنوع الروابط هنا! احنا مش مكتب إعلانات 😂",
            parse_mode="HTML")
    except Exception:
        pass