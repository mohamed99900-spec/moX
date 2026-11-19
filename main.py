import os
import asyncio
import logging
import aiohttp
import importlib
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as Btn, BotCommand

from ai_engine import ask_grok_with_buttons, BUTTON_CACHE
from games_engine import games_router, CHALLENGES
from mini_games import mini_router
try:
    quran_router = importlib.import_module("quran").quran_router
except (ImportError, AttributeError):
    logging.warning("Optional Quran module could not be loaded; Quran commands will be unavailable")
    quran_router = Router()
try:
    duas_router = importlib.import_module("duas").duas_router
except (ImportError, AttributeError):
    logging.warning("Optional Duas module could not be loaded; Duas commands will be unavailable")
    duas_router = Router()
try:
    _prayer = importlib.import_module("prayer")
    prayer_router = _prayer.prayer_router
    adhan_loop = _prayer.adhan_loop
except (ImportError, AttributeError):
    logging.warning("Optional prayer module could not be loaded; prayer and adhan features will be unavailable")
    prayer_router = Router()

    async def adhan_loop(bot):
        return None

try:
    extras_router = importlib.import_module("extras").extras_router
except (ImportError, AttributeError):
    logging.warning("Optional extras module could not be loaded; extra commands will be unavailable")
    extras_router = Router()
from persona import fun_router, extract_call, call
from group_admin import admin_router
try:
    gate_module = importlib.import_module("gate")
    gate_router = gate_module.gate_router
    gate_mw = gate_module.gate_mw
    GATE_ENABLED = getattr(gate_module, "GATE_ENABLED", False)
except (ImportError, AttributeError):
    logging.warning("Optional gate module could not be loaded; subscription gate will be disabled")
    gate_router = Router()

    async def gate_mw(handler, event, data):
        return await handler(event, data)

    GATE_ENABLED = False
from utils import safe_edit, safe_answer

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ متغير BOT_TOKEN غير موجود. أضفه في ملف .env أو في إعدادات Render.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ------------------------------------------------------------------
# القوائم
# ------------------------------------------------------------------
def get_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="🧠 اسأل مو الذكي", callback_data="ask_grok_info")],
        [Btn(text="🔥 تحدي", callback_data="start_challenges"),
         Btn(text="🎮 العاب", callback_data="games")],
        [Btn(text="📖 المصحف والقرآن 🎧", callback_data="quran_menu"),
         Btn(text="🤲 أذكار وأدعية", callback_data="duas_menu")],
        [Btn(text="🕌 مواقيت وأذان", callback_data="prayer_menu"),
         Btn(text="📋 مهام اليوم", callback_data="quests")],
        [Btn(text="🏆 المتصدرين", callback_data="lb"),
         Btn(text="📊 إحصائياتي", callback_data="my_stats")],
        [Btn(text="🎁 هدية يومية", callback_data="daily"),
         Btn(text="🛒 المتجر", callback_data="shop")],
        [Btn(text="😂 نكتة", callback_data="joke"),
         Btn(text="📚 الأقسام", callback_data="cats")],
        [Btn(text="🛡️ أوامر الإدارة", callback_data="admin_help")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[Btn(text="🏠 القائمة الرئيسية", callback_data="main_menu")]])


WELCOME = (
    "🚀 يا أهلاً بـ {n} في <b>MoX Assistant</b>!\n\n"
    "أنا <b>مو</b> 😎 بوت الجروب الأسطوري:\n"
    "• 🧠 اسألني أي حاجة وهجاوبك بالمصري\n"
    f"• 🔥 {len(CHALLENGES)} سؤال + سباقات + ألعاب حظ ومهارة 🎰🎯⚽\n"
    "• 📖 المصحف الشريف والتلاوة بصوت الشيخ مشاري العفاسي 🎧\n"
    "• 🕌 مواقيت الصلاة + أذان تلقائي في الجروبات + أذكار وأدعية\n"
    "• 🏆 متصدرين: الجروب والعالم وأقوى الجروبات\n"
    "• 📋 مهام يومية + 🛒 ألقاب + 🏅 شارات + 🎁 هدايا\n\n"
    "اختار من القائمة 👇"
)


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await safe_answer(message, WELCOME.format(n=call(message.from_user)), get_main_menu())


@dp.message(Command("menu", "help"))
async def cmd_menu(message: types.Message):
    await safe_answer(message, "🏠 <b>القائمة الرئيسية لـ MoX Assistant</b>", get_main_menu())


@dp.message(F.text.in_(["القائمة", "المساعدة", "مساعدة", "الاوامر", "الأوامر"]))
async def txt_menu(message: types.Message):
    await safe_answer(message, "🏠 <b>القائمة الرئيسية لـ MoX Assistant</b>", get_main_menu())


@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery):
    await callback.answer()
    await safe_edit(callback.message,
                    "🏠 <b>القائمة الرئيسية لـ MoX Assistant</b>\n\nاختار اللي يعجبك 👇",
                    get_main_menu())


@dp.callback_query(F.data == "ask_grok_info")
async def ask_info(callback: types.CallbackQuery):
    await callback.answer()
    text = (
        "🧠 <b>اسأل مو الذكي</b>\n\n"
        "• في الخاص: اكتب سؤالك على طول وهرد عليك.\n"
        "• في الجروب: <code>/ask سؤالك</code> أو ابدأ رسالتك بـ <code>مو</code> وبعدها السؤال، "
        "أو اعمل Reply على رسالة من رسايلي.\n\n"
        "💡 بفتكر آخر كلامنا، فكمّل في نفس الموضوع براحتك."
    )
    await safe_edit(callback.message, text, back_kb())


@dp.callback_query(F.data == "admin_help")
async def show_admin_help(callback: types.CallbackQuery):
    await callback.answer()
    help_text = (
        "🛡️ <b>أوامر الإدارة:</b>\n"
        "<code>حظر</code> • <code>الغاء الحظر</code> • <code>طرد</code> • <code>كتم</code> (<code>كتم 30</code> = 30 دقيقة) • "
        "<code>الغاء الكتم</code> • <code>تحذير</code> (3 = كتم 24 ساعة) • <code>قفل الشات</code> • "
        "<code>فتح الشات</code> • <code>تثبيت</code> • <code>حذف</code>\n\n"
        "🕌 <b>الأذان (للمشرفين):</b>\n"
        "<code>تفعيل الاذان</code> أو <code>تفعيل الاذان المنصورة</code> • <code>ايقاف الاذان</code> • "
        "<code>ضبط المدينة طنطا</code> • <code>تجربة الاذان</code>\n"
        "للجميع: <code>مواقيت الصلاة</code>\n\n"
        "📖 <b>المصحف:</b> <code>سورة الكهف</code> • <code>اية 2 255</code> • <code>صفحة 50</code> • "
        "<code>المصحف</code> • <code>اذكار الصباح</code>\n\n"
        "🎮 <b>اللعب:</b> <code>تحدي</code> • <code>العاب</code> • <code>سلوت</code> • <code>نرد</code> • "
        "<code>خمن</code> • <code>اسرع كاتب</code> • <code>فك الكلمة</code> • <code>حساب</code> • "
        "<code>كمل المثل</code> • <code>لو خيروك</code> • 🎯⚽🏀🎳\n"
        "<code>المتصدرين</code> (الجروب) • <code>متصدري العالم</code> • <code>الجروبات</code> • "
        "<code>نقاطي</code> • <code>هدية</code> • <code>مهام</code> • <code>المتجر</code>\n\n"
        "😂 <code>نكتة</code> • <code>تحشيش</code> (بالرد) • <code>قيسني</code> • <code>حظي</code>\n\n"
        "⚡ <i>لازم البوت يبقى مشرف بصلاحيات الحذف والحظر، وتقفل Privacy Mode من BotFather.</i>"
    )
    await safe_edit(callback.message, help_text, back_kb())


# ------------------------------------------------------------------
# الذكاء الاصطناعي
# ------------------------------------------------------------------
@dp.callback_query(F.data.startswith("ai_btn:"))
async def handle_ai_dynamic_button(callback: types.CallbackQuery):
    btn_id = callback.data.split(":", 1)[1]
    question = BUTTON_CACHE.get(btn_id)
    if not question:
        await callback.answer("الزرار ده انتهت صلاحيته، ابعت سؤالك كتابةً.", show_alert=True)
        return
    await callback.answer("⏳ لحظة أفكر...")
    wait_msg = await callback.message.answer(f"🔎 {question}\n⏳ ثواني وهرد عليك...")
    answer, kb = await ask_grok_with_buttons(question, callback.from_user.id, callback.from_user.first_name)
    await safe_edit(wait_msg, answer, kb, parse_mode="Markdown")


ai_router = Router()


def group_ai_filter(message: types.Message):
    """في الجروبات: رد على رسالة البوت، أو مناداة 'مو' + سؤال حقيقي."""
    if message.chat.type not in ("group", "supergroup") or not message.text:
        return False
    if message.text.startswith("/") or not message.from_user or message.from_user.is_bot:
        return False
    r = message.reply_to_message
    if r and r.from_user and r.from_user.id == message.bot.id:
        return {"question": message.text}
    called, rest = extract_call(message.text)
    if called and len(rest) >= 12:
        return {"question": rest}
    return False


@ai_router.message(Command("ask"))
async def cmd_ask(message: types.Message, command: CommandObject):
    if not command.args:
        await message.reply("اكتب سؤالك بعد الأمر يا باشا، مثال:\n/ask ما هي عاصمة فرنسا؟")
        return
    wait_msg = await message.reply("⏳ لحظة أفكر...")
    answer, kb = await ask_grok_with_buttons(command.args, message.from_user.id, message.from_user.first_name)
    await safe_edit(wait_msg, answer, kb, parse_mode="Markdown")


@ai_router.message(group_ai_filter)
async def group_ai(message: types.Message, question: str):
    wait_msg = await message.reply("⏳ لحظة أفكر...")
    answer, kb = await ask_grok_with_buttons(question, message.from_user.id, message.from_user.first_name)
    await safe_edit(wait_msg, answer, kb, parse_mode="Markdown")


@ai_router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def handle_text_question(message: types.Message):
    wait_msg = await message.answer("⏳ لحظة أفكر...")
    answer, kb = await ask_grok_with_buttons(message.text, message.from_user.id, message.from_user.first_name)
    await safe_edit(wait_msg, answer, kb, parse_mode="Markdown")


# ------------------------------------------------------------------
# بوابة الاشتراك: بتتركّب على كل الراوترات ما عدا الإدارة والدردشة المرحة
# ------------------------------------------------------------------
for _r in (dp, games_router, mini_router, quran_router, duas_router, prayer_router, extras_router, ai_router):
    _r.message.middleware(gate_mw)
    _r.callback_query.middleware(gate_mw)

# ترتيب الراوترات مهم
dp.include_router(gate_router)     # زرار التحقق (بدون بوابة)
dp.include_router(admin_router)    # الإدارة (بدون بوابة)
dp.include_router(games_router)
dp.include_router(mini_router)
dp.include_router(quran_router)
dp.include_router(duas_router)
dp.include_router(prayer_router)
dp.include_router(extras_router)
dp.include_router(fun_router)      # الدردشة المرحة (بدون بوابة)
dp.include_router(ai_router)


# ------------------------------------------------------------------
# خادم الويب للتوافق مع Render
# ------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="MoX Assistant is running!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()


async def keep_alive():
    """بيعمل ping لنفسه كل 10 دقايق عشان Render المجاني ما ينامش."""
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    await asyncio.sleep(60)
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)):
                    pass
        except Exception as e:
            logging.warning("keep-alive failed: %s", e)
        await asyncio.sleep(600)


async def main():
    await start_web_server()
    asyncio.create_task(keep_alive())
    asyncio.create_task(adhan_loop(bot))
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands([
        BotCommand(command="start", description="ابدأ"),
        BotCommand(command="menu", description="القائمة الرئيسية"),
        BotCommand(command="quran", description="المصحف بصوت العفاسي"),
        BotCommand(command="prayer", description="مواقيت الصلاة"),
        BotCommand(command="duas", description="أذكار وأدعية"),
        BotCommand(command="challenge", description="تحدي / سباق أسئلة"),
        BotCommand(command="games", description="صالة الألعاب"),
        BotCommand(command="quests", description="مهام اليوم"),
        BotCommand(command="top", description="المتصدرين"),
        BotCommand(command="world", description="متصدري العالم"),
        BotCommand(command="groups", description="أقوى الجروبات"),
        BotCommand(command="me", description="إحصائياتي"),
        BotCommand(command="daily", description="الهدية اليومية"),
        BotCommand(command="shop", description="متجر الألقاب"),
        BotCommand(command="slot", description="سلوت"),
        BotCommand(command="joke", description="نكتة"),
        BotCommand(command="ask", description="اسأل الذكاء الاصطناعي"),
    ])
    logging.info("Gate enabled: %s", GATE_ENABLED)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main()) 