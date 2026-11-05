"""Offline demo for stage 3: synthetic articles + a canned analysis (no API calls).
All companies, outlets' stories and links here are fictional placeholders."""
from __future__ import annotations

from datetime import date

from .analyst import NewsAnalysis, validate
from .collect import NewsCollection, make_windows
from .sources import Article

_RAW = [
    # window index, date, source, title, summary, kind, coverage
    (4, "2025-11-12", "Reuters", "Demo Corp beats estimates, raises full-year outlook on enterprise demand",
     "Revenue rose 9% as enterprise orders accelerated; management raised guidance.", "news", 5),
    (3, "2026-02-03", "Bloomberg", "Demo Corp extends payment terms for distributors to 120 days",
     "Company says longer terms support channel partners during product transition.", "news", 3),
    (2, "2026-05-06", "WSJ", "Demo Corp revenue jumps 20%, but cash flow lags",
     "Operating cash flow fell even as reported profit hit a record; CFO cites timing of collections.", "news", 6),
    (2, "2026-05-20", "PR Newswire", "Demo Corp announces $5 billion buyback program",
     "Board authorizes new share repurchase program.", "press_release", 2),
    (1, "2026-08-14", "Financial Times", "Demo Corp restates prior-year revenue after review of distributor deals",
     "Revenue for fiscal 2024 reduced by about 10% following an internal review of channel sales.", "news", 8),
    (1, "2026-09-02", "CNBC", "Demo Corp CFO departs; interim finance chief named", "", "news", 4),
    (0, "2026-10-08", "Barron's", "Is Demo Corp stock a bargain after the selloff?",
     "Some analysts see value after shares fell 25% from highs.", "opinion", 1),
    (0, "2026-10-21", "Reuters", "SEC opens inquiry into Demo Corp revenue recognition - sources",
     "The inquiry focuses on distributor arrangements, according to two people familiar.", "news", 7),
    (0, "2026-10-29", "Bloomberg", "Demo Corp inventory swells as distributors cut orders",
     "Inventory up nearly 40% year over year; company expects normalization by mid-2027.", "news", 3),
    (0, "2026-11-02", "Yahoo Finance", "Demo Corp guides below consensus, cites 'channel digestion'",
     "Next-quarter revenue guide 8% below analyst expectations.", "news", 5),
]


def demo_collection(today: date = date(2026, 11, 5)) -> NewsCollection:
    wins = make_windows(today)
    arts = []
    for wi, d, src, title, summ, kind, cov in _RAW:
        a = Article(title=title, source=src, url="https://example.com/demo-article", published=d, summary=summ,
                    provider="demo", kind=kind, coverage=cov, period=wins[wi].label, score=3.0)
        wins[wi].articles.append(a)
        arts.append(a)
    for w in wins:
        w.raw_count = len(w.articles) * 12
    for i, a in enumerate(sorted(arts, key=lambda a: a.published), 1):
        a.id = f"S{i}"
    return NewsCollection("Demo Corp", "DEMO", wins)


def _c(text, *src):
    return {"text": text, "sources": list(src)}


def demo_analysis() -> NewsAnalysis:
    data = {
        "summary": _c("Demo Corp עברה בשנה האחרונה מסיפור צמיחה מהיר לסיפור של אמינות דיווח. הצמיחה החדה בהכנסות ב-2026 "
                      "לוותה בהארכת תנאי האשראי למפיצים ובתזרים מזומנים שפיגר אחרי הרווח. באוגוסט החברה הציגה מחדש את "
                      "הכנסות 2024 (ירידה של כ-10%), סמנכ\"ל הכספים עזב, ובאוקטובר דווח על בדיקה של ה-SEC. "
                      "החודש האחרון מצביע על האטה: מלאי תופח ותחזית מתחת לציפיות.", "S2", "S3", "S5", "S6", "S8", "S9", "S10"),
        "current_state": [
            _c("ה-SEC בודק את אופן ההכרה בהכנסות מול מפיצים — לפי מקורות, לא הודעה רשמית.", "S8"),
            _c("המלאי גדל בכ-40% בשנה כשהמפיצים מצמצמים הזמנות; החברה צופה נורמליזציה רק באמצע 2027.", "S9"),
            _c("התחזית לרבעון הבא נמוכה ב-8% מהקונצנזוס, בנימוק של 'עיכול בערוץ'.", "S10"),
            _c("המניה ירדה כ-25% מהשיא; חלק מהכותבים רואים בזה הזדמנות, אך מדובר בכתבת דעה.", "S7"),
        ],
        "timeline": [
            {"period": "לפני 10–13 חודשים", "headline": "מומנטום חזק", "text": "תוצאות מעל הציפיות והעלאת תחזית.", "sources": ["S1"]},
            {"period": "לפני 7–10 חודשים", "headline": "הארכת תנאי אשראי", "text": "תנאי תשלום למפיצים הוארכו ל-120 יום.", "sources": ["S2"]},
            {"period": "לפני 4–7 חודשים", "headline": "רווח שיא, תזרים חלש", "text": "ההכנסות קפצו 20% אבל התזרים מפעילות ירד; במקביל הוכרזה תוכנית רכישה עצמית.", "sources": ["S3", "S4"]},
            {"period": "לפני 1–4 חודשים", "headline": "הצגה מחדש ועזיבת CFO", "text": "הכנסות 2024 הוקטנו בכ-10% וסמנכ\"ל הכספים עזב.", "sources": ["S5", "S6"]},
            {"period": "החודש האחרון", "headline": "בדיקת SEC והאטה", "text": "דיווח על בדיקת SEC, מלאי תופח ותחזית חלשה.", "sources": ["S8", "S9", "S10"]},
        ],
        "concerns": [
            {"title": "אמינות ההכנסות", "severity": "high", "related_red_flags": ["restatements", "ar_vs_rev", "beneish"],
             "text": "הארכת תנאי האשראי, ההצגה מחדש ובדיקת ה-SEC מתיישבות עם הדגלים האדומים בשלב 2 (לקוחות שגדלים מהר מההכנסות, "
                     "ציון Beneish גבוה). ייתכן שחלק מהצמיחה של 2026 'נמשך קדימה' מרבעונים עתידיים.", "sources": ["S2", "S5", "S8"]},
            {"title": "רווח שלא הופך למזומן", "severity": "high", "related_red_flags": ["ni_vs_cfo", "sloan"],
             "text": "התזרים מפעילות פיגר אחרי הרווח כבר במאי, והנתונים הכספיים מראים יחס של כ-0.7 בשלוש שנים.", "sources": ["S3"]},
            {"title": "עזיבת סמנכ\"ל הכספים בעיתוי רגיש", "severity": "medium", "related_red_flags": [],
             "text": "עזיבה כשבועיים אחרי הצגה מחדש — לא בהכרח קשורה, אבל מחייבת תשומת לב.", "sources": ["S5", "S6"]},
            {"title": "רכישה עצמית לצד תזרים חלש", "severity": "medium", "related_red_flags": ["dilution"],
             "text": "תוכנית רכישה של $5B הוכרזה ברבעון שבו התזרים ירד; ובפועל מספר המניות עלה. הודעת חברה, לא ביצוע.", "sources": ["S3", "S4"]},
            {"title": "מלאי ותחזית", "severity": "medium", "related_red_flags": ["inv_vs_cogs"],
             "text": "מלאי תופח ותחזית חלשה מצביעים על ביקוש בפועל נמוך ממה שההכנסות המדווחות שיקפו.", "sources": ["S9", "S10"]},
        ],
        "positives": [
            _c("הביקוש מצד לקוחות ארגוניים היה חזק בתחילת התקופה.", "S1"),
            _c("ההנהלה מודה בבעיית המלאי ונותנת לוח זמנים לנורמליזציה.", "S9"),
        ],
        "numbers_vs_narrative": [
            _c("הדגלים 'צמיחת לקוחות מול הכנסות' ו'רווח מול תזרים' מוסברים בחדשות: הארכת תנאי אשראי למפיצים.", "S2", "S3"),
            _c("הדגל 'הצגה מחדש' (שינוי של כ-10% בהכנסות 2024) מאומת בדיווח העיתונאי.", "S5"),
            _c("גם אחרי הירידה, המחיר מגלם צמיחה גבוהה מזו שהתחזית האחרונה מרמזת עליה.", "S10"),
        ],
        "questions": [
            _c("כמה מההכנסות של 2026 תלויות במפיצים עם תנאי תשלום מורחבים?", "S2"),
            _c("מה היקף בדיקת ה-SEC והאם היא עשויה להוביל להצגות מחדש נוספות?", "S8"),
            _c("מי ימונה לסמנכ\"ל כספים קבוע, ומה יאמר רואה החשבון בדוח השנתי הבא?", "S6"),
            _c("האם ירידת המחיר משקפת את הסיכון — או שהשוק עדיין מתמחר את סיפור הצמיחה הישן?", "S7", "S10"),
        ],
        "conclusion": {
            "text": "התמונה מצביעה על סיכון גבוה סביב איכות הדיווח: החדשות מסבירות היטב את הדגלים האדומים מהדוחות, "
                    "והשילוב של הצגה מחדש, עזיבת CFO ובדיקת SEC מצדיק זהירות. הערכות השווי המבוססות על ההכנסות המדווחות "
                    "עלולות להיות אופטימיות, כי ייתכן שהבסיס עצמו מנופח.",
            "what_would_change_view": "סגירת בדיקת ה-SEC בלי ממצאים, החזרת תנאי האשראי לנורמה ותזרים שמתיישר עם הרווח לאורך שני רבעונים.",
            "confidence": "medium",
            "confidence_reason": "המקורות חזקים ומרובים, אך חלק מהמידע מבוסס על מקורות אנונימיים.",
            "sources": ["S5", "S6", "S8"]},
        "source_analysis": [
            {"id": "S1", "takeaway": "תוצאות חזקות והעלאת תחזית — נקודת השיא של הסיפור.", "sentiment": "positive", "importance": "medium", "reliability_note": "סוכנות ידיעות, עובדתי"},
            {"id": "S2", "takeaway": "הארכת אשראי למפיצים — מקדימה את הצמיחה בלקוחות.", "sentiment": "negative", "importance": "high", "reliability_note": "מקור חזק; ההסבר של החברה הוא טענה שלה"},
            {"id": "S3", "takeaway": "פער בין רווח לתזרים כבר באמצע השנה.", "sentiment": "mixed", "importance": "high", "reliability_note": "מקור חזק, מגובה בנתונים"},
            {"id": "S4", "takeaway": "הכרזה על רכישה עצמית — הצהרה, לא ביצוע.", "sentiment": "positive", "importance": "low", "reliability_note": "הודעת חברה"},
            {"id": "S5", "takeaway": "הצגה מחדש של הכנסות 2024 בכ-10%.", "sentiment": "negative", "importance": "high", "reliability_note": "מקור חזק, סיקור רחב"},
            {"id": "S6", "takeaway": "עזיבת CFO בעיתוי רגיש.", "sentiment": "negative", "importance": "medium", "reliability_note": "כותרת בלבד"},
            {"id": "S7", "takeaway": "טיעון 'מציאה' אחרי ירידה.", "sentiment": "positive", "importance": "low", "reliability_note": "כתבת דעה"},
            {"id": "S8", "takeaway": "בדיקת SEC בנושא הכרה בהכנסות.", "sentiment": "negative", "importance": "high", "reliability_note": "מקורות אנונימיים, סוכנות חזקה"},
            {"id": "S9", "takeaway": "מלאי תופח וצמצום הזמנות.", "sentiment": "negative", "importance": "medium", "reliability_note": "מקור חזק"},
            {"id": "S10", "takeaway": "תחזית מתחת לציפיות.", "sentiment": "negative", "importance": "medium", "reliability_note": "עובדתי"},
        ],
    }
    ids = {f"S{i}" for i in range(1, len(_RAW) + 1)}
    data, removed = validate(data, ids)
    return NewsAnalysis(data=data, model="demo (תשובה מוכנה מראש)", removed_claims=removed)
