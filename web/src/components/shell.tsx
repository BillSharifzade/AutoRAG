"use client";

/* App shell: logo sidebar with an animated active pill, glass topbar, and a
   split-screen connect gate (form left · Hyperspeed brand panel right).
   Every page is token-gated.

   Chat is the one destination with contents of its own, so its saved
   conversations hang underneath it in the sidebar rather than taking a column
   away from the conversation itself. The topbar is left with nothing but the
   name of where you are; the answer-language control sits with the other
   session settings at the foot of the sidebar. */

import {
  ArrowRight,
  BookOpenCheck,
  Bot,
  Code2,
  Database,
  FileText,
  FileSpreadsheet,
  LogOut,
  MessageSquareText,
  Moon,
  ScrollText,
  Gauge,
  Settings2,
  ShieldCheck,
  Sun,
  Wrench,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { LANGUAGE_LABELS, type Language } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useChat } from "@/lib/chat-store";
import { ChatHistory } from "@/components/chat-history";
import { BrandLogo, Button, Input, Picker } from "@/components/ui";

const Hyperspeed = dynamic(() => import("@/components/hyperspeed/Hyperspeed"), {
  ssr: false,
});

/* Company colors: slate #3e3b4e road world, red #ec2336 light trails.
   Module-level constant so the WebGL scene is never re-created. */
const ROAD_OPTIONS = {
  onSpeedUp: () => {},
  onSlowDown: () => {},
  distortion: "turbulentDistortion",
  length: 400,
  roadWidth: 10,
  islandWidth: 2,
  lanesPerRoad: 3,
  fov: 90,
  fovSpeedUp: 150,
  speedUp: 2,
  carLightsFade: 0.4,
  totalSideLightSticks: 20,
  lightPairsPerRoadWay: 40,
  shoulderLinesWidthPercentage: 0.05,
  brokenLinesWidthPercentage: 0.1,
  brokenLinesLengthPercentage: 0.5,
  lightStickWidth: [0.12, 0.5],
  lightStickHeight: [1.3, 1.7],
  movingAwaySpeed: [60, 80],
  movingCloserSpeed: [-120, -160],
  carLightsLength: [12, 80],
  carLightsRadius: [0.05, 0.14],
  carWidthPercentage: [0.3, 0.5],
  carShiftX: [-0.8, 0.8],
  carFloorSeparation: [0, 5],
  colors: {
    roadColor: 0x131118,
    islandColor: 0x17151f,
    background: 0x0b0a10,
    shoulderLines: 0x4c485e,
    brokenLines: 0x4c485e,
    leftCars: [0xec2336, 0xff4d5e, 0xb3121f],
    rightCars: [0xdad8e6, 0x8f8aad, 0x6b6685],
    sticks: 0xec2336,
  },
};

/* `gate` hides a destination unless the session holds one of those roles —
   cosmetic only; every endpoint behind them is authorised server-side too. */
const NAV = [
  { href: "/", label: "Chat", icon: MessageSquareText },
  { href: "/assistants", label: "Assistants", icon: Bot },
  { href: "/documents", label: "Documents", icon: FileText },
  {
    href: "/skills",
    label: "Skills",
    icon: Wrench,
    gate: ["admin", "skill_author", "ceo"],
  },
  {
    href: "/admin",
    label: "Admin",
    icon: Settings2,
    gate: ["admin", "ceo", "platform_admin"],
  },
  {
    href: "/engineering",
    label: "Engineering",
    icon: Code2,
    gate: ["karag_engineer"],
  },
  { href: "/audit", label: "Audit", icon: ScrollText },
  { href: "/usage", label: "Usage", icon: Gauge },
];

const FEATURES = [
  { icon: BookOpenCheck, text: "Answers cite their sources — every claim traceable" },
  { icon: Database, text: "Live figures come from verified skills, never guesses" },
  { icon: FileSpreadsheet, text: "Ready .xlsx / .docx / .pptx reports on demand" },
  { icon: ShieldCheck, text: "Forbidden data never reaches the model" },
];

/* ---------------- connect gate ---------------- */

function ConnectGate() {
  const { connect } = useAuth();
  const [value, setValue] = useState("");
  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      {/* Form panel */}
      <div className="flex items-center justify-center p-8">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, ease: [0.2, 0.8, 0.2, 1] }}
          className="w-full max-w-md"
        >
          <BrandLogo className="h-14 w-auto" />

          <h2 className="font-display mt-10 text-3xl font-bold tracking-tight">
            Welcome back
          </h2>
          <p className="mt-2 text-[15px] text-mut">
            Sign in with your access token.
          </p>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (value.trim()) connect(value.trim());
            }}
            className="mt-8 flex flex-col gap-3.5"
          >
            <Input
              autoFocus
              type="password"
              placeholder="Access token…"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              aria-label="Access token"
              className="h-12"
            />
            <Button type="submit" disabled={!value.trim()} className="h-12 text-[15px]">
              Continue <ArrowRight className="size-4" />
            </Button>
          </form>
        </motion.div>
      </div>

      {/* Brand panel — Hyperspeed road in company colors */}
      <div className="relative hidden overflow-hidden bg-[#0b0a10] lg:block">
        <Hyperspeed effectOptions={ROAD_OPTIONS} />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-[#0b0a10]/90 via-transparent to-[#0b0a10]/60" />
        <div className="pointer-events-none relative z-10 flex h-full flex-col justify-between p-14">
          {/* always the white artwork — this panel is dark in both themes */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo-dark.png" alt="KARAG" className="h-11 w-auto self-start object-contain" />

          <div>
            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, ease: [0.2, 0.8, 0.2, 1] }}
              className="font-display max-w-lg text-5xl font-bold leading-[1.12] tracking-tight text-white"
            >
              Your company&apos;s AI.{" "}
              <span className="text-[#ec2336]">On your data.</span>
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.12, duration: 0.6, ease: [0.2, 0.8, 0.2, 1] }}
              className="mt-5 max-w-md text-[16px] leading-relaxed text-white/65"
            >
              Knowledge, live numbers and ready-made documents — inside your
              perimeter, governed by your roles.
            </motion.p>

            <ul className="mt-10 flex flex-col gap-4">
              {FEATURES.map(({ icon: Icon, text }, i) => (
                <motion.li
                  key={text}
                  initial={{ opacity: 0, x: -16 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.25 + i * 0.09, duration: 0.5 }}
                  className="flex items-center gap-3.5 text-[14.5px] text-white/70"
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-white/10 text-[#ff4d5e] backdrop-blur">
                    <Icon className="size-4" />
                  </span>
                  {text}
                </motion.li>
              ))}
            </ul>
          </div>

          <div />
        </div>
      </div>
    </div>
  );
}

/* ---------------- language ---------------- */

/* §2 sells Russian and Tajik as the differentiator, so the choice stays one
   click away — but it belongs with the other session settings at the foot of
   the sidebar, not in the topbar of every page. It pins the *answer* language;
   the chrome stays English. */
function LanguageSwitcher() {
  const { language, setLanguage } = useAuth();
  return (
    <div className="hidden lg:block">
      <p className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
        Answer language
      </p>
      <Picker
        compact
        dropUp
        value={language}
        onChange={(v) => setLanguage(v as Language)}
        options={(Object.keys(LANGUAGE_LABELS) as Language[]).map((v) => ({
          value: v,
          label: LANGUAGE_LABELS[v],
        }))}
        ariaLabel="Answer language"
        className="w-full"
      />
    </div>
  );
}

/* ---------------- signature ---------------- */

/* Quiet on purpose — it only comes forward when someone goes looking. */
function CraftedBy() {
  return (
    <a
      href="https://billsharifzade.github.io/"
      target="_blank"
      rel="noreferrer noopener"
      title="crafted by qwantum"
      className="mt-3 hidden select-none text-center text-[10px] tracking-[0.08em] text-faint/40 transition-colors duration-500 hover:text-accent lg:block"
    >
      crafted by <span className="font-semibold">qwantum</span>
    </a>
  );
}

/* ---------------- app frame ---------------- */

export function Shell({ children }: { children: ReactNode }) {
  const { token, ready, disconnect, theme, toggleTheme, me } = useAuth();
  const pathname = usePathname();
  const chat = useChat();
  const onChat = pathname === "/";

  if (!ready) return null;
  if (!token) return <ConnectGate />;

  // Until identity resolves, show only the ungated destinations rather than
  // flashing admin links at someone who may not have them.
  const nav = NAV.filter(
    (item) => !item.gate || (me?.roles ?? []).some((r) => item.gate.includes(r)),
  );

  const activeLabel =
    NAV.find(({ href }) =>
      href === "/" ? pathname === "/" : pathname.startsWith(href),
    )?.label ?? "KARAG";

  return (
    <div className="flex min-h-dvh">
      {/* Sidebar */}
      <aside className="sticky top-0 z-20 flex h-dvh w-[72px] shrink-0 flex-col border-r border-line bg-surface/60 backdrop-blur-xl transition-[width] lg:w-64">
        <Link
          href="/"
          className="flex h-[72px] items-center justify-center border-b border-line px-5 lg:justify-start"
        >
          <span className="lg:hidden">
            <BrandLogo mark className="size-11" />
          </span>
          <span className="hidden lg:block">
            <BrandLogo className="h-12 w-auto" />
          </span>
        </Link>

        <nav className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto p-3.5">
          {nav.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <div key={href} className={onChat && href === "/" ? "contents" : ""}>
                <Link
                  href={href}
                  title={label}
                  className={`relative flex items-center justify-center gap-3 rounded-xl px-3.5 py-3 text-[14px] font-semibold transition-colors lg:justify-start ${
                    active ? "text-accent-strong" : "text-mut hover:text-ink"
                  }`}
                >
                  {active && (
                    <motion.span
                      layoutId="nav-pill"
                      transition={{ type: "spring", bounce: 0.18, duration: 0.5 }}
                      className="absolute inset-0 rounded-xl bg-accent-soft"
                    />
                  )}
                  <Icon className="relative z-10 size-[19px] shrink-0" />
                  <span className="relative z-10 hidden lg:block">{label}</span>
                </Link>

                {/* Chat's own contents, nested under it and only while you are
                    there. The rail is icon-only below lg, so the chat page
                    keeps a drawer for narrow screens. */}
                <AnimatePresence initial={false}>
                  {href === "/" && onChat && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
                      className="hidden overflow-hidden lg:block"
                    >
                      <div className="ml-4 max-h-[46vh] border-l border-line pb-2 pl-2.5 pt-1.5">
                        <ChatHistory
                          sessions={chat.sessions}
                          loading={chat.loadingSessions}
                          activeId={chat.activeId}
                          onNew={chat.newChat}
                          onOpen={(id) => void chat.openChat(id)}
                          onRename={(id, t) => void chat.renameChat(id, t)}
                          onDelete={(id) => void chat.deleteChat(id)}
                        />
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </nav>

        {/* session controls */}
        <div className="border-t border-line p-3.5">
          <LanguageSwitcher />
          <div className="mt-2 flex items-center justify-center gap-1 lg:justify-between">
            <button
              onClick={toggleTheme}
              title="Toggle theme"
              className="grid size-10 cursor-pointer place-items-center rounded-lg text-mut transition-colors hover:bg-surface-2 hover:text-ink"
            >
              {theme === "dark" ? (
                <Sun className="size-[18px]" />
              ) : (
                <Moon className="size-[18px]" />
              )}
            </button>
            <button
              onClick={disconnect}
              title="Disconnect"
              className="grid size-10 cursor-pointer place-items-center rounded-lg text-mut transition-colors hover:bg-bad-soft hover:text-bad"
            >
              <LogOut className="size-[18px]" />
            </button>
          </div>
          <CraftedBy />
        </div>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="glass sticky top-0 z-10 flex h-[72px] items-center gap-4 border-b border-line px-8">
          <AnimatePresence mode="wait">
            <motion.h2
              key={activeLabel}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.2 }}
              className="font-display text-[19px] font-bold tracking-tight"
            >
              {activeLabel}
            </motion.h2>
          </AnimatePresence>
        </header>
        <main className="mx-auto w-full max-w-[1520px] flex-1 px-8 py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
