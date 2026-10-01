// Built-in drawing (no packages), as the planner exports it: place + box + curve + polygon.
#block(width: 11.80cm, height: 3.23cm, breakable: false)[
  #place(curve(stroke: 0.6pt, curve.move((3.44cm, 0.65cm)), curve.line((3.98cm, 0.65cm))))
  #place(polygon(fill: black, (4.16cm, 0.65cm), (3.94cm, 0.74cm), (3.94cm, 0.56cm)))
  #place(curve(stroke: 0.6pt, curve.move((7.41cm, 1.34cm)), curve.line((8.43cm, 1.81cm))))
  #place(polygon(fill: black, (8.59cm, 1.89cm), (8.36cm, 1.88cm), (8.43cm, 1.71cm)))
  #place(dx: 0.00cm, dy: 0.00cm, box(width: 3.40cm, height: 1.30cm, inset: 3pt, radius: 3pt, fill: luma(228), stroke: 0.6pt, align(center + horizon, text(size: 9.0pt, fill: luma(80))[Aufbau])))
  #place(dx: 4.20cm, dy: 0.00cm, box(width: 3.40cm, height: 1.30cm, inset: 3pt, radius: 3pt, fill: white, stroke: 1.4pt, align(center + horizon, text(size: 9.0pt, fill: black)[Messen])))
  #place(dx: 8.40cm, dy: 1.93cm, box(width: 3.40cm, height: 1.30cm, inset: 3pt, radius: 3pt, fill: white, stroke: 0.6pt, align(center + horizon, text(size: 9.0pt, fill: black)[Auswerten \[Teil 1\]])))
]
