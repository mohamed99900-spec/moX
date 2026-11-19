"""المصحف والقرآن الكريم بصوت الشيخ مشاري راشد العفاسي."""
import re
import random
import asyncio
import logging
import uuid
from datetime import datetime, timezone

import aiohttp
from aiogram import Router, types, F
from aiogram.filters import Command, or_f
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton as Btn,
                           BufferedInputFile)

import persona
try:
    from .quran_data import (SURAHS, TOTAL_AYAT, DATA_OK, SAFE_MAKKI, SAFE_MADANI, locate,  # type: ignore[reportMissingImports]
                             ayah_audio, surah_audio_urls, find_surah, ar_digits)
except ImportError:
    from quran_data import (SURAHS, TOTAL_AYAT, DATA_OK, SAFE_MAKKI, SAFE_MADANI, locate,  # type: ignore[reportMissingImports]
                            ayah_audio, surah_audio_urls, find_surah, ar_digits)
from storage import get_user, add_points, save_data
from utils import esc, show, safe_edit, safe_answer

log = logging.getLogger("mox.quran")
quran_router = Router()

API = "https://api.alquran.cloud/v1"
RECITER = "الشيخ مشاري راشد العفاسي"
PER_INDEX_PAGE = 24
MAX_DOWNLOAD = 49 * 1024 * 1024
_dl_lock = asyncio.Semaphore(1)
_session = None
CACHE: dict = {}


def http() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25))
    return _session


async def fetch_json(url: str):
    async with http().get(url) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}")
        return await r.json()


def cache_put(key, value):
    if len(CACHE) > 400:
        CACHE.pop(next(iter(CACHE)))
    CACHE[key] = value
    return value


async def get_surah_ayahs(n: int):
    key = ("s", n)
    if key in CACHE:
        return CACHE[key]
    j = await fetch_json(f"{API}/surah/{n}/quran-uthmani")
    return cache_put(key, [(a["numberInSurah"], a["text"]) for a in j["data"]["ayahs"]])


async def get_page_ayahs(p: int):
    key = ("p", p)
    if key in CACHE:
        return CACHE[key]
    j = await fetch_json(f"{API}/page/{p}/quran-uthmani")
    return cache_put(key, [(a["surah"]["number"], a["numberInSurah"], a["text"]) for a in j["data"]["ayahs"]])


async def get_ayah_text(s: int, a: int) -> str:
    key = ("a", s, a)
    if key in CACHE:
        return CACHE[key]
    j = await fetch_json(f"{API}/ayah/{s}:{a}/quran-uthmani")
    return cache_put(key, j["data"]["text"])


def chunk_surah(ayahs, limit=3300):
    pages, cur = [], ""
    for num, text in ayahs:
        piece = f"{text} ﴿{ar_digits(num)}﴾ "
        if cur and len(cur) + len(piece) > limit:
            pages.append(cur.strip())
            cur = ""
        cur += piece
    if cur.strip():
        pages.append(cur.strip())
    return pages


# ==================================================================
#                       إرسال الصوت (العفاسي)
# ==================================================================
async def download(url: str):
    async with _dl_lock:
        try:
            async with http().get(url, timeout=aiohttp.ClientTimeout(total=300)) as r:
                if r.status != 200:
                    return None
                size = int(r.headers.get("Content-Length") or 0)
                if size > MAX_DOWNLOAD:
                    return "big"
                data = await r.read()
                return "big" if len(data) > MAX_DOWNLOAD else data
        except Exception as e:
            log.warning("download failed %s: %s", url, e)
            return None


async def send_audio_smart(msg: types.Message, urls: list, title: str, caption: str, kb=None) -> str:
    """بيجرب الإرسال بالرابط، وبعدين بالتحميل والرفع. يرجع: ok / big / fail."""
    for url in urls[:2]:
        try:
            await msg.answer_audio(audio=url, title=title, performer=RECITER, caption=caption,
                                   reply_markup=kb, parse_mode="HTML")
            return "ok"
        except Exception as e:
            log.info("audio by url failed (%s): %s", url, e)
        data = await download(url)
        if data == "big":
            return "big"
        if data:
            try:
                await msg.answer_audio(
                    audio=BufferedInputFile(data, filename=f"{title}.mp3"),
                    title=title, performer=RECITER, caption=caption,
                    reply_markup=kb, parse_mode="HTML")
                return "ok"
            except Exception as e:
                log.warning("upload failed: %s", e)
    return "fail"


# ==================================================================
#                         القوائم والصفحات
# ==================================================================
def quran_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="📚 فهرس السور", callback_data="qi:0"), Btn(text="📄 صفحات المصحف", callback_data="qp:1")],
        [Btn(text="🎲 آية عشوائية 🎧", callback_data="qrand"), Btn(text="🌟 آية اليوم", callback_data="qday")],
        [Btn(text="🕌 آية الكرسي 🎧", callback_data="qk"), Btn(text="🧠 تحدي القرآن", callback_data="qq:new")],
        [Btn(text="🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])


QURAN_TEXT = (
    "📖 <b>المصحف الشريف</b>\n"
    f"🎧 التلاوة بصوت <b>{RECITER}</b>\n\n"
    "• تصفح السور واقرأ واسمع كل سورة\n"
    "• 604 صفحة من المصحف المدني للقراءة\n"
    "• آية عشوائية وآية اليوم بالصوت\n"
    "• اكتب: <code>سورة الكهف</code> أو <code>اية 2 255</code> أو <code>صفحة 50</code>\n\n"
    "<i>﴿ وَرَتِّلِ الْقُرْآنَ تَرْتِيلًا ﴾</i>"
)


@quran_router.callback_query(F.data == "quran_menu")
async def quran_menu_cb(callback: types.CallbackQuery):
    await callback.answer()
    await show(callback, QURAN_TEXT, quran_menu_kb())


@quran_router.message(or_f(Command("quran"), F.text.in_(["المصحف", "القران", "القرآن", "مصحف", "قران"])))
async def quran_menu_msg(message: types.Message):
    await safe_answer(message, QURAN_TEXT, quran_menu_kb())


def index_kb(page: int):
    total_pages = (114 + PER_INDEX_PAGE - 1) // PER_INDEX_PAGE
    page = max(0, min(page, total_pages - 1))
    chunk = SURAHS[page * PER_INDEX_PAGE:(page + 1) * PER_INDEX_PAGE]
    rows, row = [], []
    for s in chunk:
        row.append(Btn(text=f"{s['n']}. {s['name']}", callback_data=f"qs:{s['n']}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if page > 0:
        nav.append(Btn(text="⬅️ السابق", callback_data=f"qi:{page - 1}"))
    nav.append(Btn(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(Btn(text="التالي ➡️", callback_data=f"qi:{page + 1}"))
    rows.append(nav)
    rows.append([Btn(text="📖 المصحف", callback_data="quran_menu"), Btn(text="🏠 الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@quran_router.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer()


@quran_router.callback_query(F.data.startswith("qi:"))
async def index_cb(callback: types.CallbackQuery):
    await callback.answer()
    page = int(callback.data.split(":")[1])
    await show(callback, "📚 <b>فهرس سور القرآن الكريم</b>\nاختار السورة:", index_kb(page))


def surah_card(n: int):
    s = SURAHS[n - 1]
    text = (f"📖 <b>سورة {esc(s['name'])}</b>\n\n"
            f"🔢 ترتيبها: <b>{n}</b>\n📍 {s['type']}\n📝 عدد آياتها: <b>{s['ayat']}</b>\n"
            f"🎧 القارئ: {RECITER}")
    nav = []
    if n > 1:
        nav.append(Btn(text="⬅️ السابقة", callback_data=f"qs:{n - 1}"))
    if n < 114:
        nav.append(Btn(text="التالية ➡️", callback_data=f"qs:{n + 1}"))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="🎧 استمع للسورة", callback_data=f"qa:{n}"), Btn(text="📖 اقرأ", callback_data=f"qr:{n}:0")],
        nav,
        [Btn(text="📚 الفهرس", callback_data=f"qi:{(n - 1) // PER_INDEX_PAGE}"),
         Btn(text="🏠 الرئيسية", callback_data="main_menu")],
    ])
    return text, kb


@quran_router.callback_query(F.data.startswith("qs:"))
async def surah_cb(callback: types.CallbackQuery):
    await callback.answer()
    text, kb = surah_card(int(callback.data.split(":")[1]))
    await show(callback, text, kb)


# ---------------- قراءة السورة ----------------
async def render_read(target, n: int, p: int):
    try:
        ayahs = await get_surah_ayahs(n)
    except Exception as e:
        log.warning("quran text failed: %s", e)
        if isinstance(target, types.CallbackQuery):
            await target.answer("⚠️ مش قادر أجيب النص دلوقتي، جرب كمان شوية.", show_alert=True)
        return
    pages = chunk_surah(ayahs)
    p = max(0, min(p, len(pages) - 1))
    s = SURAHS[n - 1]
    head = f"📖 <b>سورة {esc(s['name'])}</b> — صفحة {p + 1}/{len(pages)}\n\n"
    nav = []
    if p > 0:
        nav.append(Btn(text="⬅️ السابق", callback_data=f"qr:{n}:{p - 1}"))
    if p < len(pages) - 1:
        nav.append(Btn(text="التالي ➡️", callback_data=f"qr:{n}:{p + 1}"))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        nav,
        [Btn(text="🎧 استمع للسورة", callback_data=f"qa:{n}"), Btn(text="ℹ️ السورة", callback_data=f"qs:{n}")],
        [Btn(text="📚 الفهرس", callback_data="qi:0"), Btn(text="🏠 الرئيسية", callback_data="main_menu")],
    ])
    await show(target, head + esc(pages[p]), kb)


@quran_router.callback_query(F.data.startswith("qr:"))
async def read_cb(callback: types.CallbackQuery):
    await callback.answer()
    _, n, p = callback.data.split(":")
    await render_read(callback, int(n), int(p))


# ---------------- صوت السورة ----------------
@quran_router.callback_query(F.data.startswith("qa:"))
async def surah_audio_cb(callback: types.CallbackQuery):
    n = int(callback.data.split(":")[1])
    s = SURAHS[n - 1]
    await callback.answer("🎧 جاري تجهيز التلاوة...")
    wait = await callback.message.answer(f"⏳ بجهزلك سورة <b>{esc(s['name'])}</b> بصوت العفاسي... ثواني 🎧", parse_mode="HTML")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="📖 اقرأ السورة", callback_data=f"qr:{n}:0"), Btn(text="📚 الفهرس", callback_data="qi:0")]])
    caption = f"🎧 <b>سورة {esc(s['name'])}</b>\n{RECITER}"
    result = await send_audio_smart(callback.message, surah_audio_urls(n), f"سورة {s['name']}", caption, kb)
    try:
        await wait.delete()
    except Exception:
        pass
    if result != "ok":
        links = InlineKeyboardMarkup(inline_keyboard=[
            [Btn(text="🎧 استمع أونلاين", url=surah_audio_urls(n)[0])],
            [Btn(text="⬅️ رجوع للسورة", callback_data=f"qs:{n}")]])
        why = "السورة طويلة وأكبر من حد تيليجرام للرفع" if result == "big" else "الملف مش متاح دلوقتي"
        await callback.message.answer(
            f"⚠️ {why}، بس تقدر تسمعها من الرابط 👇", reply_markup=links)


# ---------------- آية (نص + صوت) ----------------
async def send_ayah(msg: types.Message, s: int, a: int, header: str = ""):
    sd = SURAHS[s - 1]
    if a < 1 or a > sd["ayat"]:
        await msg.answer(f"⚠️ سورة {sd['name']} فيها {sd['ayat']} آية بس يا باشا 😅")
        return
    try:
        text = await get_ayah_text(s, a)
    except Exception:
        text = None
    body = f"{header}📖 <b>سورة {esc(sd['name'])}</b> — الآية {a}\n\n"
    body += f"﴿ {esc(text)} ﴾" if text else "(النص مش متاح دلوقتي، اسمع الصوت 👇)"
    nav = []
    if a > 1:
        nav.append(Btn(text="⬅️ الآية السابقة", callback_data=f"qy:{s}:{a - 1}"))
    if a < sd["ayat"]:
        nav.append(Btn(text="الآية التالية ➡️", callback_data=f"qy:{s}:{a + 1}"))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        nav,
        [Btn(text="🎲 آية أخرى", callback_data="qrand"), Btn(text="📖 المصحف", callback_data="quran_menu")],
    ])
    status = await send_audio_smart(msg, [ayah_audio(s, a)], f"{sd['name']} - آية {a}", body, kb)
    if status != "ok":
        await msg.answer(body, reply_markup=kb, parse_mode="HTML")


@quran_router.callback_query(F.data.startswith("qy:"))
async def ayah_cb(callback: types.CallbackQuery):
    await callback.answer()
    _, s, a = callback.data.split(":")
    await send_ayah(callback.message, int(s), int(a))


@quran_router.callback_query(F.data == "qrand")
async def random_ayah(callback: types.CallbackQuery):
    await callback.answer("🎲")
    s, a = locate(random.randint(1, TOTAL_AYAT))
    await send_ayah(callback.message, s, a, "🎲 <b>آية عشوائية</b>\n")


@quran_router.callback_query(F.data == "qday")
async def ayah_of_day(callback: types.CallbackQuery):
    await callback.answer("🌟")
    day = datetime.now(timezone.utc).toordinal()
    s, a = locate((day * 7919) % TOTAL_AYAT + 1)
    await send_ayah(callback.message, s, a, "🌟 <b>آية اليوم</b>\n")


@quran_router.callback_query(F.data == "qk")
async def ayat_kursi(callback: types.CallbackQuery):
    await callback.answer("🕌")
    await send_ayah(callback.message, 2, 255, "🕌 <b>آية الكرسي</b>\n")


# ---------------- صفحات المصحف ----------------
async def render_page(target, p: int):
    p = max(1, min(604, p))
    try:
        ayahs = await get_page_ayahs(p)
    except Exception as e:
        log.warning("page failed: %s", e)
        if isinstance(target, types.CallbackQuery):
            await target.answer("⚠️ مش قادر أجيب الصفحة دلوقتي.", show_alert=True)
        return
    out, last = [], None
    for sn, an, text in ayahs:
        if sn != last:
            out.append(f"\n— سورة {SURAHS[sn - 1]['name']} —\n")
            last = sn
        out.append(f"{text} ﴿{ar_digits(an)}﴾ ")
    body = f"📄 <b>صفحة {p} من 604</b>\n" + esc("".join(out))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="⏮ -10", callback_data=f"qp:{max(1, p - 10)}"), Btn(text="◀️", callback_data=f"qp:{max(1, p - 1)}"),
         Btn(text="▶️", callback_data=f"qp:{min(604, p + 1)}"), Btn(text="+10 ⏭", callback_data=f"qp:{min(604, p + 10)}")],
        [Btn(text="📖 المصحف", callback_data="quran_menu"), Btn(text="🏠 الرئيسية", callback_data="main_menu")],
    ])
    await show(target, body, kb)


@quran_router.callback_query(F.data.startswith("qp:"))
async def page_cb(callback: types.CallbackQuery):
    await callback.answer()
    await render_page(callback, int(callback.data.split(":")[1]))


# ---------------- أوامر نصية: سورة X / اية S A / صفحة N ----------------
SURAH_RE = re.compile(r"^(?:سورة|سوره|اقرأ|اقرا|استمع|اسمع|شغل)\s+(?:سورة\s+|سوره\s+)?(.+)$")
AYAH_RE = re.compile(r"^(?:آية|اية|ايه)\s+(\d{1,3})\s*[: ]\s*(\d{1,3})$")
PAGE_RE = re.compile(r"^(?:صفحة|صفحه)\s+(\d{1,3})$")


def quran_text_filter(message: types.Message):
    t = (message.text or "").strip()
    if not t or t.startswith("/") or len(t) > 40:
        return False
    m = AYAH_RE.match(t)
    if m:
        s, a = int(m.group(1)), int(m.group(2))
        if 1 <= s <= 114:
            return {"kind": "ayah", "a": s, "b": a}
    m = PAGE_RE.match(t)
    if m and 1 <= int(m.group(1)) <= 604:
        return {"kind": "page", "a": int(m.group(1)), "b": 0}
    m = SURAH_RE.match(t)
    if m:
        n = find_surah(m.group(1))
        if n:
            return {"kind": "surah", "a": n, "b": 0}
    return False


@quran_router.message(quran_text_filter)
async def quran_text_handler(message: types.Message, kind: str, a: int, b: int):
    if kind == "ayah":
        await send_ayah(message, a, b)
    elif kind == "page":
        await render_page(message, a)
    else:
        text, kb = surah_card(a)
        await safe_answer(message, text, kb)


# ==================================================================
#                         تحدي القرآن (أسئلة تلقائية)
# ==================================================================
QQ: dict = {}


def _nums_options(correct: int, pool: list):
    opts = {correct}
    pool = [x for x in set(pool) if x != correct]
    random.shuffle(pool)
    for x in pool:
        if len(opts) >= 4:
            break
        opts.add(x)
    opts = list(opts)
    random.shuffle(opts)
    return [str(o) for o in opts], opts.index(correct)


def make_quran_question():
    kind = random.choice(["count", "order", "name", "type", "next"])
    s = random.choice(SURAHS)
    if kind == "count":
        opts, idx = _nums_options(s["ayat"], [x["ayat"] for x in SURAHS])
        return {"q": f"كم عدد آيات سورة {s['name']}؟", "opts": opts, "ans": idx, "pts": 20}
    if kind == "order":
        opts, idx = _nums_options(s["n"], random.sample(range(1, 115), 12))
        return {"q": f"ما ترتيب سورة {s['name']} في المصحف؟", "opts": opts, "ans": idx, "pts": 15}
    if kind == "name":
        others = random.sample([x["name"] for x in SURAHS if x["n"] != s["n"]], 3)
        opts = others + [s["name"]]
        random.shuffle(opts)
        return {"q": f"ما اسم السورة رقم {s['n']} في المصحف؟", "opts": opts, "ans": opts.index(s["name"]), "pts": 15}
    if kind == "type":
        n = random.choice(SAFE_MAKKI + SAFE_MADANI)
        s = SURAHS[n - 1]
        opts = ["مكية", "مدنية"]
        return {"q": f"سورة {s['name']} مكية أم مدنية؟", "opts": opts, "ans": opts.index(s["type"]), "pts": 10}
    s = SURAHS[random.randint(0, 112)]
    nxt = SURAHS[s["n"]]
    others = random.sample([x["name"] for x in SURAHS if x["n"] not in (s["n"], nxt["n"])], 3)
    opts = others + [nxt["name"]]
    random.shuffle(opts)
    return {"q": f"أي سورة تأتي مباشرة بعد سورة {s['name']}؟", "opts": opts, "ans": opts.index(nxt["name"]), "pts": 15}


def qq_kb(token: str, opts: list):
    rows = [[Btn(text=f"🔹 {o}", callback_data=f"qz:{token}:{i}")] for i, o in enumerate(opts)]
    rows.append([Btn(text="📖 المصحف", callback_data="quran_menu"), Btn(text="🏠 الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@quran_router.callback_query(F.data == "qq:new")
async def quiz_new(callback: types.CallbackQuery):
    await callback.answer()
    if not DATA_OK:
        await callback.message.answer("⚠️ بيانات التحدي فيها مشكلة، بلّغ صاحب البوت.")
        return
    q = make_quran_question()
    token = uuid.uuid4().hex[:8]
    if len(QQ) > 300:
        QQ.pop(next(iter(QQ)))
    QQ[token] = {**q, "done": False, "wrong": set()}
    text = (f"🧠 <b>تحدي القرآن</b>\n💎 الجائزة: <b>{q['pts']}</b> نقطة\n\n❓ <b>{esc(q['q'])}</b>")
    await show(callback, text, qq_kb(token, q["opts"]))


@quran_router.message(or_f(Command("quranquiz"), F.text.in_(["تحدي القران", "تحدي القرآن", "مسابقة القران", "مسابقة القرآن"])))
async def quiz_msg(message: types.Message):
    q = make_quran_question()
    token = uuid.uuid4().hex[:8]
    QQ[token] = {**q, "done": False, "wrong": set()}
    await safe_answer(message, f"🧠 <b>تحدي القرآن</b>\n💎 الجائزة: <b>{q['pts']}</b> نقطة\n\n❓ <b>{esc(q['q'])}</b>",
                      qq_kb(token, q["opts"]))


@quran_router.callback_query(F.data.startswith("qz:"))
async def quiz_answer(callback: types.CallbackQuery):
    _, token, chosen = callback.data.split(":")
    q = QQ.get(token)
    if not q or q["done"]:
        await callback.answer("⌛ السؤال ده خلص!", show_alert=True)
        return
    user = callback.from_user
    group = callback.message.chat.type in ("group", "supergroup")
    if group and user.id in q["wrong"]:
        await callback.answer("جاوبت غلط قبل كده 😂", show_alert=True)
        return
    u = get_user(user)
    chosen = int(chosen)
    again = InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="🧠 سؤال تاني", callback_data="qq:new")],
        [Btn(text="📖 المصحف", callback_data="quran_menu"), Btn(text="🏠 الرئيسية", callback_data="main_menu")]])
    right = esc(q["opts"][q["ans"]])
    if chosen == q["ans"]:
        q["done"] = True
        u["correct"] += 1
        u["streak"] += 1
        u["best_streak"] = max(u["best_streak"], u["streak"])
        lvl = add_points(user, q["pts"], callback.message.chat)
        await callback.answer("✅ صح!")
        text = (f"✅ {persona.correct_line(user)}\n\n✔️ الإجابة: <b>{right}</b>\n➕ <b>{q['pts']}</b> نقطة | 💰 {u['score']}")
        if lvl:
            text += "\n\n" + persona.levelup_line(user, lvl)
        await safe_edit(callback.message, text, again)
    elif group:
        q["wrong"].add(user.id)
        u["wrong"] += 1
        u["streak"] = 0
        save_data()
        await callback.answer("❌ غلط! حد تاني يجرب", show_alert=True)
    else:
        q["done"] = True
        u["wrong"] += 1
        u["streak"] = 0
        save_data()
        await callback.answer()
        await safe_edit(callback.message,
                        f"{persona.wrong_line(user)}\n\n✔️ الإجابة الصحيحة: <b>{right}</b>", again)