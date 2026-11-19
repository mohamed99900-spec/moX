"""مواقيت الصلاة + الأذان التلقائي في الجروبات (تكبير الأذان + صوت الأذان + دعاء بعد الأذان)."""
import os
import re
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp
from aiogram import Router, types, F
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton as Btn, FSInputFile)
from aiogram.exceptions import TelegramForbiddenError

from group_admin import is_user_admin
from quran_data import norm_ar
from storage import DATA, save_data
from utils import esc, show, safe_answer

log = logging.getLogger("mox.prayer")
prayer_router = Router()

API = "https://api.aladhan.com/v1/timingsByCity"

# اسم المدينة: (city, country, method, timezone)
EG = ("Egypt", 5, "Africa/Cairo")
SA = ("Saudi Arabia", 4, "Asia/Riyadh")
CITIES = {
    "القاهرة": ("Cairo",) + EG, "الجيزة": ("Giza",) + EG, "الإسكندرية": ("Alexandria",) + EG,
    "المنصورة": ("Mansoura",) + EG, "طنطا": ("Tanta",) + EG, "الزقازيق": ("Zagazig",) + EG,
    "بورسعيد": ("Port Said",) + EG, "السويس": ("Suez",) + EG, "الإسماعيلية": ("Ismailia",) + EG,
    "دمياط": ("Damietta",) + EG, "الفيوم": ("Faiyum",) + EG, "بني سويف": ("Beni Suef",) + EG,
    "المنيا": ("Minya",) + EG, "أسيوط": ("Asyut",) + EG, "سوهاج": ("Sohag",) + EG, "قنا": ("Qena",) + EG,
    "الأقصر": ("Luxor",) + EG, "أسوان": ("Aswan",) + EG, "شرم الشيخ": ("Sharm El Sheikh",) + EG,
    "الغردقة": ("Hurghada",) + EG, "مرسى مطروح": ("Marsa Matruh",) + EG, "دمنهور": ("Damanhur",) + EG,
    "بنها": ("Banha",) + EG, "شبين الكوم": ("Shibin El Kom",) + EG, "كفر الشيخ": ("Kafr El Sheikh",) + EG,
    "مكة": ("Makkah",) + SA, "المدينة المنورة": ("Medina",) + SA, "الرياض": ("Riyadh",) + SA,
    "جدة": ("Jeddah",) + SA, "الدمام": ("Dammam",) + SA,
    "دبي": ("Dubai", "United Arab Emirates", 16, "Asia/Dubai"),
    "أبوظبي": ("Abu Dhabi", "United Arab Emirates", 16, "Asia/Dubai"),
    "الكويت": ("Kuwait City", "Kuwait", 9, "Asia/Kuwait"),
    "الدوحة": ("Doha", "Qatar", 10, "Asia/Qatar"),
    "عمان": ("Amman", "Jordan", 3, "Asia/Amman"),
    "القدس": ("Jerusalem", "Palestine", 3, "Asia/Jerusalem"),
    "بيروت": ("Beirut", "Lebanon", 3, "Asia/Beirut"),
    "بغداد": ("Baghdad", "Iraq", 3, "Asia/Baghdad"),
    "الخرطوم": ("Khartoum", "Sudan", 5, "Africa/Khartoum"),
    "طرابلس": ("Tripoli", "Libya", 3, "Africa/Tripoli"),
    "تونس": ("Tunis", "Tunisia", 18, "Africa/Tunis"),
    "الجزائر": ("Algiers", "Algeria", 3, "Africa/Algiers"),
    "الرباط": ("Rabat", "Morocco", 21, "Africa/Casablanca"),
}
CITY_INDEX = {norm_ar(k).replace("ال", "", 1) if norm_ar(k).startswith("ال") else norm_ar(k): k for k in CITIES}
QUICK = ["القاهرة", "الإسكندرية", "الجيزة", "المنصورة", "طنطا", "أسوان", "مكة", "الرياض"]
DEFAULT_CITY = "القاهرة"

PRAYERS = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
AR = {"Fajr": "الفجر", "Sunrise": "الشروق", "Dhuhr": "الظهر", "Asr": "العصر", "Maghrib": "المغرب", "Isha": "العشاء"}
TCACHE: dict = {}
SENT: set = set()
FILE_IDS: dict = {}

# ---------------- ملفات صوت الأذان ----------------
# الأفضل: حط ملف adhan.mp3 (و adhan_fajr.mp3 اختياري) جنب main.py.
ADHAN_LOCAL = {"normal": "adhan.mp3", "fajr": "adhan_fajr.mp3"}
DEFAULT_URLS = [
    "https://www.islamcan.com/audio/adhan/azan1.mp3",
    "https://github.com/AalianKhan/adhans/raw/master/adhan.mp3",
]
FAJR_URLS = ["https://github.com/AalianKhan/adhans/raw/master/adhan_fajr.mp3"]


def adhan_sources(prayer: str):
    kind = "fajr" if prayer == "Fajr" else "normal"
    srcs = []
    local = ADHAN_LOCAL[kind] if os.path.exists(ADHAN_LOCAL[kind]) else (
        ADHAN_LOCAL["normal"] if os.path.exists(ADHAN_LOCAL["normal"]) else None)
    if local:
        srcs.append(FSInputFile(local))
    env = os.getenv("ADHAN_FAJR_URL") if kind == "fajr" else None
    env = env or os.getenv("ADHAN_URL")
    if env:
        srcs.append(env)
    if kind == "fajr":
        srcs += FAJR_URLS
    srcs += DEFAULT_URLS
    return kind, srcs


ADHAN_TEXT = (
    "اللَّهُ أَكْبَرُ اللَّهُ أَكْبَرُ\nاللَّهُ أَكْبَرُ اللَّهُ أَكْبَرُ\n"
    "أَشْهَدُ أَنْ لَا إِلَهَ إِلَّا اللَّهُ\nأَشْهَدُ أَنْ لَا إِلَهَ إِلَّا اللَّهُ\n"
    "أَشْهَدُ أَنَّ مُحَمَّدًا رَسُولُ اللَّهِ\nأَشْهَدُ أَنَّ مُحَمَّدًا رَسُولُ اللَّهِ\n"
    "حَيَّ عَلَى الصَّلَاةِ\nحَيَّ عَلَى الصَّلَاةِ\nحَيَّ عَلَى الْفَلَاحِ\nحَيَّ عَلَى الْفَلَاحِ\n"
    "{fajr}"
    "اللَّهُ أَكْبَرُ اللَّهُ أَكْبَرُ\nلَا إِلَهَ إِلَّا اللَّهُ"
)
FAJR_LINE = "الصَّلَاةُ خَيْرٌ مِنَ النَّوْمِ\nالصَّلَاةُ خَيْرٌ مِنَ النَّوْمِ\n"
DUA_AFTER = (
    "🤲 <b>دعاء بعد الأذان:</b>\n"
    "اللَّهُمَّ رَبَّ هَذِهِ الدَّعْوَةِ التَّامَّةِ وَالصَّلَاةِ الْقَائِمَةِ، آتِ مُحَمَّدًا الْوَسِيلَةَ "
    "وَالْفَضِيلَةَ، وَابْعَثْهُ مَقَامًا مَحْمُودًا الَّذِي وَعَدْتَهُ\n<i>(البخاري)</i>\n\n"
    "🤍 قوموا إلى صلاتكم يرحمكم الله... ولا تنسوا الصلاة على النبي ﷺ"
)


# ---------------- المواقيت ----------------
def find_city(text: str):
    q = norm_ar(text or "")
    if not q:
        return None
    q = q[2:] if q.startswith("ال") else q
    if q in CITY_INDEX:
        return CITY_INDEX[q]
    for k, v in CITY_INDEX.items():
        if k.startswith(q) and len(q) >= 3:
            return v
    return None


async def get_timings(ckey: str, day):
    ck = (ckey, day.isoformat())
    if ck in TCACHE:
        return TCACHE[ck]
    city, country, method, _tz = CITIES[ckey]
    url = f"{API}/{day.strftime('%d-%m-%Y')}"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
        async with s.get(url, params={"city": city, "country": country, "method": method}) as r:
            if r.status != 200:
                raise RuntimeError(f"aladhan HTTP {r.status}")
            j = await r.json()
    raw = j["data"]["timings"]
    out = {}
    for k in ("Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"):
        m = re.search(r"(\d{1,2}):(\d{2})", raw[k])
        out[k] = (int(m.group(1)), int(m.group(2)))
    if len(TCACHE) > 200:
        TCACHE.clear()
    TCACHE[ck] = out
    return out


def fmt12(h, m) -> str:
    suffix = "ص" if h < 12 else "م"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def chat_cfg(chat_id: int) -> dict:
    return DATA["adhan"].setdefault(str(chat_id), {"city": DEFAULT_CITY, "on": False})


async def times_text(ckey: str):
    tz = ZoneInfo(CITIES[ckey][3])
    now = datetime.now(tz)
    t = await get_timings(ckey, now.date())
    lines = [f"🕌 <b>مواقيت الصلاة — {esc(ckey)}</b>", f"📅 {now.strftime('%Y-%m-%d')}\n"]
    nxt = None
    for k in ("Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"):
        h, m = t[k]
        when = now.replace(hour=h, minute=m, second=0, microsecond=0)
        is_next = nxt is None and when > now and k != "Sunrise"
        if is_next:
            nxt = (k, when)
        lines.append(f"{'👉 ' if is_next else '▫️ '}{AR[k]}: <b>{fmt12(h, m)}</b>")
    if nxt is None:
        tomorrow = await get_timings(ckey, now.date() + timedelta(days=1))
        h, m = tomorrow["Fajr"]
        nxt = ("Fajr", (now + timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0))
    mins = int((nxt[1] - now).total_seconds() // 60)
    lines.append(f"\n⏳ باقي على <b>{AR[nxt[0]]}</b>: {mins // 60} ساعة و{mins % 60} دقيقة")
    return "\n".join(lines)


def prayer_kb(chat_is_group: bool):
    rows, row = [], []
    for i, name in enumerate(QUICK):
        row.append(Btn(text=name, callback_data=f"pt:{name}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Btn(text="🤲 أذكار وأدعية", callback_data="duas_menu"), Btn(text="📖 المصحف", callback_data="quran_menu")])
    rows.append([Btn(text="🏠 الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_times(target, chat: types.Chat, ckey: str = None):
    cfg = chat_cfg(chat.id)
    ckey = ckey or cfg["city"]
    try:
        text = await times_text(ckey)
    except Exception as e:
        log.warning("times failed: %s", e)
        text = "⚠️ مش قادر أجيب المواقيت دلوقتي، جرب كمان شوية."
    if chat.type in ("group", "supergroup"):
        state = "✅ شغال" if cfg["on"] else "⏸️ مقفول"
        text += f"\n\n🔔 الأذان التلقائي: {state}\n<i>(المشرف يكتب: تفعيل الاذان)</i>"
    await show(target, text, prayer_kb(chat.type != "private"))


@prayer_router.callback_query(F.data == "prayer_menu")
async def prayer_menu_cb(callback: types.CallbackQuery):
    await callback.answer()
    await show_times(callback, callback.message.chat)


@prayer_router.callback_query(F.data.startswith("pt:"))
async def city_cb(callback: types.CallbackQuery):
    ckey = callback.data.split(":", 1)[1]
    if ckey not in CITIES:
        await callback.answer()
        return
    chat = callback.message.chat
    if chat.type == "private" or await is_admin_callback(callback):
        chat_cfg(chat.id)["city"] = ckey
        save_data()
    await callback.answer(f"📍 {ckey}")
    await show_times(callback, chat, ckey)


async def is_admin_callback(callback: types.CallbackQuery) -> bool:
    try:
        m = await callback.bot.get_chat_member(callback.message.chat.id, callback.from_user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


# ---------------- أوامر نصية ----------------
def parse(m: types.Message, cmds, phrases):
    t = (m.text or "").strip()
    if not t:
        return None
    if t.startswith("/"):
        head, _, rest = t.partition(" ")
        return rest.strip() if head[1:].split("@")[0].lower() in cmds else None
    for p in phrases:
        if t == p or t.startswith(p + " "):
            return t[len(p):].strip()
    return None


def f_times(m):
    a = parse(m, {"prayer", "salah"}, ["مواقيت الصلاة", "مواقيت الصلاه", "مواعيد الصلاة", "الصلاة", "الصلاه", "مواقيت"])
    return {"args": a} if a is not None else False


def f_on(m):
    a = parse(m, {"adhan_on"}, ["تفعيل الاذان", "تفعيل الأذان", "شغل الاذان", "شغل الأذان"])
    return {"args": a} if a is not None else False


def f_off(m):
    a = parse(m, {"adhan_off"}, ["ايقاف الاذان", "إيقاف الأذان", "ايقاف الأذان", "قفل الاذان", "قفل الأذان"])
    return {"args": a} if a is not None else False


def f_city(m):
    a = parse(m, {"city"}, ["ضبط المدينة", "ضبط المدينه", "تغيير المدينة"])
    return {"args": a} if a is not None else False


def f_test(m):
    a = parse(m, {"adhan_test"}, ["تجربة الاذان", "تجربة الأذان"])
    return {"args": a} if a is not None else False


@prayer_router.message(f_times)
async def cmd_times(message: types.Message, args: str):
    ckey = find_city(args) if args else None
    if args and not ckey:
        await message.reply("🤔 مش لاقي المدينة دي. جرب: القاهرة، الإسكندرية، المنصورة، مكة، الرياض، دبي...")
        return
    await show_times(message, message.chat, ckey)


async def admin_only(message: types.Message) -> bool:
    if message.chat.type == "private":
        await message.reply("🕌 الأذان التلقائي بيشتغل في الجروبات بس يا باشا. ضيفني لجروبك واكتب: تفعيل الاذان")
        return False
    if not await is_user_admin(message):
        await message.reply("⚠️ الأمر ده للمشرفين بس يا معلم 😅")
        return False
    return True


@prayer_router.message(f_on)
async def cmd_on(message: types.Message, args: str):
    if not await admin_only(message):
        return
    cfg = chat_cfg(message.chat.id)
    if args:
        ckey = find_city(args)
        if not ckey:
            await message.reply("🤔 مش لاقي المدينة دي. اكتب مثلاً: <b>تفعيل الاذان المنصورة</b>", parse_mode="HTML")
            return
        cfg["city"] = ckey
    cfg["on"] = True
    save_data()
    await message.reply(
        f"✅ <b>تم تفعيل الأذان التلقائي!</b>\n📍 المدينة: <b>{esc(cfg['city'])}</b>\n\n"
        "هبعت تكبير الأذان + صوت الأذان + دعاء بعده في كل صلاة 🕌\n"
        "لتغيير المدينة: <code>ضبط المدينة الإسكندرية</code>\nللتجربة: <code>تجربة الاذان</code>",
        parse_mode="HTML")


@prayer_router.message(f_off)
async def cmd_off(message: types.Message, args: str):
    if not await admin_only(message):
        return
    chat_cfg(message.chat.id)["on"] = False
    save_data()
    await message.reply("⏸️ تم إيقاف الأذان التلقائي. (اكتب: تفعيل الاذان لما تحب ترجّعه)")


@prayer_router.message(f_city)
async def cmd_city(message: types.Message, args: str):
    if not await admin_only(message):
        return
    ckey = find_city(args)
    if not ckey:
        await message.reply("🤔 اكتب اسم المدينة بعد الأمر، مثال: <code>ضبط المدينة طنطا</code>", parse_mode="HTML")
        return
    chat_cfg(message.chat.id)["city"] = ckey
    save_data()
    await message.reply(f"📍 اتضبطت المدينة على <b>{esc(ckey)}</b> ✅", parse_mode="HTML")


@prayer_router.message(f_test)
async def cmd_test(message: types.Message, args: str):
    if not await admin_only(message):
        return
    await send_adhan(message.bot, message.chat.id, "Dhuhr", chat_cfg(message.chat.id)["city"], test=True)


# ---------------- إرسال الأذان ----------------
async def send_adhan_audio(bot, chat_id: int, prayer: str) -> bool:
    kind, sources = adhan_sources(prayer)
    title = f"أذان {AR[prayer]}"
    fid = FILE_IDS.get(kind)
    if fid:
        try:
            await bot.send_audio(chat_id, fid, title=title, performer="الأذان")
            return True
        except Exception:
            FILE_IDS.pop(kind, None)
    for src in sources:
        try:
            msg = await bot.send_audio(chat_id, src, title=title, performer="الأذان")
            if msg.audio:
                FILE_IDS[kind] = msg.audio.file_id
            return True
        except TelegramForbiddenError:
            raise
        except Exception as e:
            log.info("adhan source failed: %s", e)
    return False


async def send_adhan(bot, chat_id: int, prayer: str, city: str, test: bool = False):
    name = AR[prayer]
    head = (f"🕌 <b>{'(تجربة) ' if test else ''}حان الآن موعد أذان {name}</b>\n📍 حسب توقيت {esc(city)}\n\n")
    text = ADHAN_TEXT.format(fajr=FAJR_LINE if prayer == "Fajr" else "")
    await bot.send_message(chat_id, head + esc(text), parse_mode="HTML")
    ok = await send_adhan_audio(bot, chat_id, prayer)
    if not ok:
        await bot.send_message(
            chat_id, "ℹ️ <i>(صوت الأذان مش متاح دلوقتي — المشرف يحط ملف adhan.mp3 في فولدر البوت أو يضبط ADHAN_URL)</i>",
            parse_mode="HTML")
    extra = []
    if prayer == "Fajr":
        extra = [Btn(text="🌅 أذكار الصباح", callback_data="du:0")]
    elif prayer == "Asr":
        extra = [Btn(text="🌇 أذكار المساء", callback_data="du:1")]
    rows = [[Btn(text="📖 المصحف", callback_data="quran_menu"), Btn(text="🤲 أذكار", callback_data="duas_menu")]]
    if extra:
        rows.insert(0, extra)
    await bot.send_message(chat_id, DUA_AFTER, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    # 🕋 تذكير الجمعة بعد أذان الفجر
    if prayer == "Fajr" and not test and datetime.now(ZoneInfo(CITIES[city][3])).weekday() == 4:
        fk = InlineKeyboardMarkup(inline_keyboard=[[
            Btn(text="🎧 استمع لسورة الكهف", callback_data="qa:18"), Btn(text="📖 اقرأ الكهف", callback_data="qr:18:0")]])
        await bot.send_message(
            chat_id,
            "🕋 <b>جمعة مباركة يا جماعة!</b> 🤍\nلا تنسوا: سورة الكهف، والإكثار من الصلاة على النبي ﷺ، "
            "وساعة الاستجابة قبل المغرب 🤲", reply_markup=fk, parse_mode="HTML")


async def _fire(bot, chat_id: str, prayer: str, city: str):
    try:
        await send_adhan(bot, int(chat_id), prayer, city)
    except TelegramForbiddenError:
        DATA["adhan"].get(chat_id, {})["on"] = False
        save_data()
    except Exception as e:
        log.warning("adhan send failed (%s): %s", chat_id, e)


async def adhan_loop(bot):
    """بيفحص كل 20 ثانية لو دخل وقت صلاة في أي جروب مفعّل."""
    log.info("🕌 adhan scheduler started")
    while True:
        try:
            for chat_id, cfg in list(DATA["adhan"].items()):
                if not cfg.get("on"):
                    continue
                ckey = cfg.get("city", DEFAULT_CITY)
                if ckey not in CITIES:
                    continue
                now = datetime.now(ZoneInfo(CITIES[ckey][3]))
                try:
                    t = await get_timings(ckey, now.date())
                except Exception as e:
                    log.warning("timings failed %s: %s", ckey, e)
                    continue
                for prayer in PRAYERS:
                    h, m = t[prayer]
                    key = (chat_id, now.date().isoformat(), prayer)
                    if now.hour == h and now.minute == m and key not in SENT:
                        SENT.add(key)
                        asyncio.create_task(_fire(bot, chat_id, prayer, ckey))
            if len(SENT) > 2000:
                SENT.clear()
        except Exception as e:
            log.exception("adhan loop error: %s", e)
        await asyncio.sleep(20)
