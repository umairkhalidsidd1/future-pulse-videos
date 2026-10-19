// The "shot list" that Python writes for every video. Remotion only draws what is in here.

export type Theme = {
  text: string;      // "#FFFFFF"
  highlight: string; // spoken word / accents
  keyword: string;   // key words in captions
  card: string;      // card background
  ink: string;       // text on cards
};

export type Shot = {
  from: number;       // frame
  duration: number;   // frames
  src: string;        // file inside public/, e.g. "runs/abc/clips/x.mp4"; "" = brand background
  kind: "video" | "image";
  width: number;
  height: number;
  trimBefore: number; // frames to skip at the start of the clip
  motion: "zoom_in" | "zoom_out" | "pan_left" | "pan_right";
  credit?: string;    // e.g. "NASA" (shown small in a corner)
  punches?: number[]; // frames (from the shot start) where a key word is stressed: quick zoom-in
};

// The look changes per series, so videos don't all look like one template.
export type Look = {
  cardStyle: "light" | "dark" | "accent";
  captionY: number;   // 0..1 of the height
  hookTilt: number;   // degrees
};

export type HeadlineData = {source: string; title: string; date?: string; highlight?: string[]};
export type SlamData = {text: string};
export type StatData = {value: number; prefix?: string; suffix?: string; decimals?: number; label: string};
export type CompareData = {title?: string; leftLabel: string; leftValue: string; rightLabel: string; rightValue: string};
export type ListData = {title: string; items: string[]};
export type QuoteData = {text: string; who: string; where?: string};
export type OutroData = {question: string; cta: string};
export type ChapterData = {number?: string; title: string};

export type Card =
  | {from: number; duration: number; template: "headline"; data: HeadlineData}
  | {from: number; duration: number; template: "stat"; data: StatData}
  | {from: number; duration: number; template: "compare"; data: CompareData}
  | {from: number; duration: number; template: "list"; data: ListData}
  | {from: number; duration: number; template: "quote"; data: QuoteData}
  | {from: number; duration: number; template: "outro"; data: OutroData}
  | {from: number; duration: number; template: "chapter"; data: ChapterData}
  | {from: number; duration: number; template: "slam"; data: SlamData};

export type CaptionWord = {text: string; startMs: number; endMs: number; key: boolean};
export type CaptionPage = {startMs: number; endMs: number; words: CaptionWord[]};

export type VideoProps = {
  fps: number;
  durationInFrames: number;
  vertical: boolean;
  theme: Theme;
  look: Look;
  brand: string;
  hook: {text: string; frames: number} | null;
  progressBar: boolean;
  shots: Shot[];
  cards: Card[];
  captions: CaptionPage[];
};
