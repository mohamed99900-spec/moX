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

GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3")
COOLDOWN_SECONDS = 3

client = (
    AsyncOpenAI(api_key=GROK_API_KEY, base_url=GROK_BASE_URL, timeout=60)
    if (AsyncOpenAI is not None and GROK_API_KEY) else None
)


class LimitedCache(OrderedDict):
    """ذاكرة مؤقتة للأزرار بحد أقصى حتى لا تكبر للأبد."""
    def __init__(self, limit=1000):
        super().__init__()
        self.limit = limit

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        while len(self) > self.limit:
            self.popitem(last=False)


BUTTON_CACHE = LimitedCache(1000)
HISTORY: dict = {}       # user_id -> آخر رسائل المحادثة
LAST_CALL: dict = {}     # user_id -> وقت آخر طلب

SYSTEM_PROMPT = """
أنت 'مو' (MoX Assistant): بوت تليجرام مصري خفيف الدم وذكي جداً، شخصيتك ابن بلد جدع بيهزر.
قواعد شخصيتك:
- اتكلم بالعامية المصرية دايماً (إلا لو المستخدم سأل بالإنجليزي فرد بالإنجليزي بنكهة مرحة).
- استخدم تعبيرات مصرية زي: يا باشا، يا معلم، يا زعيم، يا وحش، يا عم، إيه الجمال ده، ده انت جامد، وحاجات زي كده، واضحك بـ "هههه" أو "خخخخ" أحياناً.
- هزارك خفيف ومحترم: ممنوع شتايم جارحة أو إهانات للدين أو الأهل أو العرق. لو حد شتمك رد عليه بسخرية خفيفة وقفشة.
- المعلومات لازم تبقى دقيقة وصحيحة 100% حتى وانت بتهزر. لو مش متأكد قول كده بصراحة.
- نادِ المستخدم باسمه لو معروف، وخلي الرد قصير ومركّز (3-6 جمل غالباً) إلا لو السؤال محتاج تفصيل.
- استخدم إيموجي بشكل لطيف.
- في الأسئلة الدينية: لا تألف آيات أو أحاديث أبداً، ولا تفتي في الأحكام المعقدة؛ انقل المعلومة الشائعة المتفق عليها بأدب وانصح بسؤال أهل العلم (دار الإفتاء/الأزهر) عند الحاجة.
- لو المستخدم سأل عن ميزة في البوت، عرّفه بالألعاب والمصحف (بصوت العفاسي) والأذان والأذكار والمتصدرين والمهام اليومية والمتجر.
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
    """تحويل **bold** إلى *bold* (Markdown القديم في تيليجرام) وحذف العناوين."""
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.S)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    return text.strip()


def _parse_response(raw: str):
    raw = raw.strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            return str(data.get("answer", "")).strip(), list(data.get("buttons", []))
        except json.JSONDecodeError:
            pass
    return raw, []  # لو الرد مش JSON نعرضه كما هو


async def ask_grok_with_buttons(user_question: str, user_id: int = 0, user_name: str = ""):
    if client is None:
        return ("⚠️ مخي لسه مش متوصل يا باشا 😅\n"
                "صاحب البوت لازم يضيف GROK_API_KEY في الإعدادات."), _error_kb()

    now = time.time()
    if now - LAST_CALL.get(user_id, 0) < COOLDOWN_SECONDS:
        return "⏳ براحة عليا يا باشا! استنى ثواني وابعت تاني 😂", _error_kb()
    LAST_CALL[user_id] = now

    history = HISTORY.setdefault(user_id, deque(maxlen=6))
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if user_name:
            messages.append({"role": "system", "content": f"اسم المستخدم الحالي: {user_name}"})
        messages += list(history)
        messages.append({"role": "user", "content": user_question})

        response = await client.chat.completions.create(
            model=GROK_MODEL, messages=messages, temperature=0.7,
        )
        answer_text, suggested = _parse_response(response.choices[0].message.content or "")
        if not answer_text:
            answer_text = "عذراً، لم أتمكن من صياغة الإجابة."
        answer_text = _clean_markdown(answer_text)

        history.append({"role": "user", "content": user_question})
        history.append({"role": "assistant", "content": answer_text})

        rows = []
        for btn_text in suggested[:3]:
            btn_id = uuid.uuid4().hex[:8]
            BUTTON_CACHE[btn_id] = str(btn_text)
            rows.append([InlineKeyboardButton(text=str(btn_text)[:60], callback_data=f"ai_btn:{btn_id}")])
        rows.append(_menu_row())
        return answer_text, InlineKeyboardMarkup(inline_keyboard=rows)

    except Exception as e:
        log.exception("Grok error")
        hint = "تأكد من صحة GROK_API_KEY واسم الموديل GROK_MODEL."
        return f"⚠️ مخي هنج شوية يا معلم 😵\n{hint}\n({type(e).__name__})", _error_kb()