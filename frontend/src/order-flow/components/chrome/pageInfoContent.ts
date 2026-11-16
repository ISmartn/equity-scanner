/**
 * The words behind every page's ⓘ dialog, kept apart from the dialog's markup.
 *
 * One entry per workspace, keyed by the same `current` string `PageBar` passes
 * (Open Interest is the exception: its four chart views carry their own entries
 * in `OpenInterestPage.tsx` and render through the same dialog).
 *
 * SOURCING. Every sentence here comes from a guide under `public/guides/`, a doc
 * under `docs/`, or the code the page runs on. Where a guide was listed as wrong
 * by `docs/audits/GUIDE-ACCURACY-AUDIT-2026-10.md` (a streaming feed, an
 * alert engine on Open Interest Spurts, an expected move equal to the whole
 * straddle) the claim is not repeated; the figure is taken from `src` instead.
 * Market facts that cannot be checked in the repo (lot sizes, expiry weekdays,
 * index levels) are left out on purpose.
 *
 * VOICE. Descriptive, never advisory (design contract §5.4). Sides read Call and
 * Put, Open Interest is written out, the four build-ups use their full names and
 * figures carry no grouping comma (docs/UI-TERMINOLOGY.md, enforced by
 * `src/utils/marketVocabulary.test.ts`, which scans this file).
 */

/**
 * The colour a marker carries, matched to the chart: Call and Put read as the
 * Option Chain draws them, up and down as a build-up's premium leg, warn is the
 * amber of Max pain and cautions, accent is the brand.
 */
import { pageTerm } from '@/order-flow/content/terms';

export type PageTone = 'call' | 'put' | 'up' | 'down' | 'warn' | 'accent';

/** One glossary row: a column, a figure or a term the page itself prints. */
export interface PageTerm {
  /** The id in src/content/terms.json, when the row is read from the one source (every static row is). */
  id?: string;
  term: string;
  meaning: string;
  /** A colour bar on the row, so a term can be matched to its colour on the page. */
  tone?: PageTone;
}

/** One chip of the colour key at the top of the card: a name, its colour, and an optional few words. */
export interface PageLegendChip {
  label: string;
  tone: PageTone;
  /** Where to find it, in a few words ("left side"). */
  hint?: string;
}

/** One control the page offers, and what it does. */
export interface PageAction {
  label: string;
  text: string;
}

export interface PageExplanation {
  /** Printed as the dialog's title. Usually `current`, spelled out in full. */
  title: string;
  /** The lead sentence — also the ⓘ's one-line accessible description. */
  summary: string;
  /** The colour key: what each colour on the page means, as small chips under the title. */
  legend?: PageLegendChip[];
  /** What the reader is looking at: the marks, the axes, the colour code. */
  measures: string;
  /** Numbered, in the order a reader's eye should move across the chart. */
  steps: string[];
  /** The one thing the reading cannot tell the reader by itself. */
  caution: string;
  /** "What you can do here": the page's own controls. */
  actions?: PageAction[];
  /** "Key terms": a compact glossary of what the page prints. */
  terms?: PageTerm[];
  /** "Quick tips": reading habits the guides teach, in one line each. */
  tips?: string[];
  /** Slug of the matching guide under `public/guides/` (no extension). */
  guide?: string;
  /**
   * Where each part of this card is taught in the guide: the id of a section of `public/guides/<guide>.html`. The dialog turns
   * each into an "In the guide" link on that part's heading. `PageInfo.test.tsx` checks every id exists in the built guide.
   */
  guideAnchors?: GuideAnchors;
  /** A small taste of the guide, printed at the foot of the card: what it teaches, one real worked line, three doors in. */
  glimpse?: GuideGlimpse;
}

/** The "From the guide" block. Every figure in `example` is one the guide itself prints; `PageInfo.test.tsx` checks each door exists. */
interface GuideGlimpse {
  /** The guide's own title. */
  title: string;
  /** A real picture of the page the guide documents, in both themes: the card shows the one that matches the app's theme. */
  image?: GuideImage;
  /** One or two plain sentences on what the guide teaches. */
  lead: string;
  /** One real worked line, on the real chain or close the guide uses (figures as the guide prints them). */
  example?: string;
  /** Three sections worth opening first: a label and the id of that section in the guide. */
  doors: { label: string; anchor: string }[];
}

/** A picture from the guide's own set: `src` is the dark file, `srcLight` its light twin (both under `public/guides/img/`). */
interface GuideImage {
  src: string;
  srcLight: string;
  alt: string;
  width: number;
  height: number;
}

/** The guide's picture `<dir>/<id>.webp` and `<id>-light.webp`, at the size the guide's catalogue records. */
export function guideImage(dir: string, id: string, width: number, height: number, alt: string): GuideImage {
  return { src: `/guides/img/${dir}/${id}.webp`, srcLight: `/guides/img/${dir}/${id}-light.webp`, alt, width, height };
}

/** The parts of the card that can point into the guide. */
export type GuideAnchorPart = 'measures' | 'steps' | 'caution' | 'actions' | 'terms';
type GuideAnchors = Partial<Record<GuideAnchorPart, string>>;

/** The guide page for a slug. The `.html` is deliberate: see `getGuideHref` in `lib/pageMeta.ts`. */
export function guideHref(slug: string, anchor?: string): string {
  return anchor ? `/guides/${slug}.html#${anchor}` : `/guides/${slug}.html`;
}

export const PAGE_EXPLANATIONS: Record<string, PageExplanation> = {
  'Option Chain': {
    title: 'Option Chain',
    summary: 'Call and Put prices, open positions and activity, strike by strike.',
    legend: [
      { label: 'Call', tone: 'call', hint: 'left side' },
      { label: 'Put', tone: 'put', hint: 'right side' },
      { label: 'ATM', tone: 'accent', hint: 'strike nearest the index' },
    ],
    measures: 'One row per strike: Call figures on the left, Put figures on the right, the strike in the centre.',
    steps: [
      'Find the ATM row, the strike nearest the index price.',
      'Compare the Call and Put Open Interest, its change and Volume at that strike.',
      'Open the insight bar for the walls and the reading.',
    ],
    caution: 'The table shows positions and prices, not who holds them or why. Read it with price and volume.',
    actions: [
      { label: 'Simple or Advanced', text: 'Simple shows plain figures. Advanced (Beta) adds bars and hover details.' },
      { label: 'Customise', text: 'Pick columns, Call or Put sides, and All, ITM or OTM contracts.' },
      { label: 'Expiry', text: 'The date above the table chooses the expiry.' },
      { label: 'Sort', text: 'Press a heading: high to low, low to high, then strike order.' },
    ],
    terms: [
      pageTerm('open-interest', { tone: 'accent' }),
      pageTerm('oi-change', { tone: 'accent' }),
      pageTerm('volume'),
      pageTerm('long-buildup', { tone: 'up' }),
      pageTerm('short-buildup', { tone: 'down' }),
      pageTerm('short-covering', { tone: 'up' }),
      pageTerm('long-unwinding', { tone: 'down' }),
      pageTerm('call-wall', { tone: 'warn' }),
      pageTerm('put-wall', { tone: 'warn' }),
      pageTerm('max-pain', { tone: 'warn' }),
      pageTerm('pcr'),
      pageTerm('greeks'),
      pageTerm('expected-move'),
      pageTerm('oi-support-resistance', { tone: 'warn' }),
      pageTerm('vol-support-resistance'),
      pageTerm('gamma-flip'),
      pageTerm('atm'),
      pageTerm('days-to-expiry'),
    ],
    tips: [
      'Read Open Interest and its change together, never either alone.',
      'Little trading or a wide bid/ask gap makes the calculated figures less reliable.',
    ],
    guide: 'option-chain',
    guideAnchors: { measures: 'oc-start', steps: 'oc-a-ladder', caution: 'oc-c-oi', actions: 'oc-a-customise', terms: 'oc-index' },
    glimpse: { title: 'How to Read an Option Chain, Cell by Cell', image: guideImage('option-chain', 'embed-b8015320', 1276, 274, 'Five rows of the real NIFTY option chain: Call figures on the left, the strike in the middle, Put figures on the right, and the spot line between the 23300 and 23350 rows'), lead: 'Every cell the chain prints, in the Simple and the Advanced view, with a worked reading on a real chain.', example: 'NIFTY 23346.40 sits between the 23300 and 23350 rows. On the 23350 row the Call last traded at 88.05 and the Put at 84.65.', doors: [{ label: 'The start', anchor: 'oc-start' }, { label: 'Every cell', anchor: 'oc-index' }, { label: 'The reading routine', anchor: 'oc-e-routine' }] },
  },
  'Options Scanner': {
    title: 'Options Scanner',
    summary: 'List option contracts, underlyings or your own conditions, sorted by the figure you ask about.',
    measures: 'Each row is one thing that matched a question: a contract such as a 25000 Call, an underlying, or a result of conditions you set. Figures compare two readings of the same contract, and the results header repeats the question with the window it measures.',
    steps: [
      'Pick a view. Contracts asks where the action is, Underlyings asks how much movement options price against what the underlying has actually done, and Custom applies conditions you set.',
      'On Contracts, choose a scan, then the window (Day, 5m, 15m, 30m or 1h), the expiry (Current, Next, Far or All) and the market (All, Stocks or Indices).',
      'Read the size of a change next to its percentage. A large percentage on a tiny base is not a large move, which is why the scans carry floors on size and traded value.',
    ],
    caution: 'A row that tops a list matched a question; it is not a conclusion, and it is not a forecast. Open Interest has a buyer and a writer on every contract, so a scan cannot say who was pushing.',
    actions: [
      { label: 'View', text: 'The switch in the page bar moves between Contracts, Underlyings and Custom. They share the same market data.' },
      { label: 'Scan', text: 'Contracts offers thirteen scans in four families: Price, Open Interest, Build-up and Volume.' },
      { label: 'Window', text: 'Day compares with the previous close. 5m, 15m, 30m and 1h compare with the stored reading that many minutes earlier. A window with no reading close to that lookback is reported as not ready.' },
      { label: 'Side and rows', text: 'Side is Both, Call or Put. Rows can be every matching contract, or only the top contract of each underlying.' },
      { label: 'Customise', text: 'Adds more limits, such as volume, bid-ask spread, distance from spot, delta and days to expiry.' },
    ],
    terms: [
      pageTerm('build-up', { context: 'On the Day window a name needs premium to move at least 0.5% and Open Interest at least 2%; a smaller move reads as no clear pattern.' }),
      pageTerm('oi-change-pct'),
      pageTerm('volume-surge'),
      pageTerm('volume-above-oi'),
      pageTerm('most-active'),
      pageTerm('traded-today-floor'),
      pageTerm('starting-size-guards'),
      pageTerm('implied-volatility'),
      pageTerm('delta'),
      pageTerm('days-to-expiry'),
    ],
    tips: [
      'A strike growing from 2 lots to 60 prints +2900%; one growing from 4000 lots to 5000 prints +25%. Read the lots added before the percentage.',
      'Current, Next and Far are each underlying’s own first, second and third tracked expiries, so they are not the same dates for an index and a stock.',
      'Ready-made strategy baskets are checked in the Strategy Builder’s Finder, not here.',
    ],
    guide: 'options-scanner',
    guideAnchors: { measures: 'os-what', steps: 'os-a-scans', caution: 'os-d-traps', actions: 'os-a-header' },
    glimpse: { title: 'The Options Scanner: Three Views, Three Questions', lead: 'Contracts finds single options that moved, Underlyings reads each stock or index through its own options, and Custom builds a list from your own conditions.', doors: [{ label: 'Three views', anchor: 'os-what' }, { label: 'Contract scans', anchor: 'os-a-scans' }, { label: 'The tiny-base trap', anchor: 'os-d-traps' }] },
  },
  'Strategy Builder': {
    title: 'Strategy Builder',
    summary: 'Combine option legs and compare their payoff, risk and sensitivities.',
    measures: 'The payoff chart plots underlying price horizontally and combined profit or loss in rupees vertically. Compare the expiry payoff with the target-date estimate. Risk and breakevens use enabled legs, quantities, entry premiums and entered costs; Greeks show combined sensitivity.',
    steps: [
      'Choose a template or add legs, then check each expiry, strike, side, quantity and premium.',
      'Read maximum profit, maximum loss and breakevens alongside the payoff chart.',
      'Adjust target price, time and volatility to compare scenarios; use Greeks to inspect the combined sensitivities.',
    ],
    caution: 'Target-date values and probability of profit are model estimates. Mixed-expiry results depend on later-expiry option values. Building or saving a strategy does not place an order.',
    actions: [
      { label: 'Templates', text: 'Ready-made strategies are grouped by market view: Bullish, Bearish, Neutral and Either way. Search finds a strategy under any name it goes by.' },
      { label: 'Add a leg', text: 'The New leg line takes an expiry, a strike, Call or Put, a side and the lots, and shows the price it would use before the leg is added.' },
      { label: 'Edit a leg', text: 'Switch a leg off to see the position without it, flip BUY or SELL and CALL or PUT, step the strike, and edit lots, quantity and entry price in place.' },
      { label: 'Shift, Width, Hedge', text: 'Each shows every leg’s old and new strike and price before it applies. Undo reverses the last edit.' },
      { label: 'Target or Expiry', text: 'Switch the figures between the exact expiry result and the target-date estimate, with a target price, a date and a change in IV. Quick targets run from −2% to +2% of spot.' },
      { label: 'Builder or Finder', text: 'The switch in the page bar changes the page from building one position to scanning for many.' },
    ],
    terms: [
      pageTerm('payoff'),
      pageTerm('target-date-estimate'),
      pageTerm('breakeven'),
      pageTerm('risk-pill'),
      pageTerm('entry-price'),
      pageTerm('lots-and-quantity'),
      pageTerm('greeks', { context: 'Here they are the combined figures of the enabled legs.' }),
      pageTerm('probability-of-profit'),
      pageTerm('atm', { context: 'Each leg notes how far in or out of the money it is, in points.' }),
      pageTerm('risk-budget'),
    ],
    tips: [
      'The book strip prints the quote time of the chain behind every figure. Read it with each estimate.',
      'Costs are deducted once from the whole position. With none entered, figures exclude fees, taxes and slippage.',
      'A position with legs on different expiries has no single expiry payoff, so scenarios stop at the first expiry.',
      'Margin is the broker’s figure and is separate from the maximum loss shown here.',
    ],
    guide: 'strategy-builder',
    guideAnchors: { measures: 'sb-what', steps: 'sb-start', caution: 'sb-limits', actions: 'sb-leg', terms: 'sb-payoff' },
    glimpse: { title: 'Building an Options Strategy and Reading Its Payoff', lead: 'The legs of a position and its payoff on one screen, so every edit shows its effect at once, and why the expiry line and the target-date line are different kinds of number.', doors: [{ label: 'What it is', anchor: 'sb-what' }, { label: 'Reading the payoff', anchor: 'sb-payoff' }, { label: 'The target date', anchor: 'sb-whatif' }] },
  },
  'Strategy Finder': {
    title: 'Strategy Finder',
    summary: 'Compare option structures using available quotes, costs and risk.',
    measures: 'Results are option baskets built from actual listed strikes. Each row shows estimated risk after the entered charges, quote quality and the selected comparison metric. Price movement adds context to each setup.',
    steps: [
      'Choose a market, then scan. Buy options, Sell with protection, Hedge and Price checks narrow the results.',
      'Open a result to check the legs, quote time, spread, available depth and price scenarios.',
      'Adjust your cost and liquidity filters, then open a basket in Strategy Builder to explore it further.',
    ],
    caution: 'Results compare structures; they do not forecast returns or place orders. Historical prices and top-of-book quotes do not guarantee fills. Pricing checks use an assumed funding rate; hedge figures describe the options alone.',
    actions: [
      { label: 'Scan', text: 'Choose indices, stocks, all, or one underlying, and one, two or three expiries.' },
      { label: 'Gains on', text: 'Keep only structures that profit on a rise, a fall, a range or a large move.' },
      { label: 'Premium', text: 'Separate premium paid (debit) from premium received (credit).' },
      { label: 'Limits', text: 'Customise adds limits on maximum loss per basket, days to expiry, reward ÷ risk, delta ranges, liquidity and costs.' },
      { label: 'Fill at', text: 'Legs are priced at the ask to buy and the bid to sell, or at the midpoint if you choose it.' },
    ],
    terms: [
      pageTerm('maximum-loss'),
      pageTerm('reward-risk'),
      pageTerm('debit-credit'),
      pageTerm('sold-strikes-from-spot'),
      pageTerm('put-skew'),
      pageTerm('delta-range'),
      pageTerm('bid-ask-spread', { context: 'Every leg must pass the limit.' }),
    ],
    tips: [
      'Quote quality always comes first, so an old cheap quote never outranks a recent one. Within that, rows follow the chosen column.',
      'The catalogue holds 22 structures in six groups, each priced for one lot per leg from actual listed strikes.',
      'Calendars and diagonals are the exception to exact figures: their figures at the current expiry are labelled estimates.',
    ],
    guide: 'strategy-builder',
    guideAnchors: { measures: 'sb-finder', caution: 'sb-limits' },
    glimpse: { title: 'Building an Options Strategy and Reading Its Payoff', lead: 'What the Strategy finder ranks, built from the same legs and the same payoff, and what a ranking does not say.', doors: [{ label: 'What it is', anchor: 'sb-what' }, { label: 'The finder', anchor: 'sb-finder' }, { label: 'Limits', anchor: 'sb-limits' }] },
  },
  'Open Interest Heatmap': {
    title: 'Open Interest Heatmap',
    summary: 'See where option positions sit across strikes and how they moved through the session.',
    measures: 'Strike price runs down the page and time runs across it. Each tile prints the Open Interest at that strike and time, with the build-up name and the change since the column before. Calls sit on the left in red and Puts on the right in green; a deeper shade means a larger position within its wing, not a price direction.',
    steps: [
      'Read a row left to right for how one strike’s position moved through the session.',
      'Read a column top to bottom to compare strikes at the same point in time.',
      'Use Session replay to step back through earlier columns instead of only viewing the latest one.',
    ],
    caution: 'A deep tile shows where Open Interest is large, not where price must go next. In the default colouring a deep tile can be flat or shrinking. Confirm a reading with that strike’s own price and volume.',
    actions: [
      { label: 'Customise › Table', text: 'Show Both wings, Calls only, Puts only or Straddle (Call plus Put per strike).' },
      { label: 'Customise › Time', text: 'Set the step between columns to 5, 15, 30 or 60 minutes, and the part of the session shown: whole session, last hour, last 30 minutes, last 15 minutes or a custom range.' },
      { label: 'Tile colour', text: 'Open Interest shades by how much is open. Build-up shades by what just happened: green where the contract’s premium rose, red where it fell.' },
      { label: 'Colour scale', text: 'Compare tiles against the whole session, each time column, or each strike’s own high.' },
      { label: 'Strikes and replay', text: 'Choose 11, 15, 21, 25 or 31 strikes around the money, and switch Session replay on to step back through the day.' },
    ],
    terms: [
      pageTerm('heatmap-tile'),
      pageTerm('heatmap-shade'),
      pageTerm('build-up', { context: 'Each tile is named from its own contract’s premium and Open Interest.' }),
      pageTerm('strike-rail'),
      pageTerm('straddle-premium', { context: 'The band across the plane shows it at the ATM strike.' }),
      pageTerm('expected-move'),
      pageTerm('max-pain', { tone: 'warn' }),
      pageTerm('oi-support-resistance', { tone: 'warn' }),
    ],
    tips: [
      'Red and green are not price directions in the default colouring: they name the side. Calls are red and Puts are green.',
      'With Build-up colouring, red and green name the move in the contract’s own premium, and the wing names the side.',
    ],
    guide: 'oi-heatmap',
    guideAnchors: { measures: 'hm-first5', steps: 'hm-b-tile', caution: 'hm-d-traps', actions: 'hm-c-views', terms: 'hm-glossary' },
    glimpse: { title: 'Reading the Open Interest Heatmap', image: guideImage('oi-heatmap', 'page-both', 1280, 856, 'The Open Interest heatmap: strikes down the middle, Calls on the left and Puts on the right, time running across each side, and every tile shaded by its build-up'), lead: 'Look at it for one minute and you can see where Open Interest sits, how it built through the session and which side is heavier, without fooling yourself.', doors: [{ label: 'First 5 minutes', anchor: 'hm-first5' }, { label: 'The tile', anchor: 'hm-b-tile' }, { label: 'Traps', anchor: 'hm-d-traps' }] },
  },
  'Open Interest Spurts': {
    title: 'Open Interest Spurts',
    summary: 'Which contracts’ Open Interest moved fastest, opened or closed.',
    legend: [
      { label: 'Long build-up', tone: 'up' },
      { label: 'Short build-up', tone: 'down' },
      { label: 'Short covering', tone: 'up' },
      { label: 'Long unwinding', tone: 'down' },
    ],
    measures: 'One card per build-up, listing its biggest contracts in the window. The rotation map draws the same window as a picture.',
    steps: [
      'Start on Top moves: one card per build-up, biggest first.',
      'Point at or tap a contract for its Open Interest and premium.',
      'Switch to the rotation map and follow a contract’s path.',
    ],
    caution: 'A spurt is a recorded change, not who made it or why. Check nearby strikes and a longer window.',
    actions: [
      { label: 'Top moves or Rotation map', text: 'The switch in the page bar (Customise on a phone). Both read the same window.' },
      { label: 'Window', text: '5m, 15m, 30m, 1h or the whole Day.' },
      { label: 'Big move', text: 'How far a contract’s Open Interest must move to count: 10%, 20% or 30%. It starts at 20%.' },
      { label: 'Paths', text: 'On the map, a path runs from the centre (window start) to where the contract is now.' },
    ],
    terms: [
      pageTerm('spurt', { tone: 'accent' }),
      pageTerm('rotation-map'),
      pageTerm('long-buildup', { tone: 'up' }),
      pageTerm('short-buildup', { tone: 'down' }),
      pageTerm('short-covering', { tone: 'up' }),
      pageTerm('long-unwinding', { tone: 'down' }),
      pageTerm('thin-book', { tone: 'warn' }),
    ],
    tips: [
      'Read the size of the change, not only the percentage: a small book can print a large percentage.',
    ],
    guide: 'oi-spurts',
    guideAnchors: { measures: 'sp-what', steps: 'sp-d-board', caution: 'sp-f-lowbase' },
    glimpse: { title: 'Reading Open Interest Spurts Without the False Positives', lead: 'A spurt is a fast change in the Open Interest of one option, measured against its own book. A far strike going from 6200 to 21300 contracts prints the largest percentage on the map and is a sliver of what moved.', doors: [{ label: 'What it is', anchor: 'sp-what' }, { label: 'The low-base trap', anchor: 'sp-f-lowbase' }, { label: 'The four corners', anchor: 'sp-b-plane' }] },
  },
  PCR: {
    title: 'PCR',
    summary: 'Compare Put open positions with Call open positions to see how their balance changes.',
    measures: 'The line plots the ratio of put Open Interest to call Open Interest through the session. A reading of 1.00 means the two sides are equal; above it, puts outweigh calls, and below it, calls outweigh puts.',
    steps: [
      'Use the 1.00 line in the middle of the chart as the balance point.',
      'Change the window control (such as 15m, 1h or Day) to see more or less history.',
      'Note how many times the line crosses 1.00 in the chosen window — the insight box prints the count and every crossing time.',
    ],
    caution: 'A ratio measures where open interest sits between puts and calls, not where price must go. Confirm any reading against price and volume before treating it as meaningful.',
    actions: [
      { label: 'Customise › Strikes', text: 'Choose the strikes that go into the ratio: the full option chain, or ATM ±20 (the default), ±10 or ±5. Expiry is under Contract.' },
      { label: 'Customise › Time', text: 'Choose a window of 15m, 30m, 1h or Day, a custom range, or 1 Month, which draws one reading per session close.' },
      { label: 'Customise › Chart', text: 'Six switches choose the lines drawn. The Put and Call Open Interest lines are off until you switch them on.' },
      { label: 'Chart time', text: 'Step the page back to an earlier reading, then return with Back to latest.' },
    ],
    terms: [
      pageTerm('pcr'),
      pageTerm('pcr-verdict'),
      pageTerm('pcr-crossing'),
      pageTerm('call-wall'),
      pageTerm('put-wall'),
      pageTerm('max-pain'),
    ],
    tips: [
      'The same book reads differently on different strikes: change the strikes in the ratio and the answer changes. The scope line under the chart says which strikes went in.',
      'A change in the ratio can come from Puts being added, Calls closing, or the strikes moving. Only the change in each total says which.',
    ],
    guide: 'pcr',
    guideAnchors: { measures: 'pc-a-formula', steps: 'pc-b-chart', caution: 'pc-limits', actions: 'pc-d-customise', terms: 'pc-glossary' },
    glimpse: { title: 'Reading the Put-Call Ratio (PCR)', image: guideImage('pcr', 'pc-chart', 1378, 843, 'The PCR page chart on an invented NIFTY day: the ratio drawn as a line against 1.00, green above and red below, with a grey price line, three level rules and two crossing dots'), lead: 'One number from the option chain: the Put Open Interest standing across the strikes you choose, divided by the Call Open Interest across the same strikes, drawn through the day against 1.00.', example: 'On the guide\'s invented NIFTY day at 2:20 pm, Put Open Interest of 13.63Cr over Call Open Interest of 12.72Cr on the 41 strikes around the price is 1.07, which the page labels Bullish. The whole expiry reads 0.95, which would be Bearish.', doors: [{ label: 'In two minutes', anchor: 'pc-fast' }, { label: 'How it is worked out', anchor: 'pc-a-formula' }, { label: 'What it cannot tell you', anchor: 'pc-limits' }] },
  },
  Straddle: {
    title: 'Straddle',
    summary: 'Track the combined price of a Call and a Put, and choose the strikes for each leg.',
    measures: 'The chart plots the combined premium of one call and one put — by default both at the at-the-money strike — through the session. A rising line means the combined premium is increasing; a falling line means it is decreasing.',
    steps: [
      'Note the strikes chosen for the call and put legs, shown above the chart.',
      'Read the line’s direction over the chosen window to see whether the combined premium widened or narrowed.',
      'Compare it with the expected-move figure in the reading below the chart, a pricing convention drawn from the same premium.',
    ],
    caution: 'A change in combined premium can come from the spot moving, implied volatility changing, or time decay — usually some mix of the three. It does not by itself point toward any particular strike or direction.',
    actions: [
      { label: 'Five views', text: 'Overview, Premium Decay, Price vs Open Interest, Multi-Strike and Multi-Straddle each draw the premium a different way.' },
      { label: 'Customise › Contract and Legs', text: 'Choose the strikes for the Call and the Put. Two different strikes make a strangle.' },
      { label: 'Customise › Time', text: 'On the Overview, choose One session or 1 Month (one reading per session close). Windows are 15m, 30m, 1h, Day or a custom range, with a time step.' },
      { label: 'Customise › Chart', text: 'One switch per line. Premium, spot and the max pain line start on; ATM implied volatility, time-decay-only and straddle breakeven start off.' },
    ],
    terms: [
      pageTerm('straddle-premium'),
      pageTerm('expected-move'),
      pageTerm('straddle-breakevens'),
      pageTerm('strangle'),
      pageTerm('time-decay-only'),
      pageTerm('decay-baselines'),
    ],
    tips: [
      'The two prices are two cells of one row of the Option Chain. The straddle and the expected move there come from the same row.',
      'The at-the-money strike here is anchored to the forward, so it can differ by one strike from the Option Chain’s nearest-to-spot badge.',
    ],
    guide: 'atm-premium',
    guideAnchors: { measures: 'stg-what', steps: 'stg-overview', caution: 'stg-limits', actions: 'stg-customise', terms: 'stg-glossary' },
    glimpse: { title: 'The Straddle Workspace: Premium, Expected Move and Five Views', image: guideImage('atm-premium', 'st-chart-default', 1378, 753, 'The Straddle Overview chart: the premium line, the underlying and the max pain line for one session'), lead: 'The at-the-money Call and Put added together, the expected move at 0.85 times it and the breakevens, then every view and control of the Straddle workspace.', example: 'On the illustrative day of the guide the 24550 Call is 131.65 and the Put 147.20. Together they are 278.85, and the Move chip prints ±237, which is 0.85 × 278.85.', doors: [{ label: 'First five minutes', anchor: 'stg-fast' }, { label: 'Which strike is at the money', anchor: 'stg-atm' }, { label: 'Why a premium falls', anchor: 'stg-why-falls' }] },
  },
  'Order Flow': {
    title: 'Order Flow',
    summary: 'Every F&O underlying sorted onto a side by its futures, the way its positions moved, and the strongest on each side with their zone and levels.',
    measures: 'Left to right: each sector with a bar of its underlyings’ sides; every underlying as a dot on the change axis (the near-month future’s change over the window, spot standing in until the future is read); the four build-up columns; and each side’s strongest as full cards. A card draws the session’s futures line with the zone shaded and the heaviest put and call Open Interest either side of spot.',
    steps: [
      'Pick the window in the page bar: Day compares with the previous close; 1 hour and 15 minutes compare with the future’s own candle that long ago.',
      'Read the plane: dots above the zero rule moved up, below it moved down, and the dashed floor is the move a future needs before its underlying takes a side.',
      'Read the columns: Long build-up and Short build-up are positions opened with the move, Short covering and Long unwinding are positions closed. Strongest first in each.',
      'Open a pick: the dots are the checks that hold, the zone is the 15-minute stretch that added the most Open Interest with the move, and the levels are the heaviest put and call Open Interest either side of spot.',
    ],
    caution: 'A side is a state, not a forecast. Open Interest has a buyer and a writer on every contract, so a build-up says positions were opened or closed, never who opened them or why.',
    actions: [
      { label: 'Window', text: 'Day, 1 hour or 15 minutes, in the page bar and in Customise.' },
      { label: 'Customise', text: 'The market (all, stocks, indices), the floor a move must clear, and how many picks each side lists.' },
      { label: 'Select', text: 'Click a dot or a column row to open that underlying’s full card above the picks; hover a sector to light its lines.' },
    ],
    terms: [
      pageTerm('flow-side'),
      pageTerm('build-up', { context: 'On Order Flow it is read on the future, not on an option.' }),
      pageTerm('flow-strength'),
      pageTerm('flow-checks'),
      pageTerm('flow-zone'),
      pageTerm('flow-levels'),
    ],
    tips: [
      'The futures arrive over a minute or two for the whole list; the picks settle as they land, biggest spot movers first.',
      'A big move with Open Interest down is a position closing, not a new one: Short covering and Long unwinding sit lower in the strength order on purpose.',
    ],
    guide: 'market-flow',
    guideAnchors: { measures: 'mf-what', steps: 'mf-fast', caution: 'mf-limits', actions: 'mf-practice' },
  },
  'GEX Levels': {
    title: 'GEX Levels',
    summary: 'See estimated levels where option hedging may influence price movement.',
    measures: 'Each bar is one strike’s net GEX — call-side exposure minus put-side exposure — drawn from a zero rule, with call and put walls marked where exposure concentrates most on each side. A curve beneath the bars re-computes net GEX at each price level and marks where it crosses zero, the gamma flip.',
    steps: [
      'Switch between Net, Call vs Put and Gamma concentration to see the exposure a different way.',
      'Locate the call wall and put wall markers — the strikes with the largest exposure on each side.',
      'Compare the spot marker with the gamma flip on the curve beneath the bars to see which side of zero the current price sits on.',
    ],
    caution: 'GEX is an estimate built from open interest and a standard option pricing model, not a measured position. The estimate depends on assumptions about who wrote the options, and those assumptions can be wrong.',
    actions: [
      { label: 'Plot view', text: 'Net draws call side minus put side. Call vs Put draws Calls above the rule and Puts below. Gamma concentration adds both sides.' },
      { label: 'Customise › Contract', text: 'Choose the expiry whose book is modelled.' },
      { label: 'Customise › Levels', text: 'Show or hide the call and put gamma walls, and the gamma flip with the ladder cross.' },
      { label: 'Customise › Strikes', text: 'Draw 11, 15, 21, 31 or 41 strikes around the money, or All.' },
      { label: 'Customise › Time', text: 'Switch on Session replay to step the whole page back to an earlier reading of the session.' },
    ],
    terms: [
      pageTerm('gex'),
      pageTerm('gamma-flip'),
      pageTerm('gamma-wall'),
      pageTerm('ladder-cross'),
      pageTerm('gamma-concentration'),
      pageTerm('gex-heaviest'),
      pageTerm('gex-both-sides'),
      pageTerm('gex-dominant'),
    ],
    tips: [
      'The sign convention assumes market makers are long every Call and short every Put in the open interest. Exchanges publish Open Interest, never who holds which side.',
      'Gamma concentration is the one reading here that survives if that assumption is wrong. It shows where hedging would be heaviest, not which way it would lean.',
    ],
    guide: 'gamma-exposure',
    guideAnchors: { measures: 'gx-what', steps: 'gx-fast', caution: 'gx-a-sign', actions: 'gx-d-customise', terms: 'gx-glossary' },
    glimpse: { title: 'Gamma Exposure (GEX Levels), and What It Can Actually Tell You', image: guideImage('gamma-exposure', 'gx-page', 1376, 1070, 'The top of the GEX Levels page for NIFTY on an invented day: the insight row reads Hedging dampens moves with a Flip chip and a Net chip, and below it the strike profile draws red bars above the zero rule and green bars below it, with badges for the gamma walls, the gamma flip and the spot price'), lead: 'How much hedging the open option book would call for as the price moves, built strike by strike from the option chain, and the assumption underneath it that Open Interest cannot confirm.', example: 'On the guide\'s invented NIFTY day at 2:20 pm the gamma flip is 24438 and NIFTY stands at 24547, 109 points above it. The lean is 21%, over the 10% needed to name a side, so the page reads Hedging dampens moves.', doors: [{ label: 'First five minutes', anchor: 'gx-fast' }, { label: 'The formula', anchor: 'gx-a-formula' }, { label: 'The assumption underneath', anchor: 'gx-a-sign' }] },
  },
  'Implied Volatility': {
    title: 'Implied Volatility',
    summary: 'Implied volatility (IV) is the size of move option prices are paying for. This page turns it into points, and shows whether options are cheap or dear right now.',
    measures: 'The four figures at the top: the at-the-money IV now; the move it prices by expiry, in points; the same move for one day, beside the days the underlying has actually had; and where the 30-day IV sits in its past year (IV Percentile and IV Rank). Four views: Intraday is IV through today, Strikes is IV at each strike now and at the open, Expiries is each expiry side by side, and History is the past year against actual moves.',
    steps: [
      'Read the priced move: the option prices are paying for about that many points by expiry, and per day.',
      'Compare the per-day move with the actual days beneath it. Bigger means options are priced above recent moves; smaller, below.',
      'Read IV Percentile: at or above 80 is high for this underlying\'s past year, at or below 20 is low.',
      'Open Strikes to see which side of spot costs more, and History to see the whole year.',
    ],
    caution: 'IV says how big a move is priced, never which way. Higher IV means dearer options. It tends to rise before events and when prices fall fast, and to drop after events and into weekends.',
    actions: [
      { label: 'Four views', text: 'Intraday, Strikes, Expiries and History, chosen in the page bar.' },
      { label: 'Customise › Contract', text: 'Choose the expiry. It sets the figures at the top and the Intraday and Strikes views; History reads a 30-day blend of every expiry.' },
      { label: 'Customise › Chart', text: 'Each chart (Intraday, Strikes, History) has its own switches for what it draws.' },
    ],
    terms: [
      pageTerm('atm-iv'),
      pageTerm('priced-move'),
      pageTerm('actual-days'),
      pageTerm('iv-percentile'),
      pageTerm('iv-rank'),
      pageTerm('smile'),
      pageTerm('forward'),
      pageTerm('iv-session-range'),
    ],
    tips: [
      'A single IV reading cannot be called high or low by itself. It reads against its own past year, the moves actually made, or today’s range.',
      'The page names options dearer only when the priced move is at least 20% bigger than the actual day, and cheaper only when it is about 17% smaller.',
      'The year uses a 30-day IV because a front-expiry IV climbs into every expiry day and resets after it, which would rank the weekday rather than the volatility.',
    ],
    guide: 'implied-volatility',
    guideAnchors: { measures: 'iv-a-points', steps: 'iv-fast', caution: 'iv-limits', terms: 'iv-glossary' },
    glimpse: { title: 'Implied Volatility, and How to Tell Whether a Reading Is High', image: guideImage('implied-volatility', 'iv-strikes', 1360, 737, 'The Strikes view of the Implied Volatility page: implied volatility at each strike, now and at the open, with the priced range shaded'), lead: 'The number is easy to find and hard to use: 9% and 23% mean nothing until you know what they are compared against and what they translate to in points.', doors: [{ label: 'Is it high?', anchor: 'iv-a-perday' }, { label: 'In points', anchor: 'iv-a-points' }, { label: 'Call against Put', anchor: 'iv-e-forward' }] },
  },
};

/**
 * The pinned Spurts widgets name themselves for their chart ("Spurts · Rotation
 * Map"); they explain themselves the same way the page does.
 */
PAGE_EXPLANATIONS['Spurts · Rotation Map'] = { ...PAGE_EXPLANATIONS['Open Interest Spurts'], title: 'Spurts · Rotation Map' };
PAGE_EXPLANATIONS['Spurts · Top moves'] = { ...PAGE_EXPLANATIONS['Open Interest Spurts'], title: 'Spurts · Top moves' };
