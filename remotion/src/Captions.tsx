import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {HEAVY} from "./fonts";
import {CaptionPage, Theme} from "./types";

// Big-channel captions: 1-3 words, the spoken word pops in the highlight colour, key words coloured.
export const Captions: React.FC<{pages: CaptionPage[]; theme: Theme; vertical: boolean}> = ({pages, theme, vertical}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const ms = (frame / fps) * 1000;
  const index = pages.findIndex((p) => ms >= p.startMs && ms < p.endMs);
  if (index < 0) return null;
  const page = pages[index];
  const sinceStart = frame - Math.round((page.startMs / 1000) * fps);
  const enter = spring({frame: sinceStart, fps, config: {damping: 12, stiffness: 220}, durationInFrames: 8});
  const tilt = [-2, 0, 2, 1, -1][index % 5];

  return (
    <AbsoluteFill style={{justifyContent: "flex-start", alignItems: "center",
      paddingTop: vertical ? 1130 : 820, pointerEvents: "none"}}>
      <div style={{display: "flex", flexWrap: "wrap", justifyContent: "center", gap: vertical ? "0 34px" : "0 24px",
        maxWidth: vertical ? 940 : 1500, transform: `scale(${interpolate(enter, [0, 1], [0.82, 1])}) rotate(${vertical ? tilt : 0}deg)`}}>
        {page.words.map((w, i) => {
          const active = ms >= w.startMs && ms < w.endMs + 40;
          const wordFrame = frame - Math.round((w.startMs / 1000) * fps);
          const bounce = active ? 1 + 0.08 * spring({frame: wordFrame, fps, config: {damping: 9, stiffness: 260}, durationInFrames: 6}) : 1;
          return (
            <span key={i} style={{fontFamily: HEAVY, fontWeight: 900, fontSize: vertical ? 92 : 64, lineHeight: 1.12,
              textTransform: vertical ? "uppercase" : "none",
              color: active ? theme.highlight : w.key ? theme.keyword : theme.text,
              transform: `scale(${bounce})`, display: "inline-block",
              WebkitTextStroke: vertical ? "3px #000" : "2px #000", paintOrder: "stroke fill",
              textShadow: "0 6px 0 rgba(0,0,0,0.85), 0 10px 26px rgba(0,0,0,0.6)"}}>
              {w.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
