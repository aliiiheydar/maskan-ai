"use client";

import { useEffect } from "react";
import dynamic from "next/dynamic";

import Header from "@/components/Header";
import ChatPanel from "@/components/Chat/ChatPanel";
import ClassicFilterPanel from "@/components/Filters/ClassicFilterPanel";
import ListingFeed from "@/components/Listings/ListingFeed";
import { useSearchStore } from "@/store/useSearchStore";

// Leaflet touches `window` at import time, so it can never run during SSR.
const NeshanMap = dynamic(() => import("@/components/Map/NeshanMap"), {
  ssr: false,
  loading: () => <div className="flex h-full items-center justify-center text-slate-400">در حال بارگذاری نقشه...</div>,
});

export default function Home() {
  const mode = useSearchStore((state) => state.mode);
  const runSearch = useSearchStore((state) => state.runSearch);

  useEffect(() => {
    runSearch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex h-screen flex-col">
      <Header />
      <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <section className="min-h-0 border-b border-slate-200 lg:w-[380px] lg:shrink-0 lg:border-b-0 lg:border-s lg:border-slate-200">
          {mode === "intelligent" ? <ChatPanel /> : <ClassicFilterPanel />}
        </section>

        <section className="min-h-[50vh] flex-1 lg:min-h-0 lg:basis-2/5">
          <ListingFeed />
        </section>

        <section className="min-h-[50vh] flex-1 lg:min-h-0 lg:basis-3/5">
          <NeshanMap />
        </section>
      </main>
    </div>
  );
}
