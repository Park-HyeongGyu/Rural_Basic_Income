const state = {
  regions: [],
  status: null,
  dashboardMap: null,
  selectedRegions: [],
  selectedVariables: new Set(),
  selectedFilters: new Map(),
};

const els = {
  sido: document.getElementById("sido-select"),
  sigungu: document.getElementById("sigungu-select"),
  addRegion: document.getElementById("dashboard-add-region"),
  clearRegions: document.getElementById("dashboard-clear-regions"),
  regionList: document.getElementById("dashboard-region-list"),
  table: document.getElementById("table-select"),
  normalize: document.getElementById("normalize-select"),
  filters: document.getElementById("filter-grid"),
  variables: document.getElementById("variable-list"),
  selectAllVariables: document.getElementById("select-all-variables"),
  refresh: document.getElementById("refresh-button"),
  chart: document.getElementById("line-chart"),
  chartTitle: document.getElementById("chart-title"),
  chartKicker: document.getElementById("chart-kicker"),
  statusLine: document.getElementById("status-line"),
  dataStatusBody: document.getElementById("data-status-body"),
  tableCount: document.getElementById("table-count"),
};

function fetchJson(url) {
  return fetch(url).then((response) => {
    if (!response.ok) {
      return response.json().catch(() => ({})).then((payload) => {
        const detail = payload.detail || response.statusText;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      });
    }
    return response.json();
  });
}

function formatDate(dateValue) {
  const raw = String(dateValue);
  if (raw.length === 6) {
    return `${raw.slice(0, 4)}.${raw.slice(4)}`;
  }
  return raw;
}

function formatNumber(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return new Intl.NumberFormat("ko-KR").format(value);
}

function setStatus(message, isError = false) {
  els.statusLine.textContent = message;
  els.statusLine.classList.toggle("error", isError);
}

function setLoading(isLoading) {
  els.refresh.disabled = isLoading;
  if (isLoading) {
    setStatus("불러오는 중");
  }
}

function currentTable() {
  return state.status.tables.find((table) => table.table_name === els.table.value);
}

function tableLabel(table) {
  return table.table;
}

function variableLabel(variable) {
  return variable.label || variable.name;
}

function selectedRegion() {
  return {
    region_sido: els.sido.value,
    region_sigungu: els.sigungu.value,
  };
}

function regionId(region) {
  return `${region.region_sido}::${region.region_sigungu}`;
}

function regionLabel(region) {
  return `${region.region_sido} ${region.region_sigungu}`;
}

function findRegion(region) {
  return state.regions.find(
    (item) =>
      item.region_sido === region.region_sido &&
      item.region_sigungu === region.region_sigungu,
  );
}

function setSelectedRegions(regions, options = {}) {
  const unique = [];
  const seen = new Set();
  for (const region of regions) {
    const matched = findRegion(region);
    if (!matched) {
      continue;
    }
    const id = regionId(matched);
    if (seen.has(id)) {
      continue;
    }
    seen.add(id);
    unique.push({ ...matched });
  }
  state.selectedRegions = unique;
  renderSelectedDashboardRegions();
  syncDashboardMapSelection();
  if (options.load !== false) {
    loadSeries();
  }
}

function addDashboardRegion(regionArg, options = {}) {
  const region = findRegion(regionArg || selectedRegion());
  if (!region) {
    setStatus("선택할 수 없는 지역입니다", true);
    return false;
  }
  if (state.selectedRegions.some((item) => regionId(item) === regionId(region))) {
    setStatus("이미 선택된 지역입니다", true);
    return false;
  }
  state.selectedRegions.push({ ...region });
  renderSelectedDashboardRegions();
  syncDashboardMapSelection();
  if (options.load !== false) {
    loadSeries();
  }
  return true;
}

function removeDashboardRegion(regionArg, options = {}) {
  const region = findRegion(regionArg);
  if (!region) {
    setStatus("선택할 수 없는 지역입니다", true);
    return false;
  }
  const nextRegions = state.selectedRegions.filter(
    (item) => regionId(item) !== regionId(region),
  );
  if (nextRegions.length === state.selectedRegions.length) {
    setStatus("선택된 지역이 아닙니다", true);
    return false;
  }
  state.selectedRegions = nextRegions;
  renderSelectedDashboardRegions();
  syncDashboardMapSelection();
  if (options.load !== false) {
    loadSeries();
  }
  return true;
}

function regionsBySido(sido) {
  return state.regions.filter((region) => region.region_sido === sido);
}

function fillSelect(select, options, valueGetter, labelGetter, preferredValue) {
  select.replaceChildren();
  for (const optionItem of options) {
    const option = document.createElement("option");
    option.value = valueGetter(optionItem);
    option.textContent = labelGetter(optionItem);
    select.append(option);
  }
  if (preferredValue && [...select.options].some((option) => option.value === preferredValue)) {
    select.value = preferredValue;
  }
}

function populateRegions() {
  const sidos = [...new Set(state.regions.map((region) => region.region_sido))].sort();
  fillSelect(els.sido, sidos, (sido) => sido, (sido) => sido, "전북");
  populateSigungu("임실군");
}

function populateSigungu(preferredSigungu) {
  const regions = regionsBySido(els.sido.value);
  fillSelect(
    els.sigungu,
    regions,
    (region) => region.region_sigungu,
    (region) => region.region_sigungu,
    preferredSigungu,
  );
}

function renderSelectedDashboardRegions() {
  els.regionList.replaceChildren();
  if (!state.selectedRegions.length) {
    const empty = document.createElement("div");
    empty.className = "selection-empty";
    empty.textContent = "지역 없음";
    els.regionList.append(empty);
    return;
  }

  state.selectedRegions.forEach((region) => {
    const item = document.createElement("div");
    item.className = "selected-region-item dashboard-region-item";

    const name = document.createElement("strong");
    name.textContent = regionLabel(region);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "text-button danger-button";
    remove.textContent = "삭제";
    remove.addEventListener("click", () => removeDashboardRegion(region));

    item.append(name, remove);
    els.regionList.append(item);
  });
}

function syncDashboardMapSelection() {
  if (!state.dashboardMap) {
    return;
  }
  state.dashboardMap.updateSelections({
    series: state.selectedRegions,
  });
}

function populateTables() {
  const tables = [...state.status.tables]
    .filter((table) => table.selectable_variables.length > 0)
    .sort((a, b) => {
      if (a.table_name === "clean_population") {
        return -1;
      }
      if (b.table_name === "clean_population") {
        return 1;
      }
      return a.table.localeCompare(b.table);
    });

  fillSelect(
    els.table,
    tables,
    (table) => table.table_name,
    (table) => tableLabel(table),
    "clean_population",
  );
  populateVariableOptions();
}

function populateFilterOptions() {
  const table = currentTable();
  const previousFilters = new Map(state.selectedFilters);
  els.filters.replaceChildren();
  state.selectedFilters.clear();

  for (const filter of table.filters || []) {
    if (!filter.values.length) {
      continue;
    }

    const label = document.createElement("label");
    label.className = "field filter-field";

    const text = document.createElement("span");
    text.textContent = filter.label || filter.name;

    const select = document.createElement("select");
    const allowedValues = new Set(filter.values.map((item) => item.value));
    const previousValue = previousFilters.get(filter.name);
    const preferredValue = allowedValues.has(previousValue)
      ? previousValue
      : allowedValues.has("all")
        ? "all"
        : filter.values[0].value;

    fillSelect(
      select,
      filter.values,
      (item) => item.value,
      (item) => item.label || item.value,
      preferredValue,
    );
    state.selectedFilters.set(filter.name, select.value);
    select.addEventListener("change", () => {
      state.selectedFilters.set(filter.name, select.value);
      loadSeries();
    });

    label.append(text, select);
    els.filters.append(label);
  }
}

function populateVariableOptions() {
  const table = currentTable();
  els.variables.replaceChildren();
  state.selectedVariables.clear();

  const preferred = table.selectable_variables.some((variable) => variable.name === "population")
    ? "population"
    : table.selectable_variables[0]?.name;

  for (const variable of table.selectable_variables) {
    const label = document.createElement("label");
    label.className = "variable-option";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = variable.name;
    input.checked = variable.name === preferred;
    if (input.checked) {
      state.selectedVariables.add(variable.name);
    }
    input.addEventListener("change", () => {
      if (input.checked) {
        state.selectedVariables.add(input.value);
      } else {
        state.selectedVariables.delete(input.value);
      }
      updateChartTitle();
      loadSeries();
    });

    const text = document.createElement("span");
    text.textContent = variableLabel(variable);

    label.append(input, text);
    els.variables.append(label);
  }

  populateFilterOptions();
  updateChartTitle();
}

function updateChartTitle() {
  const table = currentTable();
  const selected = table.selectable_variables.filter((variable) =>
    state.selectedVariables.has(variable.name),
  );
  els.chartKicker.textContent = table.table;
  const title = selected.length
    ? selected.map((variable) => variableLabel(variable)).join(", ")
    : "변수";
  els.chartTitle.textContent =
    els.normalize.value === "first100" ? `${title} (첫 관측치=100)` : title;
}

function renderDataStatus() {
  els.tableCount.textContent = `${state.status.table_count}개`;
  els.dataStatusBody.replaceChildren();

  for (const table of state.status.tables) {
    const tr = document.createElement("tr");
    const period = table.min_date && table.max_date
      ? `${formatDate(table.min_date)} - ${formatDate(table.max_date)}`
      : "";
    const variables = document.createElement("div");
    variables.className = "variable-tags";
    for (const variable of table.selectable_variables) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = variableLabel(variable);
      variables.append(tag);
    }

    const filters = document.createElement("div");
    filters.className = "variable-tags";
    for (const filter of table.filters || []) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = filter.label || filter.name;
      filters.append(tag);
    }

    tr.append(
      cell(table.table),
      cell(period),
      cell(formatNumber(table.row_count)),
      cell(filters),
      cell(variables),
    );
    els.dataStatusBody.append(tr);
  }
}

function cell(content) {
  const td = document.createElement("td");
  if (content instanceof Node) {
    td.append(content);
  } else {
    td.textContent = content;
  }
  return td;
}

function selectedVariables() {
  const table = currentTable();
  return table.selectable_variables.filter((variable) =>
    state.selectedVariables.has(variable.name),
  );
}

function seriesUrl(variable, region) {
  const params = new URLSearchParams({
    region_sido: region.region_sido,
    region_sigungu: region.region_sigungu,
    table: els.table.value,
    variable: variable.name,
  });

  const table = currentTable();
  for (const filter of table.filters || []) {
    const value = state.selectedFilters.get(filter.name);
    if (value) {
      params.set(filter.name, value);
    }
  }
  return `/api/series?${params.toString()}`;
}

function seriesLabel(variable, region, regionCount, variableCount) {
  const variableText = variableLabel(variable);
  const regionText = regionLabel(region);
  if (regionCount > 1 && variableCount > 1) {
    return `${regionText} · ${variableText}`;
  }
  if (regionCount > 1) {
    return regionText;
  }
  if (variableCount > 1) {
    return variableText;
  }
  return `${regionText} · ${variableText}`;
}

function normalizeGroups(groups) {
  if (els.normalize.value !== "first100") {
    return groups;
  }
  return groups.map((group) => {
    const basePoint = group.points.find((point) => {
      const value = Number(point.value);
      return Number.isFinite(value) && value !== 0;
    });
    if (!basePoint) {
      return {
        ...group,
        points: group.points.map((point) => ({ ...point, value: null })),
      };
    }
    const base = Number(basePoint.value);
    return {
      ...group,
      points: group.points.map((point) => {
        const value = Number(point.value);
        return {
          ...point,
          value: Number.isFinite(value) ? (value / base) * 100 : null,
        };
      }),
    };
  });
}

async function loadSeries() {
  const variables = selectedVariables();
  if (!variables.length) {
    window.RBICharts.renderLineChart(els.chart, [], { emptyMessage: "변수 없음" });
    setStatus("변수 없음", true);
    return;
  }
  if (!state.selectedRegions.length) {
    window.RBICharts.renderLineChart(els.chart, [], { emptyMessage: "지역 없음" });
    setStatus("지역 없음", true);
    return;
  }

  setLoading(true);
  try {
    const requests = [];
    for (const region of state.selectedRegions) {
      for (const variable of variables) {
        requests.push(
          fetchJson(seriesUrl(variable, region)).then((payload) => ({
          label: seriesLabel(
            variable,
            region,
            state.selectedRegions.length,
            variables.length,
          ),
          points: payload.series,
          })),
        );
      }
    }
    const responses = normalizeGroups(await Promise.all(requests));
    window.RBICharts.renderLineChart(els.chart, responses, {
      hoverTemplate:
        els.normalize.value === "first100"
          ? "%{y:,.2f}<extra></extra>"
          : "%{y:,.0f}<extra></extra>",
      yTickFormat: els.normalize.value === "first100" ? ",.1f" : ",",
    });
    const totalPoints = responses.reduce((sum, group) => sum + group.points.length, 0);
    setStatus(
      `${formatNumber(totalPoints)}개 관측치 · ${formatNumber(state.selectedRegions.length)}개 지역`,
    );
  } catch (error) {
    window.RBICharts.renderLineChart(els.chart, [], { emptyMessage: "조회 실패" });
    setStatus(error.message, true);
  } finally {
    setLoading(false);
  }
}

function bindEvents() {
  els.sido.addEventListener("change", () => {
    populateSigungu();
    setSelectedRegions([selectedRegion()]);
  });
  els.sigungu.addEventListener("change", () => {
    setSelectedRegions([selectedRegion()]);
  });
  els.addRegion.addEventListener("click", () => {
    addDashboardRegion(selectedRegion());
  });
  els.clearRegions.addEventListener("click", () => {
    setSelectedRegions([]);
  });
  els.table.addEventListener("change", () => {
    populateVariableOptions();
    loadSeries();
  });
  els.normalize.addEventListener("change", () => {
    updateChartTitle();
    loadSeries();
  });
  els.refresh.addEventListener("click", loadSeries);
  els.selectAllVariables.addEventListener("click", () => {
    const inputs = els.variables.querySelectorAll("input[type='checkbox']");
    const shouldSelectAll = [...inputs].some((input) => !input.checked);
    state.selectedVariables.clear();
    for (const input of inputs) {
      input.checked = shouldSelectAll;
      if (input.checked) {
        state.selectedVariables.add(input.value);
      }
    }
    updateChartTitle();
    loadSeries();
  });
}

function initDashboardMap() {
  const panel = document.getElementById("dashboard-map-panel");
  if (!panel || !window.RBIRegionMap) {
    return;
  }
  state.dashboardMap = window.RBIRegionMap.create({
    root: panel,
    mapUrl: panel.dataset.mapSrc,
    regions: state.regions,
    labels: true,
    selections: {
      series: state.selectedRegions,
    },
    callbacks: {
      select: (region) => {
        addDashboardRegion(region);
      },
      clearSelection: (region) => {
        removeDashboardRegion(region);
      },
      setStatus,
    },
  });
}

async function init() {
  bindEvents();
  try {
    const [regionsPayload, statusPayload] = await Promise.all([
      fetchJson("/api/regions"),
      fetchJson("/api/data-status"),
    ]);
    state.regions = regionsPayload.regions;
    state.status = statusPayload;
    populateRegions();
    setSelectedRegions([selectedRegion()], { load: false });
    populateTables();
    renderDataStatus();
    initDashboardMap();
    await loadSeries();
  } catch (error) {
    setStatus(error.message, true);
    els.chart.innerHTML = '<div class="empty-state">초기화 실패</div>';
  }
}

document.addEventListener("DOMContentLoaded", init);
