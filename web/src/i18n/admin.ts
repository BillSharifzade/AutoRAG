import type { Dictionary } from "./index";

/* Strings for the admin page. Keys are prefixed "admin." so they cannot
   collide with another page's. English is the source; Russian is the
   default interface language. */
export const admin: Dictionary = {
  en: {
    "admin.restricted.what": "Only administrators manage people",
    "admin.restricted.who":
      "Adding colleagues, changing what they can see and setting up alerts is limited to administrators and leadership at your company.",
    "admin.eyebrow": "Administration",
    "admin.title": "Who’s here, and what they can see",
    "admin.lead":
      "Everyone gets their own access key and their own view of the company’s knowledge. Change someone’s role and it takes effect on their very next question — no waiting, no re-sync.",

    "admin.key.title": "{who}’s access key",
    "admin.key.sub":
      "Copy it now and give it to them directly. It exists only in this box — close it and nobody, including you, can read it again. If it goes missing, make a new one.",
    "admin.key.close": "I’ve saved it — close this",

    "admin.tabs": "What to manage",
    "admin.tab.people": "People",
    "admin.tab.alerts": "Alerts",
    "admin.tab.companies": "Companies",
    "admin.suspend": "Suspend",
    "admin.restore": "Restore",

    "admin.people.title": "People at your company",
    "admin.people.sub":
      "Each person sees only what their role covers — enforced every time they ask, not just at sign-in.",
    "admin.people.add": "Add someone",
    "admin.people.addFirst": "Add the first person",
    "admin.people.name": "Their name",
    "admin.people.namePh": "Nilufar Rahimova",
    "admin.people.id": "Sign-in ID",
    "admin.people.idPh": "nilufar",
    "admin.people.idHint": "Short, no spaces. Appears in the activity log.",
    "admin.people.roles": "What should they be able to see?",
    "admin.people.create": "Create their access key",
    "admin.people.empty": "Nobody added yet",
    "admin.people.emptyHint":
      "Add your colleagues one at a time. Each gets their own key and only sees what their role allows.",
    "admin.people.you": "you",
    "admin.people.suspended": "suspended",
    "admin.people.rotate": "New key",
    "admin.people.rotateHint": "Give them a new key — the old one stops working",
    "admin.people.removeQ": "Remove {name}?",
    "admin.people.removeAria": "Remove {name}",

    "admin.every.15m": "Every 15 minutes",
    "admin.every.1h": "Every hour",
    "admin.every.6h": "Every 6 hours",
    "admin.every.1d": "Once a day",
    "admin.every.min": "Every {n} min",
    "admin.alerts.title": "Messages that send themselves",
    "admin.alerts.sub":
      "Instead of someone remembering to check, KARAG checks on a schedule and only speaks up when there’s something to say.",
    "admin.alerts.new": "New alert",
    "admin.alerts.name": "What should we call it?",
    "admin.alerts.namePh": "Stock running low",
    "admin.alerts.lookup": "What should it check?",
    "admin.alerts.lookupPh": "Choose a lookup…",
    "admin.alerts.lookupAria": "Which lookup",
    "admin.alerts.every": "How often?",
    "admin.alerts.everyAria": "How often",
    "admin.alerts.message": "What should it say?",
    "admin.alerts.messagePh": "Some items are running low",
    "admin.alerts.create": "Create alert",
    "admin.alerts.createOne": "Create one",
    "admin.alerts.empty": "No alerts set up",
    "admin.alerts.emptyNoLookup":
      "Alerts run a live lookup on a schedule, so you’ll need at least one lookup first.",
    "admin.alerts.emptyHint":
      "Pick something worth watching — stock levels, expiring batches, an overdue figure — and KARAG will keep an eye on it for you.",
    "admin.alerts.lastChecked": "last checked {when}",
    "admin.alerts.notRun": "not run yet",
    "admin.alerts.failed": "last check failed",
    "admin.alerts.pause": "Pause",
    "admin.alerts.resume": "Resume",
    "admin.alerts.runNow": "Check now",
    "admin.alerts.deleteQ": "Delete this alert?",
    "admin.alerts.deleteYes": "Yes, delete",
    "admin.alerts.deleteAria": "Delete {name}",

    "admin.companies.title": "Companies on the platform",
    "admin.companies.sub":
      "Each one is sealed off from the others. No question asked in one can ever reach another’s data.",
    "admin.companies.add": "Add a company",
    "admin.companies.name": "Company name",
    "admin.companies.namePh": "Dusti Pharma",
    "admin.companies.code": "Short code",
    "admin.companies.codePh": "dusti",
    "admin.companies.empty": "No companies yet",
    "admin.companies.emptyHint":
      "Each company gets its own sealed space for knowledge, people and data.",
    "admin.companies.suspended": "suspended",
    "admin.companies.added": "Added {when}",
  },
  ru: {
    "admin.restricted.what": "Людьми управляют только администраторы",
    "admin.restricted.who":
      "Добавлять коллег, менять их доступ и настраивать оповещения могут только администраторы и руководство вашей компании.",
    "admin.eyebrow": "Управление",
    "admin.title": "Кто здесь и что им видно",
    "admin.lead":
      "У каждого свой ключ доступа и своё представление о знаниях компании. Измените роль — и это подействует уже на следующий вопрос, без ожидания и пересинхронизации.",

    "admin.key.title": "Ключ доступа: {who}",
    "admin.key.sub":
      "Скопируйте его сейчас и передайте лично. Ключ есть только в этом окне — закройте его, и прочитать ключ не сможет никто, включая вас. Если ключ потеряется, создайте новый.",
    "admin.key.close": "Я сохранил — закрыть",

    "admin.tabs": "Чем управлять",
    "admin.tab.people": "Люди",
    "admin.tab.alerts": "Оповещения",
    "admin.tab.companies": "Компании",
    "admin.suspend": "Приостановить",
    "admin.restore": "Восстановить",

    "admin.people.title": "Люди в вашей компании",
    "admin.people.sub":
      "Каждый видит только то, что открыто его роли, — это проверяется при каждом вопросе, а не только при входе.",
    "admin.people.add": "Добавить человека",
    "admin.people.addFirst": "Добавить первого",
    "admin.people.name": "Имя",
    "admin.people.namePh": "Нилуфар Рахимова",
    "admin.people.id": "Логин",
    "admin.people.idPh": "nilufar",
    "admin.people.idHint": "Коротко, без пробелов. Отображается в журнале действий.",
    "admin.people.roles": "Что этот человек должен видеть?",
    "admin.people.create": "Создать ключ доступа",
    "admin.people.empty": "Пока никого нет",
    "admin.people.emptyHint":
      "Добавляйте коллег по одному. У каждого будет свой ключ и доступ только к тому, что разрешает роль.",
    "admin.people.you": "вы",
    "admin.people.suspended": "приостановлен",
    "admin.people.rotate": "Новый ключ",
    "admin.people.rotateHint": "Выдать новый ключ — старый перестанет работать",
    "admin.people.removeQ": "Убрать {name}?",
    "admin.people.removeAria": "Убрать {name}",

    "admin.every.15m": "Каждые 15 минут",
    "admin.every.1h": "Каждый час",
    "admin.every.6h": "Каждые 6 часов",
    "admin.every.1d": "Раз в день",
    "admin.every.min": "Каждые {n} мин",
    "admin.alerts.title": "Сообщения, которые приходят сами",
    "admin.alerts.sub":
      "Вместо того чтобы кто-то помнил о проверке, KARAG проверяет по расписанию и пишет только тогда, когда есть что сказать.",
    "admin.alerts.new": "Новое оповещение",
    "admin.alerts.name": "Как назвать?",
    "admin.alerts.namePh": "Заканчивается товар",
    "admin.alerts.lookup": "Что проверять?",
    "admin.alerts.lookupPh": "Выберите запрос к данным…",
    "admin.alerts.lookupAria": "Какой запрос",
    "admin.alerts.every": "Как часто?",
    "admin.alerts.everyAria": "Как часто",
    "admin.alerts.message": "Что написать?",
    "admin.alerts.messagePh": "Некоторые позиции заканчиваются",
    "admin.alerts.create": "Создать оповещение",
    "admin.alerts.createOne": "Создать",
    "admin.alerts.empty": "Оповещений пока нет",
    "admin.alerts.emptyNoLookup":
      "Оповещения по расписанию выполняют запрос к живым данным, поэтому сначала нужен хотя бы один такой запрос.",
    "admin.alerts.emptyHint":
      "Выберите, за чем стоит следить — остатки, партии с истекающим сроком, просроченный показатель, — и KARAG будет присматривать за этим вместо вас.",
    "admin.alerts.lastChecked": "последняя проверка {when}",
    "admin.alerts.notRun": "ещё не запускалось",
    "admin.alerts.failed": "последняя проверка не удалась",
    "admin.alerts.pause": "Приостановить",
    "admin.alerts.resume": "Возобновить",
    "admin.alerts.runNow": "Проверить сейчас",
    "admin.alerts.deleteQ": "Удалить это оповещение?",
    "admin.alerts.deleteYes": "Да, удалить",
    "admin.alerts.deleteAria": "Удалить {name}",

    "admin.companies.title": "Компании на платформе",
    "admin.companies.sub":
      "Каждая полностью изолирована от остальных. Вопрос, заданный в одной, никогда не доберётся до данных другой.",
    "admin.companies.add": "Добавить компанию",
    "admin.companies.name": "Название компании",
    "admin.companies.namePh": "Дусти Фарма",
    "admin.companies.code": "Короткий код",
    "admin.companies.codePh": "dusti",
    "admin.companies.empty": "Компаний пока нет",
    "admin.companies.emptyHint":
      "У каждой компании своё закрытое пространство для знаний, людей и данных.",
    "admin.companies.suspended": "приостановлена",
    "admin.companies.added": "Добавлена {when}",
  },
};
