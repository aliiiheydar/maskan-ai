"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, ImageOff, ShieldAlert } from "lucide-react";
import clsx from "clsx";

import { imageUrl } from "@/lib/api";

/**
 * The photo strip on the detail view.
 *
 * Photos are loaded one at a time on purpose: they come from Divar's CDN
 * through our proxy, and eagerly pulling eight full-size JPEGs per listing
 * would make opening a card feel slower than it is. Each frame keeps its
 * 4:3 box whether or not the image arrives, so the layout never jumps.
 */
export default function ListingGallery({
  images,
  title,
  authentic = true,
  variant = "modal",
}: {
  images: string[];
  title: string;
  authentic?: boolean;
  /** The standalone page gets a cinematic 16:9 hero; the modal keeps the
   * squarer 4:3 frame, which shows more of a room in the same width and
   * leaves space for the rest of the listing above the fold. */
  variant?: "modal" | "page";
}) {
  // 3:2 rather than 4:3 in the overlay: at 4:3 the photo filled a laptop
  // viewport on its own and the price sat below the fold on the one surface
  // whose whole job is a quick verdict.
  const frame = variant === "page" ? "aspect-[16/9]" : "aspect-[3/2]";
  const [index, setIndex] = useState(0);
  const [failed, setFailed] = useState<Set<number>>(new Set());
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setIndex(0);
  }, [images]);

  useEffect(() => {
    setLoaded(false);
  }, [index]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // The document is RTL but the photo order is not: ArrowLeft always means
      // "the next photo" here, matching how the on-screen chevrons point.
      if (event.key === "ArrowLeft") setIndex((i) => Math.min(i + 1, images.length - 1));
      if (event.key === "ArrowRight") setIndex((i) => Math.max(i - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [images.length]);

  if (images.length === 0) {
    return (
      <div className={clsx("flex w-full items-center justify-center rounded-2xl bg-slate-100 text-slate-500", frame)}>
        <div className="flex flex-col items-center gap-2 text-xs">
          <ImageOff size={26} />
          این آگهی تصویری ندارد
        </div>
      </div>
    );
  }

  const current = imageUrl(images[index]);
  const isBroken = failed.has(index);

  return (
    <div className="space-y-2">
      <div className={clsx("relative w-full overflow-hidden rounded-2xl bg-slate-200 ring-1 ring-line", frame)}>
        {!loaded && !isBroken && <div className="absolute inset-0 animate-pulse bg-slate-200/70" />}
        {isBroken ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-xs text-slate-500">
            <ImageOff size={26} />
            بارگذاری این تصویر ممکن نشد
          </div>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            // Keyed on the URL so switching photos remounts the element, which
            // is what re-runs the ref below.
            key={current}
            ref={(element) => {
              // A cached image is already decoded by the time React attaches
              // onLoad, so that event never fires and the fade-in would leave
              // the photo permanently transparent. Asking the element whether
              // it is already complete covers exactly that case.
              if (element?.complete && element.naturalWidth > 0) setLoaded(true);
            }}
            src={current ?? ""}
            alt={`${title} — تصویر ${index + 1}`}
            className={clsx("h-full w-full object-cover transition-opacity", loaded ? "opacity-100" : "opacity-0")}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed((previous) => new Set(previous).add(index))}
          />
        )}

        {images.length > 1 && (
          <>
            <button
              type="button"
              aria-label="تصویر بعدی"
              onClick={() => setIndex((i) => Math.min(i + 1, images.length - 1))}
              disabled={index === images.length - 1}
              className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-white/85 p-1.5 text-slate-700 shadow-sm transition hover:bg-white disabled:opacity-0"
            >
              <ChevronLeft size={18} />
            </button>
            <button
              type="button"
              aria-label="تصویر قبلی"
              onClick={() => setIndex((i) => Math.max(i - 1, 0))}
              disabled={index === 0}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-white/85 p-1.5 text-slate-700 shadow-sm transition hover:bg-white disabled:opacity-0"
            >
              <ChevronRight size={18} />
            </button>
            <span className="absolute bottom-2 right-2 rounded-full bg-slate-900/75 px-2.5 py-1 text-xs font-semibold tabular-nums text-white">
              {(index + 1).toLocaleString("fa-IR")} / {images.length.toLocaleString("fa-IR")}
            </span>
          </>
        )}
      </div>

      {/* Divar asks the advertiser to confirm the photos show this unit. A "no"
          is a real warning about the listing, not a rendering detail. */}
      {!authentic && (
        <p className="flex items-center gap-1.5 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700">
          <ShieldAlert size={13} />
          آگهی‌دهنده اعلام کرده تصاویر مربوط به همین ملک نیست.
        </p>
      )}

      {images.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {images.map((source, position) => (
            <button
              key={source}
              type="button"
              onClick={() => setIndex(position)}
              className={clsx(
                "h-14 w-20 shrink-0 overflow-hidden rounded-lg border-2 bg-slate-100 transition",
                position === index ? "border-tier1" : "border-transparent opacity-70 hover:opacity-100",
              )}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={imageUrl(source) ?? ""}
                alt=""
                loading="lazy"
                className="h-full w-full object-cover"
                onError={(event) => {
                  event.currentTarget.style.visibility = "hidden";
                }}
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
