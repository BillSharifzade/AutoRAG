import type { Dictionary } from "./index";

/* Strings for the engineering page. Keys are prefixed "engineering." so they cannot
   collide with another page's. English is the source; Russian is the
   default interface language.

   "engineering.file.*" follows `Intl.PluralRules` categories so a Russian
   file count declines correctly. */
export const engineering: Dictionary = {
  en: {
    "engineering.restricted.what": "Reviewing KARAG's own code is restricted",
    "engineering.unavailable.what": "Proposing code changes isn't available in this deployment.",
    "engineering.unavailable.who": "It needs a git checkout of KARAG with git installed — a container image ships without one. Run KARAG from a checkout to use it.",
    "engineering.restricted.who":
      "This screen decides whether a change reaches the running platform. It's limited to platform engineers, and only a platform operator can grant that.",

    "engineering.eyebrow": "Engineering",
    "engineering.title": "Changes waiting for a human",
    "engineering.lead":
      "KARAG can write a change to its own source, but it can never ship one. Each proposal lands on its own branch with the full test suite already run against it, and stays there until someone here applies it.",

    "engineering.gate.role": "Role-gated",
    "engineering.gate.role.d":
      "Only a platform engineer can ask for a change, and only an operator can grant that role.",
    "engineering.gate.files": "Off-limits files",
    "engineering.gate.files.d":
      "Access control, the tenant directory and the guard itself can never be edited — by any role.",
    "engineering.gate.untrusted": "Untrusted input refused",
    "engineering.gate.untrusted.d":
      "A conversation carrying an uploaded or retrieved document cannot produce a change at all.",
    "engineering.gate.you": "You apply it",
    "engineering.gate.you.d":
      "The running system is untouched until someone presses Apply on this page.",

    "engineering.suggested": "Suggested changes",
    "engineering.suggested.sub": "Read the diff before you apply. Nothing here has run yet.",
    "engineering.lens.aria": "Which proposals",
    "engineering.lens.pending": "Waiting",
    "engineering.lens.settled": "Decided",

    "engineering.empty.pending": "Nothing waiting",
    "engineering.empty.pending.hint":
      "Ask KARAG in chat to change something about itself. The proposal appears here with its test results, and nothing moves until you say so.",
    "engineering.empty.settled": "Nothing decided yet",
    "engineering.empty.settled.hint":
      "Once you apply or discard a proposal it moves here, with who decided and when.",

    "engineering.testsPassed": "All tests passed",
    "engineering.testsFailed": "Tests failed",
    "engineering.file.one": "{n} file",
    "engineering.file.few": "{n} files",
    "engineering.file.many": "{n} files",
    "engineering.file.other": "{n} files",
    "engineering.status.applied": "applied",
    "engineering.status.discarded": "discarded",

    "engineering.testsFailed.notice":
      "The test suite failed against this change. Applying it would put failing code on the running platform.",
    "engineering.files": "Files it touches",
    "engineering.testsSaid": "What the tests said",
    "engineering.theChange": "The change",
    "engineering.loadingDiff": "Loading the diff…",

    "engineering.confirm.q": "Put this on the running platform?",
    "engineering.confirm.yes": "Yes, apply it",
    "engineering.apply": "Apply this change",
    "engineering.discard": "Discard",
    "engineering.byline": "Written by {model} · asked for by {author}",
    "engineering.decided.applied": "Applied by {who} {when}.",
    "engineering.decided.discarded": "Discarded by {who} {when}.",
  },
  ru: {
    "engineering.restricted.what": "Проверка кода самого KARAG ограничена",
    "engineering.unavailable.what": "Предлагать изменения кода в этом развёртывании нельзя.",
    "engineering.unavailable.who": "Нужна git-копия KARAG и установленный git — в образе контейнера их нет. Запустите KARAG из копии репозитория, чтобы пользоваться этим.",
    "engineering.restricted.who":
      "Здесь решается, попадёт ли изменение на работающую платформу. Доступ есть только у инженеров платформы, и выдать его может только оператор платформы.",

    "engineering.eyebrow": "Инженерия",
    "engineering.title": "Изменения ждут решения человека",
    "engineering.lead":
      "KARAG может написать изменение в свой код, но никогда не выпустит его сам. Каждое предложение попадает в отдельную ветку с уже прогнанными тестами и остаётся там, пока кто-то здесь его не применит.",

    "engineering.gate.role": "Только по роли",
    "engineering.gate.role.d":
      "Запросить изменение может только инженер платформы, а выдать эту роль — только оператор.",
    "engineering.gate.files": "Неприкосновенные файлы",
    "engineering.gate.files.d":
      "Контроль доступа, справочник компаний и сам защитный механизм нельзя изменить никакой ролью.",
    "engineering.gate.untrusted": "Чужой ввод отклоняется",
    "engineering.gate.untrusted.d":
      "Разговор, в котором есть загруженный или найденный документ, вообще не может породить изменение.",
    "engineering.gate.you": "Применяете вы",
    "engineering.gate.you.d":
      "Работающая система не меняется, пока кто-то не нажмёт «Применить» на этой странице.",

    "engineering.suggested": "Предложенные изменения",
    "engineering.suggested.sub":
      "Прочитайте изменения перед применением. Ничего из этого ещё не запущено.",
    "engineering.lens.aria": "Какие предложения",
    "engineering.lens.pending": "Ожидают",
    "engineering.lens.settled": "Решены",

    "engineering.empty.pending": "Ничего не ожидает",
    "engineering.empty.pending.hint":
      "Попросите KARAG в чате что-то изменить в себе. Предложение появится здесь с результатами тестов, и ничего не произойдёт без вашего решения.",
    "engineering.empty.settled": "Решений пока нет",
    "engineering.empty.settled.hint":
      "Когда вы примените или отклоните предложение, оно окажется здесь — с тем, кто и когда решил.",

    "engineering.testsPassed": "Все тесты прошли",
    "engineering.testsFailed": "Тесты не прошли",
    "engineering.file.one": "{n} файл",
    "engineering.file.few": "{n} файла",
    "engineering.file.many": "{n} файлов",
    "engineering.file.other": "{n} файла",
    "engineering.status.applied": "применено",
    "engineering.status.discarded": "отклонено",

    "engineering.testsFailed.notice":
      "Тесты на этом изменении не прошли. Применив его, вы выпустите неработающий код на платформу.",
    "engineering.files": "Затронутые файлы",
    "engineering.testsSaid": "Что показали тесты",
    "engineering.theChange": "Изменение",
    "engineering.loadingDiff": "Загружаем изменения…",

    "engineering.confirm.q": "Выпустить это на работающую платформу?",
    "engineering.confirm.yes": "Да, применить",
    "engineering.apply": "Применить изменение",
    "engineering.discard": "Отклонить",
    "engineering.byline": "Написано {model} · по запросу {author}",
    "engineering.decided.applied": "Применил {who} {when}.",
    "engineering.decided.discarded": "Отклонил {who} {when}.",
  },
};
