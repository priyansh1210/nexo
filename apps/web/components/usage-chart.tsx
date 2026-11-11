import { formatChange, formatNumber } from "@/lib/format";
import type { FeatureUsage } from "@/lib/types";

// A dumbbell per feature: the 30 days before (light) to the last 30 days (accent), on one shared
// scale from zero. One hue in two validated shades; the figures are printed beside each row, so
// the chart never relies on colour alone, and "Show as table" gives every number.
export function UsageChart({ features }: { features: FeatureUsage[] }) {
  const rows = [...features].sort((a, b) => b.events_last_30d - a.events_last_30d);
  const max = Math.max(1, ...rows.flatMap((f) => [f.events_last_30d, f.events_prior_30d]));
  const x = (events: number) => `${(events / max) * 100}%`; // where on the track, from zero

  return (
    <figure>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-ink-2" aria-hidden="true">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-accent" /> Last 30 days
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-chart-before" /> The 30 days before
        </span>
      </div>

      <ul className="mt-3 space-y-2.5">
        {rows.map((feature) => {
          const low = Math.min(feature.events_prior_30d, feature.events_last_30d);
          const high = Math.max(feature.events_prior_30d, feature.events_last_30d);
          return (
            <li key={feature.feature} className="grid grid-cols-[7.5rem_minmax(0,1fr)_auto] items-center gap-3 text-sm">
              <span className="truncate" title={feature.feature}>
                {feature.feature}
              </span>
              {/* The track: a hairline from zero, the change as a line, a dot at each end. */}
              <span className="relative mx-[5px] h-4" aria-hidden="true">
                <span className="absolute inset-x-0 top-1/2 h-px bg-rule" />
                <span
                  className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-chart-before"
                  style={{ left: x(low), width: `calc(${x(high)} - ${x(low)})` }}
                />
                <Dot at={x(feature.events_prior_30d)} className="bg-chart-before" label={`${feature.feature}, the 30 days before: ${formatNumber(feature.events_prior_30d)} events`} />
                <Dot at={x(feature.events_last_30d)} className="bg-accent" label={`${feature.feature}, last 30 days: ${formatNumber(feature.events_last_30d)} events`} />
              </span>
              <span className="whitespace-nowrap text-right tabular-nums">
                {formatNumber(feature.events_last_30d)}
                <span className="text-ink-2">
                  {" · "}
                  {feature.usage_change === null ? "new" : formatChange(feature.usage_change)}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
      <figcaption className="mt-2 text-[12px] text-ink-2 tabular-nums">
        Events per feature, on one scale from 0 to {formatNumber(max)}.
      </figcaption>

      <details className="mt-3 text-sm">
        <summary className="link cursor-pointer text-[13px]">Show as table</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Feature</th>
                <th scope="col" className="num">Events, last 30 days</th>
                <th scope="col" className="num">The 30 days before</th>
                <th scope="col" className="num">Change</th>
                <th scope="col" className="num">Users, last 30 days</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <tr key={f.feature}>
                  <td>{f.feature}</td>
                  <td className="num">{formatNumber(f.events_last_30d)}</td>
                  <td className="num">{formatNumber(f.events_prior_30d)}</td>
                  <td className="num">{f.usage_change === null ? "new" : formatChange(f.usage_change)}</td>
                  <td className="num">{formatNumber(f.users_last_30d)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

function Dot({ at, className, label }: { at: string; className: string; label: string }) {
  // 10px across with a 2px ring in the page colour, so overlapping dots stay readable; the title is
  // its hover tooltip.
  return (
    <span
      title={label}
      style={{ left: at }}
      className={`absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-paper ${className}`}
    />
  );
}
