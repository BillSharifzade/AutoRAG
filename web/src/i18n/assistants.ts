import type { Dictionary } from "./index";

/* Strings for the assistants page. Keys are prefixed "assistants." so they cannot
   collide with another page's. English is the source; Russian is the
   default interface language.

   Plural forms carry a `.one` / `.few` / `.many` suffix — the page picks one
   with `pluralKey()` because Russian counts differently from English. The
   three template instructions live here too, so a template fills the box in
   the interface language. */
export const assistants: Dictionary = {
  en: {
    "assistants.eyebrow": "Assistants",
    "assistants.title": "Set up a helper for a team",
    "assistants.lead":
      "An assistant is the same AI with a job description: how to answer and which company data it may use. Everyone in the team gets the same behaviour.",
    "assistants.new": "New assistant",
    "assistants.back": "All assistants",

    "assistants.empty.title": "No assistants yet",
    "assistants.empty.hint": "The first one takes under a minute.",

    "assistants.access.all": "Everything the person can use",
    "assistants.access.all.hint": "Their documents and skills, as in the plain chat.",
    "assistants.access.docs": "Documents only",
    "assistants.access.docs.hint": "Reads documents, never live data.",
    "assistants.access.some": "Only these skills",
    "assistants.access.some.hint": "A short list for a narrow job.",
    "assistants.skillsCount.one": "{n} skill",
    "assistants.skillsCount.few": "{n} skills",
    "assistants.skillsCount.many": "{n} skills",

    "assistants.by": "by {who}",
    "assistants.byYou": "by you",
    "assistants.card.open": "Open in chat",

    "assistants.field.name.placeholder": "For example, Helpdesk",
    "assistants.field.behaviour": "How should it behave?",
    "assistants.field.behaviour.placeholder":
      "Answer briefly. Always say which document an answer came from. If you don't know, say so.",
    "assistants.field.access": "What may it use?",
    "assistants.templates": "Start from:",

    "assistants.template.helpdesk": "Helpdesk",
    "assistants.template.helpdesk.text":
      "Answer staff questions about our policies and procedures. Quote the exact rule and say which document it came from. If the answer isn't in the documents, say so and suggest who to ask.",
    "assistants.template.finance": "Finance analyst",
    "assistants.template.finance.text":
      "Report figures exactly as the data returns them — never estimate or round without saying so. Always state the period a number covers. If a figure looks unusual, point it out rather than explain it away.",
    "assistants.template.hr": "HR assistant",
    "assistants.template.hr.text":
      "Help with leave, onboarding and workplace policy questions. Be warm and concrete. Never speculate about an individual's records; direct anything sensitive to a person rather than answering it yourself.",

    "assistants.skills.picked": "{n} of {total} selected",
    "assistants.skills.selectAll": "Select all",
    "assistants.skills.clear": "Clear",
    "assistants.skills.none": "No skills to choose from yet.",
    "assistants.skills.pickOne": "Tick at least one skill, or choose another option above.",

    "assistants.error.name": "Give it a name first.",
    "assistants.ready": "Ready — open it in chat.",
    "assistants.saved": "Saved. Everyone using it sees the change straight away.",
    "assistants.deleted": "Assistant removed.",
    "assistants.delete.question": "Remove it for everyone?",

    "assistants.detail.noInstruction": "No special instructions — it answers like the plain chat.",

    "assistants.try.title": "Try a question",
    "assistants.try.caption": "One question, no memory — for a real conversation, open the chat.",
    "assistants.try.placeholder": "Ask it something…",
    "assistants.try.ask": "Ask",
    "assistants.try.empty": "No answer came back.",
    "assistants.try.used": "used: {skills}",
    "assistants.try.sources.one": "{n} source",
    "assistants.try.sources.few": "{n} sources",
    "assistants.try.sources.many": "{n} sources",
    "assistants.try.continue": "Continue in chat",
    "assistants.try.download": "Download {name}",
  },
  ru: {
    "assistants.eyebrow": "Помощники",
    "assistants.title": "Настройте помощника для команды",
    "assistants.lead":
      "Помощник — это тот же ИИ с должностной инструкцией: как отвечать и какими данными компании пользоваться. Вся команда получает одинаковое поведение.",
    "assistants.new": "Новый помощник",
    "assistants.back": "Все помощники",

    "assistants.empty.title": "Помощников пока нет",
    "assistants.empty.hint": "Первый займёт меньше минуты.",

    "assistants.access.all": "Всё, что доступно сотруднику",
    "assistants.access.all.hint": "Его документы и навыки — как в обычном чате.",
    "assistants.access.docs": "Только документы",
    "assistants.access.docs.hint": "Читает документы, не трогает живые данные.",
    "assistants.access.some": "Только выбранные навыки",
    "assistants.access.some.hint": "Короткий список для узкой задачи.",
    "assistants.skillsCount.one": "{n} навык",
    "assistants.skillsCount.few": "{n} навыка",
    "assistants.skillsCount.many": "{n} навыков",

    "assistants.by": "автор: {who}",
    "assistants.byYou": "автор: вы",
    "assistants.card.open": "Открыть в чате",

    "assistants.field.name.placeholder": "Например, Служба поддержки",
    "assistants.field.behaviour": "Как он должен себя вести?",
    "assistants.field.behaviour.placeholder":
      "Отвечайте кратко. Всегда указывайте документ-источник. Если не знаете — так и скажите.",
    "assistants.field.access": "Чем он может пользоваться?",
    "assistants.templates": "Взять за основу:",

    "assistants.template.helpdesk": "Служба поддержки",
    "assistants.template.helpdesk.text":
      "Отвечайте на вопросы сотрудников о правилах и процедурах компании. Цитируйте точную формулировку и указывайте, из какого документа она взята. Если ответа в документах нет — скажите об этом и подскажите, к кому обратиться.",
    "assistants.template.finance": "Финансовый аналитик",
    "assistants.template.finance.text":
      "Приводите цифры ровно так, как их возвращают данные, — не оценивайте и не округляйте без оговорки. Всегда указывайте период, к которому относится показатель. Если цифра выглядит необычно, обратите на это внимание, а не объясняйте её.",
    "assistants.template.hr": "HR-помощник",
    "assistants.template.hr.text":
      "Помогайте с вопросами об отпусках, адаптации новых сотрудников и правилах на рабочем месте. Отвечайте тепло и по существу. Никогда не стройте догадок о данных конкретного человека; всё чувствительное направляйте к живому сотруднику, а не отвечайте сами.",

    "assistants.skills.picked": "Выбрано {n} из {total}",
    "assistants.skills.selectAll": "Выбрать все",
    "assistants.skills.clear": "Снять все",
    "assistants.skills.none": "Пока нет навыков для выбора.",
    "assistants.skills.pickOne": "Отметьте хотя бы один навык или выберите другой вариант выше.",

    "assistants.error.name": "Сначала дайте помощнику название.",
    "assistants.ready": "Готово — откройте его в чате.",
    "assistants.saved": "Сохранено. Все, кто им пользуется, увидят изменения сразу.",
    "assistants.deleted": "Помощник удалён.",
    "assistants.delete.question": "Удалить для всех?",

    "assistants.detail.noInstruction": "Без особых указаний — отвечает как обычный чат.",

    "assistants.try.title": "Задайте вопрос",
    "assistants.try.caption": "Один вопрос, без памяти — для настоящего разговора откройте чат.",
    "assistants.try.placeholder": "Спросите что-нибудь…",
    "assistants.try.ask": "Спросить",
    "assistants.try.empty": "Ответ не пришёл.",
    "assistants.try.used": "использовал: {skills}",
    "assistants.try.sources.one": "{n} источник",
    "assistants.try.sources.few": "{n} источника",
    "assistants.try.sources.many": "{n} источников",
    "assistants.try.continue": "Продолжить в чате",
    "assistants.try.download": "Скачать {name}",
  },
};
