import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {BOLD, CONDENSED, HEAVY} from "../fonts";
import {Card, Look, Theme} from "../types";

// Cards slide in over the moving footage, like on news channels. All designs are our own (no logos).

const useEnterExit = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 14, stiffness: 160}, durationInFrames: 14});
  const exit = interpolate(frame, [durationInFrames - 6, durationInFrames], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return {frame, fps, durationInFrames, enter, opacity: Math.min(enter * 1.4, 1) * exit};
};

const Panel: React.FC<{children: React.ReactNode; theme: Theme; vertical: boolean; width?: number}> = ({children, theme, vertical, width}) => {
  const {enter, opacity} = useEnterExit();
  return (
    <AbsoluteFill style={{alignItems: "center", justifyContent: "flex-start", paddingTop: vertical ? 330 : 150}}>
      <div style={{width: width ?? (vertical ? 920 : 1300), background: theme.card, color: theme.ink, borderRadius: 34,
        padding: vertical ? "44px 48px" : "48px 60px", opacity,
        transform: `translateY(${interpolate(enter, [0, 1], [90, 0])}px) scale(${interpolate(enter, [0, 1], [0.94, 1])})`,
        boxShadow: "0 40px 90px rgba(0,0,0,0.55)", borderTop: `10px solid ${theme.highlight}`}}>
        {children}
      </div>
    </AbsoluteFill>
  );
};

const Dim: React.FC = () => {
  const {opacity} = useEnterExit();
  return <AbsoluteFill style={{background: "rgba(3,6,14,0.45)", opacity}} />;
};

const Headline: React.FC<{d: Extract<Card, {template: "headline"}>["data"]; theme: Theme; vertical: boolean}> = ({d, theme, vertical}) => {
  const {frame, fps} = useEnterExit();
  // A marker sweeps over the key words of the real headline, like a reader highlighting it.
  const sweep = interpolate(frame, [Math.round(fps * 0.45), Math.round(fps * 0.85)], [0, 100], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const keys = new Set((d.highlight ?? []).map((w) => w.toLowerCase().replace(/[^a-z0-9]/g, "")));
  return (
    <Panel theme={theme} vertical={vertical}>
      <div style={{display: "flex", alignItems: "center", gap: 16, marginBottom: 26}}>
        <div style={{width: 22, height: 22, borderRadius: 11, background: "#e5383b"}} />
        <div style={{fontFamily: BOLD, fontWeight: 700, fontSize: vertical ? 34 : 30, letterSpacing: 2, textTransform: "uppercase", opacity: 0.75}}>
          {d.source}{d.date ? `  ·  ${d.date}` : ""}
        </div>
      </div>
      <div style={{fontFamily: HEAVY, fontWeight: 900, fontSize: vertical ? 64 : 62, lineHeight: 1.12}}>
        {d.title.split(" ").map((w, i) => {
          const hit = keys.has(w.toLowerCase().replace(/[^a-z0-9]/g, ""));
          return (
            <span key={i} style={hit ? {backgroundImage: `linear-gradient(transparent 58%, ${theme.highlight}cc 58%)`,
              backgroundRepeat: "no-repeat", backgroundSize: `${sweep}% 100%`} : undefined}>{w}{" "}</span>
          );
        })}
      </div>
    </Panel>
  );
};

const Slam: React.FC<{d: Extract<Card, {template: "slam"}>["data"]; theme: Theme; vertical: boolean}> = ({d, theme, vertical}) => {
  const {frame, fps, opacity} = useEnterExit();
  const words = d.text.split(" ").slice(0, 5);
  return (
    <AbsoluteFill style={{alignItems: "center", justifyContent: "center", background: `rgba(3,6,14,${0.72 * opacity})`}}>
      <div style={{display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "0 26px", maxWidth: vertical ? 960 : 1600,
        marginTop: vertical ? -260 : 0}}>
        {words.map((w, i) => {
          const s = spring({frame: frame - i * 4, fps, config: {damping: 11, stiffness: 240}, durationInFrames: 9});
          return (
            <span key={i} style={{fontFamily: CONDENSED, fontSize: vertical ? 170 : 200, lineHeight: 1.02, textTransform: "uppercase",
              color: i === words.length - 1 ? theme.highlight : "#fff", opacity: Math.min(1, s * 1.5) * opacity,
              transform: `scale(${interpolate(s, [0, 1], [2.2, 1])})`, display: "inline-block",
              WebkitTextStroke: "4px #000", paintOrder: "stroke fill", textShadow: "0 12px 40px rgba(0,0,0,0.7)"}}>{w}</span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const Stat: React.FC<{d: Extract<Card, {template: "stat"}>["data"]; theme: Theme; vertical: boolean}> = ({d, theme, vertical}) => {
  const {frame, fps} = useEnterExit();
  const p = interpolate(frame, [4, Math.round(fps * 1.1)], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const eased = 1 - Math.pow(1 - p, 3);
  const n = (d.value * eased).toLocaleString("en-US", {minimumFractionDigits: d.decimals ?? 0, maximumFractionDigits: d.decimals ?? 0});
  return (
    <Panel theme={theme} vertical={vertical}>
      <div style={{fontFamily: CONDENSED, fontSize: vertical ? 210 : 220, lineHeight: 1, color: theme.ink, textAlign: "center"}}>
        <span style={{color: theme.highlight === "#FFFFFF" ? theme.ink : undefined}}>{d.prefix ?? ""}{n}</span>
        <span style={{fontSize: vertical ? 90 : 96, marginLeft: 12}}>{d.suffix ?? ""}</span>
      </div>
      <div style={{fontFamily: BOLD, fontWeight: 700, fontSize: vertical ? 46 : 44, textAlign: "center", marginTop: 18, opacity: 0.85}}>
        {d.label}
      </div>
    </Panel>
  );
};

const Compare: React.FC<{d: Extract<Card, {template: "compare"}>["data"]; theme: Theme; vertical: boolean}> = ({d, theme, vertical}) => {
  const {frame, fps} = useEnterExit();
  const right = spring({frame: frame - Math.round(fps * 0.45), fps, config: {damping: 13}, durationInFrames: 14});
  const box = (label: string, value: string, strong: boolean, s: number) => (
    <div style={{flex: 1, borderRadius: 24, padding: vertical ? "30px 22px" : "34px 30px", textAlign: "center",
      background: strong ? (theme.card === theme.highlight ? theme.ink : theme.highlight) : "rgba(127,127,127,0.12)",
      color: strong ? (theme.card === theme.highlight ? theme.highlight : "#000") : theme.ink,
      transform: `scale(${s})`, opacity: s}}>
      <div style={{fontFamily: BOLD, fontWeight: 700, fontSize: vertical ? 34 : 32, textTransform: "uppercase", letterSpacing: 2, opacity: 0.8}}>{label}</div>
      <div style={{fontFamily: HEAVY, fontWeight: 900, fontSize: vertical ? 64 : 70, lineHeight: 1.1, marginTop: 12}}>{value}</div>
    </div>
  );
  return (
    <Panel theme={theme} vertical={vertical}>
      {d.title ? <div style={{fontFamily: HEAVY, fontWeight: 900, fontSize: vertical ? 50 : 52, marginBottom: 28, textAlign: "center"}}>{d.title}</div> : null}
      <div style={{display: "flex", gap: 22, alignItems: "stretch"}}>
        {box(d.leftLabel, d.leftValue, false, 1)}
        <div style={{alignSelf: "center", fontFamily: CONDENSED, fontSize: vertical ? 60 : 64, opacity: 0.6}}>→</div>
        {box(d.rightLabel, d.rightValue, true, right)}
      </div>
    </Panel>
  );
};

const List: React.FC<{d: Extract<Card, {template: "list"}>["data"]; theme: Theme; vertical: boolean}> = ({d, theme, vertical}) => {
  const {frame, durationInFrames} = useEnterExit();
  const step = durationInFrames / Math.max(1, d.items.length);
  const active = Math.min(d.items.length - 1, Math.floor(frame / step));
  return (
    <Panel theme={theme} vertical={vertical}>
      <div style={{fontFamily: HEAVY, fontWeight: 900, fontSize: vertical ? 52 : 54, marginBottom: 24}}>{d.title}</div>
      {d.items.map((it, i) => {
        const shown = i <= active;
        return (
          <div key={i} style={{display: "flex", gap: 22, alignItems: "center", marginTop: 16, opacity: shown ? (i === active ? 1 : 0.55) : 0.15,
            transform: `translateX(${shown ? 0 : 30}px)`}}>
            <div style={{minWidth: vertical ? 74 : 70, height: vertical ? 74 : 70, borderRadius: 37, background: i === active ? theme.highlight : "rgba(0,0,0,0.1)",
              color: "#000", fontFamily: CONDENSED, fontSize: vertical ? 48 : 46, display: "flex", alignItems: "center", justifyContent: "center"}}>{i + 1}</div>
            <div style={{fontFamily: BOLD, fontWeight: 700, fontSize: vertical ? 44 : 42, lineHeight: 1.2}}>{it}</div>
          </div>
        );
      })}
    </Panel>
  );
};

const Quote: React.FC<{d: Extract<Card, {template: "quote"}>["data"]; theme: Theme; vertical: boolean}> = ({d, theme, vertical}) => (
  <Panel theme={theme} vertical={vertical}>
    <div style={{fontFamily: CONDENSED, fontSize: vertical ? 150 : 150, lineHeight: 0.6, color: theme.highlight, WebkitTextStroke: "2px #000"}}>“</div>
    <div style={{fontFamily: HEAVY, fontWeight: 900, fontSize: vertical ? 56 : 56, lineHeight: 1.18, marginTop: 10}}>{d.text}</div>
    <div style={{fontFamily: BOLD, fontWeight: 700, fontSize: vertical ? 36 : 34, marginTop: 26, opacity: 0.75}}>
      — {d.who}{d.where ? `, ${d.where}` : ""}
    </div>
  </Panel>
);

const Outro: React.FC<{d: Extract<Card, {template: "outro"}>["data"]; theme: Theme; vertical: boolean}> = ({d, theme, vertical}) => (
  <Panel theme={theme} vertical={vertical}>
    <div style={{fontFamily: HEAVY, fontWeight: 900, fontSize: vertical ? 60 : 62, lineHeight: 1.15, textAlign: "center"}}>{d.question}</div>
    <div style={{margin: "30px auto 0", width: "fit-content", background: theme.highlight, color: "#000", borderRadius: 999,
      padding: "16px 36px", fontFamily: BOLD, fontWeight: 700, fontSize: vertical ? 38 : 36}}>{d.cta}</div>
  </Panel>
);

const Chapter: React.FC<{d: Extract<Card, {template: "chapter"}>["data"]; theme: Theme; vertical: boolean}> = ({d, theme, vertical}) => {
  const {enter, opacity} = useEnterExit();
  return (
    <AbsoluteFill style={{alignItems: "flex-start", justifyContent: "flex-start", padding: vertical ? "260px 60px" : "90px 110px"}}>
      <div style={{opacity, transform: `translateX(${interpolate(enter, [0, 1], [-60, 0])}px)`}}>
        {d.number ? <div style={{fontFamily: CONDENSED, fontSize: vertical ? 120 : 140, color: theme.highlight, lineHeight: 1,
          WebkitTextStroke: "3px #000"}}>{d.number}</div> : null}
        <div style={{fontFamily: HEAVY, fontWeight: 900, fontSize: vertical ? 64 : 72, color: "#fff", background: "rgba(0,0,0,0.55)",
          padding: "10px 24px", borderRadius: 14, marginTop: 8, textTransform: "uppercase"}}>{d.title}</div>
      </div>
    </AbsoluteFill>
  );
};

const styled = (theme: Theme, look?: Look): Theme => {
  if (look?.cardStyle === "dark") return {...theme, card: "rgba(12,16,30,0.9)", ink: "#FFFFFF"};
  if (look?.cardStyle === "accent") return {...theme, card: theme.highlight, ink: "#000000"};
  return theme;
};

export const CardView: React.FC<{card: Card; theme: Theme; vertical: boolean; look?: Look}> = ({card, theme: base, vertical, look}) => {
  const theme = styled(base, look);
  const body = (() => {
    switch (card.template) {
      case "headline": return <Headline d={card.data} theme={theme} vertical={vertical} />;
      case "stat": return <Stat d={card.data} theme={theme} vertical={vertical} />;
      case "compare": return <Compare d={card.data} theme={theme} vertical={vertical} />;
      case "list": return <List d={card.data} theme={theme} vertical={vertical} />;
      case "quote": return <Quote d={card.data} theme={theme} vertical={vertical} />;
      case "outro": return <Outro d={card.data} theme={theme} vertical={vertical} />;
      case "chapter": return <Chapter d={card.data} theme={theme} vertical={vertical} />;
      case "slam": return <Slam d={card.data} theme={theme} vertical={vertical} />;
      default: return null;
    }
  })();
  return (
    <AbsoluteFill>
      {card.template !== "chapter" && card.template !== "slam" ? <Dim /> : null}
      {body}
    </AbsoluteFill>
  );
};
