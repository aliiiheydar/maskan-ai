"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ArrowLeft, Loader2, RotateCcw, Send, Sparkles } from "lucide-react";
import clsx from "clsx";

import { faDigits } from "@/lib/format";
import { useSearchStore } from "@/store/useSearchStore";

const MILLION = 1_000_000;

const STARTERS = [
  "دو خوابه نزدیک مترو در نارمک، تا ۵۰۰ پیش",
  "بین ۷۰ تا ۹۰ متر در سعادت‌آباد با آسانسور",
  "نوساز نزدیک میدان ونک، نزدیکی به مترو برام مهمه",
];

function millions(value: number): string {
  return Math.round(value / MILLION).toLocaleString("fa-IR");
}

/**
 * What the assistant understood, as chips. The conversation extracts filters
 * the user never typed into a form -- neighborhoods, a budget, an area range,
 * a priority -- and applying them invisibly would leave the user unable to
 * tell a misread from a genuinely empty result set.
 */
function UnderstoodFilters() {
  const state = useSearchStore();
  const byKey = useMemo(
    () => new Map(state.neighborhoodCatalog.map((n) => [n.key, n.title])),
    [state.neighborhoodCatalog],
  );

  const chips: string[] = [];
  for (const key of state.selectedNeighborhoods) chips.push(byKey.get(key) ?? key);
  if (state.minDepositToman || state.depositToman) {
    chips.push(
      `ودیعه ${state.minDepositToman ? millions(state.minDepositToman) : "۰"}–${
        state.depositToman ? millions(state.depositToman) : "∞"
      } م`,
    );
  }
  if (state.minRentToman || state.rentToman) {
    chips.push(
      `اجاره ${state.minRentToman ? millions(state.minRentToman) : "۰"}–${
        state.rentToman ? millions(state.rentToman) : "∞"
      } م`,
    );
  }
  if (state.minAreaSqm || state.maxAreaSqm) {
    chips.push(`${state.minAreaSqm || "۰"}–${state.maxAreaSqm || "∞"} متر`);
  }
  if (state.rooms) chips.push(`${state.rooms}+ خواب`);
  if (state.hasElevator) chips.push("آسانسور");
  if (state.hasParking) chips.push("پارکینگ");

  if (chips.length === 0) return null;

  return (
    <div className="border-t border-line-soft px-4 py-2.5">
      <p className="mb-1.5 text-xs font-medium text-slate-500">آنچه از گفتگو برداشت شد</p>
      <div className="flex flex-wrap gap-1.5">
        {chips.map((chip) => (
          <span key={chip} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">
            {chip}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function ChatPanel() {
  const { chatMessages, isChatStreaming, chatError, sendChatMessage, setFilters } = useSearchStore();
  // The user's own last turn, so a failed message can be resent without
  // retyping it -- retrying is the only useful action on a transport error,
  // and making the user scroll up and copy their sentence is not that.
  const lastUserMessage = useMemo(
    () => [...chatMessages].reverse().find((m) => m.role === "user")?.content ?? "",
    [chatMessages],
  );
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [chatMessages]);

  const send = (message: string) => {
    if (!message || isChatStreaming) return;
    setDraft("");
    void sendChatMessage(message);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* The filter panel opens with a section heading and this one opened
          with nothing, so switching modes read as the column having emptied
          rather than changed. It also gives «گفتگوی جدید» somewhere to live --
          starting over was previously only possible by reloading. */}
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-white px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-bold text-slate-800">
          <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-brand/10 text-brand">
            <Sparkles size={14} />
          </span>
          دستیار گفت‌وگو
          <span className="rounded-full bg-amber-100 px-1.5 py-px text-xs font-bold text-amber-700">بتا</span>
        </h2>
        {chatMessages.length > 0 && (
          <button
            type="button"
            onClick={() => setFilters({ chatMessages: [], chatError: null })}
            className="flex items-center gap-1 text-xs font-medium text-slate-500 transition hover:text-slate-800"
          >
            <RotateCcw size={13} />
            گفتگوی جدید
          </button>
        )}
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-4">
        {chatMessages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2.5 px-1 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-light text-brand">
              <Sparkles size={26} />
            </div>
            <p className="text-base font-bold text-slate-800">بگویید دنبال چه خانه‌ای می‌گردید</p>
            <p className="max-w-[34ch] text-sm leading-7 text-slate-600">
              محله، بودجه، متراژ و اولویت‌هایتان را به زبان خودتان بنویسید؛ فیلترها خودشان تنظیم می‌شوند.
            </p>
            {/* Said once, where the user is about to rely on it -- not buried
                in a tooltip on the tab. What it understood is always visible
                in the chips below, and the filter panel is one click away. */}
            <p className="max-w-[36ch] rounded-xl bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800 ring-1 ring-amber-200/70">
              این بخش نسخهٔ آزمایشی است و ممکن است بخشی از خواستهٔ شما را اشتباه بفهمد. برداشت دستیار همیشه
              پایین همین ستون نشان داده می‌شود و می‌توانید آن را در «جستجو و رتبه‌بندی» اصلاح کنید.
            </p>
            <div className="mt-3 flex w-full flex-col gap-2">
              <p className="text-start text-xs font-semibold text-slate-500">مثلاً بنویسید:</p>
              {STARTERS.map((starter) => (
                <button
                  key={starter}
                  type="button"
                  onClick={() => send(starter)}
                  className="flex items-center gap-2 rounded-xl border border-line bg-white px-3 py-2.5 text-start text-sm leading-6 text-slate-700 transition-all hover:border-brand hover:bg-brand-light/40 hover:text-brand"
                >
                  <ArrowLeft size={14} className="shrink-0 text-slate-400" />
                  {starter}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {chatMessages.map((message, i) => (
              <div key={i} className={clsx("flex", message.role === "user" ? "justify-start" : "justify-end")}>
                <div
                  className={clsx(
                    "max-w-[88%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm leading-7",
                    // The person's own words are the tinted ones; the
                    // assistant answers on plain paper. Green-on-green for
                    // every reply made the transcript read as a wall of
                    // highlighted text with the user's turn hidden in it.
                    message.role === "user"
                      ? "rounded-bl-md bg-brand text-white"
                      : "rounded-br-md border border-line bg-white text-slate-800",
                  )}
                >
                  {/* The model writes its figures in Latin numerals ("500
                      میلیون") while every price the app prints beside it is in
                      Persian ones. Transliterating the digits -- and nothing
                      else -- keeps one transcript from reading as two
                      languages. */}
                  {message.content ? faDigits(message.content) : <Loader2 className="animate-spin" size={14} />}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* An amber notice, not a red failure banner: the assistant being
            briefly unreachable is a hiccup the user can retry or route around
            with the filter panel, and styling it as an error makes the
            product look broken when it is not. */}
        {chatError && (
          <div className="mt-3 flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2.5">
            <AlertCircle size={15} className="mt-0.5 shrink-0 text-amber-500" />
            <div className="flex-1">
              <p className="text-xs leading-5 text-amber-800">{chatError}</p>
              <div className="mt-1.5 flex gap-3">
                {lastUserMessage && (
                  <button
                    type="button"
                    onClick={() => {
                      setFilters({ chatError: null });
                      void sendChatMessage(lastUserMessage);
                    }}
                    disabled={isChatStreaming}
                    className="flex items-center gap-1 text-xs font-medium text-amber-700 transition-opacity hover:opacity-70 disabled:opacity-40"
                  >
                    <RotateCcw size={12} />
                    تلاش دوباره
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setFilters({ mode: "ranked", chatError: null })}
                  className="text-xs font-medium text-amber-700 transition-opacity hover:opacity-70"
                >
                  رفتن به جستجو و رتبه‌بندی
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {chatMessages.length > 0 && <UnderstoodFilters />}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(draft.trim());
        }}
        className="flex items-center gap-2 border-t border-line p-3 pb-20 lg:pb-3"
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="پیام خود را بنویسید..."
          className="min-w-0 flex-1 rounded-full border border-line bg-slate-50 px-4 py-2.5 text-sm text-slate-800 outline-none transition-colors placeholder:text-slate-500 focus:border-brand focus:bg-white"
          disabled={isChatStreaming}
        />
        <button
          type="submit"
          disabled={isChatStreaming || !draft.trim()}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand text-white transition-opacity disabled:opacity-40"
          aria-label="ارسال"
        >
          {isChatStreaming ? <Loader2 className="animate-spin" size={16} /> : <Send size={16} />}
        </button>
      </form>
    </div>
  );
}
