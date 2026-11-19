# GOTIt School — «Машина часів» Telegram Bot

Готовий production-ready каркас бота для Render + GitHub.

## Що реалізовано

- Telegram-бот на aiogram 3 + FastAPI webhook.
- SQLite для студентів, платежів, доступів, пакетів та домашок.
- Персональний access code / deep-link після оплати.
- 3 пакети: `self`, `curator`, `valeria`.
- Доступ = 90 днів від дати оплати.
- Графік відкриття: день 0 / 7 / 14 / 21 / 28 / 35 / 80 / 90.
- Автоматичне відкриття блоків.
- Автоматичні нагадування.
- Захищені Telegram-матеріали (`protect_content=True`).
- Домашки: текст / фото / файл / voice → адміну/куратору.
- Прив'язка куратора.
- Простий admin API для імпорту оплати та перевірки студента.
- Health endpoint для Render.
- Dockerfile + render.yaml.
- Контент відокремлений від коду: `content/blocks.json`.

## Важливе

За матеріалами технічної інструкції GOTIt, оплата є точкою входу в бот: до оплати матеріали не відкриваються; пакет визначає роль/кнопки; дата оплати є днем 0; доступ закінчується через 90 днів. fileciteturn0file0L187-L206

Цей репозиторій не містить реальних Telegram token / webhook secret / Pay credentials. Їх потрібно додати в Render Environment Variables.

## Локальний запуск

1. Python 3.12+
2. `cp .env.example .env`
3. Заповнити `BOT_TOKEN`, `ADMIN_IDS`.
4. `pip install -r requirements.txt`
5. `python -m app.main`

Для локальної роботи бот працює через polling.

## Render

Найпростіше:

1. Створити GitHub repository.
2. Завантажити весь вміст цього проєкту.
3. У Render → New → Web Service.
4. Build Command:
   `pip install -r requirements.txt`
5. Start Command:
   `python -m app.main`
6. Додати env:
   - `BOT_TOKEN`
   - `ADMIN_IDS`
   - `PUBLIC_BASE_URL`
   - `ADMIN_API_KEY`
   - `DATABASE_URL=sqlite:///data/bot.db`
7. У Render додати persistent disk для `/data`, якщо потрібне збереження SQLite між деплоями.

## Підключення оплати

Pay у презентації описаний як окреме джерело підтвердження платежу. У цьому боті зроблено endpoint:

`POST /api/payments/confirm`

Передає:
- external_payment_id
- customer_name
- telegram_id (якщо вже відомий)
- package
- paid_at

Після підтвердження бот створює/оновлює студента і генерує персональний deep link.

Якщо Pay-сервіс у GOTIt має власний webhook, його можна підключити до цього endpoint без переписування логіки бота.

## Логіка доступу

День 0:
- welcome
- інструкція
- блок 1

День 7:
- блок 2

День 14:
- блок 3

День 21:
- блок 4

День 28:
- блок 5

День 35:
- bonus week

День 80:
- попередження про завершення

День 90:
- доступ закривається

Це відповідає технічній схемі в матеріалах GOTIt. fileciteturn0file0L231-L242

## Контент

У `content/blocks.json` уже є структура для 5 блоків + bonus.
Замініть placeholder `file_id` на реальні Telegram file_id після завантаження матеріалів.

Бот не потребує Google Drive: матеріали можна надсилати прямо в Telegram із `protect_content=True`, як передбачено інструкцією. fileciteturn0file0L265-L283

## Команди

Студент:
- `/start`
- `/menu`
- `/status`
- `/support`

Адмін:
- `/admin`
- `/student <telegram_id>`

## Захист

Telegram `protect_content` зменшує просте пересилання/збереження контенту, але не є DRM. Інструкція GOTIt також прямо зазначає, що 100% захист неможливий. fileciteturn0file0L290-L300
