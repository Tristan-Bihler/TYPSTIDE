// Correct English text using every pattern the insert toolbar generates. LTeX+ must report
// nothing here after our filter (backend/tests/test_ltex_real.py).
#set page(paper: "a4", numbering: "1")
#set text(lang: "en")
#set heading(numbering: "1.1")

#outline()

= Introduction <sec:intro>

This thesis examines a simple measuring setup. The results are summarized in
@sec:results and compared with the literature @knuth1984.

== Motivation

The experiment is *important* for teaching, because it shows _clearly_ how measurement
errors arise.#footnote[A detailed derivation is given in the appendix.] It is also cheap.

=== Goals

- The measurement should be repeatable.
- The setup should cost little.

+ First, the sensor is calibrated.
+ Then the values are recorded.

= Method

#figure(
  image("/bilder/aufbau.svg", width: 80%),
  caption: [The experimental setup in the lab],
) <fig:setup>

The measurement is carried out as shown in @fig:setup. The values are listed in
@tab:values.

#figure(
  table(
    columns: 3,
    table.header[*Quantity*][*Value*][*Unit*],
    [Length], [12], [mm],
    [Mass], [3], [g],
  ),
  caption: [The measured values],
) <tab:values>

The energy follows from $E = m c^2$ and is described in more detail in @eq:energy.

#math.equation(block: true, numbering: "(1)", $ E = m c^2 $) <eq:energy>

An unnumbered equation also appears in the text:

$ sum_(i=1)^n i = (n(n+1)) / 2 $

The following code is not checked:

```python
def evaluate(values):
    return sum(values) / len(values)
```

Even `inline_code()` stays untouched.

#pagebreak()

= Results <sec:results>

The results confirm the expectation (see @tab:values). The deviation is small, as
already suspected in @sec:intro.

#bibliography("/quellen.bib")
