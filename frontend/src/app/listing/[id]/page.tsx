import Link from "next/link";
import { ArrowRight, Building2 } from "lucide-react";

import ListingDetailLoader from "@/components/Listings/ListingDetail";

export const metadata = { title: "جزئیات ملک | مسکن‌یار" };

/** The listing on its own page: what a shared link, a new tab, or a refresh of
 * the modal's URL resolves to.
 *
 * Unlike the overlay, this owns the whole window -- there is no search behind
 * it to preserve -- so it gets a real site header, a wide content column and
 * the page layout of the detail view rather than the compact one.
 */
export default function ListingPage({ params }: { params: { id: string } }) {
  return (
    <main className="min-h-screen bg-slate-100/70">
      <header className="sticky top-0 z-20 border-b border-line bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-2.5 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-tier1 text-white shadow-sm shadow-tier1/25">
              <Building2 size={19} />
            </span>
            <span className="text-base font-bold tracking-tight text-slate-800">مسکن‌یار</span>
          </Link>
          {/* The way back is the primary action in this header, so it is a
              button rather than the faint text link it used to be: a shared
              link lands here with no history behind it, and "back" in the
              browser leaves the site entirely. */}
          <Link
            href="/"
            className="flex items-center gap-1.5 rounded-full border border-line bg-white px-3.5 py-1.5 text-sm font-semibold text-slate-700 transition hover:border-line-strong hover:bg-slate-50"
          >
            <ArrowRight size={15} />
            بازگشت به جستجو
          </Link>
        </div>
      </header>

      {/* No white sheet around the content: the detail view is itself a stack
          of white cards, and wrapping them in another one made every border
          inside it invisible. They sit on the slate ground instead. */}
      <div className="mx-auto max-w-5xl px-4 py-5 sm:px-6 sm:py-8">
        <ListingDetailLoader id={decodeURIComponent(params.id)} variant="page" />
      </div>
    </main>
  );
}
