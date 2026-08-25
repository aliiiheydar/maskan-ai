"use client";

import { Building2, Sparkles, SlidersHorizontal } from "lucide-react";

import { useSearchStore } from "@/store/useSearchStore";

export default function Header() {
  const mode = useSearchStore((state) => state.mode);
  const setMode = useSearchStore((state) => state.setMode);

  return (
    <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 shadow-sm sm:px-6">
      <div className="flex items-center gap-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-tier1 text-white">
          <Building2 size={20} />
        </div>
        <span className="text-lg font-bold text-slate-800">مسکن‌یار</span>
      </div>

      <div className="flex items-center rounded-full border border-slate-200 bg-slate-100 p-1 text-sm font-medium">
        <button
          type="button"
          onClick={() => setMode("intelligent")}
          className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 transition-colors ${
            mode === "intelligent" ? "bg-white text-tier1 shadow" : "text-slate-500 hover:text-slate-700"
          }`}
        >
          <Sparkles size={16} />
          هوشمند
        </button>
        <button
          type="button"
          onClick={() => setMode("classic")}
          className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 transition-colors ${
            mode === "classic" ? "bg-white text-tier1 shadow" : "text-slate-500 hover:text-slate-700"
          }`}
        >
          <SlidersHorizontal size={16} />
          فیلتر کلاسیک
        </button>
      </div>
    </header>
  );
}
