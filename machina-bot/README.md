# Машина часів — Telegram-бот курсу (GOTit)

Бот із ТЗ «Машина часів · технічна частина»: доступ тільки після оплати, пакети = ролі, графік блоків від дня оплати,
домашки/дзвінки/підтримка, автоповідомлення, захист контенту, облік студентів.
Логіка детально: `docs/LOGIC.md`.

## 1. Бот у Telegram
1. @BotFather → `/newbot` → отримай **BOT_TOKEN**.
2. Свій Telegram ID (і Валерії) — у @userinfobot → це **ADMIN_IDS** (через кому).

## 2. GitHub
```bash
cd machina-bot
git init && git add . && git commit -m "Machina bot"
git branch -M main
git remote add origin https://github.com/<you>/machina-bot.git
git push -u origin main
```
(`.env` у `.gitignore` — токен у репозиторій не потрапить.)

## 3. Render
1. **New + → PostgreSQL** → скопіюй **Internal Database URL**. (Безкоштовна база на Render має обмежений термін — для курсу на 3+ місяці бери платну.)
2. **New + → Blueprint** → вибери репозиторій (підхопиться `render.yaml`), або **Web Service** вручну:
   Build `pip install -r requirements.txt` · Start `python -m app.main` · Health check `/health`.
3. Змінні середовища (Environment):

| Змінна | Що |
|---|---|
| `BOT_TOKEN` | токен від BotFather **(обов'язково)** |
| `ADMIN_IDS` | Telegram ID менеджерки та Валерії **(обов'язково)** |
| `DATABASE_URL` | Internal Database URL з Postgres **(обов'язково)** |
| `PAYMENT_WEBHOOK_SECRET` | довільний секрет для вебхука оплати (Blueprint згенерує) |
| `DIRECT_URL` | `https://ig.me/m/<instagram школи>` — кнопка «Як отримати доступ» |
| `CALL_BOOKING_URL` | Calendly/Cal.com для дзвінків (можна пусто) |
| `FEEDBACK_URL`, `EXTEND_URL`, `WORKBOOK_URL`, `GRAMMAR_URL` | посилання для «Ще більше» і відгуку (можна пусто) |
| `PRICE_CHANGE_AT` | `2026-12-02T00:00` (за Києвом) |
| `VALERIA_SEATS_LIMIT` | `5` |
| `QUIET_HOURS` | `1` = автоповідомлення тільки 09:00–21:00 |
| `WATERMARK_CAPTIONS` | `1` = у підписі файлів нік студента (водяний знак) |

`WEBHOOK_BASE_URL` вказувати не треба — Render дає `RENDER_EXTERNAL_URL`, бот сам ставить вебхук.
Не став безкоштовний web-план: він «засинає», а бот має слати автоповідомлення за графіком.

## 4. Перший запуск і тест (5 хвилин)
1. Відкрий бота → `/admin` (бачиш лише ти).
2. **Вигляд для неоплаченого:** `/guest` → `/start`. Побачиш привітання + кнопку в Direct; будь-яка кнопка/текст → «розділ відкривається після оплати».
3. **Вигляд для оплаченого:** `/testas valeria` (або `self`, `curator`) — ти одразу студент: привітання, меню, уроки.
4. Завантаж контент: `/upload auto` і кидай файли **як файл** (не стисненим відео): `MCh_Урок01_Present-Simple.pdf`, `MCh_Урок01_Розбір.pdf`, `MCh_Урок01_Вправи.pdf`, `MCh_Урок01_Відео.mp4`, `MCh_Урок01_Аудіо.mp3`, `MCh_Таблиця.pdf` → `/done`.
5. Подивись урок: «📚 Мої уроки» → блок 1 → урок. Спробуй переслати чи зберегти відео — Telegram не дасть.
6. Домашка: «📩 Надіслати домашку» (у тесті вона приходить тобі) → **відповідай реплаєм** → студент отримає.
7. Графік: `/shift <id> 7` — наступний блок відкриється, автоповідомлення прийде за ≤5 хв. `/shift <id> 80` — нагадування про кінець, `/shift <id> 90` — доступ закрито.
8. Справжня оплата: `/issue valeria Марія @maria` → скопіюй готове повідомлення з посиланням і надішли в Direct.

## 5. Інтеграція оплати (за бажанням)
`POST https://<твій-сервіс>.onrender.com/webhook/payment`, заголовок `X-Webhook-Secret: <PAYMENT_WEBHOOK_SECRET>`,
JSON: `{"order_id":"123","package":"self|curator|valeria","name":"Марія","instagram":"@maria"}` (або замість `package` — `"amount": 1890`).
Бот створить код і напише менеджерці в Telegram з готовим текстом — вона після перевірки надходження шле його в Direct.
Підходить для Make/Zapier/ManyChat «External request» або будь-якого Pay з вебхуками (підпис конкретного Pay — окрема дрібна доробка).

## 6. Тексти, стиль, стікери
- `/texts` → `/settext welcome` — змінити будь-який текст прямо з Telegram (без редеплою); `/resettext` — повернути.
- `/setsticker welcome` (+ надіслати стікер) — стікери для: welcome, block_open, quiz_high, hw_got, bonus, expired.
- Назви блоків/уроків і тема тижня — `data/course.json`; тести — `data/quizzes.json` (формат див. `quizzes.example.json`).

## Важливе і чесно
- Захист: `protect_content` забороняє пересилання/збереження в Telegram; на телефонах блокує скріншоти, на комп'ютері — не повністю.
  Нік студента в підписі — водяний знак. Справжній водяний знак *всередині* PDF/відео — окрема доробка.
- Файли тримаються в Telegram (file_id), тому завантажуй їх **через бота** (`/upload`), а не посиланнями на Drive.
- Стан діалогів (FSM) у пам'яті: після рестарту незавершена дія (напр. «пишу домашку») скидається — дані в базі не втрачаються.
- Бота перевірено юніт-тестами логіки (`python tests/test_course.py`), але повний запуск з Telegram потребує токена — тестуй за п. 4.
