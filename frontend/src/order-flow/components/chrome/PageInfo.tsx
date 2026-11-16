import { useCallback, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { ArrowUpRight, InfoIcon, Warning, X } from '@/order-flow/assets/svg/icons';
import { useDialog } from '@/order-flow/components/common/useDialog';
import { CapsuleSegmented, type CapsuleOption } from '@/order-flow/components/common/CapsuleSegmented';
import { termHref } from '@/order-flow/content/terms';
import { guideHref, PAGE_EXPLANATIONS, type GuideAnchorPart, type PageExplanation, type PageTerm } from './pageInfoContent';
import './PageInfo.css';

export type { PageAction, PageExplanation, PageTerm } from './pageInfoContent';

/**
 * The full per-workspace ⓘ explanation (contract §5.4 shape): a lead, what the
 * view measures, numbered steps for reading it, and a caution on the amber
 * rule, then the reference detail a reader comes back for — the page's own
 * controls, a glossary of what it prints, a few reading habits — and a link to
 * the matching guide. The words live in `pageInfoContent.ts`; this file is the
 * dialog. Open Interest renders the same dialog from its own per-chart-view
 * entries (`OpenInterestPage.tsx`'s `OI_VIEW_HELP`), so every workspace's ⓘ
 * opens one surface.
 *
 * Written the same way OI's own entries are: say what the view IS, then what
 * it DRAWS, in the terms the page itself uses for its axes and controls. The
 * "How to read it" steps are reading instructions for the chart in front of
 * the reader ("start at…", "compare…") — the same imperative voice OI's own
 * entries use — not a forecast or an instruction to trade, which is what the
 * caution and the tone rule (contract §5.4, `insightCopyTone.test.ts`) forbid.
 */

/** Glossary rows shown before "Show all terms" on a phone. */
const PHONE_TERMS = 4;
type HelpSection = 'overview' | 'controls' | 'terms' | 'guide';

/** The headings the card prints, spoken in the link that points each one into the guide. */
const PART_LABEL: Record<GuideAnchorPart, string> = {
  measures: 'What it measures',
  steps: 'How to read it',
  caution: 'Caution',
  actions: 'What you can do here',
  terms: 'Key terms',
};

/**
 * FOCUS RETURN is explicit, the same reason the Open Interest dialog stated it:
 * `useDialog` restores focus to whatever held it when the dialog opened, and
 * that is not always the ⓘ button — Safari does not focus a clicked button —
 * so closing by any route (×, scrim, Escape) hands focus back to the
 * trigger first (contract §8).
 */
export function PageInfoDialog({ help, onClose, anchorRef, closeLabel, dismissLabel, id }: {
  help: PageExplanation;
  onClose: () => void;
  anchorRef: RefObject<HTMLButtonElement | null>;
  /** Accessible names for the two ways out; the defaults name the page. */
  closeLabel?: string;
  dismissLabel?: string;
  /** The dialog's DOM id, when the trigger names it in `aria-controls` (a widget's carries its scope). */
  id?: string;
}) {
  const dialogRef = useRef<HTMLElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const [bodyScrolls, setBodyScrolls] = useState(false);
  const [termsOpen, setTermsOpen] = useState(false);
  const [section, setSection] = useState<HelpSection>('overview');
  const sections: CapsuleOption<HelpSection>[] = [
    { value: 'overview', label: 'Overview' },
    ...(help.actions?.length ? [{ value: 'controls' as const, label: 'Controls' }] : []),
    ...(help.terms?.length ? [{ value: 'terms' as const, label: 'Key terms' }] : []),
    ...(help.guide && help.glimpse ? [{ value: 'guide' as const, label: 'Guide' }] : []),
  ];
  const close = useCallback(() => {
    anchorRef.current?.focus({ preventScroll: true });
    onClose();
  }, [anchorRef, onClose]);

  /* The body is the one scroller, with a keyboard stop when content overflows. */
  const measure = useCallback(() => {
    const body = bodyRef.current;
    if (!body) return;
    const scrolls = body.scrollHeight > body.clientHeight + 1;
    setBodyScrolls(current => (current === scrolls ? current : scrolls));
  }, []);
  useLayoutEffect(() => {
    const body = bodyRef.current;
    if (!body) return undefined;
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    observer?.observe(body);
    return () => observer?.disconnect();
  }, [help, termsOpen, section, measure]);
  useLayoutEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = 0;
  }, [help, section]);
  useDialog(true, close, { ref: dialogRef });

  const uid = useId();
  const titleId = `${uid}-title`;
  const leadId = `${uid}-lead`;
  const termsId = `${uid}-terms`;
  const glimpseId = `${uid}-glimpse`;
  const terms = help.terms ?? [];
  const collapsible = terms.length > PHONE_TERMS;
  /* A section heading: the label, and (when the guide teaches that part) a link to the guide's matching section. */
  const head = (part: GuideAnchorPart, label: ReactNode) => {
    const anchor = help.guide ? help.guideAnchors?.[part] : undefined;
    return (
      <div className="ui-page-info-dialog__sechead">
        <h3>{label}</h3>
        {help.guide && anchor && (
          <a className="ui-page-info-dialog__learn" href={guideHref(help.guide, anchor)} target="_blank" rel="noopener noreferrer">
            <span aria-hidden="true">In the guide</span>
            <ArrowUpRight size={12} weight="bold" aria-hidden="true" />
            <span className="ui-page-info-dialog__sr">In the guide: {PART_LABEL[part]} (opens in a new tab)</span>
          </a>
        )}
      </div>
    );
  };
  /* PORTALLED to <body>. The ⓘ sits inside the page bar's breadcrumb `nav`, whose
     `ol` / `li` / `a` rules (nowrap 11px crumbs, `li` hidden on phones) would
     otherwise restyle every list and link in the dialog. The strike studio and the
     other fixed layers are portalled for the same reason. */
  return createPortal(
    <>
      {/* tabIndex -1: a pointer target, not a stop — matching the app's other
          explanation dialogs (Open Interest, Open Interest Spurts). */}
      <button type="button" tabIndex={-1} className="ui-page-info-dialog-scrim" aria-label={dismissLabel ?? `Dismiss ${help.title} explanation`} onClick={close} />
      <aside ref={dialogRef} id={id} tabIndex={-1} className="ui-page-info-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={leadId}>
        <i className="ui-page-info-dialog__grab" aria-hidden="true" />
        <header className="ui-page-info-dialog__head">
          <div className="ui-page-info-dialog__heading">
            <h2 id={titleId} className="ui-page-info-dialog__title">{help.title}</h2>
            <p id={leadId}>{help.summary}</p>
          </div>
          <button type="button" className="ui-page-info-dialog__close" aria-label={closeLabel ?? `Close ${help.title} explanation`} onClick={close}><X size={16} weight="bold" aria-hidden="true" /></button>
        </header>
        <div className="ui-page-info-dialog__tabs">
          <CapsuleSegmented options={sections} value={section} onChange={setSection} role="tablist" ariaLabel="Explanation sections" groupId={`${uid}-sections`} fill />
        </div>
        <div
          ref={bodyRef}
          className="ui-page-info-dialog__body"
          tabIndex={bodyScrolls ? 0 : undefined}
          onScroll={measure}
          role="tabpanel"
          aria-label={sections.find(item => item.value === section)?.label}
        >
          {help.legend && help.legend.length > 0 && (
            <ul role="list" hidden={section !== 'overview'} className="ui-page-info-dialog__legend" aria-label="Colour key">
              {help.legend.map(chip => (
                <li key={chip.label} data-tone={chip.tone}>
                  <b>{chip.label}</b>
                  {chip.hint ? <span>{chip.hint}</span> : null}
                </li>
              ))}
            </ul>
          )}
          <section hidden={section !== 'overview'}>
            {head('measures', <span>What it measures</span>)}
            <p>{help.measures}</p>
          </section>
          <section hidden={section !== 'overview'}>
            {head('steps', <span>How to read it</span>)}
            {/* role="list": `list-style: none` makes Safari drop list semantics. */}
            <ol role="list" className="ui-page-info-dialog__steps">{help.steps.map(step => <li key={step}>{step}</li>)}</ol>
          </section>
          <section hidden={section !== 'overview'} className="ui-page-info-dialog__caution">
            {head('caution', <><Warning size={14} weight="fill" aria-hidden="true" /><span>Caution</span></>)}
            <p>{help.caution}</p>
          </section>
          {help.actions && help.actions.length > 0 && (
            <section hidden={section !== 'controls'}>
              {head('actions', <span>What you can do here</span>)}
              <dl className="ui-page-info-dialog__actions">
                {help.actions.map(action => (
                  <div key={action.label}>
                    <dt>{action.label}</dt>
                    <dd>{action.text}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}
          {terms.length > 0 && (
            <section hidden={section !== 'terms'}>
              {head('terms', <span>Key terms</span>)}
              <dl id={termsId} className={['ui-page-info-dialog__terms', termsOpen ? 'is-expanded' : ''].filter(Boolean).join(' ')}>
                {terms.map(entry => (
                  <div key={entry.term} data-tone={entry.tone}>
                    <dt>{entry.id
                      ? <a href={termHref(entry.id)} target="_blank" rel="noopener noreferrer" aria-label={`${entry.term}: open its glossary entry in a new tab`}>{entry.term}</a>
                      : entry.term}</dt>
                    <dd>{entry.meaning}</dd>
                  </div>
                ))}
              </dl>
              {collapsible && (
                <button type="button" className="ui-page-info-dialog__more" aria-expanded={termsOpen} aria-controls={termsId} onClick={() => setTermsOpen(open => !open)}>
                  {termsOpen ? 'Show fewer terms' : `Show all ${terms.length} terms`}
                </button>
              )}
            </section>
          )}
          {help.tips && help.tips.length > 0 && (
            <section hidden={section !== 'controls'}>
              <div className="ui-page-info-dialog__sechead"><h3><span>Quick tips</span></h3></div>
              <ul role="list" className="ui-page-info-dialog__tips">{help.tips.map(tip => <li key={tip}>{tip}</li>)}</ul>
            </section>
          )}
          {help.guide && help.glimpse && (
            <section hidden={section !== 'guide'} className="ui-page-info-dialog__glimpse" aria-labelledby={glimpseId}>
              <div className="ui-page-info-dialog__sechead"><h3 id={glimpseId}><span>From the guide</span></h3></div>
              {help.glimpse.image && (
                <a className="ui-page-info-dialog__shot" href={guideHref(help.guide)} target="_blank" rel="noopener noreferrer" tabIndex={-1} aria-hidden="true">
                  {/* Two files, one shown: the app's theme picks. A hidden lazy image is never fetched, so a reader downloads one. */}
                  <img className="is-dark" src={help.glimpse.image.src} width={help.glimpse.image.width} height={help.glimpse.image.height} alt="" loading="lazy" decoding="async" />
                  <img className="is-light" src={help.glimpse.image.srcLight} width={help.glimpse.image.width} height={help.glimpse.image.height} alt="" loading="lazy" decoding="async" />
                </a>
              )}
              <p className="ui-page-info-dialog__glimpse-title">{help.glimpse.title}</p>
              <p>{help.glimpse.lead}</p>
              {help.glimpse.example && (
                <p className="ui-page-info-dialog__example"><b>A real example</b>{help.glimpse.example}</p>
              )}
              <ul role="list" className="ui-page-info-dialog__doors" aria-label="Start with">
                {help.glimpse.doors.map(door => (
                  <li key={door.anchor}>
                    <a href={guideHref(help.guide!, door.anchor)} target="_blank" rel="noopener noreferrer">
                      <span>{door.label}</span>
                      <ArrowUpRight size={12} weight="bold" aria-hidden="true" />
                      <span className="ui-page-info-dialog__sr">(opens in a new tab)</span>
                    </a>
                  </li>
                ))}
              </ul>
              {help.glimpse.image && <span className="ui-page-info-dialog__sr">{help.glimpse.image.alt}</span>}
            </section>
          )}
        </div>
        {help.guide && (
          <footer className="ui-page-info-dialog__foot">
            <a href={guideHref(help.guide)} target="_blank" rel="noopener noreferrer">
              <span>Read the full guide</span>
              <ArrowUpRight size={14} weight="bold" aria-hidden="true" />
              <span className="ui-page-info-dialog__sr">(opens in a new tab)</span>
            </a>
            <span className="ui-page-info-dialog__hint" aria-hidden="true">Esc to close</span>
          </footer>
        )}
      </aside>
    </>,
    document.body,
  );
}

/**
 * `extraTerms` lead the card's Key terms: a page whose paint changes with its
 * settings (the heatmap's key) supplies the reading of what is on screen now.
 */
export function PageInfo({ current, extraTerms }: { current: string; extraTerms?: PageTerm[] }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const dialogId = useId();
  const base = PAGE_EXPLANATIONS[current];
  if (!base) return null;
  // A page term replaces the static one of the same name (the heatmap's live
  // "Build-up" reading over the card's general one), never sits beside it.
  const help = extraTerms?.length
    ? { ...base, terms: [...extraTerms, ...(base.terms ?? []).filter(entry => !extraTerms.some(extra => extra.term === entry.term))] }
    : base;
  return <span className="ui-page-info">
    <button ref={button} type="button" aria-label={`About ${current}`} title={`How to read ${current}`} aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? dialogId : undefined} onClick={() => setOpen(true)}>
      <InfoIcon size={16} weight="bold" aria-hidden="true" />
    </button>
    {open && <PageInfoDialog id={dialogId} help={help} anchorRef={button} onClose={() => setOpen(false)} />}
  </span>;
}
