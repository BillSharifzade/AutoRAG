"""The data every part of the testbench serves: one pharmacy chain.

The point of a testbench is that two runs answer the same question the same
way, so nothing here is random at call time — a fixed seed builds the rows
once and the mock API, Postgres, MySQL and the SQLite file all serve *that*.
A number a tester sees in chat can then be checked by hand.

The domain is deliberately the user's own: a Tajik pharmacy chain, Russian
names, som prices, a prescription flag and a salary column — enough for the
data plane (aggregate over sales), the knowledge plane (a schema description
worth reading) and RBAC (salaries are not for everyone).
"""

from __future__ import annotations

import datetime as dt
import random

SEED = 7
START = dt.date(2025, 1, 1)
END = dt.date(2026, 8, 31)

CITIES = ("Душанбе", "Худжанд", "Бохтар", "Куляб")

STORES = [
    (1, "Аптека №1 «Центральная»", "Душанбе", "ул. Рудаки 42", "2019-04-15", "Азиза Рахимова"),
    (2, "Аптека №2 «Сино»", "Душанбе", "пр. Сомони 17", "2020-09-01", "Фаррух Назаров"),
    (3, "Аптека №3 «Исмоили»", "Душанбе", "ул. Айни 108", "2022-02-20", "Мадина Юсупова"),
    (4, "Аптека №4 «Сугд»", "Худжанд", "ул. Ленина 5", "2021-06-11", "Джамшед Karimov"),
    (5, "Аптека №5 «Вахш»", "Бохтар", "ул. Дружбы 63", "2023-03-05", "Нилуфар Саидова"),
    (6, "Аптека №6 «Хатлон»", "Куляб", "ул. Борбад 9", "2024-11-18", "Рустам Шарипов"),
]

# (id, name, category, form, price in somoni, prescription only)
PRODUCTS = [
    (1, "Парацетамол 500 мг", "Анальгетики", "таблетки", 4.50, False),
    (2, "Ибупрофен 400 мг", "Анальгетики", "таблетки", 9.80, False),
    (3, "Анальгин 500 мг", "Анальгетики", "таблетки", 3.20, False),
    (4, "Кеторол 10 мг", "Анальгетики", "таблетки", 21.00, True),
    (5, "Нурофен для детей", "Анальгетики", "суспензия", 34.50, False),
    (6, "Амоксициллин 500 мг", "Антибиотики", "капсулы", 27.40, True),
    (7, "Азитромицин 500 мг", "Антибиотики", "таблетки", 41.90, True),
    (8, "Цефтриаксон 1 г", "Антибиотики", "порошок", 18.60, True),
    (9, "Ципрофлоксацин 500 мг", "Антибиотики", "таблетки", 23.10, True),
    (10, "Доксициклин 100 мг", "Антибиотики", "капсулы", 15.70, True),
    (11, "Витамин C 1000 мг", "Витамины", "шипучие таблетки", 29.00, False),
    (12, "Витамин D3 2000 МЕ", "Витамины", "капли", 48.30, False),
    (13, "Магний B6", "Витамины", "таблетки", 55.90, False),
    (14, "Мультивитамины «Актив»", "Витамины", "таблетки", 62.00, False),
    (15, "Железо + фолиевая кислота", "Витамины", "таблетки", 37.40, False),
    (16, "Эналаприл 10 мг", "Сердечно-сосудистые", "таблетки", 12.80, True),
    (17, "Амлодипин 5 мг", "Сердечно-сосудистые", "таблетки", 16.20, True),
    (18, "Бисопролол 5 мг", "Сердечно-сосудистые", "таблетки", 19.50, True),
    (19, "Аторвастатин 20 мг", "Сердечно-сосудистые", "таблетки", 44.00, True),
    (20, "Кардиомагнил 75 мг", "Сердечно-сосудистые", "таблетки", 31.60, False),
    (21, "Метформин 850 мг", "Эндокринология", "таблетки", 22.70, True),
    (22, "Гликлазид 60 мг", "Эндокринология", "таблетки", 39.80, True),
    (23, "Тест-полоски для глюкометра", "Эндокринология", "расходники", 148.00, False),
    (24, "Инсулиновые шприцы U-100", "Эндокринология", "расходники", 26.50, False),
    (25, "Лоратадин 10 мг", "Аллергология", "таблетки", 11.90, False),
    (26, "Цетиризин 10 мг", "Аллергология", "таблетки", 14.30, False),
    (27, "Назальный спрей «Аква»", "Аллергология", "спрей", 33.20, False),
    (28, "Омепразол 20 мг", "Гастроэнтерология", "капсулы", 17.80, False),
    (29, "Смекта", "Гастроэнтерология", "порошок", 25.40, False),
    (30, "Активированный уголь", "Гастроэнтерология", "таблетки", 2.90, False),
    (31, "Регидрон", "Гастроэнтерология", "порошок", 13.50, False),
    (32, "Мазь «Левомеколь»", "Дерматология", "мазь", 19.90, False),
    (33, "Крем «Бепантен»", "Дерматология", "крем", 58.70, False),
    (34, "Хлоргексидин 0,05%", "Дерматология", "раствор", 8.40, False),
    (35, "Бинт стерильный 5 м", "Гигиена", "перевязка", 6.20, False),
    (36, "Маска медицинская (50 шт)", "Гигиена", "расходники", 42.00, False),
    (37, "Перчатки нитриловые (100 шт)", "Гигиена", "расходники", 96.00, False),
    (38, "Термометр электронный", "Гигиена", "прибор", 74.50, False),
    (39, "Тонометр автоматический", "Гигиена", "прибор", 385.00, False),
    (40, "Пластырь бактерицидный (20 шт)", "Гигиена", "перевязка", 10.60, False),
]

ROLES = ("Провизор", "Фармацевт", "Кассир", "Заведующий")

_FIRST = ("Азиза", "Фаррух", "Мадина", "Джамшед", "Нилуфар", "Рустам", "Зарина",
          "Бахтиёр", "Сабрина", "Далер", "Гулнора", "Шерали", "Малика", "Умед",
          "Фируза", "Искандар", "Дилноза", "Комрон", "Ситора", "Хуршед")
_LAST = ("Рахимов", "Назаров", "Юсупов", "Каримов", "Саидов", "Шарипов",
         "Мирзоев", "Холов", "Сафаров", "Иброхимов")


def _full_name(rng: random.Random) -> str:
    first = rng.choice(_FIRST)
    last = rng.choice(_LAST)
    # crude but consistent feminine ending, so the names read naturally
    if first.endswith(("а", "я")):
        last += "а"
    return f"{first} {last}"


def build() -> dict[str, list[tuple]]:
    """Every table, as plain row tuples in column order."""
    rng = random.Random(SEED)

    employees = []
    for i in range(1, 31):
        store = (i - 1) % len(STORES) + 1
        role = ROLES[i % len(ROLES)]
        hired = START - dt.timedelta(days=rng.randint(30, 1800))
        salary = {"Заведующий": 6500, "Провизор": 4800, "Фармацевт": 3600,
                  "Кассир": 2700}[role] + rng.randrange(0, 900, 50)
        employees.append((i, store, _full_name(rng), role, hired.isoformat(), float(salary)))

    # Sales: every store sells every day, a handful of lines each. Store 1 is
    # the busiest and store 6 the newest, so "which store sells most" has an
    # answer a tester can predict.
    weight = {1: 1.45, 2: 1.20, 3: 1.00, 4: 0.90, 5: 0.70, 6: 0.45}
    sales: list[tuple] = []
    sale_id = 0
    day = START
    while day <= END:
        season = 1.25 if day.month in (11, 12, 1, 2) else 1.0  # cold season
        weekend = 0.8 if day.weekday() >= 5 else 1.0
        for store_id, _, _, _, opened, _ in STORES:
            if day < dt.date.fromisoformat(opened):
                continue  # a store cannot sell before it opened
            lines = max(1, round(rng.gauss(4, 1.2) * weight[store_id] * season * weekend))
            for _ in range(lines):
                product = rng.choice(PRODUCTS)
                qty = rng.choice((1, 1, 1, 2, 2, 3, 5))
                amount = round(product[4] * qty, 2)
                sale_id += 1
                sales.append((sale_id, store_id, product[0], day.isoformat(), qty, amount))
        day += dt.timedelta(days=1)

    stock = []
    stock_id = 0
    for store_id, *_ in STORES:
        for product in PRODUCTS:
            stock_id += 1
            on_hand = rng.randint(0, 240)
            stock.append((stock_id, store_id, product[0], on_hand,
                          rng.randint(10, 60), (END - dt.timedelta(days=rng.randint(0, 20))).isoformat()))

    return {"stores": list(STORES), "products": list(PRODUCTS),
            "employees": employees, "sales": sales, "stock": stock}


# Column order per table, used by every emitter and by the mock API.
COLUMNS = {
    "stores": ("id", "name", "city", "address", "opened_on", "manager"),
    "products": ("id", "name", "category", "form", "unit_price", "prescription_only"),
    "employees": ("id", "store_id", "full_name", "role", "hired_on", "monthly_salary"),
    "sales": ("id", "store_id", "product_id", "sold_on", "quantity", "amount"),
    "stock": ("id", "store_id", "product_id", "on_hand", "reorder_at", "counted_on"),
}


def as_dicts(table: str, rows: list[tuple]) -> list[dict]:
    cols = COLUMNS[table]
    return [dict(zip(cols, row)) for row in rows]
