import {AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig, interpolate} from "remotion";
import "./fonts";
import {CONDENSED} from "./fonts";
import {Footage} from "./templates/Footage";
import {Captions} from "./Captions";
import {CardView} from "./templates/Cards";
import {VideoProps} from "./types";

const ProgressBar: React.FC<{color: string}> = ({color}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, width} = useVideoConfig();
  return (
    <div style={{position: "absolute", top: 0, left: 0, height: 12, width: (frame / durationInFrames) * width,
      background: color, boxShadow: `0 0 18px ${color}`}} />
  );
};

const Hook: React.FC<{text: string; color: string; vertical: boolean}> = ({text, color, vertical}) => {
  const frame = useCurrentFrame();
  const pop = interpolate(frame, [0, 6, 10], [0.6, 1.06, 1], {extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{alignItems: "center", paddingTop: vertical ? 300 : 120}}>
      <div style={{background: color, color: "#000", fontFamily: CONDENSED, fontSize: vertical ? 104 : 120,
        lineHeight: 1.05, padding: "18px 34px", borderRadius: 18, transform: `scale(${pop}) rotate(-2deg)`,
        textAlign: "center", maxWidth: vertical ? 920 : 1500, textTransform: "uppercase",
        boxShadow: "0 18px 50px rgba(0,0,0,0.45)"}}>
        {text}
      </div>
    </AbsoluteFill>
  );
};

export const Main: React.FC<VideoProps> = (p) => {
  const {theme} = p;
  return (
    <AbsoluteFill style={{background: "#05070d"}}>
      {p.shots.map((s, i) => (
        <Sequence key={`shot-${i}`} name={`Shot ${i}`} from={s.from} durationInFrames={s.duration}>
          <Footage shot={s} vertical={p.vertical} />
        </Sequence>
      ))}
      {p.cards.map((c, i) => (
        <Sequence key={`card-${i}`} name={`Card ${c.template}`} from={c.from} durationInFrames={c.duration}>
          <CardView card={c} theme={theme} vertical={p.vertical} />
        </Sequence>
      ))}
      <Captions pages={p.captions} theme={theme} vertical={p.vertical} />
      {p.hook && p.hook.text ? (
        <Sequence name="Hook" durationInFrames={p.hook.frames}>
          <Hook text={p.hook.text} color={theme.highlight} vertical={p.vertical} />
        </Sequence>
      ) : null}
      {p.progressBar ? <ProgressBar color={theme.highlight} /> : null}
    </AbsoluteFill>
  );
};
