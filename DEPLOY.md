# העלאה לענן: חינם, עם התחברות Google

**הארכיטקטורה (כל הרכיבים בחינם):**

| רכיב | שירות | למה |
|---|---|---|
| אירוח האפליקציה | **Streamlit Community Cloud** | חינמי, מתחבר ל-GitHub ומתעדכן בכל push |
| התחברות | **Google** (OIDC, דרך `st.login`) | כניסה עם חשבון Google; רק מיילים מורשים |
| מסד נתונים | **Neon** (Postgres חינמי) | רשימות מעקב והיסטוריה נשמרות גם כשהשרת מתאפס |
| מודל שפה | **Gemini** — כל משתמש עם מפתח חינמי משלו | אין עלות למנהל; ההסבר להשגת מפתח מופיע באפליקציה |

זמן הקמה משוער: 30–40 דקות, פעם אחת.

> Vercel ו-Cloudflare לא מתאימים לאפליקציה הזו. הם מריצים פונקציות קצרות שנקטעות אחרי זמן קצר, וניתוח החדשות לוקח כמה דקות. בנוסף, Streamlit צריך שרת שרץ ברציפות.

---

## שלב 1: GitHub

1. צור חשבון ב-[github.com](https://github.com), אם עדיין אין לך.
2. צור מאגר (repository) חדש, למשל `stock-analyzer`. אפשר Private.
3. העלה אליו את כל תיקיית הפרויקט.
   - הקבצים `keys.env` ו-`.streamlit/secrets.toml` מוחרגים ב-`.gitignore`, כך שהמפתחות שלך לא יעלו.
   - **בדוק שהם באמת לא עלו.**

```bash
cd stock_analyzer
git init && git add . && git commit -m "Stock analyzer"
git branch -M main
git remote add origin https://github.com/<USER>/stock-analyzer.git
git push -u origin main
```

## שלב 2: מסד נתונים חינמי (Neon)

1. היכנס ל-[neon.tech](https://neon.tech) ← **Sign up** (אפשר עם Google). לא צריך כרטיס אשראי.
2. **Create project**. בחר אזור קרוב, למשל Frankfurt.
3. בדשבורד לחץ **Connect** והעתק את ה-**Connection string**. הוא נראה כך:
   `postgresql://user:password@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require`
4. שמור אותו לשלב 4. הטבלאות נוצרות אוטומטית בהפעלה הראשונה.

> אם תדלג על השלב הזה, האפליקציה תעבוד עם SQLite, אבל רשימות המעקב וההיסטוריה יימחקו בכל אתחול של השרת בענן.

## שלב 3: התחברות עם Google (OAuth)

1. היכנס ל-[Google Cloud Console](https://console.cloud.google.com/) וצור פרויקט חדש, למשל `stock-analyzer-auth`.
2. בתפריט: **Google Auth Platform**. אם מופיע **Get started**, לחץ עליו.
3. **Branding:**
   - App name: `ניתוח מניות`.
   - User support email: המייל שלך.
   - Authorized domains: `streamlit.app`.
   - **Save**.
4. **Audience:**
   - בחר **External**.
   - יש שתי אפשרויות:
     - **Testing:** רק מי שתוסיף תחת **Test users** יוכל להתחבר, עד 100 משתמשים.
     - **Publish app (מומלץ):** כל חשבון Google יכול להשלים התחברות, אבל **האפליקציה עצמה** חוסמת כל מי שלא ברשימת המורשים שלך. עם ההרשאות הבסיסיות (email, profile) לא נדרש אימות של Google.
5. **Clients** ← **Create client**:
   - Application type: **Web application**.
   - **Authorized redirect URIs** — הוסף שתי כתובות:
     - `https://<שם-האפליקציה>.streamlit.app/oauth2callback` (תדע את השם בשלב 4; אפשר לחזור ולעדכן).
     - `http://localhost:8501/oauth2callback`, לבדיקה מקומית.
   - **Create**. העתק את **Client ID** ואת **Client secret**.

## שלב 4: פריסה ב-Streamlit Community Cloud

1. היכנס ל-[share.streamlit.io](https://share.streamlit.io) עם חשבון GitHub.
2. **Create app** ← **Deploy a public app from GitHub**.
   - Repository: המאגר שיצרת. Branch: `main`. Main file: `app.py`.
   - **App URL:** בחר שם, למשל `my-stocks`. הכתובת תהיה `https://my-stocks.streamlit.app`.
   - **Advanced settings:**
     - Python version: **3.12**.
     - **Secrets:** הדבק את התוכן של `.streamlit/secrets.toml.example` ומלא את הערכים. ראה הטבלה בהמשך.
3. **Deploy**. ההתקנה הראשונה לוקחת כמה דקות.
4. חזור ל-Google (שלב 3.5) וודא שה-redirect URI הוא בדיוק `https://my-stocks.streamlit.app/oauth2callback`.

**ערכי ה-Secrets:**

| מפתח | מאיפה |
|---|---|
| `ADMIN_EMAILS` | המייל שלך (מנהל). לדוגמה: `["you@gmail.com"]` |
| `ALLOWED_EMAILS` | אופציונלי. אפשר להשאיר `[]` ולנהל מתוך האפליקציה |
| `APP_SECRET` | מחרוזת אקראית ארוכה: `python -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `DATABASE_URL` | ה-Connection string מ-Neon |
| `GEMINI_API_KEY` | המפתח שלך. משמש **רק מנהלים** |
| `[auth] redirect_uri` | `https://my-stocks.streamlit.app/oauth2callback` |
| `[auth] cookie_secret` | עוד מחרוזת אקראית ארוכה |
| `[auth] client_id` / `client_secret` | משלב 3 |
| `[auth] server_metadata_url` | `https://accounts.google.com/.well-known/openid-configuration` (כמו שהוא) |

## שלב 5: הוספת משתמשים

1. היכנס לאפליקציה עם המייל שהגדרת ב-`ADMIN_EMAILS`.
2. **🔑 הגדרות ומפתח** ← **ניהול** ← **הוסף מייל**. אפשר גם `*@company.com` לדומיין שלם.
3. המשתמש נכנס עם Google, נכנס ל-**🔑 הגדרות ומפתח**, ופותח את הלשונית **איך משיגים מפתח Gemini חינמי**. יש שם הסבר צעד-אחר-צעד עם קישור. הוא מדביק את המפתח, לוחץ **בדוק ושמור**, והמפתח נשמר מוצפן בחשבון שלו.

---

## הערות

- **שינה:** אפליקציה ב-Community Cloud שלא נכנסו אליה זמן מה נכנסת למצב שינה. הכניסה הבאה מעירה אותה תוך כחצי דקה.
- **Yahoo Finance משרתי ענן:** לפעמים חוסם בקשות. במקרה כזה המחיר נלקח מ-Stooq כגיבוי. מכפילי המתחרים, שמגיעים רק מ-Yahoo, עלולים להיות חסרים, ואז המודל הזה פשוט לא נכנס לשקלול.
- **עדכונים:** כל `git push` למאגר מעדכן את האפליקציה אוטומטית.
- **בדיקה מקומית עם התחברות:** העתק את `secrets.toml.example` ל-`.streamlit/secrets.toml`, שנה את `redirect_uri` ל-`http://localhost:8501/oauth2callback`, והרץ `streamlit run app.py`. בלי קובץ secrets האפליקציה רצה במצב מקומי, בלי התחברות.
- **פרטיות:** מפתחות שמשתמשים שומרים מוצפנים ב-`APP_SECRET`. אם תשנה את `APP_SECRET`, המפתחות השמורים יפסיקו לעבוד, והמשתמשים יצטרכו להזין אותם מחדש.
