import type { Dictionary } from "./index";

/* Strings for the audit page. Keys are prefixed "audit." so they cannot
   collide with another page's. English is the source; Russian is the
   default interface language. */
export const audit: Dictionary = {
  en: {
    "audit.restricted.what": "The activity log is for administrators and leadership",
    "audit.restricted.who":
      "It records every question, every document read and every refusal across the company — including who asked and from where. That's kept to administrators and leadership.",

    "audit.eyebrow": "Activity",
    "audit.title": "Everything that happened, in order",
    "audit.lead":
      "Every question asked, every document read, every refusal — with who, when and from where. Nothing here can be edited, including by an administrator.",

    "audit.tally.recorded": "Recorded",
    "audit.tally.blocked": "Blocked",

    "audit.lens.aria": "Which events",
    "audit.lens.all": "Everything",
    "audit.lens.allow": "Allowed",
    "audit.lens.deny": "Blocked",

    "audit.search": "Search by person or action…",
    "audit.search.aria": "Search activity",

    "audit.empty.title": "Nothing recorded yet",
    "audit.empty.hint":
      "Ask a question or add a document — everything anyone does lands here within a second.",
    "audit.noMatch.title": "Nothing matches",
    "audit.noMatch.hint": "Try a different name, or switch back to Everything.",
    "audit.more": "Go further back ({n} more)",

    "audit.pill.allowed": "allowed",
    "audit.pill.blocked": "blocked",

    "audit.row.signedAs": "Signed in as",
    "audit.row.appliedTo": "Applied to",
    "audit.row.from": "From",
    "audit.row.device": "Device",
  },
  ru: {
    "audit.restricted.what": "Журнал действий — для администраторов и руководства",
    "audit.restricted.who":
      "В нём записан каждый вопрос, каждый открытый документ и каждый отказ по всей компании — включая кто спрашивал и откуда. Это доступно только администраторам и руководству.",

    "audit.eyebrow": "Действия",
    "audit.title": "Всё, что произошло, по порядку",
    "audit.lead":
      "Каждый вопрос, каждый открытый документ, каждый отказ — кто, когда и откуда. Здесь ничего нельзя изменить, даже администратору.",

    "audit.tally.recorded": "Записано",
    "audit.tally.blocked": "Отказано",

    "audit.lens.aria": "Какие события",
    "audit.lens.all": "Все",
    "audit.lens.allow": "Разрешено",
    "audit.lens.deny": "Отказано",

    "audit.search": "Поиск по человеку или действию…",
    "audit.search.aria": "Поиск по журналу",

    "audit.empty.title": "Пока ничего не записано",
    "audit.empty.hint":
      "Задайте вопрос или добавьте документ — всё, что кто-либо делает, появляется здесь за секунду.",
    "audit.noMatch.title": "Ничего не найдено",
    "audit.noMatch.hint": "Попробуйте другое имя или вернитесь к «Все».",
    "audit.more": "Показать раньше (ещё {n})",

    "audit.pill.allowed": "разрешено",
    "audit.pill.blocked": "отказано",

    "audit.row.signedAs": "Вошёл как",
    "audit.row.appliedTo": "Объект",
    "audit.row.from": "Откуда",
    "audit.row.device": "Устройство",
  },
};
