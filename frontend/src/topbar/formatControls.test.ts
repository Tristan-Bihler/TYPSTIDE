import { describe, expect, it } from "vitest";

import { filterFonts, sizeLabel, spacingLabel, targetText } from "./formatControls";

const SPACINGS = [
  { label: "1.0", leading: "0.5em", default: false },
  { label: "1.15", leading: "0.65em", default: true },
  { label: "1.5", leading: "1.05em", default: false },
];

describe("format labels", () => {
  it("shows sizes in pt without the unit", () => {
    expect(sizeLabel("14pt", 11)).toBe("14");
    expect(sizeLabel("10.5pt", 11)).toBe("10.5");
    expect(sizeLabel(null, 11)).toBe("11");
    expect(sizeLabel("1.2em", 11)).toBe("1.2em");
  });

  it("names line spacings by their option", () => {
    expect(spacingLabel("1.05em", SPACINGS)).toBe("1.5");
    expect(spacingLabel(null, SPACINGS)).toBe("1.15");
    expect(spacingLabel("0.8em", SPACINGS)).toBe("0.8em");
  });

  it("says what a change applies to", () => {
    expect(targetText("size", false, "main.typ")).toBe("Selected text");
    expect(targetText("line_spacing", false, "main.typ")).toBe("The selected paragraphs");
    expect(targetText("font", true, "kapitel/main.typ")).toBe("Whole document (main.typ)");
    expect(targetText("font", true, null)).toContain("set a main file first");
  });
});

describe("filterFonts", () => {
  const fonts = [
    { family: "DejaVu Sans Mono", builtin: true },
    { family: "Libertinus Serif", builtin: true },
    { family: "DejaVu Sans", builtin: false },
  ];

  it("keeps fonts containing every typed word, in order", () => {
    expect(filterFonts(fonts, "dejavu sans").map((f) => f.family)).toEqual(["DejaVu Sans Mono", "DejaVu Sans"]);
    expect(filterFonts(fonts, "  serif ").map((f) => f.family)).toEqual(["Libertinus Serif"]);
    expect(filterFonts(fonts, "")).toHaveLength(3);
    expect(filterFonts(fonts, "comic")).toEqual([]);
  });
});
