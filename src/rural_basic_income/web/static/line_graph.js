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

  function formatDate(dateValue) {
    const raw = String(dateValue);
    if (raw.length === 6) {
      return `${raw.slice(0, 4)}.${raw.slice(4)}`;
    }
    return raw;
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

    const traces = seriesGroups.map((group, index) => ({
      type: "scatter",
      mode: "lines+markers",
      name: group.label,
      x: group.points.map((point) => formatDate(point.date)),
      y: group.points.map((point) => point.value),
      line: {
        color: colors[index % colors.length],
        width: 2.5,
      },
      marker: {
        color: colors[index % colors.length],
        size: 6,
      },
      hovertemplate: "%{y:,.0f}<extra></extra>",
    }));

    const layout = {
      margin: { t: 18, r: 26, b: 48, l: 68 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
      hovermode: "x unified",
      xaxis: {
        showgrid: false,
        tickfont: { color: "#65717f" },
        zeroline: false,
      },
      yaxis: {
        gridcolor: "#e6ebf1",
        tickfont: { color: "#65717f" },
        tickformat: ",",
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
