import {AbsoluteFill, Img, OffthreadVideo, spring, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {BOLD} from "../fonts";
import {Shot} from "../types";

// Real footage with gentle motion. A wide clip inside a tall Short is shown large in the middle over a
// blurred copy of itself, instead of being cropped hard (which looks far too zoomed in).
export const Footage: React.FC<{shot: Shot; vertical: boolean}> = ({shot, vertical}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const t = frame / Math.max(1, durationInFrames - 1);
  // A punch is a quick zoom-in on a stressed word that holds until the next cut.
  const punch = (shot.punches ?? []).reduce((acc, p) => acc + (frame >= p
    ? 0.09 * spring({frame: frame - p, fps, config: {damping: 14, stiffness: 320}, durationInFrames: 5}) : 0), 0);
  const base = shot.motion === "zoom_in" ? 1 + 0.08 * t : shot.motion === "zoom_out" ? 1.08 - 0.08 * t : 1.06;
  const zoom = base + Math.min(punch, 0.18);
  const pan = shot.motion === "pan_left" ? 3 - 6 * t : shot.motion === "pan_right" ? -3 + 6 * t : 0;
  const grade = "contrast(1.07) saturate(1.22) brightness(1.01)";

  if (!shot.src) {
    return <AbsoluteFill style={{background: "radial-gradient(circle at 30% 20%, #1b2a4a, #05070d 70%)"}} />;
  }
  const media = (style: React.CSSProperties) =>
    shot.kind === "image" ? (
      <Img src={staticFile(shot.src)} style={style} />
    ) : (
      <OffthreadVideo src={staticFile(shot.src)} trimBefore={shot.trimBefore} muted style={style} />
    );
  const wideInTall = vertical && shot.width > shot.height;
  const fill: React.CSSProperties = {width: "100%", height: "100%", objectFit: "cover",
    transform: `scale(${zoom}) translateX(${pan}%)`, filter: grade};

  return (
    <AbsoluteFill style={{overflow: "hidden"}}>
      {wideInTall ? (
        <>
          {media({width: "100%", height: "100%", objectFit: "cover", transform: "scale(1.3)",
            filter: "blur(38px) brightness(0.55) saturate(1.3)"})}
          <AbsoluteFill style={{justifyContent: "center"}}>
            <div style={{width: "100%", height: "50%", overflow: "hidden", marginTop: -120,
              boxShadow: "0 30px 80px rgba(0,0,0,0.6)"}}>
              {media(fill)}
            </div>
          </AbsoluteFill>
        </>
      ) : (
        media(fill)
      )}
      {/* soft dark edges keep captions and cards readable on bright footage */}
      <AbsoluteFill style={{background: "linear-gradient(180deg, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0) 25%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.55) 100%)"}} />
      {shot.credit ? (
        <div style={{position: "absolute", right: vertical ? 40 : 50, bottom: vertical ? 520 : 40,
          fontFamily: BOLD, fontWeight: 600, fontSize: vertical ? 24 : 22, color: "rgba(255,255,255,0.75)"}}>
          {shot.credit}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
