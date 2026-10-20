import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {geoMercator, geoPath} from "d3-geo";
import type {FeatureCollection} from "geojson";
import world from "../geo/world.json";
import {BOLD, CONDENSED, HEAVY} from "../fonts";
import {ChartData, MapData, Theme, TimelineData} from "../types";

// Our own infographics: a zooming world map (Natural Earth, public domain), a timeline and a bar chart.

const WORLD = world as unknown as FeatureCollection;

const useLife = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames, width, height} = useVideoConfig();
  const exit = interpolate(frame, [durationInFrames - 6, durationInFrames], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const enter = interpolate(frame, [0, 8], [0, 1], {extrapolateRight: "clamp"});
  return {frame, fps, durationInFrames, width, height, opacity: Math.min(enter, exit)};
};

export const MapCard: React.FC<{d: MapData; theme: Theme; vertical: boolean}> = ({d, theme, vertical}) => {
  const {frame, fps, durationInFrames, width, height, opacity} = useLife();
  // Zoom from a wide view down to the place over the first ~60% of the card.
  const t = interpolate(frame, [0, durationInFrames * 0.6], [0, 1], {extrapolateRight: "clamp"});
  const ease = 1 - Math.pow(1 - t, 3);
  const z0 = Math.max(1, (d.zoom ?? 4) / 4);
  const zoom = z0 + ((d.zoom ?? 4) - z0) * ease;
  const base = (vertical ? height : width) / 6.5;
  const proj = geoMercator().center([d.lon, d.lat]).scale(base * zoom).translate([width / 2, height * (vertical ? 0.4 : 0.5)]);
  const path = geoPath(proj);
  const hits = new Set((d.highlight ?? []).map((n) => n.toLowerCase()));
  const pin = proj([d.lon, d.lat]) ?? [width / 2, height / 2];
  const pinIn = spring({frame: frame - Math.round(durationInFrames * 0.45), fps, config: {damping: 10}, durationInFrames: 12});
  const pulse = 1 + 0.25 * Math.sin(frame / 5);
  return (
    <AbsoluteFill style={{opacity, background: "#0a1628"}}>
      <svg width={width} height={height}>
        {WORLD.features.map((f, i) => {
          const name = String((f.properties as {name?: string})?.name ?? "").toLowerCase();
          const on = hits.has(name);
          return <path key={i} d={path(f) ?? ""} fill={on ? theme.highlight : "#1f3350"} stroke={on ? "#000" : "#3b5478"}
            strokeWidth={on ? 2.5 : 1} opacity={on ? 0.95 : 1} />;
        })}
        <circle cx={pin[0]} cy={pin[1]} r={26 * pinIn * pulse} fill="none" stroke={theme.highlight} strokeWidth={5} opacity={pinIn} />
        <circle cx={pin[0]} cy={pin[1]} r={11 * pinIn} fill={theme.highlight} stroke="#000" strokeWidth={3} />
      </svg>
      <div style={{position: "absolute", left: 0, right: 0, top: vertical ? height * 0.4 + 60 : pin[1] + 48, textAlign: "center",
        opacity: pinIn, transform: `translateY(${interpolate(pinIn, [0, 1], [20, 0])}px)`}}>
        <span style={{background: "rgba(0,0,0,0.75)", color: "#fff", fontFamily: HEAVY, fontWeight: 900, fontSize: vertical ? 58 : 52,
          padding: "10px 26px", borderRadius: 14, border: `3px solid ${theme.highlight}`}}>{d.label}</span>
      </div>
    </AbsoluteFill>
  );
};

export const TimelineCard: React.FC<{d: TimelineData; theme: Theme; vertical: boolean}> = ({d, theme, vertical}) => {
  const {frame, fps, durationInFrames, opacity} = useLife();
  const n = d.events.length;
  const gap = Math.max(4, Math.floor((durationInFrames * 0.6) / Math.max(1, n)));
  return (
    <AbsoluteFill style={{alignItems: "center", justifyContent: "flex-start", paddingTop: vertical ? 300 : 120, opacity}}>
      <div style={{background: theme.card, color: theme.ink, borderRadius: 30, padding: vertical ? "40px 46px" : "44px 60px",
        width: vertical ? 920 : 1400, boxShadow: "0 40px 90px rgba(0,0,0,0.55)", borderTop: `10px solid ${theme.highlight}`}}>
        {d.title ? <div style={{fontFamily: HEAVY, fontWeight: 900, fontSize: vertical ? 50 : 52, marginBottom: 24}}>{d.title}</div> : null}
        <div style={{display: "flex", flexDirection: vertical ? "column" : "row", gap: vertical ? 18 : 30, position: "relative"}}>
          {d.events.map((e, i) => {
            const s = spring({frame: frame - 6 - i * gap, fps, config: {damping: 13}, durationInFrames: 12});
            return (
              <div key={i} style={{flex: 1, display: "flex", flexDirection: vertical ? "row" : "column", gap: vertical ? 22 : 10,
                alignItems: vertical ? "center" : "flex-start", opacity: s, transform: `translate${vertical ? "X" : "Y"}(${(1 - s) * 30}px)`}}>
                <div style={{fontFamily: CONDENSED, fontSize: vertical ? 74 : 80, color: theme.highlight === theme.card ? theme.ink : undefined,
                  WebkitTextStroke: "2px #000", minWidth: vertical ? 210 : undefined}}>
                  <span style={{color: theme.highlight}}>{e.year}</span>
                </div>
                <div style={{fontFamily: BOLD, fontWeight: 700, fontSize: vertical ? 40 : 38, lineHeight: 1.2}}>{e.label}</div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const ChartCard: React.FC<{d: ChartData; theme: Theme; vertical: boolean}> = ({d, theme, vertical}) => {
  const {frame, fps, opacity} = useLife();
  const max = Math.max(...d.bars.map((b) => b.value), 1);
  const fmt = (v: number) => (Math.abs(v) >= 100 ? Math.round(v).toLocaleString("en-US") : v.toFixed(v % 1 ? 1 : 0));
  return (
    <AbsoluteFill style={{alignItems: "center", justifyContent: "flex-start", paddingTop: vertical ? 300 : 120, opacity}}>
      <div style={{background: theme.card, color: theme.ink, borderRadius: 30, padding: vertical ? "40px 46px" : "44px 60px",
        width: vertical ? 920 : 1400, boxShadow: "0 40px 90px rgba(0,0,0,0.55)", borderTop: `10px solid ${theme.highlight}`}}>
        <div style={{fontFamily: HEAVY, fontWeight: 900, fontSize: vertical ? 50 : 52, marginBottom: 26}}>{d.title}</div>
        {d.bars.map((b, i) => {
          const g = spring({frame: frame - 6 - i * 5, fps, config: {damping: 16}, durationInFrames: 18});
          const strong = i === d.bars.length - 1;
          return (
            <div key={i} style={{display: "flex", alignItems: "center", gap: 18, marginTop: 14}}>
              <div style={{width: vertical ? 220 : 260, fontFamily: BOLD, fontWeight: 700, fontSize: vertical ? 34 : 34}}>{b.label}</div>
              <div style={{flex: 1, height: vertical ? 58 : 54, background: "rgba(127,127,127,0.15)", borderRadius: 12, overflow: "hidden"}}>
                <div style={{width: `${(b.value / max) * 100 * g}%`, height: "100%", borderRadius: 12,
                  background: strong ? (theme.card === theme.highlight ? theme.ink : theme.highlight) : "rgba(127,127,127,0.55)"}} />
              </div>
              <div style={{minWidth: 150, textAlign: "right", fontFamily: CONDENSED, fontSize: vertical ? 50 : 50}}>
                {d.prefix ?? ""}{fmt(b.value * g)}{d.unit ?? ""}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
