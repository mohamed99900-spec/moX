"""بيانات سور القرآن + روابط صوت الشيخ مشاري راشد العفاسي."""
import re

RAW = """الفاتحة|7|M
البقرة|286|D
آل عمران|200|D
النساء|176|D
المائدة|120|D
الأنعام|165|M
الأعراف|206|M
الأنفال|75|D
التوبة|129|D
يونس|109|M
هود|123|M
يوسف|111|M
الرعد|43|D
إبراهيم|52|M
الحجر|99|M
النحل|128|M
الإسراء|111|M
الكهف|110|M
مريم|98|M
طه|135|M
الأنبياء|112|M
الحج|78|D
المؤمنون|118|M
النور|64|D
الفرقان|77|M
الشعراء|227|M
النمل|93|M
القصص|88|M
العنكبوت|69|M
الروم|60|M
لقمان|34|M
السجدة|30|M
الأحزاب|73|D
سبأ|54|M
فاطر|45|M
يس|83|M
الصافات|182|M
ص|88|M
الزمر|75|M
غافر|85|M
فصلت|54|M
الشورى|53|M
الزخرف|89|M
الدخان|59|M
الجاثية|37|M
الأحقاف|35|M
محمد|38|D
الفتح|29|D
الحجرات|18|D
ق|45|M
الذاريات|60|M
الطور|49|M
النجم|62|M
القمر|55|M
الرحمن|78|D
الواقعة|96|M
الحديد|29|D
المجادلة|22|D
الحشر|24|D
الممتحنة|13|D
الصف|14|D
الجمعة|11|D
المنافقون|11|D
التغابن|18|D
الطلاق|12|D
التحريم|12|D
الملك|30|M
القلم|52|M
الحاقة|52|M
المعارج|44|M
نوح|28|M
الجن|28|M
المزمل|20|M
المدثر|56|M
القيامة|40|M
الإنسان|31|D
المرسلات|50|M
النبأ|40|M
النازعات|46|M
عبس|42|M
التكوير|29|M
الانفطار|19|M
المطففين|36|M
الانشقاق|25|M
البروج|22|M
الطارق|17|M
الأعلى|19|M
الغاشية|26|M
الفجر|30|M
البلد|20|M
الشمس|15|M
الليل|21|M
الضحى|11|M
الشرح|8|M
التين|8|M
العلق|19|M
القدر|5|M
البينة|8|D
الزلزلة|8|D
العاديات|11|M
القارعة|11|M
التكاثر|8|M
العصر|3|M
الهمزة|9|M
الفيل|5|M
قريش|4|M
الماعون|7|M
الكوثر|3|M
الكافرون|6|M
النصر|3|D
المسد|5|M
الإخلاص|4|M
الفلق|5|M
الناس|6|M"""

SURAHS = []
for _i, _line in enumerate(RAW.strip().splitlines(), 1):
    _name, _n, _t = _line.split("|")
    SURAHS.append({"n": _i, "name": _name, "ayat": int(_n), "type": "مكية" if _t == "M" else "مدنية"})

TOTAL_AYAT = sum(s["ayat"] for s in SURAHS)
# فحص سلامة البيانات (لو غلطة في الإدخال البوت يبلّغ بدل ما يعرض معلومة غلط)
DATA_OK = len(SURAHS) == 114 and TOTAL_AYAT == 6236

# سور متفق عليها مكية/مدنية (للأسئلة)
SAFE_MAKKI = [6, 7, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 23, 25, 26, 27, 28, 29, 30, 31, 32, 34, 35, 36,
              37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 50, 51, 52, 53, 54, 56, 67, 68, 69, 70, 71, 72, 73, 74,
              75, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 100, 101,
              102, 103, 104, 105, 106, 107, 108, 109, 111, 113, 114]
SAFE_MADANI = [2, 3, 4, 5, 8, 9, 24, 33, 47, 48, 49, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 110]

AYAH_START = []
_acc = 0
for _s in SURAHS:
    AYAH_START.append(_acc)
    _acc += _s["ayat"]


def locate(global_n: int):
    """رقم الآية الكلي (1..6236) -> (رقم السورة, رقم الآية)."""
    g = max(1, min(global_n, TOTAL_AYAT)) - 1
    for i in range(113, -1, -1):
        if g >= AYAH_START[i]:
            return i + 1, g - AYAH_START[i] + 1
    return 1, 1


# ---------- الروابط (مشاري راشد العفاسي) ----------
def ayah_audio(s: int, a: int) -> str:
    return f"https://everyayah.com/data/Alafasy_128kbps/{s:03d}{a:03d}.mp3"


def surah_audio_urls(s: int) -> list:
    return [
        f"https://cdn.islamic.network/quran/audio-surah/128/ar.alafasy/{s}.mp3",
        f"https://cdn.islamic.app/quran/audio-surah/ar.alafasy/{s}.mp3",
        f"https://server8.mp3quran.net/afs/{s:03d}.mp3",
    ]


# ---------- البحث بالاسم ----------
_TASH = re.compile(r"[\u064B-\u0652\u0640\u0670]")
_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})


def norm_ar(s: str) -> str:
    s = _TASH.sub("", s).translate(_MAP).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _strip_al(s: str) -> str:
    s = s.replace(" ", "")
    return s[2:] if s.startswith("ال") and len(s) > 3 else s


NAME_INDEX = {_strip_al(norm_ar(s["name"])): s["n"] for s in SURAHS}
ALIASES = {"ياسين": 36, "يا سين": 36, "فاتحه": 1, "اخلاص": 112, "كوثر": 108, "فلق": 113, "ناس": 114,
           "كافرون": 109, "رحمن": 55, "ملك": 67, "كهف": 18, "بقره": 2, "عمران": 3, "عمران": 3,
           "اسراء": 17, "بني اسرائيل": 17, "سجده": 32, "واقعه": 56, "مزمل": 73}
ALIASES = {_strip_al(k): v for k, v in ALIASES.items()}


def find_surah(query: str):
    q = norm_ar(query)
    q = re.sub(r"^(سوره|سورة)\s+", "", q)
    q = _strip_al(q)
    if not q:
        return None
    if q in NAME_INDEX:
        return NAME_INDEX[q]
    if q in ALIASES:
        return ALIASES[q]
    if len(q) >= 3:
        cands = [n for k, n in NAME_INDEX.items() if k.startswith(q)]
        if len(cands) == 1:
            return cands[0]
        cands = [n for k, n in NAME_INDEX.items() if q in k]
        if len(cands) == 1:
            return cands[0]
    return None


def ar_digits(n: int) -> str:
    return str(n).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))