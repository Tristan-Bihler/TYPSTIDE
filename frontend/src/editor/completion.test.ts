import { describe, expect, it } from "vitest";

import { lspSnippet } from "./completion";

describe("lspSnippet", () => {
  it("keeps numbered fields", () => {
    expect(lspSnippet("figure(${1:body})")).toBe("figure(${1:body})");
    expect(lspSnippet("footnote[${1:}]")).toBe("footnote[${1}]");
    expect(lspSnippet("f($1, $0)")).toBe("f(${1}, ${0})");
  });

  it("escapes literal braces so Typst code blocks are not taken for fields", () => {
    expect(lspSnippet("if ${1:x} {\n\t$2\n}")).toBe("if ${1:x} \\{\n\t${2}\n\\}");
    expect(lspSnippet("#{ x }")).toBe("#\\{ x \\}");
  });

  it("resolves escapes, choices and variables", () => {
    expect(lspSnippet("\\$x \\} \\\\")).toBe("$x \\} \\");
    expect(lspSnippet("${1|left,right|}")).toBe("${1:left}");
    expect(lspSnippet("${TM_SELECTED_TEXT:sel} $NAME!")).toBe("sel !");
    expect(lspSnippet("${1:a\\}b}")).toBe("${1:ab}");
  });

  it("leaves text without fields alone", () => {
    expect(lspSnippet("sec:intro")).toBe("sec:intro");
    expect(lspSnippet("cost $ 5")).toBe("cost $ 5");
  });
});
