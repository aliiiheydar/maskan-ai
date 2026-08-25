"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Send, Sparkles } from "lucide-react";
import clsx from "clsx";

import { useSearchStore } from "@/store/useSearchStore";

export default function ChatPanel() {
  const { chatMessages, isChatStreaming, chatError, sendChatMessage, tier1Results } = useSearchStore();
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [chatMessages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const message = draft.trim();
    if (!message || isChatStreaming) return;
    setDraft("");
    sendChatMessage(message);
  };

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4">
        {chatMessages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-slate-400">
            <Sparkles size={28} />
            <p className="text-sm">
              بگویید دنبال چه خانه‌ای می‌گردید؛ مثلاً «آپارتمان دو خوابه نزدیک مترو با آسانسور تا سقف ۲۰ تومن اجاره»
            </p>
          </div>
        )}

        <div className="flex flex-col gap-3">
          {chatMessages.map((message, i) => (
            <div
              key={i}
              className={clsx("flex", message.role === "user" ? "justify-start" : "justify-end")}
            >
              <div
                className={clsx(
                  "max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm leading-relaxed",
                  message.role === "user"
                    ? "rounded-bl-sm bg-slate-100 text-slate-800"
                    : "rounded-br-sm bg-tier1-light text-tier1",
                )}
              >
                {message.content || (
                  <Loader2 className="animate-spin" size={14} />
                )}
              </div>
            </div>
          ))}
        </div>

        {chatError && (
          <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{chatError}</p>
        )}

        {!isChatStreaming && chatMessages.length > 0 && tier1Results.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {tier1Results.slice(0, 3).map((listing) => (
              <span
                key={listing.id}
                className="rounded-full bg-tier1 px-2.5 py-1 text-xs font-medium text-white"
              >
                {listing.neighborhood} · %{Math.round(listing.utility_score * 100)}
              </span>
            ))}
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex items-center gap-2 border-t border-slate-200 p-3">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="پیام خود را بنویسید..."
          className="flex-1 rounded-full border border-slate-300 px-4 py-2 text-sm outline-none focus:border-tier1"
          disabled={isChatStreaming}
        />
        <button
          type="submit"
          disabled={isChatStreaming || !draft.trim()}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-tier1 text-white disabled:opacity-40"
        >
          {isChatStreaming ? <Loader2 className="animate-spin" size={16} /> : <Send size={16} />}
        </button>
      </form>
    </div>
  );
}
