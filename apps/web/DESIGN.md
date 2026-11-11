# Nexo web: design direction ("Case file")

Visual thesis: **a case file where every figure is cited.** A CSM opens Nexo to decide what to do
about an account. Answers read like a briefing a careful analyst wrote: a plain lead sentence, the
observed facts each carrying a source chip, possible causes kept visibly apart, and the data's age
always in view. Nothing decorative competes with that.

## Type

IBM Plex Sans (Google Fonts, SIL OFL), one family. Tabular figures (`tabular-nums`) wherever numbers
line up: tables, metrics, dates.

| Role | Size / weight | Use |
| --- | --- | --- |
| Page title | 22 / 600 | one per screen |
| Account name | 28 / 600 | profile header only |
| Answer lead | 18 / 500 | the summary sentence of an answer |
| Body | 15 / 400, line-height 1.55 | prose, notes |
| Table | 14 / 400 | rows, cells |
| Label | 12 / 600, letter-spacing 0.04em, uppercase | section labels ("Observed", "Possible cause") |
| Meta | 13 / 400, ink-2 | timestamps, sources, help text |

## Colour (tokens in `app/globals.css`, light and dark from the same names)

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| paper | #F7F5F0 | #15171A | page background |
| surface | #FFFFFF | #1D2024 | raised layer: the approval card, the evidence panel, inputs |
| ink | #1B1A17 | #ECEAE4 | primary text |
| ink-2 | #5C5951 | #A5A29A | secondary text |
| rule | #E3DED3 | #30343A | hairlines between rows and sections |
| accent | #0F6B66 | #5FBFB5 | the one action colour: buttons, links, focus, source chips |
| fresh | #2F7D4F | #6CC48F | a source is up to date |
| stale | #8F5B06 | #E3A74A | a source is late; also "possible cause" emphasis is NOT this colour |
| failed | #B3382C | #F08476 | a check failed, an action was refused or blocked |

Status colours are used only for data freshness and outcomes, never for decoration. All text pairs
meet WCAG AA (4.5:1) on paper and surface.

## Layout and material

- Top bar navigation (five places: Chat, Accounts, Tasks, Audit, Data health); the user's name and
  sign-out on the right. No avatars: there are no real photos, and initials are not used.
- Hairline rules separate rows and sections. Cards only where something is a real layer: the
  approval card (an action waiting on you) and the evidence panel (opened over the page on mobile).
- Chat: the conversation in a 720px reading measure; the evidence panel on the right from 1100px,
  a bottom sheet below that.
- Radius 6px on controls and the approval card; no shadows except the approval card and the sheet.

## Components

- **Source chip**: a small bracketed number, `[2]`, after a claim. It is a button: it opens that
  tool call's evidence. Accent colour, underlined on hover, visible focus ring.
- **Answer**: lead sentence; "Observed" list (each line ends in chips); "Possible cause" list with a
  dashed left rule and the label, so a hypothesis can never be read as a fact; a tool trace as a
  collapsed line ("Checked account, usage, tickets").
- **Freshness note**: above an answer only when a source it used is stale or failed a check; stale
  colour, one line per problem, saying what it means.
- **Approval card**: what will happen, to whom, the editable text for an email, who may approve it,
  and Approve / Edit / Reject. After a decision it becomes a receipt (done, blocked with the changes,
  refused with the reason, rejected) linking to its audit trail.

## Motion

Only to explain state: the evidence panel slides in (150 ms), a pending answer shows what is being
checked. Nothing moves under `prefers-reduced-motion`. No smooth-scroll engine, no GSAP: these are
dense product screens, and the blueprint keeps that motion system for landing pages.

## States

Every data block has loading (a quiet "Loading accounts…" line, not skeleton shimmer), empty (one
sentence saying why and what to do), error (what failed and a retry), and stale (the freshness note).

## Assets

- Font: IBM Plex Sans via `next/font/google` (SIL Open Font License).
- Icons: a handful of Solar icons (CC BY 4.0, by 480 Design), inlined in `components/icons.tsx`
  with attribution.
- No illustrations, photos or logos: nothing in the product needs them, and none would be honest.
