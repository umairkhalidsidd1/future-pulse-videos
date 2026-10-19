import {VideoProps} from "./types";

// Demo data so every template can be previewed without running the Python pipeline.
export const sampleProps = (vertical: boolean): VideoProps => {
  const fps = 30;
  const s = (sec: number) => Math.round(sec * fps);
  const words = "SpaceX just flew its biggest rocket for the eleventh time and this time it caught the booster".split(" ");
  const step = 7000 / words.length;
  const pages = [];
  for (let i = 0; i < words.length; i += 3) {
    const chunk = words.slice(i, i + 3).map((w, k) => ({text: w, startMs: (i + k) * step, endMs: (i + k + 1) * step,
      key: ["biggest", "eleventh", "caught"].includes(w)}));
    pages.push({startMs: chunk[0].startMs, endMs: chunk[chunk.length - 1].endMs, words: chunk});
  }
  return {
    fps,
    durationInFrames: s(21),
    vertical,
    theme: {text: "#FFFFFF", highlight: "#FFE600", keyword: "#39FF14", card: "#F7F7F2", ink: "#0B0F1A"},
    brand: "Reality Shockwaves",
    hook: {text: "It caught a skyscraper", frames: s(2.4)},
    progressBar: vertical,
    shots: [{from: 0, duration: s(21), src: "", kind: "video", width: 1920, height: 1080, trimBefore: 0, motion: "zoom_in"}],
    cards: [
      {from: s(3), duration: s(3), template: "headline", data: {source: "Space.com", title: "SpaceX catches Super Heavy booster on 11th Starship flight", date: "Oct 19"}},
      {from: s(6), duration: s(3), template: "stat", data: {value: 6300, suffix: "lbs", label: "of cargo and science on board"}},
      {from: s(9), duration: s(3), template: "compare", data: {title: "Cost to orbit", leftLabel: "Shuttle era", leftValue: "$54,500/kg", rightLabel: "Falcon 9", rightValue: "$2,700/kg"}},
      {from: s(12), duration: s(3), template: "list", data: {title: "3 things to know", items: ["Booster caught by the tower", "Ship reached orbit", "Next flight in weeks"]}},
      {from: s(15), duration: s(3), template: "quote", data: {text: "This is the most complex flight we have ever attempted.", who: "SpaceX", where: "launch webcast"}},
      {from: s(18), duration: s(3), template: "outro", data: {question: "Would you fly on a reused rocket?", cta: "Follow for daily tech"}},
    ],
    captions: pages,
  };
};
