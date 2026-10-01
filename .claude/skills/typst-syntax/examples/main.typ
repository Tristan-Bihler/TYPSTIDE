// Verified against Typst 0.15.0 (backend/tests/test_typst_skill.py compiles this project).
// Every pattern here is one the insert toolbar generates or relies on.
#set page(paper: "a4", numbering: "1")
#set text(lang: "de")
#set heading(numbering: "1.1")

#outline()

= Überschrift 1
== Überschrift 2
=== Überschrift 3
==== Überschrift 4

*fett* und _kursiv_ und eine Fußnote#footnote[Text der Fußnote.].

- Aufzählung
- zweiter Punkt
+ Nummerierung
+ zweiter Schritt

#figure(
  table(
    columns: 3,
    table.header[*Spalte 1*][*Spalte 2*][*Spalte 3*],
    [ ], [ ], [ ],
    [ ], [ ], [ ],
  ),
  caption: [Messwerte mit \[Klammern\], \#Raute und \/\/ Schrägstrichen],
) <tab:messwerte>

Inline-Mathematik $a^2 + b^2 = c^2$ und eine abgesetzte Formel:

$ sum_(i=1)^n i $

#math.equation(block: true, numbering: "(1)", $ sum_(i=1)^n i = (n(n+1)) / 2 $) <eq:summe>

#include "kapitel/eins.typ"

#pagebreak()

Der Ablauf in @fig:plan-ablauf ist ohne Pakete gezeichnet.

#figure(include "/plans/ablauf.typ", caption: [Ablauf der Messung]) <fig:plan-ablauf>

#bibliography("refs.bib")
