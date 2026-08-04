# tiny-agent

Coding agent harness for tiny LLMs (0.5B–3B). Оптимизирован под микро-модели, которые не умеют стабильно вызывать инструменты, теряют контекст через 3-4 шага и галлюцинируют на ровном месте.

**Основная тестовая модель**: Qwen3.5 0.8B (Q5_K_M, llama.cpp). Проект заточен под модели этого класса: дешёвые, запускаемые на CPU, с контекстным окном 2-10K токенов.

---

## Статус реализации (2026-08)

**MVP реализован и протестирован на Qwen3.5 0.8B (llama.cpp, `http://127.0.0.1:8080`).**

| Этап | Статус | Результат теста на 0.8B |
|---|---|---|
| Agent loop (ls → ответ) | ✅ | Модель вызывает `ls`, получает дерево, отвечает текстом. Repeat-guard блокирует повторные `ls`. |
| Создание файла (`write_file`) | ✅ | `calc.py` создан корректно. Повторная запись в существующий файл заблокирована (guard). |
| Редактирование (`edit_file`) | ✅ | `sub()` добавлена в `calc.py`. Idempotency-guard не даёт повторно применить ту же правку. |
| Architect → `ARCHITECTURE.md` | ✅ | Сгенерирован полный документ (обзор, компоненты, data model, API, tech choices). |
| Planner → `TASKS.md` | ✅ | Двухфазный механизм: модель пишет текст → харнес сохраняет в файл. |
| Implementer → `*.py` | ✅ | `temperature.py` сгенерирован, синтаксис валиден, тесты проходят. |
| Tester (bash + pytest) | ⚠️ | Guard-ы и субагент работают, но 0.8B деградирует на длинных сессиях (>5K токенов) — нужна более сильная модель или ручной режим. |
| Judge | ✅ | Score 100 (хороший кейс) / 70 (плохой кейс). Правила сохраняются в `.tiny-agent/rules/`. |
| Субагент-корректор | ✅ | Исправляет неверные пути (`hello.py` вместо `.tiny-agent/hello.py`), оборачивает команды в `bash`. |

**Ключевые выводы из тестирования 0.8B:**
1. **Thinking надо отключать** (`chat_template_kwargs: {"enable_thinking": false}`) — иначе модель тратит весь бюджет токенов на `reasoning_content` и отвечает пустотой.
2. **Двухфазная генерация артефактов** — 0.8B не может выдать длинный `write_file` в tool-call режиме (обрезка по max_tokens, repetition). Рабочая схема: модель пишет контент текстом → харнес сохраняет в файл.
3. **Агрессивный compaction на 4K** — модель деградирует после ~5K токенов контекста, поэтому суммаризация должна срабатывать раньше, чем на 80% окна.
4. **Репитиция**: 0.8B повторяет фразы и вызовы. Нужны все три механизма: window-loop-detector, text-repetition-detector, path-blacklist.
5. **`2>&1` ложно блокировался** как shell-write — исправлено (redirect descriptors не считаются записью файла).
6. **Рестарт с суммаризацией вреден для 0.8B** — суммаризация генерирует новые галлюцинации (`PROJECT_ROOT/...`). Приоритет: force-complete → two-phase → (только потом) restart.

---

## Содержание

- [Концепция](#концепция)
- [Сравнение с little-coder](#сравнение-с-little-coder)
- [Архитектура](#архитектура)
  - [Обзор компонентов](#обзор-компонентов)
  - [Agent Loop — цикл агента](#agent-loop--цикл-агента)
  - [Context Pipeline — что попадает в промпт](#context-pipeline--что-попадает-в-промпт)
- [Компоненты](#компоненты)
  - [app/ — ядро приложения](#app--ядро-приложения)
  - [agents/ — конфиги агентов](#agents--конфиги-агентов)
  - [tools/ — имплементация инструментов](#tools--имплементация-инструментов)
  - [skills/ — навыки для модели](#skills--навыки-для-модели)
  - [docs/ — документация для RAG](#docs--документация-для-rag)
  - [rules/ — правила LLM-as-judge](#rules--правила-llm-as-judge)
  - [front/ — терминальный интерфейс (Textual)](#front--терминальный-интерфейс-textual)
- [Подсистемы](#подсистемы)
  - [Управление контекстным окном](#управление-контекстным-окном)
  - [Tool Calling — вызов инструментов](#tool-calling--вызов-инструментов)
  - [Саб-агенты](#саб-агенты)
  - [RAG и BM25](#rag-и-bm25)
  - [LLM-as-Judge и генерация правил](#llm-as-judge-и-генерация-правил)
  - [SDD-воркфлоу (Plan → Docs → Code → Test → Fix)](#sdd-воркфлоу-plan--docs--code--test--fix)
- [Конфигурация](#конфигурация)
  - [Модели](#модели)
  - [Настройки проекта](#настройки-проекта)
  - [Режимы работы](#режимы-работы)
- [Структура проекта](#структура-проекта)
- [Установка и запуск](#установка-и-запуск)
- [Roadmap / План разработки](#roadmap--план-разработки)
- [Corner Cases и риски](#corner-cases-и-риски)

---

## Концепция

**Проблема**: Маленькие модели (0.5B–8B) в агентном режиме:
1. Ломают формат tool call — пишут JSON текстом, путают имена, выдумывают параметры
2. Зацикливаются — повторяют один и тот же вызов 3+ раз
3. Не исследуют окружение — перезаписывают файлы с нуля вместо правки
4. Пишут код в чат вместо вызова Write
5. Теряют задачу на длинных процессах
6. Не понимают короткие промпты — нужна декомпозиция
7. Галлюцинируют методы, параметры, deprecated API
8. Принимают неоптимальные архитектурные решения

**Решение**: Система-харнес ("упряжь") вокруг модели, которая:
- Ловит сломанные tool call и предлагает модели/пользователю исправленный вариант
- Детектирует циклы и принудительно перезапускает диалог с summary
- Управляет контекстом: промпт ≤ ⅓ окна, агрессивная суммаризация
- Даёт модели только релевантные инструменты и документацию под текущую задачу
- Разбивает работу на фазы (plan → docs → code → test → fix) с разными агентами
- Использует RAG/BM25 для подтягивания справки по библиотекам, bash, git
- Запускает LLM-as-Judge для ретроспективного анализа и генерации правил

---

## Сравнение с little-coder

| Характеристика | little-coder | tiny-agent |
|---|---|---|
| Целевой размер модели | 9B–35B | **0.5B–8B** (основная: 0.8B) |
| Эффективное окно | ~7K cold start, 16K–256K runtime | **2K–10K** (промпт ≤ ⅓ окна) |
| Tool call recovery | output-parser (5 форматов) + nudge | **Саб-агент для вызова + выбор Y/N + варианты** |
| Loop detection | 2 повтора → correction, без перегенерации | **3 повтора → суммаризация → новый чат** |
| Контекст-менеджмент | compaction (LLM-суммаризация) | **Скользящее окно + чеклист задач + авто-саммари** |
| Инжект знаний | skill-inject + knowledge-inject (score-based) | **RAG/BM25 гибридный поиск по docs + проекту** |
| Саб-агенты | dispatch (read-only, изолированные) | **Саб-агенты с выбором команды + подтверждение** |
| LLM-as-Judge | Нет | **Ретроспектива + генерация правил на лету** |
| Фронтенд | pi TUI (Node.js) | **Textual TUI (Python)** |
| Язык | TypeScript (Node.js) | **Python** |
| Модели провайдеров | pi-экосистема | **OpenAI-совместимый API (собственная обёртка)** |
| SDD-воркфлоу | Plan Mode (decompose → research → plan) | **Полный цикл: plan → docs → code → test → fix → docs** |
| Разделение агентов по ролям | Единый агент + plan mode | **Разные агенты: архитектор, планировщик, имплементатор, тестировщик** |

**Ключевые отличия, заимствованные из little-coder и адаптированные под микро-модели**:
- KV-cache preservation (tail messages вместо system prompt) — **критично** для 0.8B
- Read-before-edit invariant (механическое, а не промптом)
- Permission gate для bash (whitelist + разбор цепочек `&&`, `||`)
- Checkpoint файлов перед записью
- Контроль переполнения контекста одним Read-результатом (truncate)
- Детект shell-записей (`>`, `>>`, `tee`, `dd of=`)
- Нормализация путей (`/foo.md` → `cwd/foo.md`)

---

## Архитектура

### Обзор компонентов

```
tiny-agent/
├── app/                     # Ядро приложения
│   ├── __init__.py
│   ├── api.py               # OpenAI-совместимый клиент с обёрткой tool calling
│   ├── loop.py              # Главный agent loop
│   ├── context.py           # Сборка и управление контекстным окном
│   ├── subagent.py          # Саб-агент: выбор команды + подтверждение
│   ├── judge.py             # LLM-as-Judge: ретроспектива + генерация правил
│   ├── prompts/             # Конструкторы промптов
│   │   ├── architect.py     # Генерация архитектуры (SDD)
│   │   ├── planner.py       # Генерация задач
│   │   ├── implementer.py   # Имплементация кода (новый проект)
│   │   ├── patcher.py       # Имплементация кода (существующий проект)
│   │   └── reviewer.py      # Ревью сгенерированного кода
│   └── rag.py               # RAG/BM25 поиск по docs + проекту
├── agents/                  # Конфиги агентов (JSON)
│   ├── architect.json       # Промпт + инструменты архитектора
│   ├── planner.json         # Промпт + инструменты планировщика
│   ├── implementer.json     # Промпт + инструменты имплементатора
│   ├── tester.json          # Промпт + инструменты тестировщика
│   ├── reviewer.json        # Промпт + инструменты ревьюера
│   └── llm-as-judge.json    # Промпт для модели-судьи
├── tools/                   # Имплементация инструментов
│   ├── __init__.py
│   ├── base.py              # Базовый класс Tool
│   ├── registry.py          # Реестр + schema generation
│   ├── read_file.py         # Чтение файла (с ограничением)
│   ├── write_file.py        # Запись файла (с guard)
│   ├── edit_file.py         # Редактирование (read-before-edit)
│   ├── bash.py              # Терминал (с permission gate)
│   ├── git.py               # Git-операции
│   ├── glob.py              # Поиск файлов по паттерну
│   ├── grep.py              # Поиск по содержимому
│   ├── ls.py                # Листинг директории
│   ├── webfetch.py          # Загрузка URL
│   ├── websearch.py         # Веб-поиск
│   ├── dispatch.py          # Вызов саб-агента
│   ├── evidence.py          # Сохранение/получение evidence
│   ├── todo.py              # Управление чеклистом задач
│   └── skill_read.py        # Чтение навыка
├── skills/                  # Навыки (md-файлы, inject в промпт)
│   ├── tools/               # Карточки использования инструментов
│   │   ├── read.md
│   │   ├── write.md
│   │   ├── edit.md
│   │   ├── bash.md
│   │   └── ...
│   ├── knowledge/           # Шпаргалки: алгоритмы, паттерны
│   │   ├── singleton.md
│   │   ├── factory.md
│   │   ├── observer.md
│   │   └── ...
│   └── protocols/           # Протоколы работы
│       ├── research.md
│       ├── debug.md
│       └── sdd-workflow.md
├── docs/                    # Векторная/BM25 база документации
│   ├── python/              # Документация Python
│   ├── bash.md              # Справка bash
│   ├── powershell.md        # Справка PowerShell
│   ├── git.md               # Справка git
│   ├── patterns/            # Паттерны программирования
│   └── libraries/           # Документация популярных библиотек
├── rules/                   # Правила, сгенерированные LLM-as-Judge
├── front/                   # Textual TUI
│   ├── app.py               # Главное приложение
│   ├── widgets/             # Виджеты интерфейса
│   └── themes/              # Темы
├── config.json              # Глобальный конфиг моделей/API
├── .tiny-tools/             # Проектный конфиг (создаётся под каждый проект)
│   ├── config.json          # Настройки для конкретного проекта
│   ├── rules/               # Правила для этого проекта
│   └── index/               # Индекс проекта (векторный/BM25)
└── .plan.md                 # План проекта (этот документ)
```

### Agent Loop — цикл агента

```
┌─────────────────────────────────────────────────────────┐
│                    ПОЛЬЗОВАТЕЛЬСКИЙ ВВОД                  │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  1. CONTEXT PIPELINE — сборка промпта                    │
│     ├── ls/dir дерева проекта (≤500 токенов)             │
│     ├── SDD-файлы: ARCHITECTURE, TASKS, RULES            │
│     ├── Чеклист: текущая задача + выполненные             │
│     ├── RAG-выборка: релевантные документы под задачу      │
│     ├── Skills: карточки инструментов под ответ модели    │
│     ├── Rules: правила LLM-as-Judge (если есть)           │
│     ├── Summary предыдущего диалога (если был loop)       │
│     ├── Справка: bash/git/язык под текущую задачу         │
│     └── Пользовательский промпт                           │
│     → Итого ≤ ⅓ контекстного окна                         │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  2. MODEL CALL — вызов модели                            │
│     ├── Отправка assembled prompt                        │
│     ├── Стриминг ответа                                  │
│     └── Парсинг tool calls / текста                      │
└────────────────────────┬────────────────────────────────┘
                         ▼
              ┌──────────┴──────────┐
              │  Есть tool calls?    │
              └──────────┬──────────┘
                    Да   │   Нет (текст)
                         │       │
              ┌──────────▼──┐  ┌──▼──────────────────────┐
              │ 3. TOOL      │  │ Проверка: код в чате?    │
              │    EXECUTION │  │ → предложить записать     │
              └──────┬───────┘  │   в файл (Y/N)           │
                     │          └──────────────────────────┘
     ┌───────────────┼───────────────┐
     │               │               │
┌────▼────┐   ┌──────▼──────┐   ┌────▼────────────┐
│SUCCESS  │   │ERROR        │   │HALLUCINATED     │
│→ отдать │   │→ суб-агент  │   │TOOL             │
│результат│   │  предлагает │   │→ предложить      │
│модели   │   │  исправление│   │  похожий         │
│         │   │  (Y/N/вар-ы)│   │  инструмент      │
└────┬────┘   └──────┬──────┘   └────┬─────────────┘
     │               │               │
     └───────────────┼───────────────┘
                     ▼
┌─────────────────────────────────────────────────────────┐
│  4. GUARD CHECKS                                         │
│     ├── Loop detector: 3+ повтора → перегенерация        │
│     ├── Context watchdog: usage > 80% → compaction       │
│     ├── Turn cap: макс. N ходов → abort                  │
│     └── Quality monitor: пустой ответ, галлюцинации      │
└────────────────────────┬────────────────────────────────┘
                         ▼
           ┌─────────────────────────┐
           │  Задача выполнена?       │
           └──────────┬──────────────┘
              Нет     │   Да
              ┌───────▼──────┐    ┌──▼──────────────────┐
              │ → к шагу 1   │    │ Финальный ответ      │
              └──────────────┘    │ пользователю         │
                                  └──────────────────────┘
```

### Context Pipeline — что попадает в промпт

Каждый вызов модели получает промпт, собранный из следующих блоков (в порядке приоритета):

| # | Блок | Источник | Ограничение | Генеративный? |
|---|------|----------|-------------|---------------|
| 1 | **System Prompt** | `agents/{role}.json` | ≤ ⅓ от общего окна | Нет |
| 2 | **Дерево проекта** | `ls` / `dir` с фильтрацией | ≤ 500 токенов | Генеративный (ls) |
| 3 | **SDD-документы** | `ARCHITECTURE.md`, `TASKS.md`, `{SERVICE}_ARCHITECTURE.md` | Релевантные секции | Нет |
| 4 | **Чеклист** | Состояние задач (текущая + N выполненных) | Динамически | Генеративный |
| 5 | **RAG-выборка** | BM25 / векторный поиск по `docs/` + проект | ≤ 300 токенов | Генеративный |
| 6 | **Skills** | `skills/` — карточки под последний tool call | ≤ 300 токенов | Генеративный |
| 7 | **Rules** | `rules/` — правила LLM-as-Judge | Без лимита | Генеративный |
| 8 | **Справка** | bash/powershell/git/язык — под задачу | ≤ 200 токенов | Генеративный |
| 9 | **Summary** | Суммаризация предыдущего диалога (при loop) | ≤ 500 токенов | Генеративный |
| 10 | **User Prompt** | Ввод пользователя (возможно расширенный) | Оставшееся место | Нет |

**Ключевое правило**: `system_prompt_tokens ≤ context_window / 3`

**KV-Cache Preservation**: Блоки 2-9 доставляются как **tail messages** (в конец диалога, роль `user`), а не модифицируют system prompt. Это сохраняет KV-кеш — все предыдущие токены не пересчитываются заново. Дедупликация: если блок не изменился с прошлого хода, он не добавляется повторно.

---

## Компоненты

### app/ — ядро приложения

#### api.py — OpenAI-совместимый клиент

Собственная обёртка над OpenAI API с расширенной обработкой tool calling:

- **Не просто ошибка при невалидном вызове**: модель получает на выбор:
  - Y — выполнить предложенный исправленный вариант
  - N — показать 3-5 альтернативных вариантов вызова
- **Fallback**: если модель возвращает tool call текстом (fenced JSON, `<tool_call>`), парсим и предлагаем либо выполнить, либо исправить
- **Retry policy**: экспоненциальный backoff при сетевых ошибках

#### loop.py — главный агентный цикл

```python
class AgentLoop:
    def run(self, user_input: str) -> str:
        while not task_complete and turns < max_turns:
            context = self.context_builder.build(user_input, history, state)
            
            if context.too_large():
                context = self.compact(history)
            
            response = self.model.generate(context)
            
            if self.loop_detector.check(response):
                history = self.summarize_and_restart(history)
                continue
            
            if response.has_tool_calls():
                for tool_call in response.tool_calls:
                    result = self.execute_tool(tool_call)
                    history.append(result)
            else:
                if self.is_code_in_chat(response):
                    self.offer_write_to_file(response)
                else:
                    return response  # финальный ответ
```

#### context.py — управление контекстным окном

- **Сборка промпта** из блоков (см. Context Pipeline выше)
- **Агрессивная суммаризация**: при превышении 80% окна — суммаризировать диалог в ≤500 токенов
- **Compaction loop guard**: если после суммаризации usage всё ещё > 80% — пауза авто-компакшна, уведомление пользователю
- **Защита от оверфлоу одним read**: если результат Read > оставшегося места — обрезать до 30 строк + инструкция использовать grep/find

#### subagent.py — саб-агент

Паттерн: вместо прямого вызова инструмента моделью, саб-агент получает описание желаемого действия и:
1. Выбирает команду и аргументы
2. Показывает основной модели на подтверждение
3. При отказе (N) — предлагает 3+ варианта
4. Выполняет одобренный вариант
5. Возвращает результат основной модели

**Защита от циклов в саб-агенте**:
- 3 повторения одной и той же ошибки → перегенерация в новом чате с summary текущего диалога
- Лимит ходов саб-агента (отдельный от основного)

#### judge.py — LLM-as-Judge

Модель-судья (более сильная модель или та же с другой инструкцией):
1. **Ретроспектива**: после завершения задачи анализирует логи диалога
2. **Генерация правил**: если найдена повторяющаяся ошибка → создаёт правило в `rules/`
3. **Оценка качества**: выставляет score задаче
4. **Промпт и конфиг**: лежит в `agents/llm-as-judge.json`

#### prompts/ — конструкторы промптов

| Конструктор | Файл | Назначение |
|---|---|---|
| Архитектор | `architect.py` | Генерация SDD: ARCHITECTURE.md, STORIES.md |
| Планировщик | `planner.py` | Декомпозиция архитектуры на TASKS.md |
| Имплементатор (новый) | `implementer.py` | Генерация кода с нуля под SDD |
| Патчер (существующий) | `patcher.py` | Правка существующего кода под задачу |
| Ревьюер | `reviewer.py` | Проверка сгенерированного кода |

#### rag.py — RAG + BM25 поиск

- **BM25** (ранжирование): для CPU-only устройств, быстрый, без embedding-модели
- **Векторный поиск** (опционально): embedding через легковесную модель (all-MiniLM-L6-v2) + FAISS
- **Гибридный режим**: BM25 + векторный с весами
- **Коллекции**: каждая папка в `docs/` → отдельная коллекция; проект → коллекция
- **Индексация**: при старте для `docs/`, при первом запуске на проекте для самого проекта

### agents/ — конфиги агентов

Каждый JSON-файл определяет:

```json
{
  "name": "architect",
  "description": "Генерирует архитектуру проекта по SDD",
  "system_prompt": "...",
  "tools": ["read_file", "write_file", "ls", "glob", "grep", "webfetch"],
  "allowed_tools": ["read_file", "write_file", "ls", "glob", "grep", "webfetch"],
  "context_budget": {
    "system_prompt_max_tokens": 1024,
    "skills_max_tokens": 200,
    "rag_max_tokens": 300
  },
  "max_turns": 40,
  "temperature": 0.3,
  "loop_detection": {
    "max_repeats": 3,
    "action": "summarize_and_restart"
  },
  "tool_execution": "subagent",  // "direct" | "subagent"
  "skills": ["sdd-workflow", "research", "cite"],
  "auto_mode": false  // true = без подтверждения пользователя
}
```

**Поля которые можно менять**:
- `tools` — доступные инструменты
- `system_prompt` — инструкция
- `context_budget` — лимиты блоков
- `max_turns` — макс. ходов
- `skills` — навыки для инжекта

Пользователь может добавлять свои JSON-файлы с произвольными ролями.

### tools/ — имплементация инструментов

Каждый инструмент — класс, наследующий `BaseTool`:

```python
class BaseTool:
    name: str
    description: str
    parameters: dict  # JSON Schema
    
    def execute(self, **kwargs) -> ToolResult: ...
    def guard(self, **kwargs) -> bool | str: ...  # pre-check
```

**Список инструментов**:

| Инструмент | Guard | Описание |
|---|---|---|
| `read_file` | read-guard (truncate) | Чтение файла с авто-усечением |
| `write_file` | write-guard (exists, reserved names) | Создание/перезапись файла |
| `edit_file` | read-before-edit guard | Замена текста в файле |
| `bash` | permission-gate (whitelist, chain-split) | Выполнение shell-команды |
| `git` | permission-gate | Git-операции (log, status, diff, ...) |
| `glob` | — | Поиск файлов по паттерну |
| `grep` | — | Поиск по содержимому |
| `ls` | — | Листинг директории |
| `webfetch` | url-validation | Загрузка веб-страницы |
| `websearch` | — | Веб-поиск |
| `dispatch` | turn-cap | Вызов саб-агента |
| `evidence_add` | — | Сохранение найденной информации |
| `evidence_get` | — | Получение сохранённой информации |
| `evidence_list` | — | Список сохранённых evidence |
| `todo_update` | — | Обновление чеклиста задач |
| `skill_read` | — | Чтение навыка из `skills/` |

**Permission Gate для bash**:
- Whitelist безопасных префиксов: `ls`, `cat`, `head`, `tail`, `grep`, `find`, `git`, `python`, `node`, `pip`, `npm`, `cargo`, `go`, `cp`, `mv`, `mkdir`, `touch`, `echo`, `pwd`, `wc`
- Разбор цепочек (`&&`, `||`, `;`, `|`): **каждый сегмент проверяется отдельно**
- Детект shell-записей: `>`, `>>`, `tee`, `dd of=` — **всегда rejected**, пиши через `write_file`
- `rm`, `sudo`, `chmod`, `chown` — отсутствуют в whitelist намеренно
- `LITTLE_CODER_BASH_ALLOW` для пользовательских префиксов

**Write Guard**:
- Нормализация: `/foo.md` → `{cwd}/foo.md`
- Reserved device names (Windows): `CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`
- Существующий файл → отказ с предложением Edit

**Read-before-Edit Guard**:
- Edit блокируется если файл не был прочитан в текущей сессии
- Read/Write автоматически регистрируют файл как "прочитанный"

### skills/ — навыки

MD-файлы с YAML-frontmatter:

```markdown
---
target_tool: Read
token_cost: 85
keywords: [read, show, view, cat, open, file, content]
---

## Read

Используй `read_file` для чтения содержимого файла.

- **Путь**: всегда относительно корня проекта
- **Если файл большой**: используй `grep` для поиска нужных строк, затем `read_file` с `offset`/`limit`
- **НИКОГДА** не предполагай содержимое файла, не прочитав его
```

**Механика инжекта** (на каждом ходу):
1. **Error recovery**: если предыдущий tool call провалился → skill card этого инструмента приоритетно
2. **Recency**: последние 4 использованных инструмента → их skill cards
3. **Intent**: keyword matching по тексту пользователя → предсказанные инструменты
4. **Budget guard**: суммарно ≤ `skills_max_tokens`

### docs/ — документация

Файлы MD, которые при старте приложения/сервиса индексируются в BM25/векторную БД:

```
docs/
├── python/
│   ├── stdlib.md           # Стандартная библиотека
│   ├── asyncio.md          # Асинхронность
│   └── typing.md           # Система типов
├── bash.md                 # Справка по bash
├── powershell.md           # Справка по PowerShell
├── git.md                  # Справка по git
├── patterns/
│   ├── singleton.md
│   ├── factory.md
│   ├── repository.md
│   └── ...
├── libraries/
│   ├── fastapi.md
│   ├── sqlalchemy.md
│   └── ...
└── languages/
    ├── typescript.md
    ├── rust.md
    └── ...
```

Пользователь может добавлять свои MD-файлы. Каждая подпапка становится поисковой коллекцией.

**Индексация проекта**: при наличии проекта, его файлы также индексируются. Модель может искать релевантный код через RAG/BM25.

### rules/ — правила LLM-as-Judge

После каждой задачи LLM-as-Judge анализирует логи. Если находит паттерн ошибок — создаёт правило:

```markdown
---
created: 2026-08-04
trigger: "модель пишет код в чат вместо write_file"
priority: high
scope: implementer
---
## Правило: всегда использовать write_file для кода

Если модель генерирует больше 5 строк кода в текстовом ответе — это ошибка.
Код должен записываться через инструмент `write_file`.
```

Правила инжектятся в промпт при следующих запусках.

### front/ — Textual TUI

Терминальный интерфейс на [Textual](https://textual.textualize.io/):

- Панель ввода (prompt)
- История диалога (scrollable)
- Статус-бар: модель, токены, прогресс
- Панель саб-агентов (live tracker)
- Горячие клавиши:
  - `Ctrl+Q` — Plan Mode
  - `Ctrl+H` — справка по клавишам
  - `Ctrl+O` — развернуть вывод инструмента
  - `Ctrl+T` — переключить показ thinking
  - `Ctrl+P` — сменить модель
  - `Ctrl+C` — прервать выполнение
- Сессии: создание, именование, переключение (`/resume`)
- Режимы: автономный / с подтверждением

---

## Подсистемы

### Управление контекстным окном

**Проблема микро-моделей**: окно 2K–10K токенов, из которых ~30% уже занято системным промптом.

**Стратегия**:

1. **Контроль на входе**: сумма токенов всех блоков ≤ 70% окна (⅓ промпт + ⅓ история + ⅓ резерв)
2. **KV-Cache Preservation**: инжект-блоки как tail messages (конец диалога), а не system prompt. Меняется только хвост — префикс остаётся в кеше llama.cpp
3. **Truncate read**: результат Read > 30% окна → обрезается до 30 строк + инструкция
4. **Compaction**: при 80% заполнения — LLM-суммаризация диалога в ≤500 токенов
5. **Compaction Loop Guard**: после суммаризации, если usage всё ещё > 80% → пауза (окно слишком мало для задачи)
6. **Loop → Restart**: 3 повтора → сохранение summary + очистка диалога + перегенерация с тем же промптом
7. **ls/dir ограничение**: дерево проекта ≤ 500 токенов (фильтрация .gitignore, бинарные, >N файлов → только директории)

### Tool Calling — вызов инструментов

**Уровни защиты** (от дешёвых к дорогим):

| Уровень | Метод | Когда срабатывает | Стоимость |
|---|---|---|---|
| 1. Прямой вызов | Модель → tool | Модель вернула валидный tool_call | Нулевая |
| 2. Text Parser | Парсинг текста (fenced JSON, `<tool_call>`) | Нет нативных tool_calls | ~10 токенов на парсинг |
| 3. Similarity Match | Похожесть имени на известные tools | Инструмент не найден в реестре | ~50 токенов |
| 4. Sub-agent Suggest | Саб-агент предлагает исправление | Ошибка валидации аргументов | ~200 токенов |
| 5. User Choice | Пользователь выбирает из вариантов | Саб-агент не смог / ручной режим | ~50 токенов + UX |

**Процесс**:
```
Model output → [Native tool_call?] → execute → guard → result
                    ↓ No
            [Text-encoded call?] → parse → "Execute corrected? (Y/N/Options)"
                    ↓ No
            [Hallucinated name?] → similarity match → "Did you mean: X? (Y/N/Options)"
                    ↓ No
            [Code in chat?] → "Write this to file? (Y/N)"
                    ↓ No
            → Return text as-is
```

### Саб-агенты

Архитектура вызова инструмента через саб-агента (конфигурируется в `agents/{role}.json` → `tool_execution: "subagent"`):

```
Основная модель:
  "Я хочу прочитать файл src/main.py"
            ↓
Саб-агент (свежий контекст):
  "Инструмент: read_file
   Аргументы: path='src/main.py'
   Причина: основная модель хочет прочитать главный файл"
            ↓
Основная модель получает предложение:
  "Execute: read_file('src/main.py')? [Y] / [N — show options] / [Edit args]"
            ↓
  Y → выполнить
  N → саб-агент предлагает 3-5 вариантов
  Edit → ручная правка аргументов
```

**Изоляция саб-агента**:
- Отдельный контекст (не засоряет основной)
- Ограниченный набор инструментов (read-only по умолчанию)
- Лимит ходов (5-10)
- Свой loop detection
- Результат возвращается как сжатый отчёт

### RAG и BM25

**Два режима**:
1. **BM25 (ранжирование)** — для слабых устройств, не требует GPU
   - TF-IDF с BM25-скором
   - Быстрая индексация при старте
   - Нет embedding-модели
2. **Векторный + BM25 (гибрид)** — для устройств с GPU или нормальным CPU
   - Embedding: all-MiniLM-L6-v2 (80MB) через sentence-transformers
   - Индекс: FAISS (CPU) или hnswlib
   - Поиск: комбинация BM25 + cosine similarity с настраиваемыми весами

**Что индексируется**:
- `docs/` — все MD-файлы документации
- Проект (опционально) — файлы кода (`.py`, `.js`, `.ts`, `.rs`, `.go`, ...)

**Когда вызывается**:
- Перед каждым ходом модели: поиск по тексту последнего ответа модели + пользовательского промпта
- Для генерации bash/git справки: поиск по `bash.md` / `git.md` с запросом из предполагаемой команды

### LLM-as-Judge и генерация правил

**Конфиг**: `agents/llm-as-judge.json`

**Процесс**:
1. После завершения задачи (или при ручном запуске `/judge`)
2. Модель-судья получает полный лог диалога
3. Анализирует:
   - Были ли ошибки tool calling
   - Зацикливалась ли модель
   - Галлюцинировала ли методы/параметры
   - Выполнила ли задачу полностью
   - Оптимален ли результат
4. Выставляет score (0-100)
5. Если найдены повторяющиеся ошибки → генерирует правило (MD) в `rules/`
6. Правило инжектится в промпт при следующих запусках

**Правила применяются**:
- Глобально: `rules/*.md`
- На проект: `.tiny-tools/rules/*.md`

### SDD-воркфлоу (Plan → Docs → Code → Test → Fix)

```
┌──────────────────────────────────────────┐
│  PHASE 1: ARCHITECTURE                   │
│  Agent: architect                        │
│  Input: пользовательское описание        │
│  Output: ARCHITECTURE.md                 │
│           {SERVICE}_ARCHITECTURE.md       │
│           STORIES.md                      │
│           RULES.md                        │
│  Tools: read_file, write_file, webfetch  │
└──────────────┬───────────────────────────┘
               ▼
┌──────────────────────────────────────────┐
│  PHASE 2: PLANNING                       │
│  Agent: planner                          │
│  Input: ARCHITECTURE + STORIES           │
│  Output: TASKS.md (декомпозиция)         │
│  Tools: read_file, write_file            │
└──────────────┬───────────────────────────┘
               ▼
┌──────────────────────────────────────────┐
│  PHASE 3: IMPLEMENTATION (цикл по TASKS) │
│  Agent: implementer / patcher            │
│  Input: TASK + ARCHITECTURE + RAG        │
│  Output: код                             │
│  Tools: read_file, write_file, edit_file,│
│         bash, glob, grep, ls             │
└──────────────┬───────────────────────────┘
               ▼
┌──────────────────────────────────────────┐
│  PHASE 4: TESTING                        │
│  Agent: tester                           │
│  Input: TASK + код                       │
│  Output: test results + bugs             │
│  Tools: read_file, bash, glob, grep      │
└──────────────┬───────────────────────────┘
               ▼
┌──────────────────────────────────────────┐
│  PHASE 5: FIX (если тесты упали)         │
│  Agent: implementer / patcher            │
│  Input: bug report + код                 │
│  Output: исправленный код                │
│  → цикл обратно на PHASE 4               │
└──────────────┬───────────────────────────┘
               ▼
┌──────────────────────────────────────────┐
│  PHASE 6: DOCUMENTATION                  │
│  Agent: reviewer                         │
│  Input: финальный код                    │
│  Output: обновлённые SDD-документы       │
│          обновлён {SERVICE}_ARCHITECTURE  │
└──────────────────────────────────────────┘
```

**Для существующего проекта**:
1. Планировщик анализирует существующий код (RAG по проекту)
2. Генерирует SDD-документы на основе найденного
3. Патчер работает с существующими файлами (edit, а не write)

---

## Конфигурация

### Модели

`config.json` в корне проекта:

```json
{
  "default_model": "qwen-0.8b",
  "models": [
    {
      "name": "qwen-0.8b",
      "provider": "llamacpp",
      "model": "qwen-3.5-0.8b",
      "endpoint": "http://127.0.0.1:8080/v1",
      "api_key_env": null,
      "context_window": 8192,
      "max_tokens": 2048
    },
    {
      "name": "gemma4-26b",
      "provider": "gemini",
      "model": "gemma-4-26b-a4b-it",
      "endpoint": null,
      "api_key_env": "GOOGLE_API"
    },
    {
      "name": "groq-llama-8b",
      "provider": "groq",
      "model": "llama-3.1-8b-instant",
      "endpoint": null,
      "api_key_env": "GROQ_API"
    }
  ]
}
```

### Настройки проекта

`.tiny-tools/config.json` (создаётся в корне каждого проекта):

```json
{
  "model": "qwen-0.8b",
  "auto_mode": false,
  "search_mode": "bm25",
  "tool_execution": "subagent",
  "hidden_mode": false,
  "context_budget": {
    "system_prompt_max_tokens": 2048,
    "ls_max_tokens": 500,
    "rag_max_tokens": 300,
    "skills_max_tokens": 300,
    "summary_max_tokens": 500
  },
  "sdd": {
    "enabled": true,
    "path": "docs/sdd"
  },
  "rag": {
    "include_project": true,
    "project_extensions": [".py", ".js", ".ts", ".rs", ".go"],
    "hybrid_weight_bm25": 0.3,
    "hybrid_weight_vector": 0.7
  },
  "llm_as_judge": {
    "enabled": true,
    "model": "groq-llama-8b",
    "auto_trigger": "on_task_complete"
  }
}
```

### Режимы работы

| Режим | Описание |
|---|---|
| **Автономный** (`auto_mode: true`) | Все действия без подтверждения пользователя |
| **С подтверждением** (`auto_mode: false`) | Каждый tool call / решение требует Y/N |
| **Скрытый** (`hidden_mode: true`) | Все артефакты в `./.tiny-tools/` |
| **Открытый** (`hidden_mode: false`) | SDD-документы и правила в корне проекта |
| **Subagent tools** (`tool_execution: "subagent"`) | Инструменты вызываются через саб-агента |
| **Direct tools** (`tool_execution: "direct"`) | Модель вызывает инструменты напрямую |
| **BM25 only** (`search_mode: "bm25"`) | Только ранжированный поиск |
| **Hybrid** (`search_mode: "hybrid"`) | Векторный + BM25 |
| **Plan Mode** (Ctrl+Q) | Исследование → план без правки файлов |

---

## Структура проекта

```
tiny-agent/
├── app/                       # Ядро приложения
│   ├── __init__.py
│   ├── main.py                # Точка входа
│   ├── api.py                 # OpenAI-клиент
│   ├── loop.py                # Agent loop
│   ├── context.py             # Context builder
│   ├── subagent.py            # Саб-агент
│   ├── judge.py               # LLM-as-Judge
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── architect.py
│   │   ├── planner.py
│   │   ├── implementer.py
│   │   ├── patcher.py
│   │   └── reviewer.py
│   └── rag.py                 # RAG/BM25
├── agents/                    # Конфиги агентов (JSON)
│   ├── architect.json
│   ├── planner.json
│   ├── implementer.json
│   ├── tester.json
│   ├── reviewer.json
│   └── llm-as-judge.json
├── tools/                     # Инструменты
│   ├── __init__.py
│   ├── base.py
│   ├── registry.py
│   ├── read_file.py
│   ├── write_file.py
│   ├── edit_file.py
│   ├── bash.py
│   ├── git.py
│   ├── glob.py
│   ├── grep.py
│   ├── ls.py
│   ├── webfetch.py
│   ├── websearch.py
│   ├── dispatch.py
│   ├── evidence.py
│   ├── todo.py
│   ├── skill_read.py
│   └── guards/
│       ├── __init__.py
│       ├── permission.py      # Bash whitelist + chain-split
│       ├── write_guard.py     # Write: exists, reserved, normalize
│       ├── read_guard.py      # Read: truncate overflow
│       ├── edit_guard.py      # Edit: read-before-edit
│       └── shell_write.py     # Detect >, >>, tee, dd of=
├── skills/                    # Навыки (MD)
│   ├── tools/
│   │   ├── read.md
│   │   ├── write.md
│   │   ├── edit.md
│   │   ├── bash.md
│   │   ├── glob.md
│   │   ├── grep.md
│   │   ├── ls.md
│   │   ├── dispatch.md
│   │   └── todo.md
│   ├── knowledge/
│   │   ├── singleton.md
│   │   ├── factory.md
│   │   ├── observer.md
│   │   └── ...
│   └── protocols/
│       ├── research.md
│       ├── debug.md
│       └── sdd-workflow.md
├── docs/                      # Документация (RAG)
│   ├── python/
│   ├── bash.md
│   ├── powershell.md
│   ├── git.md
│   ├── patterns/
│   ├── libraries/
│   └── languages/
├── rules/                     # Правила LLM-as-Judge
├── front/                     # Textual TUI
│   ├── __init__.py
│   ├── app.py
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── chat.py            # История диалога
│   │   ├── input.py           # Панель ввода
│   │   ├── status.py          # Статус-бар
│   │   ├── subagents.py       # Трекер саб-агентов
│   │   └── hotkeys.py         # Справка по клавишам
│   └── themes/
├── config.json                # Глобальный конфиг
├── .tiny-tools/               # Проектный конфиг (создаётся авто)
│   ├── config.json
│   ├── rules/
│   └── index/
├── requirements.txt
├── setup.py / pyproject.toml
├── README.md
├── .plan.md
└── .gitignore
```

---

## Установка и запуск

### Требования

- Python 3.11+
- Для локальной модели: llama.cpp (llama-server) или Ollama
- Windows / Linux / macOS

### Установка

```bash
git clone https://github.com/user/tiny-agent.git
cd tiny-agent
python -m venv .venv
.venv\Scripts\activate        # Windows (или source .venv/bin/activate)
pip install -r requirements.txt
```

### Запуск локальной модели

```bash
# llama.cpp (сервер должен быть запущен на http://127.0.0.1:8080)
llama-server -m /path/to/Qwen3.5-0.8B-Q5_K_M.gguf \
  --host 127.0.0.1 --port 8080 \
  -c 65536 -ngl 99
```

> ⚠️ **Важно**: Qwen3.5 — reasoning-модель. tiny-agent отключает thinking через
> `chat_template_kwargs: {"enable_thinking": false}`, иначе весь бюджет токенов уходит в размышления.

### Запуск tiny-agent

```bash
# Интерактивный режим в текущей папке (создаётся .tiny-agent/)
python app/main.py

# Работа в другом проекте
python app/main.py --cwd /path/to/project

# Роль агента: coder | architect | planner | implementer | tester | reviewer
python app/main.py --cwd /path/to/project --agent architect

# Одноразовый промпт (non-interactive)
python app/main.py --cwd /path/to/project -p "Create ARCHITECTURE.md for..."

# Список моделей и ролей
python app/main.py --list-models
python app/main.py --list-agents
```

При первом запуске в целевой папке создаётся `.tiny-agent/` с `config.json` и `rules/`.
LLM-as-judge подключается автоматически, если в `config.json` есть облачная модель с ключом в env.

---

## Roadmap / План разработки

### Фаза 1: Минимальный жизнеспособный агент (MVP) — ✅ выполнено
- [x] `app/api.py` — OpenAI-клиент с кастомной обработкой tool calling
- [x] `tools/` — 7 инструментов: read_file, write_file, edit_file, bash, ls, glob, grep
- [x] `app/loop.py` — agent loop с анти-цикловыми защитами
- [x] `app/context.py` — сборка контекста (tail messages, KV-cache, дедупликация)
- [x] `front/` — минимальный TUI (prompt_toolkit, non-TTY fallback)
- [x] `config.json` — конфигурация моделей (llama.cpp, Groq, Cerebras, Gemini)
- [x] **Критерий**: модель 0.8B читает файл и отвечает на вопрос о нём

### Фаза 2: Tool Calling Recovery — ✅ выполнено (базово)
- [x] Text parser для fenced JSON / `<tool_call>` (app/api.py)
- [x] Similarity match для hallucinated tool names (difflib)
- [x] `app/subagent.py` — субагент-корректор с RAG-справкой
- [x] Guard-ы: write-guard, read-guard, edit-guard, permission-gate
- [x] Loop detector (window-based) + path-blacklist + text-repetition
- [x] Idempotency-guard для write/edit + read-repeat-guard
- [x] Двухфазная генерация артефактов (модель → текст → харнес → файл)
- [ ] Loop detector (3 повтора → restart)
- [ ] **Критерий**: модель восстанавливается после сломанных tool calls в 80% случаев

### Фаза 3: Контекст-менеджмент и Skills
- [ ] KV-cache preservation (tail messages)
- [ ] Compaction (LLM-суммаризация)
- [ ] Compaction loop guard
- [ ] Skills injection system (error → recency → intent)
- [ ] `skills/tools/` — карточки всех инструментов
- [ ] **Критерий**: агент работает на окне 4K без деградации

### Фаза 4: RAG, Документация и Саб-агенты
- [ ] `app/rag.py` — BM25 индексация и поиск
- [ ] `docs/` — наполнение документации (bash, git, python, patterns)
- [ ] Индексация проекта
- [ ] Саб-агенты с выбором команды + подтверждением
- [ ] Защита от циклов в саб-агенте
- [ ] **Критерий**: модель использует RAG для поиска документации при ошибках

### Фаза 5: SDD-воркфлоу
- [ ] `app/prompts/architect.py` — генерация архитектуры
- [ ] `app/prompts/planner.py` — декомпозиция на задачи
- [ ] `app/prompts/implementer.py` — имплементация с нуля
- [ ] `app/prompts/patcher.py` — правка существующего кода
- [ ] `app/prompts/reviewer.py` — ревью
- [ ] Агенты в `agents/` с разными наборами инструментов
- [ ] **Критерий**: сквозной проход plan → docs → code → test → fix

### Фаза 6: LLM-as-Judge и Правила
- [ ] `app/judge.py` — ретроспективный анализ
- [ ] Генерация правил в `rules/`
- [ ] Инжект правил в промпт
- [ ] Score-трекинг по задачам
- [ ] **Критерий**: качество ответов модели улучшается от задачи к задаче

### Фаза 7: Полноценный TUI и Production-ready
- [ ] Полноценный Textual интерфейс (сессии, hotkeys, статус-бар)
- [ ] Автономный / ручной режимы
- [ ] Скрытый / открытый режимы
- [ ] `.tiny-tools/` — проектная конфигурация
- [ ] Векторный поиск (гибридный режим)
- [ ] Интеграция с разными провайдерами
- [ ] **Критерий**: можно использовать как daily-driver для программирования

---

## Corner Cases и риски

### Технические риски

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| **Модель 0.8B не держит формат tool call вообще** | Высокая | Критическое | Text parser + subagent для ВСЕХ вызовов |
| **2K окна не хватает даже на промпт + 1 ход** | Средняя | Высокое | Агрессивный truncate, минимальный system prompt |
| **Саб-агент зацикливается сам** | Высокая | Среднее | Жёсткий turn cap (5) + loop detection |
| **KV-cache сбрасывается на Windows** | Средняя | Среднее | Тестировать на llama.cpp Windows |
| **Textual TUI тормозит на слабых машинах** | Средняя | Низкое | async-стриминг, минимум виджетов |
| **BM25 не находит релевантные документы** | Средняя | Среднее | N-gram индексация, синонимы, расширение запроса моделью |
| **LLM-as-Judge генерирует бесполезные правила** | Высокая | Низкое | Фильтр по score < 50, лимит правил, ручная модерация |

### Поведенческие corner cases

1. **Модель пишет код в чат вместо write_file**
   - Детект: эвристика (3+ строки с отступами → предлагать записать)
   - Можно детектить через отдельный вызов модели с классификационной инструкцией

2. **Модель вызывает Edit для несуществующего файла**
   - Edit guard: проверка существования перед вызовом
   - Предложить Write вместо Edit (как little-coder)

3. **Модель пытается писать в `/dev/null` или `NUL`**
   - Reserved device names guard (Windows + Unix)
   - `/dev/null` разрешён только для `2>/dev/null`

4. **Модель не понимает что задача выполнена и продолжает**
   - Чеклист в промпте: галочки у выполненных задач
   - Turn cap как последняя защита

5. **Модель игнорирует guard-сообщения и повторяет ошибку**
   - 2 последовательных guard-отказа → force redirect (не даём повторить)
   - 3 отказа → abort + restart с summary

6. **Пользователь вводит очень короткий промпт ("пофикси баг")**
   - Планировщик расширяет: анализ проекта + уточняющие вопросы (Y/N + свой вариант)
   - Без понимания контекста → отказаться с запросом уточнения

7. **RAG возвращает нерелевантный результат из-за плохого запроса**
   - Модель формулирует поисковый запрос → RAG → результат
   - Если модель говорит "это не то" → переформулировка запроса

8. **Модель и саб-агент разошлись во мнениях (основная не принимает варианты)**
   - 3 цикла → эскалация к пользователю / LLM-as-Judge
   - Запись в лог для анализа

9. **Сетевая ошибка при вызове cloud API**
   - Retry: экспоненциальный backoff (1s → 2s → 4s → 8s)
   - После 3 неудач → fail с сообщением пользователю

10. **llama-server упал во время выполнения**
    - Health-check перед каждым вызовом
    - Авто-переподключение
    - Сохранение состояния для восстановления

### Метрики успеха

| Метрика | Цель MVP | Цель v1.0 |
|---|---|---|
| Tool call success rate (0.8B) | > 60% | > 85% |
| Tool call success rate (8B) | > 85% | > 95% |
| Loop recovery rate | > 70% | > 90% |
| Задач выполненных без перезапуска | > 50% | > 80% |
| Токенов на ход (оверхед системы) | < 500 | < 300 |
| Среднее время ответа (локально) | < 30s | < 15s |

---

## Лицензия

Apache License v2.0
