import {CalculateMetadataFunction, Composition} from "remotion";
import {Main} from "./Main";
import {VideoProps} from "./types";
import {sampleProps} from "./sample";

const fromProps: CalculateMetadataFunction<VideoProps> = ({props}) => ({
  durationInFrames: Math.max(1, props.durationInFrames),
  fps: props.fps,
});

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="Short"
      component={Main}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={300}
      defaultProps={sampleProps(true)}
      calculateMetadata={fromProps}
    />
    <Composition
      id="Long"
      component={Main}
      width={1920}
      height={1080}
      fps={30}
      durationInFrames={300}
      defaultProps={sampleProps(false)}
      calculateMetadata={fromProps}
    />
  </>
);
