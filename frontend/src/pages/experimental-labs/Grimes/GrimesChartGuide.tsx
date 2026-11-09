import { useState } from "react";
import type { GrimesChartGuideItem, GrimesChartGuideSection } from "@/lib/api";

type Props = {
  intro: string;
  sections: GrimesChartGuideSection[];
  compact?: boolean;
  initialSection?: string;
};

function GuideItemCard({ item }: { item: GrimesChartGuideItem }) {
  return (
    <article className="rounded-lg border border-surface-border/80 bg-[#0f1419] p-2">
      <div className="mb-1.5 flex items-center gap-2">
        {item.symbol ? (
          <span
            className="shrink-0 font-mono text-[12px]"
            style={{ color: item.color ?? "#94a3b8" }}
          >
            {item.symbol}
          </span>
        ) : null}
        <h4 className="text-[12px] font-medium text-slate-100">{item.label}</h4>
      </div>
      <p className="mb-2 text-[11px] leading-relaxed text-slate-300">{item.plain}</p>
      <dl className="space-y-1 text-data-xs">
        <div>
          <dt className="font-medium uppercase tracking-wide text-sky-400/90">When you see it</dt>
          <dd className="mt-0.5 text-slate-400">{item.when}</dd>
        </div>
        <div>
          <dt className="font-medium uppercase tracking-wide text-emerald-400/90">
            What to expect next
          </dt>
          <dd className="mt-0.5 text-slate-400">{item.expect}</dd>
        </div>
        {item.worry && item.worry !== "—" ? (
          <div>
            <dt className="font-medium uppercase tracking-wide text-rose-400/90">When to worry</dt>
            <dd className="mt-0.5 text-slate-400">{item.worry}</dd>
          </div>
        ) : null}
      </dl>
    </article>
  );
}

export function GrimesChartGuide({ intro, sections, compact = false, initialSection }: Props) {
  const [openSection, setOpenSection] = useState<string | null>(
    initialSection ?? sections[0]?.id ?? null,
  );

  if (!sections.length) {
    return (
      <p className="p-2 text-data-sm text-slate-400">
        Chart guide loading… Reload the page or check{" "}
        <code className="text-slate-400">docs/grimes_chart_guide.md</code>.
      </p>
    );
  }

  return (
    <div className={`flex min-h-0 flex-col ${compact ? "" : "h-full"}`}>
      <p className={`shrink-0 text-slate-400 ${compact ? "mb-2 text-[11px]" : "mb-1.5 px-2 pt-1 text-data-sm"}`}>
        {intro}
      </p>
      {!compact ? (
        <p className="mb-1.5 shrink-0 px-2 text-[10px] text-slate-400">
          Full reference:{" "}
          <code className="text-slate-400">docs/grimes_chart_guide.md</code>
        </p>
      ) : null}
      <div className={`min-h-0 flex-1 space-y-1.5 overflow-auto ${compact ? "" : "px-2 pb-2"}`}>
        {sections.map((section) => {
          const open = openSection === section.id;
          return (
            <section
              key={section.id}
              className="rounded-lg border border-surface-border bg-[#121820]"
            >
              <button
                type="button"
                className="flex w-full items-center justify-between px-2 py-1 text-left"
                onClick={() => setOpenSection(open ? null : section.id)}
              >
                <span className="text-data-sm font-medium text-slate-200">{section.title}</span>
                <span className="text-[10px] text-slate-400">{open ? "−" : "+"}</span>
              </button>
              {open ? (
                <div className="space-y-2 border-t border-surface-border px-2 py-1.5">
                  <p className="text-data-xs text-slate-400">{section.blurb}</p>
                  <div className="grid gap-2 sm:grid-cols-1">
                    {section.items.map((item) => (
                      <GuideItemCard key={item.id} item={item} />
                    ))}
                  </div>
                </div>
              ) : null}
            </section>
          );
        })}
      </div>
    </div>
  );
}
