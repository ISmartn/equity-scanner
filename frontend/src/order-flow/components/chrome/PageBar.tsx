import { forwardRef, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import './PageBar.css';
import { PageInfo } from './PageInfo';
import type { PageTerm } from './pageInfoContent';
import { WebsitePreviewSearch, WebsitePreviewTheme, useWebsitePreviewControls } from '../WebsitePreviewControls';

/** Trailing slashes only: these are app routes, never external URLs. */
const samePath = (a: string, b: string) => a.replace(/\/+$/, '') === b.replace(/\/+$/, '');

interface PageBarCrumb {
  label: string;
  to?: string;
}

interface PageBarProps {
  current: string;
  /** Short visible title for narrow headers; the breadcrumb keeps the full name. */
  compactTitle?: string;
  breadcrumbAction?: ReactNode;
  /** The ⓘ's entry when the page explains itself under a different name from its title (the builder's Finder view). */
  infoKey?: string;
  /** Terms that lead the ⓘ card's glossary (see PageInfo). */
  infoTerms?: PageTerm[];
  homeTo?: string;
  parent?: PageBarCrumb;
  children?: ReactNode;
  className?: string;
  label?: string;
  /** False drops the breadcrumb and its ⓘ, leaving only the page's controls. */
  crumbs?: boolean;
  /** A product wordmark drawn at the start of the bar (Order Flow's title). */
  brand?: ReactNode;
}

/** The shared page-level navigation row below the terminal shell. */
export const PageBar = forwardRef<HTMLElement, PageBarProps>(function PageBar({
  current,
  compactTitle,
  breadcrumbAction,
  infoKey,
  infoTerms,
  homeTo = '/option-chain',
  parent,
  children,
  className,
  label = 'Workspace controls',
  crumbs = true,
  brand,
}, ref) {
  const parentSegment = parent?.label !== current ? parent : undefined;
  const preview = useWebsitePreviewControls();

  /* `homeTo` defaults to the Option Chain, which IS the chain's own route — so
     on that page "Home" was a link to the page you are already standing on,
     and on a phone it was drawn as the back chevron: a control that looks like
     the way out and does nothing. A breadcrumb never links to itself, so it
     becomes plain text here, and the phone rules drop the chevron with it
     (`li:nth-last-child(3):not(:has(a))`). That reclaims 42px of a 320px row
     for the controls that DO something. */
  const homeIsHere = samePath(homeTo, useLocation().pathname);

  return (
    <section ref={ref} className={['ui-pagebar', className].filter(Boolean).join(' ')} aria-label={label}>
      {brand}
      {crumbs && <nav className="ui-pagebar__crumbs" aria-label="Breadcrumb">
        <ol>
          <li>{homeIsHere ? <span className="ui-pagebar__here">Home</span> : <Link to={homeTo}>Home</Link>}</li>
          <li className="ui-pagebar__chev" aria-hidden="true" />
          {parentSegment ? (
            <>
              <li>{parentSegment.to ? <Link to={parentSegment.to}>{parentSegment.label}</Link> : parentSegment.label}</li>
              <li className="ui-pagebar__chev" aria-hidden="true" />
            </>
          ) : null}
          <li className="ui-pagebar__current" aria-current="page" title={current}>
            {compactTitle ? <>
              <span className="ui-pagebar__title-full">{current}</span>
              <span className="ui-pagebar__title-compact" aria-hidden="true">{compactTitle}</span>
            </> : current}
          </li>
        </ol>
        {breadcrumbAction ?? <PageInfo key={infoKey ?? current} current={infoKey ?? current} extraTerms={infoTerms} />}
      </nav>}
      {preview?.ticker ? <div className="ui-pagebar__ticker">{preview.ticker}</div> : null}
      {/* Search, then the theme switch at the far right, on every page (owner, 10 Oct). */}
      {children || preview ? <div className="ui-pagebar__actions">{children}<WebsitePreviewSearch /><WebsitePreviewTheme /></div> : null}
    </section>
  );
});
