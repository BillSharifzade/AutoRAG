import type { Dictionary } from "./index";

/* Strings for the usage page. Keys are prefixed "usage." so they cannot
   collide with another page's. English is the source; Russian is the
   default interface language.

   Plural forms follow `Intl.PluralRules` categories (one / few / many /
   other) so Russian counts decline correctly; English only ever hits
   "one" and "other" but carries all four so a lookup never misses. */
export const usage: Dictionary = {
  en: {
    "usage.tile.requests": "Requests",
    "usage.tile.input_tokens": "Input tokens",
    "usage.tile.output_tokens": "Output tokens",
    "usage.tile.total_tokens": "Total tokens",

    "usage.range.all": "Overall",
    "usage.range.today": "Today",
    "usage.range.7d": "7 days",
    "usage.range.30d": "30 days",

    "usage.title": "Tenant usage",
    "usage.sub.allTime": "All-time totals for {tenant}.",
    "usage.sub.range": "{range} · {tenant}.",
    "usage.sub.idle": "Token and request accounting.",
    "usage.notAvailable": "Not available",

    "usage.cost": "Cost",
    "usage.cost.sub": "Priced per model — local inference is free.",
    "usage.th.model": "Model",
    "usage.th.requests": "Requests",
    "usage.th.input": "Input",
    "usage.th.output": "Output",
    "usage.th.cost": "Cost",
    "usage.noRate": "no rate",
    "usage.noMetered": "No metered requests in this range.",
    "usage.noPrice":
      "No price configured for {models} — set KARAG_PRICING rather than letting a wrong number reach an invoice.",

    "usage.budget": "Budget meter",
    "usage.budget.sub": "Share of the token budget consumed.",
    "usage.budget.money.sub": "Share of this month's AI budget already spent.",
    "usage.budget.money": "{spent} of {budget} · {month}",
    "usage.budget.none": "No monthly limit set · {spent} spent in {month}",
    "usage.budget.none.sub": "A platform operator can set a monthly AI budget for your company.",
    "usage.ofBudget": "of a {n} token budget",

    "usage.split": "Token split",
    "usage.split.sub": "Prompt tokens in, generated tokens out.",
    "usage.tokens": "tokens",
    "usage.input": "Input",
    "usage.output": "Output",

    "usage.perRequest": "Per request",
    "usage.perRequest.sub": "Average cost of a single question.",
    "usage.avgPerRequest": "avg tokens per request",
    "usage.avgIn": "Avg input / request",
    "usage.avgOut": "Avg output / request",

    "usage.activity": "Activity",
    "usage.activity.sub": "Tokens per interval — stacked input and output.",
    "usage.noActivity": "No activity yet",
    "usage.noActivity.hint": "Ask a question in Chat — every request lands on this timeline.",
    "usage.noWindow": "Nothing in this window",
    "usage.noWindow.hint": "No requests fell in the selected range. Try a wider window.",

    "usage.request.one": "{n} request",
    "usage.request.few": "{n} requests",
    "usage.request.many": "{n} requests",
    "usage.request.other": "{n} requests",
    "usage.in": "{n} in",
    "usage.out": "{n} out",
  },
  ru: {
    "usage.tile.requests": "Запросы",
    "usage.tile.input_tokens": "Входящие токены",
    "usage.tile.output_tokens": "Исходящие токены",
    "usage.tile.total_tokens": "Всего токенов",

    "usage.range.all": "За всё время",
    "usage.range.today": "Сегодня",
    "usage.range.7d": "7 дней",
    "usage.range.30d": "30 дней",

    "usage.title": "Расход компании",
    "usage.sub.allTime": "Итого за всё время для {tenant}.",
    "usage.sub.range": "{range} · {tenant}.",
    "usage.sub.idle": "Учёт токенов и запросов.",
    "usage.notAvailable": "Недоступно",

    "usage.cost": "Стоимость",
    "usage.cost.sub": "Цена зависит от модели — локальные модели бесплатны.",
    "usage.th.model": "Модель",
    "usage.th.requests": "Запросы",
    "usage.th.input": "Вход",
    "usage.th.output": "Выход",
    "usage.th.cost": "Стоимость",
    "usage.noRate": "нет тарифа",
    "usage.noMetered": "За этот период учтённых запросов нет.",
    "usage.noPrice":
      "Для {models} не задана цена — настройте KARAG_PRICING, чтобы в счёт не попала неверная сумма.",

    "usage.budget": "Бюджет",
    "usage.budget.sub": "Какая доля бюджета токенов израсходована.",
    "usage.budget.money.sub": "Какая доля месячного бюджета на ИИ уже потрачена.",
    "usage.budget.money": "{spent} из {budget} · {month}",
    "usage.budget.none": "Месячный лимит не задан · потрачено {spent} за {month}",
    "usage.budget.none.sub": "Месячный бюджет на ИИ для компании задаёт оператор платформы.",
    "usage.ofBudget": "из бюджета {n} токенов",

    "usage.split": "Вход и выход",
    "usage.split.sub": "Токены запроса на входе, токены ответа на выходе.",
    "usage.tokens": "токенов",
    "usage.input": "Вход",
    "usage.output": "Выход",

    "usage.perRequest": "На запрос",
    "usage.perRequest.sub": "Средний расход на один вопрос.",
    "usage.avgPerRequest": "токенов на запрос в среднем",
    "usage.avgIn": "Вход в среднем на запрос",
    "usage.avgOut": "Выход в среднем на запрос",

    "usage.activity": "Активность",
    "usage.activity.sub": "Токены по интервалам — вход и выход столбиком.",
    "usage.noActivity": "Пока нет активности",
    "usage.noActivity.hint": "Задайте вопрос в чате — каждый запрос попадает на эту шкалу.",
    "usage.noWindow": "За этот период ничего нет",
    "usage.noWindow.hint": "В выбранный период запросов не было. Попробуйте более широкий.",

    "usage.request.one": "{n} запрос",
    "usage.request.few": "{n} запроса",
    "usage.request.many": "{n} запросов",
    "usage.request.other": "{n} запроса",
    "usage.in": "{n} вх.",
    "usage.out": "{n} исх.",
  },
};
