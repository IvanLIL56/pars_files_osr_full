# File Processor — Система обработки документов

Автоматизированная система для скачивания документов по URL из Excel-файла, их обработки (OCR, извлечение текста) и загрузки метаданных в базу данных.

## Возможности

### Поддерживаемые форматы файлов
- **Документы**: DOC, DOCX, RTF, ODT, TXT, PDF
- **Таблицы**: XLS, XLSX
- **Изображения**: JPG, JPEG, PNG, BMP, TIFF, GIF (с OCR)
- **Архивы**: ZIP, RAR, 7Z, TAR, GZ (рекурсивное извлечение)

### Источники данных
- Excel-файлы со списком URL документов
- Автоматическое извлечение номера договора из URL


### Обработка
- Извлечение текста из PDF (текстовый слой + OCR для сканов)
- Извлечение текста из Word-документов
- OCR для изображений и сканированных PDF
- Рекурсивная обработка вложенных архивов
- Поиск ключевых слов в текстах
- Вычисление хэшей для дедупликации

### База данных
- Поддержка SQLite, PostgreSQL, MySQL
- Идемпотентная запись (пропуск уже обработанных файлов)
- Атомарная блокировка задач при параллельной обработке
- Хранение метаданных и результатов обработки

## Структура проекта

```
/workspace
├── main.py                 # Точка входа CLI
├── config.py               # Конфигурация через pydantic
├── requirements.txt        # Зависимости Python
├── .env                    # Переменные окружения
├── .env.example            # Шаблон переменных
├── README.md               # Эта документация
│
├── auth/                   # Модуль аутентификации
│   ├── __init__.py
│   └── authenticator.py    # Авторизация на сайте, получение токена
│
├── config/                 # (опционально) вынесенная конфигурация
│
├── db/                     # Модуль базы данных
│   ├── __init__.py
│   ├── repository.py       # Репозиторий для работы с БД
│   └── models.py           # SQLAlchemy модели
│
├── downloader/             # Модуль загрузки файлов
│   ├── __init__.py
│   └── file_downloader.py  # Скачивание файлов по API
│
├── ingest/                 # Модуль импорта из Excel
│   ├── __init__.py
│   └── excel_ingester.py   # Чтение Excel, управление загрузкой
│
├── models/                 # Модели данных
│   ├── __init__.py
│   └── db_models.py        # SQLAlchemy модели таблиц
│
├── processors/             # Модуль обработки файлов
│   ├── __init__.py
│   ├── content_extractor.py    # Главный экстрактор контента
│   ├── document_reader.py      # Чтение DOC/DOCX
│   ├── pdf_reader.py           # Чтение PDF + OCR
│   ├── image_ocr.py            # OCR изображений
│   └── file_scanner.py         # Сканирование директорий
│
├── utils/                  # Утилиты
│   ├── __init__.py
│   ├── logger.py           # Настройка логирования
│   ├── hash_utils.py       # Вычисление хэшей
│   ├── keyword_search.py   # Поиск ключевых слов
│   └── streaming.py        # Потоковая обработка
│
├── logs/                   # Логи приложения
├── downloaded_files/       # Скачанные файлы (по договорам)
├── data/                   # Данные (SQLite БД)
└── input/                  # Входные файлы
```

## Установка

### 1. Клонирование репозитория
```bash
git clone <repository-url>
cd <project-directory>
```

### 2. Создание виртуального окружения
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
```

### 3. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 4. Настройка окружения
```bash
cp .env.example .env
# Отредактируйте .env, указав ваши параметры
```

### 5. Системные зависимости (для OCR и работы с документами)

#### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-rus \
    antiword \
    poppler-utils \
    libpoppler-cpp-dev
```

#### macOS
```bash
brew install tesseract antiword poppler
```

#### Windows
- Установите [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
- Установите [antiword](http://www.winfield.demon.nl/) (опционально)
- Добавьте пути к исполняемым файлам в PATH

## Конфигурация (.env)

### Основные настройки
```env
PROJECT_NAME=FileProcessor

# Пути
PATH_INPUT_DIR=./input
PATH_LOG_DIR=./logs
PATH_DOWNLOAD_DIR=./downloaded_files
```

### База данных
```env
# Тип БД: sqlite, postgresql, mysql
DB_DB_TYPE=sqlite

# Для PostgreSQL
DB_PG_HOST=localhost
DB_PG_PORT=5432
DB_PG_USER=postgres
DB_PG_PASSWORD=postgres
DB_PG_DB=file_processor

# Для MySQL
DB_MYSQL_HOST=localhost
DB_MYSQL_PORT=3306
DB_MYSQL_USER=root
DB_MYSQL_PASSWORD=root
DB_MYSQL_DB=file_processor

# Для SQLite
DB_SQLITE_PATH=./data/file_processor.db

# Пул соединений (для PostgreSQL/MySQL)
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_PRE_PING=true
```

### Excel файл
```env
EXCEL_FILE_PATH=./contracts.xlsx
EXCEL_URL_COLUMN=Url документа
```

### Загрузка файлов
```env
DOWNLOAD_MAX_PARALLEL_DOWNLOADS=5
DOWNLOAD_RETRY_COUNT=3
DOWNLOAD_RETRY_DELAY=5
DOWNLOAD_SKIP_IF_EXISTS=true
DOWNLOAD_OVERWRITE_EXISTING=false
DOWNLOAD_MAX_FILENAME_LENGTH=155
```

### Обработка
```env
PROC_MAX_WORKERS=4
PROC_MAX_OCR_WORKERS=2
PROC_BATCH_SIZE=50
PROC_ENABLE_KEYWORD_SEARCH=true
PROC_KEYWORDS_FILE=./keywords.txt
```

### Логирование
```env
LOG_LEVEL_CONSOLE=INFO
LOG_LEVEL_FILE=DEBUG
LOG_USE_SINGLE_FILE=true
```

## Использование

### Базовый запуск
```bash
python main.py
```
Использует настройки из `.env` по умолчанию.

### Запуск с указанием Excel-файла
```bash
python main.py --excel ./my_contracts.xlsx
```

### Полный пример с параметрами
```bash
python main.py \
    --excel ./contracts.xlsx \
    --column "Url документа" \
    --output-report ./report.json \
    --skip-downloaded \
    --reprocess-errors
```

### Параметры командной строки
| Параметр | Описание |
|----------|----------|
| `--excel` | Путь к Excel-файлу со списком URL |
| `--column` | Название колонки с URL (по умолчанию: "Url документа") |
| `--output-report` | Путь для JSON-отчёта о результатах |
| `--skip-downloaded` | Пропустить уже скачанные файлы |
| `--reprocess-errors` | Повторно обработать файлы с ошибками |
| `--max-workers` | Переопределить количество воркеров |
| `--dry-run` | Тестовый запуск без реальных действий |

## Как это работает

### 1. Чтение Excel
- Открывается Excel-файл из `EXCEL_FILE_PATH`
- Извлекаются все уникальные URL из колонки `EXCEL_URL_COLUMN`
- Из каждого URL извлекается номер договора (последняя часть пути)

### 2. Обработка файлов
Для каждого скачанного файла:
1. Определение типа файла по расширению
2. Извлечение текста:
   - **PDF**: текстовый слой или OCR
   - **DOC/DOCX**: python-docx или antiword
   - **Изображения**: Tesseract OCR
   - **Архивы**: рекурсивное извлечение и обработка
3. Поиск ключевых слов (если включено)
4. Вычисление полного хэша содержимого
5. Запись результатов в БД

### 3. Параллелизм и блокировки
- **Скачивание**: ThreadPoolExecutor с `MAX_PARALLEL_DOWNLOADS`
- **Обработка**: Отдельный пул с `MAX_OCR_WORKERS` (ограничено для CPU-intensive OCR)
- **Блокировка задач**: Атомарное обновление статуса в БД предотвращает дублирование
- **Идемпотентность**: Повторный запуск обрабатывает только новые/ошибочные файлы

### 4. Отчётность
В конце работы выводится статистика:
- Количество обработанных договоров
- Количество скачанных файлов (успешно/ошибки/пропущено)
- Количество обработанных файлов
- Время выполнения

Опционально сохраняется JSON-отчёт.

## Архитектура обработки очередей

### Очередь на парсинг
1. После скачивания файл регистрируется в БД со статусом `PENDING`
2. Воркеры сканирования периодически проверяют БД на наличие `PENDING` файлов
3. При взятии задачи воркер атомарно меняет статус на `PROCESSING`
4. Это гарантирует, что каждый файл обрабатывается только одним воркером

### Защита от гонок
```sql
UPDATE files_metadata 
SET status = 'PROCESSING', worker_id = :worker_id 
WHERE id = :file_id AND status = 'PENDING'
```
Если обновлена 1 строка — задача захвачена успешно, иначе — другой воркер уже обрабатывает.

### Восстановление после сбоев
Файлы со статусом `PROCESSING`, которые не обновлялись более N минут, автоматически возвращаются в `PENDING` для повторной обработки.

## Логирование

Все события логируются в:
- **Консоль**: уровень `LOG_LEVEL_CONSOLE`
- **Файл**: `./logs/app.log`, уровень `LOG_LEVEL_FILE`

Используется единый файл лога (без ротации по времени), ротация по размеру.

## Тестирование

### Быстрая проверка
```bash
python -c "from config import settings; print('Config OK')"
python -c "from db.repository import get_repository; print('DB OK')"
python -c "from auth.authenticator import SiteAuthenticator; print('Auth OK')"
```

### Запуск с тестовым Excel
1. Создайте `./input/test.xlsx` с колонкой "Url документа"
2. Добавьте 2-3 тестовых URL
3. Запустите: `python main.py --excel ./input/test.xlsx --dry-run`

## Troubleshooting

### Ошибка: "pytesseract not found"
Установите Tesseract OCR и добавьте в PATH. Проверьте:
```bash
tesseract --version
```

### Ошибка: "antiword not found"
Установите antiword или используйте fallback-режим (ZIP-чтение DOCX).

### Ошибка подключения к БД
Проверьте параметры в `.env`:
```env
DB_DB_TYPE=sqlite  # для локальной разработки
```


## Лицензия

Проект разработан для внутренней автоматизации процессов обработки документов.

## Контакты

По вопросам обращайтесь к разработчикам проекта.
