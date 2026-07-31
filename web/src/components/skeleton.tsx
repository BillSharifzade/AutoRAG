"use client";

/* Global skeleton system — a small set of shimmer primitives plus per-page
   skeletons shaped like the real content, so the swap to loaded data is
   seamless. The shimmer + reduced-motion handling live in globals.css. */

import { motion } from "motion/react";
import type { CSSProperties, ReactNode } from "react";

/* ---------- primitives ---------- */

export function Skeleton({
  className = "",
  style,
  accent = false,
}: {
  className?: string;
  style?: CSSProperties;
  /** red-tinted sweep for hero elements */
  accent?: boolean;
}) {
  return (
    <div
      className={`${accent ? "skeleton-accent" : "skeleton"} rounded-lg ${className}`}
      style={style}
    />
  );
}

export function SkeletonText({
  lines = 3,
  className = "",
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={`flex flex-col gap-2.5 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className="h-3"
          // last line is shorter, like real wrapped text
          style={{ width: i === lines - 1 ? "60%" : "100%" }}
        />
      ))}
    </div>
  );
}

/* Fades a whole skeleton screen in/out gently so it never pops. */
export function SkeletonScreen({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25 }}
      aria-hidden
      className={className}
    >
      {children}
    </motion.div>
  );
}

function SkelCard({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl border border-line bg-surface [box-shadow:var(--shadow-sm)] ${className}`}
    >
      {children}
    </div>
  );
}

function SkelCardHeader() {
  return (
    <div className="flex items-center gap-3 border-b border-line px-6 py-5">
      <Skeleton className="size-8 shrink-0 rounded-lg" />
      <div className="flex flex-1 flex-col gap-2">
        <Skeleton className="h-3.5 w-40" />
        <Skeleton className="h-2.5 w-64 max-w-[70%]" />
      </div>
    </div>
  );
}

/* ---------- usage page ---------- */

export function UsageSkeleton() {
  return (
    <SkeletonScreen className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-56" />
        </div>
        <Skeleton className="h-10 w-72 rounded-xl" />
      </div>
      <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkelCard key={i} className="p-6">
            <div className="flex items-center justify-between">
              <Skeleton className="h-2.5 w-24" />
              <Skeleton className="size-9 rounded-lg" />
            </div>
            <Skeleton className="mt-5 h-9 w-28" accent />
          </SkelCard>
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <SkelCard key={i}>
            <SkelCardHeader />
            <div className="grid place-items-center p-8">
              <Skeleton className="size-44 rounded-full" accent />
            </div>
          </SkelCard>
        ))}
      </div>
      <SkelCard>
        <SkelCardHeader />
        <div className="flex h-56 items-end gap-[5px] p-6">
          {Array.from({ length: 24 }).map((_, i) => (
            <Skeleton
              key={i}
              className="flex-1 rounded-t-md"
              style={{ height: `${20 + ((i * 37) % 80)}%` }}
            />
          ))}
        </div>
      </SkelCard>
    </SkeletonScreen>
  );
}

/* ---------- audit page ---------- */

export function AuditSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <SkeletonScreen>
      <SkelCard>
        <SkelCardHeader />
        <div className="flex flex-col gap-3 p-6">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="flex items-center gap-4">
              <Skeleton className="size-9 shrink-0 rounded-xl" />
              <Skeleton className="h-3.5 w-28" />
              <Skeleton className="h-5 w-16 rounded-md" />
              <Skeleton className="hidden h-3 w-24 sm:block" />
              <Skeleton className="ml-auto hidden h-3 w-40 md:block" />
            </div>
          ))}
        </div>
      </SkelCard>
    </SkeletonScreen>
  );
}

/* ---------- assistants page ---------- */

export function AssistantsSkeleton() {
  return (
    <SkeletonScreen className="grid items-start gap-6 xl:grid-cols-12">
      <div className="flex flex-col gap-2.5 xl:col-span-3">
        <Skeleton className="h-10 w-full rounded-xl" />
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-3.5"
          >
            <Skeleton className="h-3.5 w-32" />
            <Skeleton className="h-2.5 w-40" />
          </div>
        ))}
      </div>
      <SkelCard className="xl:col-span-5">
        <SkelCardHeader />
        <div className="flex flex-col gap-4 p-6">
          <Skeleton className="h-10 w-full rounded-xl" />
          <Skeleton className="h-24 w-full rounded-xl" />
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-xl" />
          ))}
        </div>
      </SkelCard>
      <SkelCard className="xl:col-span-4">
        <SkelCardHeader />
        <div className="grid place-items-center p-10">
          <Skeleton className="size-12 rounded-2xl" accent />
        </div>
      </SkelCard>
    </SkeletonScreen>
  );
}

/* ---------- chat history rail ---------- */

export function ChatListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-1.5" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex flex-col gap-2 rounded-xl px-3 py-2.5">
          <Skeleton className="h-3 w-full" style={{ width: `${90 - (i % 3) * 15}%` }} />
          <Skeleton className="h-2 w-16" />
        </div>
      ))}
    </div>
  );
}
