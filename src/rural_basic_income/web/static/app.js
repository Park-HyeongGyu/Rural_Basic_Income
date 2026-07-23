const state = {
  regions: [],
  status: null,
  selectedVariables: new Set(),
};

const els = {
  sido: document.getElementById("sido-select"),
  sigungu: document.getElementById("sigungu-select"),
  table: document.getElementById("table-select"),
  sex: document.getElementById("sex-select"),
  age: document.getElementById("age-select"),
  sexField: document.getElementById("sex-field"),
  ageField: document.getElementById("age-field"),
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

const ageOptions = [
  "all",
  "0-4",
  "5-9",
  "10-14",
  "15-19",
  "20-24",
  "25-29",
  "30-34",
  "35-39",
  "40-44",
  "45-49",
  "50-54",
  "55-59",
  "60-64",
  "65-69",
  "70-74",
  "75-79",
  "80-",
];

const ageLabels = new Map([
  ["all", "전체"],
  ["80-", "80세 이상"],
]);

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
  const dimensions = new Set(table.dimensions);
  els.sexField.classList.toggle("is-hidden", !dimensions.has("sex"));
  els.ageField.classList.toggle("is-hidden", !dimensions.has("age"));

  fillSelect(
    els.age,
    ageOptions,
    (age) => age,
    (age) => ageLabels.get(age) || `${age}세`,
    "all",
  );
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
  els.chartTitle.textContent = selected.length
    ? selected.map((variable) => variableLabel(variable)).join(", ")
    : "변수";
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

    tr.append(
      cell(table.table),
      cell(period),
      cell(formatNumber(table.row_count)),
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

function seriesUrl(variable) {
  const region = selectedRegion();
  const params = new URLSearchParams({
    region_sido: region.region_sido,
    region_sigungu: region.region_sigungu,
    table: els.table.value,
    variable: variable.name,
  });

  const table = currentTable();
  const dimensions = new Set(table.dimensions);
  if (dimensions.has("sex")) {
    params.set("sex", els.sex.value);
  }
  if (dimensions.has("age")) {
    params.set("age", els.age.value);
  }
  return `/api/series?${params.toString()}`;
}

async function loadSeries() {
  const variables = selectedVariables();
  if (!variables.length) {
    window.RBICharts.renderLineChart(els.chart, [], { emptyMessage: "변수 없음" });
    setStatus("변수 없음", true);
    return;
  }

  setLoading(true);
  try {
    const responses = await Promise.all(
      variables.map((variable) =>
        fetchJson(seriesUrl(variable)).then((payload) => ({
          label: variableLabel(variable),
          points: payload.series,
        })),
      ),
    );
    window.RBICharts.renderLineChart(els.chart, responses);
    const totalPoints = responses.reduce((sum, group) => sum + group.points.length, 0);
    setStatus(`${formatNumber(totalPoints)}개 관측치`);
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
    loadSeries();
  });
  els.sigungu.addEventListener("change", loadSeries);
  els.table.addEventListener("change", () => {
    populateVariableOptions();
    loadSeries();
  });
  els.sex.addEventListener("change", loadSeries);
  els.age.addEventListener("change", loadSeries);
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

async function init() {
  bindEvents();
  populateFilterOptionsPlaceholder();
  try {
    const [regionsPayload, statusPayload] = await Promise.all([
      fetchJson("/api/regions"),
      fetchJson("/api/data-status"),
    ]);
    state.regions = regionsPayload.regions;
    state.status = statusPayload;
    populateRegions();
    populateTables();
    renderDataStatus();
    await loadSeries();
  } catch (error) {
    setStatus(error.message, true);
    els.chart.innerHTML = '<div class="empty-state">초기화 실패</div>';
  }
}

function populateFilterOptionsPlaceholder() {
  fillSelect(
    els.age,
    ageOptions,
    (age) => age,
    (age) => ageLabels.get(age) || `${age}세`,
    "all",
  );
}

document.addEventListener("DOMContentLoaded", init);
