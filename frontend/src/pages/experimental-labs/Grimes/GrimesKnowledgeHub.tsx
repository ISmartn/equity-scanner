import { useState } from "react";
import Dialog from "@mui/material/Dialog";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import type { GrimesKnowledgeResponse } from "@/lib/api";

type Props = {
  knowledge: GrimesKnowledgeResponse | null;
  checklist: GrimesKnowledgeResponse["checklists"][string] | null;
  checklistOpen: boolean;
  onCloseChecklist: () => void;
  showCards?: boolean;
};

export function GrimesKnowledgeHub({
  knowledge,
  checklist,
  checklistOpen,
  onCloseChecklist,
  showCards = true,
}: Props) {
  const [openId, setOpenId] = useState<string | null>("pullback");
  const cards = knowledge?.cards ?? [];

  return (
    <>
      {showCards ? (
      <div className="flex min-h-0 flex-col">
        <p className="mb-1.5 text-data-xs text-slate-400">
          Synthesis of Grimes Parts I–IV for execution. Chart markers explained in plain language on the{" "}
          <strong className="font-medium text-slate-300">Guide</strong> section and via the{" "}
          <strong className="font-medium text-slate-300">📖</strong> button on the chart. Full spec:{" "}
          <code className="text-slate-400">docs/adam_grimes_complete_framework.md</code> ·{" "}
          <code className="text-slate-400">docs/grimes_chart_guide.md</code>
        </p>
        <div className="flex flex-col gap-1">
          {cards.map((c) => {
            const open = openId === c.id;
            return (
              <div
                key={c.id}
                className="rounded-lg border border-surface-border bg-[#121820]"
              >
                <button
                  type="button"
                  className="flex w-full items-center justify-between px-2 py-1 text-left"
                  onClick={() => setOpenId(open ? null : c.id)}
                >
                  <span className="text-data-sm font-medium text-slate-200">
                    <span className="mr-1.5 text-[10px] text-slate-400">Pt {c.part}</span>
                    {c.title}
                  </span>
                  <span className="text-[10px] text-slate-400">{open ? "−" : "+"}</span>
                </button>
                {open ? (
                  <div className="border-t border-surface-border px-2 py-1.5 text-data-xs text-slate-300">
                    <p className="mb-1.5 text-slate-400">{c.summary}</p>
                    <ul className="list-disc space-y-0.5 pl-4">
                      {c.rules.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                    {c.failure ? (
                      <p className="mt-1.5 text-rose-300/90">Failure: {c.failure}</p>
                    ) : null}
                    {c.management ? (
                      <p className="mt-1 text-emerald-300/90">Manage: {c.management}</p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
      ) : null}

      <Dialog open={checklistOpen} onClose={onCloseChecklist} maxWidth="sm" fullWidth>
        <DialogTitle className="text-slate-100">
          {checklist?.title ?? "Execution checklist"}
        </DialogTitle>
        <DialogContent>
          {checklist ? (
            <dl className="space-y-2 text-[13px] text-slate-300">
              <div>
                <dt className="text-[10px] uppercase text-slate-400">Entry</dt>
                <dd>{checklist.entry}</dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase text-slate-400">Stop</dt>
                <dd>{checklist.stop}</dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase text-slate-400">Targets</dt>
                <dd>{checklist.targets}</dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase text-rose-400">Failure</dt>
                <dd>{checklist.fail}</dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase text-slate-400">Time stop</dt>
                <dd>{checklist.time_stop}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-slate-400">No active setup on this bar.</p>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
