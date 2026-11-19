"""محرك الذكاء الاصطناعي: بيجرّب أكتر من مزوّد (Grok / Gemini / Groq / OpenAI) ويكتشف الموديل المتاح لوحده."""
import os
import re
import json
import time
import uuid
import logging
from collections import OrderedDict, deque

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None

log = logging.getLogger("mox.ai")

OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
COOLDOWN_SECONDS = 3

# ------------------------------------------------------------------
# المزوّدين (كلهم بيشتغلوا بمكتبة openai). اللي معاه مفتاح بيتفعّل.
# ------------------------------------------------------------------
SPECS = [
    {"name": "Grok (xAI)", "key": os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY"),
     "url": os.getenv("GROK_BASE_URL", "https://api.x.ai/v1"), "model": os.getenv("GROK_MODEL", ""),
     "prefs": ["grok-4.3", "grok-4-fast-non-reasoning", "grok-4.20-0309-non-reasoning", "grok-3", "grok-3-mini", "grok-4"]},
    {"name": "Gemini", "key": os.getenv("GEMINI_API_KEY"),
     "url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": os.getenv("GEMINI_MODEL", ""),
     "prefs": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest", "gemini-1.5-flash"]},
    {"name": "Groq", "key": os.getenv("GROQ_API_KEY"),
     "url": "https://api.groq.com/openai/v1", "model": os.getenv("GROQ_MODEL", ""),
     "prefs": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b"]},
    {"name": "OpenAI", "key": os.getenv("OPENAI_API_KEY"),
     "url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"), "model": os.getenv("OPENAI_MODEL", ""),
     "prefs": ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"]},
]
_BAD_WORDS = ("image", "imagine", "video", "embed", "whisper", "tts", "guard", "moderation", "audio",
              "vision", "tuning", "aqa", "transcribe", "realtime", "dall", "learnlm")


class ProviderDown(Exception):
    def __init__(self, kind, detail):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def classify(e: Exception) -> str:
    status = getattr(e, "status_code", None)
    msg = str(e).lower()
    name = type(e).__name__
    if "credit" in msg or "billing" in msg or "quota" in msg or "insufficient" in msg:
        return "credits"
    if status == 401 or "invalid api key" in msg or "incorrect api key" in msg:
        return "auth"
    if status == 403:
        return "auth"
    if status == 429:
        return "ratelimit"
    if status in (400, 404) and "model" in msg:
        return "model"
    if name in ("APIConnectionError", "APITimeoutError", "ConnectError", "TimeoutError"):
        return "net"
    return "other"


class Provider:
    def __init__(self, spec):
        self.name = spec["name"]
        self.model = spec["model"]
        self.prefs = spec["prefs"]
        self.client = AsyncOpenAI(api_key=spec["key"], base_url=spec["url"], timeout=45, max_retries=0)
        self.disabled_until = 0.0
        self.last_error = ""

    async def discover(self):
        page = await self.client.models.list()
        ids = [(m.id or "").replace("models/", "") for m in page.data]
        ids = [i for i in ids if i and not any(b in i.lower() for b in _BAD_WORDS)]
        ranked = [m for m in self.prefs if m in ids] + [i for i in ids if i not in self.prefs]
        return ranked[:5]

    async def complete(self, messages) -> str:
        order = ([self.model] if self.model else []) + [m for m in self.prefs if m != self.model]
        discovered, i, attempts = False, 0, 0
        while i < len(order) and attempts < 5:
            model = order[i]
            i += 1
            attempts += 1
            try:
                r = await self.client.chat.completions.create(
                    model=model, messages=messages, temperature=0.7, max_tokens=1000)
                text = (r.choices[0].message.content or "").strip()
                if not text:
                    raise RuntimeError("empty response")
                self.model = model
                return text
            except Exception as e:
                kind = classify(e)
                self.last_error = f"{type(e).__name__}: {str(e)[:220]}"
                log.warning("[%s/%s] %s -> %s", self.name, model, kind, self.last_error)
                if kind in ("auth", "credits", "ratelimit", "net"):
                    raise ProviderDown(kind, self.last_error)
                if kind == "model" and not discovered:
                    discovered = True
                    try:
                        order, i = await self.discover(), 0
                    except Exception as e2:
                        log.warning("[%s] discovery failed: %s", self.name, e2)
        raise ProviderDown("other", self.last_error or "no working model")


PROVIDERS = []
if AsyncOpenAI is not None:
    for _s in SPECS:
        if _s["key"] and not _s["key"].startswith("PUT_"):
            PROVIDERS.append(Provider(_s))


class AIUnavailable(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


async def generate(messages):
    now = time.time()
    errors = []
    for p in PROVIDERS:
        if p.disabled_until > now:
            errors.append(f"{p.name}: (موقوف مؤقتاً) {p.last_error}")
            continue
        try:
            return await p.complete(messages), p
        except ProviderDown as d:
            p.disabled_until = time.time() + (600 if d.kind in ("auth", "credits") else 30)
            errors.append(f"{p.name} [{d.kind}]: {d.detail}")
    raise AIUnavailable(errors)


async def diagnose() -> str:
    """تقرير حالة الذكاء الاصطناعي (لأمر /aitest)."""
    if AsyncOpenAI is None:
        return "❌ مكتبة openai مش متسطبة."
    if not PROVIDERS:
        return ("❌ مفيش أي مفتاح AI متضبط.\nضيف واحد على الأقل في Render → Environment:\n"
                "GROK_API_KEY أو GEMINI_API_KEY (مجاني) أو GROQ_API_KEY (مجاني)")
    lines = []
    for p in PROVIDERS:
        p.disabled_until = 0
        try:
            text = await p.complete([{"role": "user", "content": "قل: تمام"}])
            lines.append(f"✅ {p.name} شغال — الموديل: {p.model}")
        except ProviderDown as d:
            hint = {"auth": "المفتاح غلط أو منتهي", "credits": "الحساب مفيهوش رصيد/كوتا",
                    "ratelimit": "ضغط طلبات", "net": "مشكلة اتصال"}.get(d.kind, "خطأ")
            lines.append(f"❌ {p.name} — {hint}\n   {d.detail[:200]}")
    return "\n".join(lines)


# ------------------------------------------------------------------
# الرد بالأزرار
# ------------------------------------------------------------------
class LimitedCache(OrderedDict):
    def __init__(self, limit=1000):
        super().__init__()
        self.limit = limit

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        while len(self) > self.limit:
            self.popitem(last=False)


BUTTON_CACHE = LimitedCache(1000)
HISTORY: dict = {}
LAST_CALL: dict = {}

SYSTEM_PROMPT = """
أنت 'مو' (MoX Assistant): بوت تليجرام مصري خفيف الدم وذكي جداً، شخصيتك ابن بلد جدع بيهزر.
قواعد شخصيتك:
- اتكلم بالعامية المصرية دايماً (إلا لو المستخدم سأل بالإنجليزي فرد بالإنجليزي بنكهة مرحة).
- استخدم تعبيرات مصرية زي: يا باشا، يا معلم، يا زعيم، يا وحش، يا عم، إيه الجمال ده، ده انت جامد، واضحك بـ "هههه" أو "خخخخ" أحياناً.
- هزارك خفيف ومحترم: ممنوع شتايم جارحة أو إهانات للدين أو الأهل أو العرق. لو حد شتمك رد عليه بسخرية خفيفة وقفشة.
- المعلومات لازم تبقى دقيقة وصحيحة 100% حتى وانت بتهزر. لو مش متأكد قول كده بصراحة.
- نادِ المستخدم باسمه لو معروف، وخلي الرد قصير ومركّز (3-6 جمل غالباً) إلا لو السؤال محتاج تفصيل.
- استخدم إيموجي بشكل لطيف.
- في الأسئلة الدينية: لا تألف آيات أو أحاديث أبداً، ولا تفتي في الأحكام المعقدة؛ انقل المعلومة الشائعة المتفق عليها بأدب وانصح بسؤال أهل العلم (دار الإفتاء/الأزهر) عند الحاجة.
- لو المستخدم سأل عن ميزة في البوت، عرّفه بالألعاب والمصحف (بصوت العفاسي) والأذان والأذكار والمتصدرين والمهام اليومية والمتجر وعجلة الحظ.
يجب أن يكون ردك دائماً بصيغة JSON فقط بدون أي نصوص إضافية خارجه، ويحتوي على مفتاحين:
1. "answer": نص الإجابة (استخدم **نص** للخط الغليظ فقط، بدون عناوين #).
2. "buttons": قائمة فيها 3 أسئلة متابعة قصيرة جداً (أقل من 30 حرفاً) بنفس لهجتك.

مثال لو سأل "ما هي عاصمة مصر؟":
{
  "answer": "دي سهلة يا باشا! عاصمة مصر هي **القاهرة** 😎 أم الدنيا وأكبر مدينة في العالم العربي وأفريقيا.",
  "buttons": ["🏛️ معالم القاهرة", "👥 عدد سكانها", "🌍 عاصمة السعودية؟"]
}
"""


def _menu_row():
    return [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="main_menu")]


def _error_kb():
    return InlineKeyboardMarkup(inline_keyboard=[_menu_row()])


def _clean_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.S)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    return text.strip()


def _parse_response(raw: str):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            return str(data.get("answer", "")).strip(), list(data.get("buttons", []))
        except json.JSONDecodeError:
            pass
    return raw, []


async def ask_grok_with_buttons(user_question: str, user_id: int = 0, user_name: str = ""):
    if not PROVIDERS:
        msg = ("⚠️ مخي لسه مش متوصل يا باشا 😅\nصاحب البوت لازم يضيف مفتاح AI في الإعدادات "
               "(GROK_API_KEY أو GEMINI_API_KEY أو GROQ_API_KEY).")
        return msg, _error_kb()

    now = time.time()
    if now - LAST_CALL.get(user_id, 0) < COOLDOWN_SECONDS:
        return "⏳ براحة عليا يا باشا! استنى ثواني وابعت تاني 😂", _error_kb()
    LAST_CALL[user_id] = now

    history = HISTORY.setdefault(user_id, deque(maxlen=6))
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if user_name:
        messages.append({"role": "system", "content": f"اسم المستخدم الحالي: {user_name}"})
    messages += list(history)
    messages.append({"role": "user", "content": user_question})

    try:
        raw, _provider = await generate(messages)
    except AIUnavailable as e:
        log.error("AI unavailable: %s", e)
        text = "⚠️ مخي هنج شوية يا معلم 😵 جرب كمان دقيقة."
        if user_id == OWNER_ID:
            text += "\n\n🛠️ (للمالك فقط)\n" + "\n".join(e.errors)[:900] + "\n\nاكتب /aitest للتشخيص."
        return text, _error_kb()
    except Exception as e:  # أي خطأ غير متوقع
        log.exception("AI error")
        return f"⚠️ حصلت مشكلة غريبة: {type(e).__name__}", _error_kb()

    answer_text, suggested = _parse_response(raw)
    answer_text = _clean_markdown(answer_text) or "عذراً، لم أتمكن من صياغة الإجابة."
    history.append({"role": "user", "content": user_question})
    history.append({"role": "assistant", "content": answer_text})

    rows = []
    for btn_text in suggested[:3]:
        btn_id = uuid.uuid4().hex[:8]
        BUTTON_CACHE[btn_id] = str(btn_text)
        rows.append([InlineKeyboardButton(text=str(btn_text)[:60], callback_data=f"ai_btn:{btn_id}")])
    rows.append(_menu_row())
    return answer_text, InlineKeyboardMarkup(inline_keyboard=rows)
