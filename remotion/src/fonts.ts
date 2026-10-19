import {loadFont} from "@remotion/fonts";
import {staticFile} from "remotion";

// Free fonts (SIL Open Font License), shipped in public/fonts.
export const HEAVY = "Montserrat Black";
export const BOLD = "Montserrat";
export const CONDENSED = "Anton";

export const fontsReady = Promise.all([
  loadFont({family: HEAVY, url: staticFile("fonts/Montserrat-Black.ttf"), weight: "900"}),
  loadFont({family: BOLD, url: staticFile("fonts/Montserrat-Bold.ttf"), weight: "700"}),
  loadFont({family: BOLD, url: staticFile("fonts/Montserrat-SemiBold.ttf"), weight: "600"}),
  loadFont({family: CONDENSED, url: staticFile("fonts/Anton-Regular.ttf"), weight: "400"}),
]);
