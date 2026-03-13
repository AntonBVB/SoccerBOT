# Polymarket Football NO Bot

Готовый 24/7 бот для VPS + Docker, который:
- ищет футбольные матчи по `tag_id` через Gamma API,
- торгует только 3-way moneyline рынки,
- открывает ENTRY как `SELL` по outcome token (эквивалент BUY NO),
- после перехода в live отменяет остаток ENTRY и через 15 секунд ставит TP как `BUY` по outcome token,
- сохраняет состояние в SQLite и переживает рестарты.

## Стек
- Python 3.11+
- Docker / docker-compose
- SQLite
- `py-clob-client`
- `httpx` + `tenacity`
- `APScheduler`

## Быстрый старт (VPS)
1. Клонировать репозиторий.
2. Скопировать env:
   ```bash
   cp .env.example .env
   ```
3. Заполнить `.env` (минимум `PRIVATE_KEY`).
4. Запуск:
   ```bash
   docker compose up -d --build
   ```
5. Логи:
   ```bash
   docker compose logs -f polymarket-bot
   ```

## DRY RUN
Для проверки пайплайна без реальных ордеров:
```env
DRY_RUN=true
```

## Что хранится
- SQLite: `./data/bot_state.db`
- Логи: `./logs/bot.log`

## Fail-safe поведение
Если в рынке не хватает необходимых полей (`token_id`, `tick_size`, `neg_risk`, orderbook, и т.д.) — рынок пропускается, причина логируется в `system_log`, отправляется Telegram CRITICAL (если включено), бот продолжает работу.

## Telegram
Включается через:
```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```
Отправляются CRITICAL уведомления + daily report в `10:00 Europe/Moscow`.

## Sanity ссылки
Для ручной проверки похожих матчей (бот HTML не парсит, только Gamma/CLOB API):
- https://polymarket.com/ru/sports/bundesliga/bun-koe-hof-2026-02-21
- https://polymarket.com/ru/sports/bundesliga/bun-uni-b04-2026-02-21

## Важно
- Торгуются только лиги из whitelist через `tag_id`.
- Draw outcome никогда не торгуется.
- Если обе команды одновременно подходят по фильтрам входа — матч целиком пропускается.
