const state = {
  regions: [],
  status: null,
  dashboardMap: null,
  selectedRegions: [],
  selectedVariables: new Set(),
  selectedFilters: new Map(),
  lastIndicatorRequest: null,
  lastIndicatorResult: null,
  loadedSavedIndicatorId: null,
  loadedSavedIndicatorTitle: "",
  savedIndicators: [],
  savedIndicatorsLoaded: false,
};

const els = {
  sido: document.getElementById("sido-select"),
  sigungu: document.getElementById("sigungu-select"),
  addRegion: document.getElementById("dashboard-add-region"),
  clearRegions: document.getElementById("dashboard-clear-regions"),
  regionList: document.getElementById("dashboard-region-list"),
  table: document.getElementById("table-select"),
  normalize: document.getElementById("normalize-select"),
  normalizeBaseField: document.getElementById("normalize-base-field"),
  normalizeBasePeriod: document.getElementById("normalize-base-period"),
  filters: document.getElementById("filter-grid"),
  variables: document.getElementById("variable-list"),
  selectAllVariables: document.getElementById("select-all-variables"),
  refresh: document.getElementById("refresh-button"),
  save: document.getElementById("indicator-save-button"),
  updateSave: document.getElementById("indicator-update-save-button"),
  chart: document.getElementById("line-chart"),
  chartTitle: document.getElementById("chart-title"),
  chartKicker: document.getElementById("chart-kicker"),
  statusLine: document.getElementById("status-line"),
  dataStatusBody: document.getElementById("data-status-body"),
  tableCount: document.getElementById("table-count"),
  savedRefresh: document.getElementById("saved-indicator-refresh"),
  savedStatus: document.getElementById("saved-indicator-status"),
  savedList: document.getElementById("saved-indicator-list"),
};

const MULTI_FILTER_NAMES = new Set(["age", "sex"]);

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

function apiJson(url, options = {}) {
  const requestOptions = {
    ...options,
    headers: {
      ...(options.headers || {}),
    },
  };
  if (requestOptions.body && !requestOptions.headers["Content-Type"]) {
    requestOptions.headers["Content-Type"] = "application/json";
  }
  return fetchJsonWithOptions(url, requestOptions);
}

function fetchJsonWithOptions(url, options) {
  return fetch(url, options).then((response) => {
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
    els.save.disabled = true;
    els.updateSave.disabled = true;
  } else {
    updateIndicatorSaveButtons();
  }
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

function setSelectIfAvailable(select, value) {
  if (!value) {
    return false;
  }
  const stringValue = String(value);
  const option = [...select.options].find((item) => item.value === stringValue);
  if (!option) {
    return false;
  }
  select.value = stringValue;
  return true;
}

function isMultiFilter(filter) {
  return MULTI_FILTER_NAMES.has(filter.name);
}

function normalizeFilterValues(value, allowedValues, fallbackValues) {
  const rawValues = Array.isArray(value)
    ? value
    : value === undefined || value === null || value === ""
      ? []
      : [value];
  const values = rawValues
    .map((item) => String(item))
    .filter((item) => allowedValues.has(item));
  return values.length ? values : fallbackValues;
}

function selectedFilterValues(filterName) {
  const value = state.selectedFilters.get(filterName);
  if (Array.isArray(value)) {
    return value;
  }
  if (value === undefined || value === null || value === "") {
    return [];
  }
  return [String(value)];
}

function filterValueLabel(filterName, value) {
  const table = currentTable();
  const filter = (table?.filters || []).find((item) => item.name === filterName);
  const option = (filter?.values || []).find((item) => item.value === value);
  return option?.label || value;
}

function filterCombinationLabel(combination) {
  return Object.entries(combination)
    .map(([name, value]) => filterValueLabel(name, value))
    .join(" · ");
}

function selectedFilterCombinations() {
  const table = currentTable();
  let combinations = [{}];
  for (const filter of table.filters || []) {
    const values = selectedFilterValues(filter.name);
    if (!values.length) {
      return [];
    }
    const next = [];
    for (const combination of combinations) {
      for (const value of values) {
        next.push({ ...combination, [filter.name]: value });
      }
    }
    combinations = next;
  }
  return combinations;
}

function tablePeriods(table) {
  const start = String(table.min_date || "");
  const end = String(table.max_date || "");
  if (!/^\d{6}$/.test(start) || !/^\d{6}$/.test(end)) {
    return [];
  }

  const periods = [];
  let year = Number(start.slice(0, 4));
  let month = Number(start.slice(4));
  const endKey = Number(end);
  while (Number(`${year}${String(month).padStart(2, "0")}`) <= endKey) {
    periods.push(`${year}${String(month).padStart(2, "0")}`);
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return periods;
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
  populateNormalizeBasePeriods();
}

function populateNormalizeBasePeriods(preferredValue) {
  const table = currentTable();
  const periods = table ? tablePeriods(table) : [];
  fillSelect(
    els.normalizeBasePeriod,
    periods,
    (period) => period,
    formatDate,
    preferredValue || els.normalizeBasePeriod.value,
  );
  if (periods.length && !periods.includes(els.normalizeBasePeriod.value)) {
    els.normalizeBasePeriod.value = periods[0];
  }
  syncNormalizeBaseField();
}

function syncNormalizeBaseField() {
  const usesBase = els.normalize.value === "base100";
  els.normalizeBaseField.classList.toggle("is-hidden", !usesBase);
  els.normalizeBasePeriod.disabled = !usesBase;
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

    const text = document.createElement("span");
    text.textContent = filter.label || filter.name;
    const allowedValues = new Set(filter.values.map((item) => item.value));
    const previousValue = previousFilters.get(filter.name);

    if (isMultiFilter(filter)) {
      const group = document.createElement("div");
      group.className = "filter-checkset";
      const fallbackValues = [
        allowedValues.has("all") ? "all" : filter.values[0].value,
      ].filter(Boolean);
      const preferredValues = normalizeFilterValues(
        previousValue,
        allowedValues,
        fallbackValues,
      );
      const selectedValues = new Set(preferredValues);
      const options = document.createElement("div");
      options.className = "filter-checkbox-list";

      for (const item of filter.values) {
        const optionLabel = document.createElement("label");
        optionLabel.className = "variable-option filter-checkbox-option";

        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = item.value;
        input.checked = selectedValues.has(item.value);
        input.addEventListener("change", () => {
          const values = [...options.querySelectorAll("input[type='checkbox']")]
            .filter((checkbox) => checkbox.checked)
            .map((checkbox) => checkbox.value);
          state.selectedFilters.set(filter.name, values);
          loadSeries();
        });

        const optionText = document.createElement("span");
        optionText.textContent = item.label || item.value;
        optionLabel.append(input, optionText);
        options.append(optionLabel);
      }

      state.selectedFilters.set(filter.name, preferredValues);
      group.append(text, options);
      els.filters.append(group);
      continue;
    }

    const label = document.createElement("label");
    label.className = "field filter-field";
    const select = document.createElement("select");
    const previousValues = normalizeFilterValues(
      previousValue,
      allowedValues,
      [],
    );
    const preferredValue = previousValues[0]
      || (allowedValues.has("all") ? "all" : filter.values[0].value);

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
    els.normalize.value === "base100"
      ? `${title} (${formatDate(els.normalizeBasePeriod.value)}=100)`
      : title;
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

function selectedVariableNames() {
  return selectedVariables().map((variable) => variable.name);
}

function selectedFilterPayload() {
  const filters = {};
  for (const [name, value] of state.selectedFilters.entries()) {
    filters[name] = Array.isArray(value) ? [...value] : value;
  }
  return filters;
}

function currentIndicatorRequest() {
  return {
    table: els.table.value,
    variables: selectedVariableNames(),
    regions: state.selectedRegions.map((region) => ({
      region_sido: region.region_sido,
      region_sigungu: region.region_sigungu,
    })),
    filters: selectedFilterPayload(),
    normalization: {
      mode: els.normalize.value,
      base_period: els.normalize.value === "base100" ? els.normalizeBasePeriod.value : null,
    },
  };
}

function currentIndicatorResult(groups) {
  return {
    table: currentTable()?.table || els.table.value,
    groups,
    generated_at: new Date().toISOString(),
  };
}

function updateIndicatorSaveButtons() {
  const hasResult = Boolean(state.lastIndicatorResult);
  els.save.disabled = !hasResult;
  els.updateSave.disabled = !hasResult || !state.loadedSavedIndicatorId;
  els.updateSave.classList.toggle("is-hidden", !state.loadedSavedIndicatorId);
}

function seriesUrl(variable, region, filterValues) {
  const params = new URLSearchParams({
    region_sido: region.region_sido,
    region_sigungu: region.region_sigungu,
    table: els.table.value,
    variable: variable.name,
  });

  const table = currentTable();
  for (const filter of table.filters || []) {
    const value = filterValues[filter.name];
    if (value) {
      params.set(filter.name, value);
    }
  }
  return `/api/series?${params.toString()}`;
}

function seriesLabel(variable, region, filterValues, regionCount, variableCount, filterCount) {
  const variableText = variableLabel(variable);
  const regionText = regionLabel(region);
  const filterText = filterCombinationLabel(filterValues);
  const labelParts = [];
  if (regionCount > 1) {
    labelParts.push(regionText);
  }
  if (variableCount > 1) {
    labelParts.push(variableText);
  }
  if (filterCount > 1 && filterText) {
    labelParts.push(filterText);
  }
  return labelParts.length ? labelParts.join(" · ") : `${regionText} · ${variableText}`;
}

function normalizeGroups(groups) {
  if (els.normalize.value !== "base100") {
    return groups;
  }
  const basePeriod = String(els.normalizeBasePeriod.value || "");
  return groups.map((group) => {
    const basePoint = group.points.find(
      (point) => String(point.date) === basePeriod,
    );
    const baseValue = basePoint ? Number(basePoint.value) : null;
    const validBase = Number.isFinite(baseValue) && baseValue !== 0;
    if (!basePoint) {
      return {
        ...group,
        points: group.points.map((point) => ({ ...point, value: null })),
      };
    }
    if (!validBase) {
      return {
        ...group,
        points: group.points.map((point) => ({ ...point, value: null })),
      };
    }
    return {
      ...group,
      points: group.points.map((point) => {
        const value = Number(point.value);
        return {
          ...point,
          value: Number.isFinite(value) ? (value / baseValue) * 100 : null,
        };
      }),
    };
  });
}

async function loadSeries() {
  const variables = selectedVariables();
  if (!variables.length) {
    state.lastIndicatorRequest = null;
    state.lastIndicatorResult = null;
    updateIndicatorSaveButtons();
    window.RBICharts.renderLineChart(els.chart, [], { emptyMessage: "변수 없음" });
    setStatus("변수 없음", true);
    return;
  }
  if (!state.selectedRegions.length) {
    state.lastIndicatorRequest = null;
    state.lastIndicatorResult = null;
    updateIndicatorSaveButtons();
    window.RBICharts.renderLineChart(els.chart, [], { emptyMessage: "지역 없음" });
    setStatus("지역 없음", true);
    return;
  }
  const filterCombinations = selectedFilterCombinations();
  if (!filterCombinations.length) {
    state.lastIndicatorRequest = null;
    state.lastIndicatorResult = null;
    updateIndicatorSaveButtons();
    window.RBICharts.renderLineChart(els.chart, [], { emptyMessage: "필터 없음" });
    setStatus("연령 또는 성별을 하나 이상 선택하세요", true);
    return;
  }

  setLoading(true);
  try {
    const requests = [];
    for (const region of state.selectedRegions) {
      for (const variable of variables) {
        for (const filterValues of filterCombinations) {
          requests.push(
            fetchJson(seriesUrl(variable, region, filterValues)).then((payload) => ({
              label: seriesLabel(
                variable,
                region,
                filterValues,
                state.selectedRegions.length,
                variables.length,
                filterCombinations.length,
              ),
              points: payload.series,
            })),
          );
        }
      }
    }
    const responses = normalizeGroups(await Promise.all(requests));
    state.lastIndicatorRequest = currentIndicatorRequest();
    state.lastIndicatorResult = currentIndicatorResult(responses);
    window.RBICharts.renderLineChart(els.chart, responses, {
      hoverTemplate:
        els.normalize.value === "base100"
          ? "%{y:,.2f}<extra></extra>"
          : "%{y:,.0f}<extra></extra>",
      yTickFormat: els.normalize.value === "base100" ? ",.1f" : ",",
    });
    const totalPoints = responses.reduce((sum, group) => sum + group.points.length, 0);
    setStatus(
      `${formatNumber(totalPoints)}개 관측치 · ${formatNumber(state.selectedRegions.length)}개 지역`,
    );
  } catch (error) {
    state.lastIndicatorRequest = null;
    state.lastIndicatorResult = null;
    window.RBICharts.renderLineChart(els.chart, [], { emptyMessage: "조회 실패" });
    setStatus(error.message, true);
  } finally {
    setLoading(false);
  }
}

function buildIndicatorSaveTitle() {
  const request = state.lastIndicatorRequest || currentIndicatorRequest();
  const variable = request.variables[0] || "indicator";
  const region = request.regions[0]
    ? `${request.regions[0].region_sido} ${request.regions[0].region_sigungu}`
    : "지역";
  const suffix = request.normalization.mode === "base100"
    ? ` ${formatDate(request.normalization.base_period)}=100`
    : "";
  return `${variable} ${region}${suffix}`;
}

function buildIndicatorSaveBody(title) {
  if (!state.lastIndicatorRequest || !state.lastIndicatorResult) {
    throw new Error("저장할 지표 결과가 없습니다");
  }
  return {
    title,
    request_payload: state.lastIndicatorRequest,
    result_payload: state.lastIndicatorResult,
  };
}

async function saveCurrentIndicator({ update = false } = {}) {
  if (!state.lastIndicatorRequest || !state.lastIndicatorResult) {
    setStatus("저장할 지표 결과가 없습니다", true);
    return;
  }

  let title = state.loadedSavedIndicatorTitle || buildIndicatorSaveTitle();
  if (!update) {
    const enteredTitle = window.prompt("저장 이름", title);
    if (enteredTitle === null) {
      return;
    }
    title = enteredTitle.trim() || title;
  }

  const targetUrl =
    update && state.loadedSavedIndicatorId
      ? `/api/indicators/saved/${encodeURIComponent(state.loadedSavedIndicatorId)}`
      : "/api/indicators/saved";
  const method = update && state.loadedSavedIndicatorId ? "PATCH" : "POST";

  els.save.disabled = true;
  els.updateSave.disabled = true;
  try {
    const response = await apiJson(targetUrl, {
      method,
      body: JSON.stringify(buildIndicatorSaveBody(title)),
    });
    const saved = response.saved;
    state.loadedSavedIndicatorId = saved.id;
    state.loadedSavedIndicatorTitle = saved.title;
    state.savedIndicatorsLoaded = false;
    updateIndicatorSaveButtons();
    setStatus(update ? "저장된 지표를 업데이트했습니다" : "지표를 저장했습니다");
  } catch (error) {
    updateIndicatorSaveButtons();
    setStatus(error.message, true);
  }
}

function formatSavedTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function savedIndicatorSummaryText(saved) {
  const summary = saved.summary || {};
  const firstRegion = summary.regions?.[0];
  const regionText = firstRegion
    ? `${firstRegion.region_sido} ${firstRegion.region_sigungu}`
    : "지역 없음";
  const normalizeText = summary.normalization_mode === "base100"
    ? `${formatDate(summary.normalization_base_period)}=100`
    : "원자료";
  return [
    summary.table || "-",
    `${formatNumber(summary.variable_count)}개 변수`,
    `${regionText} 외 ${formatNumber(summary.region_count)}개 지역`,
    normalizeText,
  ].join(" · ");
}

function renderSavedIndicators() {
  els.savedList.replaceChildren();
  if (!state.savedIndicators.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "저장된 지표 없음";
    els.savedList.append(empty);
    return;
  }

  for (const saved of state.savedIndicators) {
    const card = document.createElement("article");
    card.className = "saved-analysis-card";

    const title = document.createElement("h3");
    title.textContent = saved.title;

    const summary = document.createElement("p");
    summary.className = "saved-analysis-summary";
    summary.textContent = savedIndicatorSummaryText(saved);

    const meta = document.createElement("p");
    meta.className = "saved-analysis-meta";
    meta.textContent = `수정 ${formatSavedTime(saved.updated_at)}`;

    const tags = document.createElement("div");
    tags.className = "saved-analysis-tags";
    for (const label of [
      `${formatNumber(saved.summary?.group_count)}개 선`,
      `${formatNumber(saved.summary?.point_count)}개 관측치`,
    ]) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = label;
      tags.append(tag);
    }

    const actions = document.createElement("div");
    actions.className = "saved-analysis-actions";

    const load = document.createElement("button");
    load.type = "button";
    load.className = "text-button";
    load.textContent = "불러오기";
    load.addEventListener("click", () => openSavedIndicator(saved.id));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "text-button danger-button";
    remove.textContent = "삭제";
    remove.addEventListener("click", () => deleteSavedIndicator(saved.id, saved.title));

    actions.append(load, remove);
    card.append(title, summary, meta, tags, actions);
    els.savedList.append(card);
  }
}

async function loadSavedIndicators({ force = false } = {}) {
  if (state.savedIndicatorsLoaded && !force) {
    renderSavedIndicators();
    return;
  }
  els.savedStatus.textContent = "저장된 지표를 불러오는 중";
  els.savedStatus.classList.remove("error");
  try {
    const response = await apiJson("/api/indicators/saved");
    state.savedIndicators = response.saved || [];
    state.savedIndicatorsLoaded = true;
    els.savedStatus.textContent = `${state.savedIndicators.length}개 저장됨`;
    renderSavedIndicators();
  } catch (error) {
    els.savedStatus.textContent = error.message;
    els.savedStatus.classList.add("error");
    els.savedList.replaceChildren();
  }
}

function applyIndicatorRequest(payload) {
  setSelectIfAvailable(els.table, payload.table);
  state.selectedFilters = new Map(Object.entries(payload.filters || {}));
  populateVariableOptions();
  populateNormalizeBasePeriods(payload.normalization?.base_period);

  state.selectedVariables.clear();
  const selected = new Set(payload.variables || []);
  for (const input of els.variables.querySelectorAll("input[type='checkbox']")) {
    input.checked = selected.has(input.value);
    if (input.checked) {
      state.selectedVariables.add(input.value);
    }
  }
  if (payload.normalization?.mode) {
    setSelectIfAvailable(els.normalize, payload.normalization.mode);
  }
  if (payload.normalization?.base_period) {
    setSelectIfAvailable(els.normalizeBasePeriod, payload.normalization.base_period);
  }
  syncNormalizeBaseField();
  setSelectedRegions(payload.regions || [], { load: false });
  updateChartTitle();
}

function renderSavedIndicatorResult(saved) {
  const requestPayload = saved.request_payload || {};
  const resultPayload = saved.result_payload || {};
  applyIndicatorRequest(requestPayload);
  state.loadedSavedIndicatorId = saved.id;
  state.loadedSavedIndicatorTitle = saved.title;
  state.lastIndicatorRequest = requestPayload;
  state.lastIndicatorResult = resultPayload;
  window.RBICharts.renderLineChart(els.chart, resultPayload.groups || [], {
    hoverTemplate:
      requestPayload.normalization?.mode === "base100"
        ? "%{y:,.2f}<extra></extra>"
        : "%{y:,.0f}<extra></extra>",
    yTickFormat: requestPayload.normalization?.mode === "base100" ? ",.1f" : ",",
  });
  if (window.Plotly?.Plots?.resize) {
    window.requestAnimationFrame(() => Plotly.Plots.resize(els.chart));
  }
  const totalPoints = (resultPayload.groups || []).reduce(
    (sum, group) => sum + (group.points || []).length,
    0,
  );
  setStatus(
    `저장된 지표를 불러왔습니다 · ${formatNumber(totalPoints)}개 관측치`,
  );
  updateIndicatorSaveButtons();
}

function nextAnimationFrame() {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => resolve());
  });
}

async function openSavedIndicator(savedId) {
  els.savedStatus.textContent = "저장된 지표를 불러오는 중";
  try {
    const response = await apiJson(`/api/indicators/saved/${encodeURIComponent(savedId)}`);
    document.querySelector('[data-view-target="dashboard-view"]')?.click();
    window.history.replaceState(null, "", "#dashboard");
    await nextAnimationFrame();
    renderSavedIndicatorResult(response.saved);
  } catch (error) {
    els.savedStatus.textContent = error.message;
    els.savedStatus.classList.add("error");
  }
}

async function deleteSavedIndicator(savedId, title) {
  if (!window.confirm(`"${title}" 저장본을 삭제할까요?`)) {
    return;
  }
  try {
    await apiJson(`/api/indicators/saved/${encodeURIComponent(savedId)}`, {
      method: "DELETE",
    });
    state.savedIndicatorsLoaded = false;
    if (state.loadedSavedIndicatorId === savedId) {
      state.loadedSavedIndicatorId = null;
      state.loadedSavedIndicatorTitle = "";
      updateIndicatorSaveButtons();
    }
    await loadSavedIndicators({ force: true });
  } catch (error) {
    els.savedStatus.textContent = error.message;
    els.savedStatus.classList.add("error");
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
    populateNormalizeBasePeriods();
    loadSeries();
  });
  els.normalize.addEventListener("change", () => {
    syncNormalizeBaseField();
    updateChartTitle();
    loadSeries();
  });
  els.normalizeBasePeriod.addEventListener("change", () => {
    updateChartTitle();
    loadSeries();
  });
  els.refresh.addEventListener("click", loadSeries);
  els.save.addEventListener("click", () => saveCurrentIndicator());
  els.updateSave.addEventListener("click", () => saveCurrentIndicator({ update: true }));
  els.savedRefresh.addEventListener("click", () => loadSavedIndicators({ force: true }));
  window.addEventListener("rbi:viewchange", (event) => {
    if (event.detail?.viewTarget === "saved-indicator-view") {
      loadSavedIndicators();
    }
    if (event.detail?.viewTarget === "dashboard-view" && window.Plotly?.Plots?.resize) {
      window.requestAnimationFrame(() => Plotly.Plots.resize(els.chart));
    }
  });
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
    treatmentUrl: panel.dataset.treatmentSrc,
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
    syncNormalizeBaseField();
    renderDataStatus();
    initDashboardMap();
    await loadSeries();
    updateIndicatorSaveButtons();
    if (window.location.hash === "#saved-indicator") {
      loadSavedIndicators();
    }
  } catch (error) {
    setStatus(error.message, true);
    els.chart.innerHTML = '<div class="empty-state">초기화 실패</div>';
  }
}

document.addEventListener("DOMContentLoaded", init);
