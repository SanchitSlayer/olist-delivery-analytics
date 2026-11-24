"""Shared Plotly styling so the notebooks and the dashboard look the same."""

import plotly.graph_objects as go
import plotly.io as pio

# Colour roles. On-time vs late are the two main series everywhere.
BLUE = "#2a78d6"     # on-time / primary series
ORANGE = "#eb6834"   # late / second series
AQUA = "#1baf7a"     # third series, used sparingly
GREY = "#a3a29c"     # context marks (e.g. "all other" bars)

TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
GRID = "#e6e5e1"
SURFACE = "#fcfcfb"

FONT = "Inter, Helvetica Neue, Arial, sans-serif"


def register_template() -> None:
    """Register an "olist" Plotly template and make it the default."""
    template = go.layout.Template()
    template.layout = go.Layout(
        font=dict(family=FONT, size=13, color=TEXT),
        title=dict(font=dict(size=16, color=TEXT), x=0, xanchor="left", y=0.97),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        colorway=[BLUE, ORANGE, AQUA],
        margin=dict(l=60, r=30, t=70, b=50),
        xaxis=dict(showgrid=False, linecolor=GRID, ticks="", tickfont=dict(color=TEXT_MUTED),
                   title=dict(font=dict(color=TEXT_MUTED))),
        yaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, ticks="",
                   tickfont=dict(color=TEXT_MUTED), title=dict(font=dict(color=TEXT_MUTED))),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    font=dict(color=TEXT_MUTED)),
        hoverlabel=dict(font=dict(family=FONT)),
        barcornerradius=4,
        bargap=0.25,
    )
    template.data.scatter = [go.Scatter(line=dict(width=2), marker=dict(size=8))]
    pio.templates["olist"] = template
    pio.templates.default = "olist"
