// Correct German text using every pattern the insert toolbar generates. LTeX+ must report
// nothing here after our filter (backend/tests/test_ltex_real.py).
#set page(paper: "a4", numbering: "1")
#set text(lang: "de")
#set heading(numbering: "1.1")

#outline()

= Einleitung <sec:einleitung>

Diese Arbeit untersucht den Aufbau eines einfachen Messplatzes. Die Ergebnisse werden in
@sec:ergebnisse zusammengefasst und mit der Literatur verglichen @knuth1984.

== Motivation

Der Versuch ist *wichtig* für die Lehre, weil er _anschaulich_ zeigt, wie Messfehler
entstehen.#footnote[Eine ausführliche Herleitung steht im Anhang.] Außerdem ist er
günstig.

=== Ziele

- Die Messung soll wiederholbar sein.
- Der Aufbau soll wenig kosten.

+ Zuerst wird der Sensor kalibriert.
+ Danach werden die Werte aufgezeichnet.

==== Abgrenzung

Andere Verfahren werden hier nicht betrachtet.

= Methode

#figure(
  image("/bilder/aufbau.svg", width: 80%),
  caption: [Der Versuchsaufbau im Labor],
) <fig:aufbau>

Die Messung wird wie in @fig:aufbau gezeigt durchgeführt. Die Messwerte stehen in
@tab:werte.

#figure(
  table(
    columns: 3,
    table.header[*Größe*][*Wert*][*Einheit*],
    [Länge], [12], [mm],
    [Masse], [3], [g],
  ),
  caption: [Die gemessenen Werte],
) <tab:werte>

Die Energie folgt aus $E = m c^2$ und wird in @eq:energie genauer beschrieben.

#math.equation(block: true, numbering: "(1)", $ E = m c^2 $) <eq:energie>

Eine unnummerierte Formel steht ebenfalls im Text:

$ sum_(i=1)^n i = (n(n+1)) / 2 $

Der folgende Code wird nicht geprüft:

```python
def auswerten(werte):
    return sum(werte) / len(werte)
```

Auch `inline_code()` bleibt unberührt.

#pagebreak()

= Ergebnisse <sec:ergebnisse>

Die Ergebnisse bestätigen die Erwartung (siehe @tab:werte). Die Abweichung ist klein, wie
schon in @sec:einleitung vermutet.

#bibliography("/quellen.bib")
