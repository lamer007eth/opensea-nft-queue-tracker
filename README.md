# OpenSea NFT Queue Tracker (Console MVP)

Консольный Python-проект для отслеживания позиции вашей NFT в очереди продаж коллекции OpenSea.

## Что делает

- Раз в `check_interval_seconds` запрашивает активные листинги коллекции.
- Сортирует листинги и определяет позицию NFT по `token_id`.
- Пишет результат в консоль и в лог-файл.
- Если позиция изменилась с прошлой проверки, пишет отдельное сообщение.
- Если NFT отсутствует среди активных листингов, выводит понятное сообщение.

## Структура

- `main.py` - точка входа.
- `config.toml` - конфиг проекта.
- `src/nft_queue_tracker/config.py` - загрузка и валидация конфига.
- `src/nft_queue_tracker/models.py` - модели данных.
- `src/nft_queue_tracker/providers/base.py` - интерфейс источника данных.
- `src/nft_queue_tracker/providers/opensea_api.py` - реализация через OpenSea API с ретраями.
- `src/nft_queue_tracker/position.py` - сортировка и расчет позиции NFT.
- `src/nft_queue_tracker/tracker.py` - основной цикл трекера.

## Требования

- Python 3.11+

## Установка

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

## Настройка

Отредактируйте `config.toml`:

```toml
collection_slug = "your-collection-slug"
token_id = "1234"
check_interval_seconds = 300
output_log_file = "tracker.log"
opensea_api_key = ""
```

`opensea_api_key` можно оставить пустым и передавать ключ через переменную окружения `OPENSEA_API_KEY`.

## Запуск

Обычный режим (каждые N секунд):

```bash
python main.py
```

Диагностический режим (один запуск и выход):

```bash
python main.py --validate-once
```

В диагностическом режиме выводятся:
- статистика извлечения полей (`token_id`, `price`, `listed_at`),
- позиция NFT,
- окно `10 до + NFT + 10 после`,
- все найденные листинги, если у `token_id` есть дубликаты.

## Обработка ошибок сети

В `OpenSeaApiProvider` включены повторные попытки при временных ошибках сети/сервера (429/5xx и сетевые исключения).

## Расширяемость (на будущее)

Архитектура построена через интерфейс `ListingsProvider`. Это позволяет позже добавить второй источник данных (например, парсинг HTML-страницы OpenSea) без изменения логики трекера и расчета позиции.
