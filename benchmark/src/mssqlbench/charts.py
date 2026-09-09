"""Chart rendering.

One PNG per theme, six panels: QPS and latency for each of the three
scenarios. Colors come from a validated two-slot categorical palette
(blue / orange), assigned to a driver by fixed order - never by rank - so the
same driver keeps the same hue across every panel.
"""

from __future__ import annotations

from pathlib import Path

# Categorical slots 1 and 2, validated for both surfaces
# (worst adjacent CVD dE 24.7 light / 26.8 dark; all six checks pass).
SERIES_LIGHT = ["#2a78d6", "#eb6834"]
SERIES_DARK = ["#3987e5", "#d95926"]

THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "primary": "#0b0b0b",
        "secondary": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "series": SERIES_LIGHT,
    },
    "dark": {
        "surface": "#1a1a19",
        "primary": "#ffffff",
        "secondary": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "series": SERIES_DARK,
    },
}

FONT_STACK = ["Segoe UI", "DejaVu Sans", "sans-serif"]


def _style_axes(ax, theme: dict, *, ylabel: str, title: str, xlabel: str = "") -> None:
    ax.set_facecolor(theme["surface"])

    ax.set_title(title, color=theme["primary"], fontsize=11, pad=10, loc="left")
    ax.set_ylabel(ylabel, color=theme["secondary"], fontsize=9)

    if xlabel:
        ax.set_xlabel(xlabel, color=theme["secondary"], fontsize=9)

    ax.tick_params(colors=theme["muted"], labelsize=9, length=0)

    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme["axis"])
        ax.spines[side].set_linewidth(0.8)

    # Recessive hairline grid on the value axis only.
    ax.yaxis.grid(True, color=theme["grid"], linewidth=0.8)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)


def _grouped_bars(
    ax,
    theme: dict,
    categories: list[str],
    series: dict[str, list[float]],
    *,
    title: str,
    ylabel: str,
    value_fmt: str = "{:,.0f}",
    label_values: bool = False,
    log: bool = False,
) -> None:
    import numpy as np

    drivers = list(series)
    count = max(len(drivers), 1)

    positions = np.arange(len(categories), dtype=float)
    slot = 0.72 / count

    for index, driver in enumerate(drivers):
        offset = (index - (count - 1) / 2) * slot

        ax.bar(
            positions + offset,
            series[driver],
            width=slot * 0.94,  # the 6% shortfall is the 2px surface gap
            label=driver,
            color=theme["series"][index % len(theme["series"])],
            edgecolor=theme["surface"],
            linewidth=1.0,
            zorder=3,
        )

        if label_values:
            for x, value in zip(positions + offset, series[driver]):
                if value != value:  # NaN
                    continue

                ax.annotate(
                    value_fmt.format(value),
                    (x, value),
                    textcoords="offset points",
                    xytext=(0, 4),
                    ha="center",
                    fontsize=8,
                    color=theme["secondary"],
                )

    ax.set_xticks(positions)
    ax.set_xticklabels(categories)

    if log:
        # Batched and row-by-row writes differ by more than an order of
        # magnitude; on a linear axis the smaller bars disappear. Every bar is
        # value-labeled so the axis is never the only way to read a magnitude.
        ax.set_yscale("log")

    _style_axes(ax, theme, ylabel=ylabel, title=title)


def _lines(
    ax,
    theme: dict,
    x_values: list[int],
    series: dict[str, list[float]],
    *,
    title: str,
    ylabel: str,
    xlabel: str,
    value_fmt: str = "{:,.0f}",
) -> None:
    # Worker levels are unevenly spaced (1, 5, 10, 25...); plotting them on
    # evenly spaced positions keeps the low end readable. The axis is ordinal,
    # so slope must be read as "next level", not as a rate.
    positions = list(range(len(x_values)))

    for index, (driver, values) in enumerate(series.items()):
        color = theme["series"][index % len(theme["series"])]

        ax.plot(
            positions,
            values,
            label=driver,
            color=color,
            linewidth=2.0,
            marker="o",
            markersize=5,
            markeredgecolor=theme["surface"],
            markeredgewidth=1.0,
            zorder=3,
        )

        # Direct-label the last point only, so identity never rests on color
        # alone without cluttering every marker.
        if values and values[-1] == values[-1]:
            ax.annotate(
                f"{driver}  {value_fmt.format(values[-1])}",
                (positions[-1], values[-1]),
                textcoords="offset points",
                xytext=(-6, 8),
                ha="right",
                fontsize=8,
                color=theme["secondary"],
            )

    ax.set_xticks(positions)
    ax.set_xticklabels([str(x) for x in x_values])

    _style_axes(ax, theme, ylabel=ylabel, title=title, xlabel=xlabel)


def _by_driver(rows: list[dict], keys: list[str], field: str) -> dict[str, list[float]]:
    drivers = list(dict.fromkeys(r["driver"] for r in rows))

    series: dict[str, list[float]] = {}

    for driver in drivers:
        lookup = {r["label"]: r[field] for r in rows if r["driver"] == driver}
        series[driver] = [lookup.get(key, float("nan")) for key in keys]

    return series


def render(results: list[dict], output_dir: Path, theme_name: str = "light") -> Path | None:
    try:
        import matplotlib

        matplotlib.use("Agg")

        import matplotlib.pyplot as plt
    except ImportError:
        print("[skip] matplotlib not installed; no chart generated.")
        return None

    theme = THEMES[theme_name]

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = FONT_STACK

    point = [r for r in results if r["scenario"] == "point_select"]
    result_set = [r for r in results if r["scenario"] == "result_set"]
    concurrent = [r for r in results if r["scenario"] == "concurrency"]
    writes = [r for r in results if r["scenario"] == "write_ops"]

    fig, axes = plt.subplots(4, 2, figsize=(14, 20))
    fig.patch.set_facecolor(theme["surface"])

    drivers = list(dict.fromkeys(r["driver"] for r in results))

    # --- Scenario 1 -----------------------------------------------------
    if point:
        _grouped_bars(
            axes[0][0],
            theme,
            [""],  # single category: the y-label already names the measure
            {r["driver"]: [r["qps"]] for r in point},
            title="1. Point select - throughput (higher is better)",
            ylabel="queries / sec",
            label_values=True,
        )

        _grouped_bars(
            axes[0][1],
            theme,
            ["avg", "p50", "p95", "p99"],
            {
                r["driver"]: [r["avg_ms"], r["p50_ms"], r["p95_ms"], r["p99_ms"]]
                for r in point
            },
            title="1. Point select - latency (lower is better)",
            ylabel="milliseconds",
            value_fmt="{:.3f}",
            label_values=True,
        )

    # --- Scenario 2 -----------------------------------------------------
    if result_set:
        labels = list(dict.fromkeys(r["label"] for r in result_set))

        _grouped_bars(
            axes[1][0],
            theme,
            labels,
            _by_driver(result_set, labels, "rows_per_second"),
            title="2. Result set - rows materialized / sec (higher is better)",
            ylabel="rows / sec",
        )

        _grouped_bars(
            axes[1][1],
            theme,
            labels,
            _by_driver(result_set, labels, "avg_ms"),
            title="2. Result set - avg time per query (lower is better)",
            ylabel="milliseconds",
            value_fmt="{:.2f}",
            label_values=True,
        )

    # --- Scenario 3 -----------------------------------------------------
    if concurrent:
        worker_levels = sorted({r["workers"] for r in concurrent})
        labels = [f"{w} workers" for w in worker_levels]

        _lines(
            axes[2][0],
            theme,
            worker_levels,
            _by_driver(concurrent, labels, "qps"),
            title="3. Concurrency - throughput vs workers (higher is better)",
            ylabel="queries / sec",
            xlabel="concurrent workers",
        )

        _lines(
            axes[2][1],
            theme,
            worker_levels,
            _by_driver(concurrent, labels, "p95_ms"),
            title="3. Concurrency - p95 latency vs workers (lower is better)",
            ylabel="p95 milliseconds",
            xlabel="concurrent workers",
            value_fmt="{:.2f}",
        )

    # --- Scenario 4 -----------------------------------------------------
    if writes:
        # One panel per commit mode: the two live on different scales, and
        # putting them on one axis would say more about the commit cadence
        # than about the drivers.
        modes = [
            ("autocommit", "4. Writes, autocommit - one commit per statement"),
            ("transaction", "4. Writes, explicit transaction - commit per batch"),
        ]

        for column, (mode, title) in enumerate(modes):
            rows = [r for r in writes if r.get("commit_mode") == mode]

            if not rows:
                continue

            labels = list(dict.fromkeys(r["label"] for r in rows))
            categories = [
                r_label.split(" [")[0].replace(" ", "\n", 1) for r_label in labels
            ]

            # bulkcopy exists only on drivers that ship it, so its group has a
            # single bar. Marked in the label rather than silently paired.
            categories = [
                f"{category}\n(driver-only)"
                if any(
                    r["label"] == label and r.get("bulk_api")
                    for r in rows
                )
                else category
                for category, label in zip(categories, labels)
            ]

            _grouped_bars(
                axes[3][column],
                theme,
                categories,
                _by_driver(rows, labels, "rows_per_second"),
                title=f"{title} (higher is better)",
                ylabel="rows / sec",
                label_values=True,
                log=mode == "transaction",
            )

    for row in axes:
        for ax in row:
            if not ax.has_data():
                ax.axis("off")

    if len(drivers) >= 2:
        handles, legend_labels = axes[0][0].get_legend_handles_labels()

        if handles:
            legend = fig.legend(
                handles,
                legend_labels,
                loc="upper right",
                ncols=len(handles),
                frameon=False,
                fontsize=10,
                bbox_to_anchor=(0.98, 0.985),
            )

            for text in legend.get_texts():
                text.set_color(theme["secondary"])

    fig.suptitle(
        "pyodbc vs mssql-python - SQL Server 2022",
        color=theme["primary"],
        fontsize=15,
        x=0.02,
        ha="left",
        y=0.98,
    )

    fig.tight_layout(rect=(0, 0, 1, 0.955))

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"benchmark-{theme_name}.png"

    fig.savefig(path, dpi=140, facecolor=theme["surface"])
    plt.close(fig)

    return path


def render_all(results: list[dict], output_dir: Path) -> list[Path]:
    paths = []

    for theme_name in THEMES:
        path = render(results, output_dir, theme_name)

        if path is not None:
            paths.append(path)

    return paths
