# 03 · Архитектура

## C1 · Контекст

```mermaid
flowchart LR
  User[Посетитель] --> App[Доступный город]
  App --> Data[Синтетический каталог]
```

Реальный источник не подтверждён.

## C2 · Контейнеры

```mermaid
flowchart LR
  Browser[Веб-интерфейс] --> Adapter[Адаптер данных]
  Adapter --> Files[mocks/fixtures]
```

Для MVP допустим адаптер, читающий локальные JSON-файлы. Отдельный сервер и база данных не обязательны. Если ИИ реализует HTTP-заглушку, она должна соблюдать `03_contracts/openapi.yaml`.

## C3 · Компоненты

```mermaid
flowchart TD
  UI[Экран каталога] --> Filter[Фильтры]
  UI --> Detail[Карточка]
  Filter --> Catalog[Сервис каталога]
  Detail --> Catalog
  Catalog --> Data[Адаптер фикстур]
```

## Модель данных

```mermaid
erDiagram
  PLACE {
    string id
    string name
    string district
    string address
    string entrance_status
    string entrance_description
    string updated_at
    string source
  }
```

ER показывает логическую сущность, а не обязательную базу. `source` всегда `demo`. C4 опущена: структура кода ещё не выбрана.

## Решения

- Исходные данные — неизменяемые JSON-файлы; фильтрация и отображение реализуются в продукте.
- Не создавать внешние интеграции и аккаунты для учебного прототипа.
- Механизм запуска ошибки источника должен быть описан в README.
