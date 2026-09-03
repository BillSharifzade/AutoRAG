import type { Dictionary } from "./index";

/* Strings for the documents page. Keys are prefixed "documents." so they cannot
   collide with another page's. English is the source; Russian is the
   default interface language.

   Counts come in three Russian forms (one / few / many) and two English
   ones; the page picks the suffix, the dictionary carries the words. */
export const documents: Dictionary = {
  en: {
    "documents.eyebrow": "Knowledge",
    "documents.title": "What your assistant has read",
    "documents.lead":
      "Everything here can be quoted back to your team, with a link to the exact source. Add a policy, a price list, a manual — anything people keep asking about.",

    "documents.count.one": "document",
    "documents.count.few": "documents",
    "documents.count.many": "documents",
    "documents.ribbon.aria": "{n} visible to {who}",

    "documents.add.title": "Add knowledge",
    "documents.add.sub": "Two ways in — type it out, or hand over a file you already have.",
    "documents.add.how": "How to add",
    "documents.mode.write": "Write it",
    "documents.mode.upload": "Upload a file",

    "documents.field.title": "What is it called?",
    "documents.field.titlePh": "Returns policy",
    "documents.field.titleHint": "People will see this name when the assistant quotes it.",
    "documents.field.text": "What does it say?",
    "documents.field.textPh":
      "Customers may return unopened goods within 14 days of purchase, with a receipt…",
    "documents.field.textHint": "Paste as much as you like — long documents are fine.",
    "documents.words.one": "{n} word",
    "documents.words.few": "{n} words",
    "documents.words.many": "{n} words",

    "documents.drop.title": "Drop a file here",
    "documents.drop.release": "Let go to add it",
    "documents.drop.sub": "or click to browse · Word, Excel, PowerPoint, PDF, CSV, text",
    "documents.drop.ready": "ready to add",
    "documents.drop.change": "Choose a different file",
    "documents.reading": "Reading the file…",
    "documents.guess.title": "This looks like it belongs under “{kind}”",
    "documents.guess.note": "It’s only a guess — your choice on the right is what counts.",

    "documents.who.title": "Who should be able to see this?",
    "documents.who.sub":
      "The assistant will never show it to anyone outside this group — not even a hint that it exists.",
    "documents.submit.write": "Add to knowledge",
    "documents.submit.upload": "Upload and add",
    "documents.need.write": "Add a name and some text first.",
    "documents.need.upload": "Choose a file first.",
    "documents.done": "“{name}” is now part of what the assistant knows.",
    "documents.replaced": "Replaced the earlier copy of this document.",

    "documents.library.title": "Everything it knows",
    "documents.library.sub":
      "You only see what your access covers — the rest isn’t listed at all.",
    "documents.library.search": "Search documents",
    "documents.library.searchPh": "Search by name…",
    "documents.filter.before": "Showing only what",
    "documents.filter.after": "can see",
    "documents.filter.clear": "Show all",
    "documents.empty.title": "Nothing here yet",
    "documents.empty.hint":
      "Add your first document above. A returns policy or a price list is a good place to start — something people ask about every week.",
    "documents.empty.noMatch": "Nothing matches that",
    "documents.empty.noMatchHint": "Try a different name, or clear the filter.",
    "documents.chip.new": "new",
    "documents.chip.replaced": "replaced",
    "documents.kind.file": "Uploaded file",
    "documents.kind.text": "Written here",
    "documents.remove.q": "Remove it?",
    "documents.remove.aria": "Remove {name}",
    "documents.showFewer": "Show fewer",
    "documents.showAll": "Show all {n} documents",
  },
  ru: {
    "documents.eyebrow": "Знания",
    "documents.title": "Что уже прочитал ваш помощник",
    "documents.lead":
      "Всё, что здесь есть, помощник может процитировать вашей команде — со ссылкой на точный источник. Добавьте регламент, прайс-лист, инструкцию — всё, о чём люди постоянно спрашивают.",

    "documents.count.one": "документ",
    "documents.count.few": "документа",
    "documents.count.many": "документов",
    "documents.ribbon.aria": "{n} — видят: {who}",

    "documents.add.title": "Добавить знания",
    "documents.add.sub": "Два способа: напечатать текст или загрузить готовый файл.",
    "documents.add.how": "Как добавить",
    "documents.mode.write": "Написать",
    "documents.mode.upload": "Загрузить файл",

    "documents.field.title": "Как это называется?",
    "documents.field.titlePh": "Правила возврата",
    "documents.field.titleHint": "Это название увидят люди, когда помощник будет его цитировать.",
    "documents.field.text": "Что там написано?",
    "documents.field.textPh":
      "Покупатель может вернуть невскрытый товар в течение 14 дней при наличии чека…",
    "documents.field.textHint": "Вставляйте сколько угодно — длинные документы тоже подходят.",
    "documents.words.one": "{n} слово",
    "documents.words.few": "{n} слова",
    "documents.words.many": "{n} слов",

    "documents.drop.title": "Перетащите файл сюда",
    "documents.drop.release": "Отпустите, чтобы добавить",
    "documents.drop.sub": "или нажмите, чтобы выбрать · Word, Excel, PowerPoint, PDF, CSV, текст",
    "documents.drop.ready": "готов к добавлению",
    "documents.drop.change": "Выбрать другой файл",
    "documents.reading": "Читаем файл…",
    "documents.guess.title": "Похоже, это подходит под «{kind}»",
    "documents.guess.note": "Это лишь предположение — решает ваш выбор справа.",

    "documents.who.title": "Кто должен это видеть?",
    "documents.who.sub":
      "Помощник никогда не покажет это никому вне этой группы — даже не намекнёт, что документ существует.",
    "documents.submit.write": "Добавить в знания",
    "documents.submit.upload": "Загрузить и добавить",
    "documents.need.write": "Сначала укажите название и текст.",
    "documents.need.upload": "Сначала выберите файл.",
    "documents.done": "«{name}» теперь в знаниях помощника.",
    "documents.replaced": "Прежняя копия этого документа заменена.",

    "documents.library.title": "Всё, что он знает",
    "documents.library.sub":
      "Вы видите только то, что открыто вашему доступу, — остального в списке просто нет.",
    "documents.library.search": "Поиск документов",
    "documents.library.searchPh": "Поиск по названию…",
    "documents.filter.before": "Показано только то, что видят:",
    "documents.filter.after": "",
    "documents.filter.clear": "Показать все",
    "documents.empty.title": "Пока ничего нет",
    "documents.empty.hint":
      "Добавьте первый документ выше. Правила возврата или прайс-лист — хорошее начало: о таком спрашивают каждую неделю.",
    "documents.empty.noMatch": "Ничего не найдено",
    "documents.empty.noMatchHint": "Попробуйте другое название или снимите фильтр.",
    "documents.chip.new": "новый",
    "documents.chip.replaced": "заменён",
    "documents.kind.file": "Загруженный файл",
    "documents.kind.text": "Написано здесь",
    "documents.remove.q": "Убрать?",
    "documents.remove.aria": "Убрать {name}",
    "documents.showFewer": "Показать меньше",
    "documents.showAll": "Показать все документы ({n})",
  },
};
