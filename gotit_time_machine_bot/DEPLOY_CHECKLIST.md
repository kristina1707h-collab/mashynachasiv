# GOTIt — запуск

## 1. Telegram
- Створити/вибрати бота в BotFather.
- Скопіювати BOT_TOKEN.
- Зробити Telegram ID Валерії/менеджерки/кураторів.
- Додати їх у ADMIN_IDS.

## 2. Матеріали
Для кожного PDF/video/audio:
1. Надіслати файл у приватний Telegram-чат.
2. Отримати Telegram `file_id`.
3. Вставити його у `content/blocks.json`.
4. Для кожного уроку додати caption.

Це дозволяє тримати матеріали всередині Telegram і використовувати `protect_content`.

## 3. GitHub
Завантажити весь репозиторій без `.env`.

## 4. Render
Створити Web Service з Dockerfile.
Додати змінні з `.env.example`.
Увімкнути persistent disk `/data`.

## 5. Pay
З Pay/webhook треба викликати:
`POST /api/payments/confirm`

Header:
`X-API-Key: ADMIN_API_KEY`

Body example:
{
  "external_payment_id": "PAY-123",
  "customer_name": "Ім'я Прізвище",
  "package": "curator",
  "paid_at": "2026-11-19T10:00:00+02:00",
  "telegram_id": 123456789,
  "amount": 7490
}

Якщо Pay не передає Telegram ID, найкращий варіант — після оплати відправляти людину на персональний link із кодом, або зробити проміжний екран/форму, де вона вводить Telegram username/ID.

## 6. Перевірка
Перевірити окремо:
- self payment
- curator payment
- valeria payment
- неправильний/повторний payment webhook
- доступ після /start
- блок до дати відкриття
- домашку
- завершення 90 днів
- protect content на iPhone / Android / desktop
