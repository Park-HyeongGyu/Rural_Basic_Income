(function () {
  const colors = [
    "#2364aa",
    "#c44900",
    "#2a7f62",
    "#7b3f98",
    "#b3261e",
    "#52616f",
    "#d89d00",
    "#008aa8",
  ];

  function formatPeriod(dateValue) {
    const raw = String(dateValue);
    const compactPeriod = raw.match(/^(\d{4})(\d{2})$/);
    if (compactPeriod) {
      return {
        axisValue: `${compactPeriod[1]}-${compactPeriod[2]}-01`,
        label: `${compactPeriod[1]}.${compactPeriod[2]}`,
      };
    }

    const delimitedPeriod = raw.match(/^(\d{4})[-.](\d{2})(?:[-.]\d{2})?$/);
    if (delimitedPeriod) {
      return {
        axisValue: `${delimitedPeriod[1]}-${delimitedPeriod[2]}-01`,
        label: `${delimitedPeriod[1]}.${delimitedPeriod[2]}`,
      };
    }

    return {
      axisValue: raw,
      label: raw,
    };
  }

  function renderEmptyState(element, message) {
    Plotly.purge(element);
    element.innerHTML = `<div class="empty-state">${message}</div>`;
  }

  function renderLineChart(element, seriesGroups, options = {}) {
    const emptyMessage = options.emptyMessage || "데이터 없음";
    if (!seriesGroups.length || seriesGroups.every((group) => group.points.length === 0)) {
      renderEmptyState(element, emptyMessage);
      return;
    }

    const traces = seriesGroups.map((group, index) => {
      const points = group.points.map((point) => ({
        period: formatPeriod(point.date),
        value: point.value,
      }));

      return {
        type: "scatter",
        mode: "lines+markers",
        name: group.label,
        x: points.map((point) => point.period.axisValue),
        y: points.map((point) => point.value),
        customdata: points.map((point) => point.period.label),
        line: {
          color: colors[index % colors.length],
          width: 2.5,
        },
        marker: {
          color: colors[index % colors.length],
          size: 6,
        },
        hovertemplate: group.hoverTemplate || options.hoverTemplate || "%{y:,.0f}<extra></extra>",
      };
    });

    const layout = {
      margin: { t: 18, r: 26, b: 48, l: 68 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
      hovermode: "x unified",
      xaxis: {
        type: "date",
        showgrid: false,
        tickfont: { color: "#65717f" },
        tickformat: "%Y.%m",
        hoverformat: "%Y.%m",
        zeroline: false,
      },
      yaxis: {
        gridcolor: "#e6ebf1",
        tickfont: { color: "#65717f" },
        tickformat: options.yTickFormat || ",",
        zeroline: false,
      },
      legend: {
        orientation: "h",
        x: 0,
        y: 1.12,
        xanchor: "left",
        font: { size: 12 },
      },
      hoverlabel: {
        bgcolor: "#ffffff",
        bordercolor: "#c8d1dc",
        font: { color: "#1f2933" },
      },
    };

    const config = {
      displayModeBar: false,
      responsive: true,
    };

    Plotly.react(element, traces, layout, config);
  }

  window.RBICharts = Object.freeze({
    renderLineChart,
  });
})();
