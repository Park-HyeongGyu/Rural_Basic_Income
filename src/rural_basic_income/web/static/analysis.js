(function () {
  const state = {
    options: null,
    treatments: [],
    controls: [],
    selectedFilters: new Map(),
    mapSelector: null,
    pollTimer: null,
  };

  const els = {
    table: document.getElementById("analysis-table-select"),
    variable: document.getElementById("analysis-variable-select"),
    filters: document.getElementById("analysis-filter-grid"),
    startPeriod: document.getElementById("analysis-start-period"),
    endPeriod: document.getElementById("analysis-end-period"),
    basePeriod: document.getElementById("analysis-base-period"),
    treatmentSido: document.getElementById("treatment-sido-select"),
    treatmentSigungu: document.getElementById("treatment-sigungu-select"),
    treatmentPeriod: document.getElementById("treatment-period-select"),
    treatmentList: document.getElementById("treatment-region-list"),
    addTreatment: document.getElementById("add-treatment-region"),
    controlSido: document.getElementById("control-sido-select"),
    controlSigungu: document.getElementById("control-sigungu-select"),
    controlList: document.getElementById("control-region-list"),
    addControl: document.getElementById("add-control-region"),
    run: document.getElementById("analysis-run-button"),
    rerun: document.getElementById("analysis-rerun-button"),
    optionsStatus: document.getElementById("analysis-options-status"),
    status: document.getElementById("analysis-status-line"),
    badge: document.getElementById("analysis-result-badge"),
    twfeEstimate: document.getElementById("twfe-estimate"),
    twfeStandardError: document.getElementById("twfe-standard-error"),
    observations: document.getElementById("analysis-observations"),
    regions: document.getElementById("analysis-regions"),
    warnings: document.getElementById("analysis-warning-list"),
    chart: document.getElementById("event-study-chart"),
    eventBody: document.getElementById("event-study-body"),
  };

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

    return fetch(url, requestOptions).then((response) => {
      if (!response.ok) {
        return response.json().catch(() => ({})).then((payload) => {
          const detail = payload.detail || response.statusText;
          throw new Error(
            typeof detail === "string" ? detail : JSON.stringify(detail),
          );
        });
      }
      return response.json();
    });
  }

  function formatPeriod(value) {
    const raw = String(value || "");
    if (/^\d{6}$/.test(raw)) {
      return `${raw.slice(0, 4)}.${raw.slice(4)}`;
    }
    return raw;
  }

  function formatNumber(value) {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return "-";
    }
    return new Intl.NumberFormat("ko-KR").format(value);
  }

  function formatEstimate(value) {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return "-";
    }
    return Number(value).toLocaleString("ko-KR", {
      maximumFractionDigits: 4,
      minimumFractionDigits: 4,
    });
  }

  function regionId(region) {
    return `${region.region_sido}::${region.region_sigungu}`;
  }

  function findRegion(region) {
    if (!state.options || !region) {
      return null;
    }
    return state.options.regions.find(
      (item) =>
        item.region_sido === region.region_sido &&
        item.region_sigungu === region.region_sigungu,
    );
  }

  function removeRegionById(regions, id) {
    const index = regions.findIndex((region) => regionId(region) === id);
    if (index === -1) {
      return false;
    }
    regions.splice(index, 1);
    return true;
  }

  function setAnalysisStatus(message, isError = false) {
    els.status.textContent = message;
    els.status.classList.toggle("error", isError);
  }

  function setBadge(message, tone = "") {
    els.badge.textContent = message || "";
    els.badge.className = tone ? `result-badge ${tone}` : "result-badge";
  }

  function setBusy(isBusy) {
    els.run.disabled = isBusy;
    els.rerun.disabled = isBusy;
    els.addTreatment.disabled = isBusy;
    els.addControl.disabled = isBusy;
  }

  function fillSelect(select, options, valueGetter, labelGetter, preferredValue) {
    select.replaceChildren();
    for (const item of options) {
      const option = document.createElement("option");
      option.value = valueGetter(item);
      option.textContent = labelGetter(item);
      select.append(option);
    }
    if (
      preferredValue &&
      [...select.options].some((option) => option.value === preferredValue)
    ) {
      select.value = preferredValue;
    }
  }

  function currentTable() {
    return state.options.tables.find((table) => table.table_name === els.table.value);
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

  function analysisPeriods() {
    const periods = tablePeriods(currentTable());
    const startIndex = periods.indexOf(els.startPeriod.value);
    const endIndex = periods.indexOf(els.endPeriod.value);
    if (startIndex === -1 || endIndex === -1 || startIndex > endIndex) {
      return [];
    }
    return periods.slice(startIndex, endIndex + 1);
  }

  function regionsBySido(sido) {
    return state.options.regions.filter((region) => region.region_sido === sido);
  }

  function populateRegionPicker(sidoSelect, sigunguSelect, preferredSido, preferredSigungu) {
    const sidos = [...new Set(state.options.regions.map((region) => region.region_sido))]
      .sort();
    fillSelect(sidoSelect, sidos, (sido) => sido, (sido) => sido, preferredSido || "전북");
    populateSigunguPicker(sidoSelect, sigunguSelect, preferredSigungu);
  }

  function populateSigunguPicker(sidoSelect, sigunguSelect, preferredSigungu) {
    const regions = regionsBySido(sidoSelect.value);
    fillSelect(
      sigunguSelect,
      regions,
      (region) => region.region_sigungu,
      (region) => region.region_sigungu,
      preferredSigungu,
    );
  }

  function selectedPickerRegion(sidoSelect, sigunguSelect) {
    return {
      region_sido: sidoSelect.value,
      region_sigungu: sigunguSelect.value,
    };
  }

  function populateAnalysisTables() {
    const tables = [...state.options.tables]
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
      (table) => table.table,
      "clean_population",
    );
    populateOutcomeControls();
  }

  function populateOutcomeControls() {
    populateVariables();
    populateFilters();
    populatePeriods();
    syncTreatmentPeriodChoices();
  }

  function populateVariables() {
    const table = currentTable();
    fillSelect(
      els.variable,
      table.selectable_variables,
      (variable) => variable.name,
      (variable) => variable.label || variable.name,
      table.selectable_variables.some((variable) => variable.name === "population")
        ? "population"
        : undefined,
    );
  }

  function populateFilters() {
    const table = currentTable();
    const previous = new Map(state.selectedFilters);
    state.selectedFilters.clear();
    els.filters.replaceChildren();

    for (const filter of table.filters || []) {
      if (!filter.values.length) {
        continue;
      }

      const label = document.createElement("label");
      label.className = "field filter-field";

      const text = document.createElement("span");
      text.textContent = filter.label || filter.name;

      const select = document.createElement("select");
      const allowed = new Set(filter.values.map((item) => item.value));
      const previousValue = previous.get(filter.name);
      const preferred = allowed.has(previousValue)
        ? previousValue
        : allowed.has("all")
          ? "all"
          : filter.values[0].value;

      fillSelect(
        select,
        filter.values,
        (item) => item.value,
        (item) => item.label || item.value,
        preferred,
      );
      state.selectedFilters.set(filter.name, select.value);
      select.addEventListener("change", () => {
        state.selectedFilters.set(filter.name, select.value);
      });

      label.append(text, select);
      els.filters.append(label);
    }
  }

  function populatePeriods() {
    const table = currentTable();
    const periods = tablePeriods(table);
    const previousStart = els.startPeriod.value;
    const previousEnd = els.endPeriod.value;
    const previousBase = els.basePeriod.value;

    fillSelect(els.startPeriod, periods, (period) => period, formatPeriod, previousStart);
    fillSelect(els.endPeriod, periods, (period) => period, formatPeriod, previousEnd);
    fillSelect(els.basePeriod, periods, (period) => period, formatPeriod, previousBase);

    if (periods.length) {
      if (!previousStart || !periods.includes(previousStart)) {
        els.startPeriod.value = periods[0];
      }
      if (!previousEnd || !periods.includes(previousEnd)) {
        els.endPeriod.value = periods[periods.length - 1];
      }
      if (!previousBase || !periods.includes(previousBase)) {
        els.basePeriod.value = els.startPeriod.value;
      }
    }
    ensurePeriodOrder();
  }

  function ensurePeriodOrder() {
    if (els.startPeriod.value > els.endPeriod.value) {
      els.endPeriod.value = els.startPeriod.value;
    }
  }

  function syncTreatmentPeriodChoices() {
    const periods = analysisPeriods();
    fillSelect(
      els.treatmentPeriod,
      periods,
      (period) => period,
      formatPeriod,
      els.treatmentPeriod.value || periods[Math.min(1, periods.length - 1)],
    );

    for (const treatment of state.treatments) {
      if (!periods.includes(treatment.treatment_period)) {
        treatment.treatment_period = periods[Math.min(1, periods.length - 1)] || "";
      }
    }
    renderSelectedRegions();
  }

  function addDefaultRegions() {
    if (state.treatments.length || state.controls.length) {
      return;
    }
    const regions = state.options.regions;
    const imsil = regions.find(
      (region) => region.region_sido === "전북" && region.region_sigungu === "임실군",
    );
    const gochang = regions.find(
      (region) => region.region_sido === "전북" && region.region_sigungu === "고창군",
    );
    const treatmentRegion = imsil || regions[0];
    const controlRegion = gochang || regions.find(
      (region) => regionId(region) !== regionId(treatmentRegion),
    );
    const periods = analysisPeriods();
    if (treatmentRegion) {
      state.treatments.push({
        ...treatmentRegion,
        treatment_period: periods[Math.min(1, periods.length - 1)] || periods[0] || "",
      });
    }
    if (controlRegion) {
      state.controls.push({ ...controlRegion });
    }
  }

  function addTreatmentRegion(regionArg, options = {}) {
    const selectedRegion =
      regionArg && regionArg.region_sido
        ? regionArg
        : selectedPickerRegion(els.treatmentSido, els.treatmentSigungu);
    const region = findRegion(selectedRegion);
    if (!region) {
      setAnalysisStatus("분석에 사용할 수 없는 지역입니다", true);
      return false;
    }
    const id = regionId(region);
    if (state.treatments.some((item) => regionId(item) === id)) {
      setAnalysisStatus("이미 추가된 처리지역입니다", true);
      return false;
    }
    if (state.controls.some((item) => regionId(item) === id)) {
      if (!options.replaceOpposite) {
        setAnalysisStatus("비교지역에 들어간 지역은 처리지역으로 추가할 수 없습니다", true);
        return false;
      }
      removeRegionById(state.controls, id);
    }
    state.treatments.push({
      ...region,
      treatment_period: options.treatmentPeriod || els.treatmentPeriod.value,
    });
    renderSelectedRegions();
    setAnalysisStatus("처리지역을 추가했습니다");
    return true;
  }

  function addControlRegion(regionArg, options = {}) {
    const selectedRegion =
      regionArg && regionArg.region_sido
        ? regionArg
        : selectedPickerRegion(els.controlSido, els.controlSigungu);
    const region = findRegion(selectedRegion);
    if (!region) {
      setAnalysisStatus("분석에 사용할 수 없는 지역입니다", true);
      return false;
    }
    const id = regionId(region);
    if (state.controls.some((item) => regionId(item) === id)) {
      setAnalysisStatus("이미 추가된 비교지역입니다", true);
      return false;
    }
    if (state.treatments.some((item) => regionId(item) === id)) {
      if (!options.replaceOpposite) {
        setAnalysisStatus("처리지역에 들어간 지역은 비교지역으로 추가할 수 없습니다", true);
        return false;
      }
      removeRegionById(state.treatments, id);
    }
    state.controls.push({ ...region });
    renderSelectedRegions();
    setAnalysisStatus("비교지역을 추가했습니다");
    return true;
  }

  function clearRegionSelection(regionArg) {
    const region = findRegion(regionArg);
    if (!region) {
      setAnalysisStatus("분석에 사용할 수 없는 지역입니다", true);
      return false;
    }
    const id = regionId(region);
    const removed =
      removeRegionById(state.treatments, id) || removeRegionById(state.controls, id);
    if (!removed) {
      setAnalysisStatus("선택된 지역이 아닙니다", true);
      return false;
    }
    renderSelectedRegions();
    setAnalysisStatus("지역 선택을 해제했습니다");
    return true;
  }

  function renderSelectedRegions() {
    renderTreatmentList();
    renderControlList();
    syncMapSelection();
  }

  function syncMapSelection() {
    if (!state.mapSelector) {
      return;
    }
    state.mapSelector.updateSelections({
      treatments: state.treatments,
      controls: state.controls,
    });
  }

  function renderTreatmentList() {
    els.treatmentList.replaceChildren();
    if (!state.treatments.length) {
      els.treatmentList.append(emptySelection("처리지역 없음"));
      return;
    }
    const periods = analysisPeriods();
    state.treatments.forEach((region, index) => {
      const item = document.createElement("div");
      item.className = "selected-region-item treatment-item";

      const name = document.createElement("strong");
      name.textContent = `${region.region_sido} ${region.region_sigungu}`;

      const periodSelect = document.createElement("select");
      periodSelect.className = "compact-select";
      fillSelect(
        periodSelect,
        periods,
        (period) => period,
        formatPeriod,
        region.treatment_period,
      );
      periodSelect.addEventListener("change", () => {
        state.treatments[index].treatment_period = periodSelect.value;
      });

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "text-button danger-button";
      remove.textContent = "삭제";
      remove.addEventListener("click", () => {
        state.treatments.splice(index, 1);
        renderSelectedRegions();
      });

      item.append(name, periodSelect, remove);
      els.treatmentList.append(item);
    });
  }

  function renderControlList() {
    els.controlList.replaceChildren();
    if (!state.controls.length) {
      els.controlList.append(emptySelection("비교지역 없음"));
      return;
    }
    state.controls.forEach((region, index) => {
      const item = document.createElement("div");
      item.className = "selected-region-item";

      const name = document.createElement("strong");
      name.textContent = `${region.region_sido} ${region.region_sigungu}`;

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "text-button danger-button";
      remove.textContent = "삭제";
      remove.addEventListener("click", () => {
        state.controls.splice(index, 1);
        renderSelectedRegions();
      });

      item.append(name, remove);
      els.controlList.append(item);
    });
  }

  function emptySelection(message) {
    const empty = document.createElement("div");
    empty.className = "selection-empty";
    empty.textContent = message;
    return empty;
  }

  function buildPayload(force = false) {
    const filters = {};
    for (const [name, value] of state.selectedFilters.entries()) {
      filters[name] = value;
    }
    return {
      outcome: {
        table: els.table.value,
        variable: els.variable.value,
        filters,
      },
      period: {
        start: els.startPeriod.value,
        end: els.endPeriod.value,
        normalization_base: els.basePeriod.value,
      },
      treatments: state.treatments.map((region) => ({
        region_sido: region.region_sido,
        region_sigungu: region.region_sigungu,
        treatment_period: region.treatment_period,
      })),
      controls: state.controls.map((region) => ({
        region_sido: region.region_sido,
        region_sigungu: region.region_sigungu,
      })),
      force,
    };
  }

  function validatePayload(payload) {
    if (!payload.treatments.length) {
      throw new Error("처리지역을 하나 이상 선택하세요");
    }
    if (!payload.controls.length) {
      throw new Error("비교지역을 하나 이상 선택하세요");
    }
    if (payload.period.start > payload.period.end) {
      throw new Error("시작월은 종료월보다 늦을 수 없습니다");
    }
    const periodSet = new Set(analysisPeriods());
    for (const treatment of payload.treatments) {
      if (!periodSet.has(treatment.treatment_period)) {
        throw new Error("처리 시작월은 분석 기간 안에 있어야 합니다");
      }
    }
  }

  async function runAnalysis(force = false) {
    clearPolling();
    let payload;
    try {
      payload = buildPayload(force);
      validatePayload(payload);
    } catch (error) {
      setAnalysisStatus(error.message, true);
      return;
    }

    setBusy(true);
    setBadge(force ? "reanalyze" : "requesting", "muted");
    setAnalysisStatus(force ? "캐시를 무시하고 분석을 요청하는 중" : "분석을 요청하는 중");

    try {
      const response = await apiJson("/api/analysis/jobs", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (response.status === "success" && response.result) {
        renderAnalysisResult(response.result, {
          cached: Boolean(response.cached),
          cacheKey: response.cache_key,
        });
        return;
      }
      if (response.task_id) {
        setBadge(response.status, response.status === "running" ? "warning" : "muted");
        setAnalysisStatus(
          response.status === "running"
            ? "같은 분석이 이미 실행 중입니다"
            : "분석 작업을 큐에 넣었습니다",
        );
        pollJob(response.task_id);
      }
    } catch (error) {
      setBadge("error", "error");
      setAnalysisStatus(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  function pollJob(taskId) {
    clearPolling();
    const poll = async () => {
      try {
        const job = await apiJson(`/api/analysis/jobs/${encodeURIComponent(taskId)}`);
        if (job.status === "SUCCESS" && job.result_available) {
          clearPolling();
          const resultPayload = await apiJson(job.result_url);
          renderAnalysisResult(resultPayload.result, {
            cached: Boolean(job.cached || resultPayload.cached),
            cacheKey: job.cache_key || resultPayload.cache_key,
          });
          return;
        }
        if (job.status === "FAILURE") {
          clearPolling();
          setBadge("failed", "error");
          setAnalysisStatus(job.error || "분석 작업이 실패했습니다", true);
          return;
        }
        setBadge(job.status.toLowerCase(), "muted");
        setAnalysisStatus(`분석 작업 상태: ${job.status}`);
      } catch (error) {
        clearPolling();
        setBadge("error", "error");
        setAnalysisStatus(error.message, true);
      }
    };

    poll();
    state.pollTimer = window.setInterval(poll, 1500);
  }

  function clearPolling() {
    if (state.pollTimer) {
      window.clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function renderAnalysisResult(result, meta = {}) {
    const coefficient = result.twfe?.coefficient || {};
    const diagnostics = result.diagnostics || {};
    const eventStudy = result.event_study || {};

    els.twfeEstimate.textContent = formatEstimate(coefficient.estimate);
    els.twfeStandardError.textContent = formatEstimate(coefficient.standard_error);
    els.observations.textContent = formatNumber(
      result.twfe?.n_observations || diagnostics.n_observations,
    );
    els.regions.textContent = formatNumber(
      result.twfe?.n_regions || diagnostics.n_regions,
    );

    setBadge(meta.cached ? "cache hit" : "fresh result", meta.cached ? "success" : "muted");
    setAnalysisStatus(
      meta.cacheKey ? `결과 cache key: ${meta.cacheKey.slice(0, 12)}` : "분석 완료",
    );
    renderWarnings(result.warnings || []);
    renderEventStudyChart(eventStudy.points || []);
    renderEventStudyTable(eventStudy.points || []);
  }

  function renderWarnings(warnings) {
    els.warnings.replaceChildren();
    if (!warnings.length) {
      return;
    }
    for (const warning of warnings) {
      const item = document.createElement("div");
      item.className = "analysis-warning";
      item.textContent = warning.message || warning.code || "warning";
      els.warnings.append(item);
    }
  }

  function renderEventStudyChart(points) {
    if (!points.length) {
      Plotly.purge(els.chart);
      els.chart.innerHTML = '<div class="empty-state">Event Study 결과 없음</div>';
      return;
    }
    const sorted = [...points].sort((a, b) => a.event_time - b.event_time);
    const estimates = sorted.map((point) => point.estimate);
    const upperErrors = sorted.map((point) =>
      point.ci_upper_95 === null || point.ci_upper_95 === undefined
        ? 0
        : point.ci_upper_95 - point.estimate,
    );
    const lowerErrors = sorted.map((point) =>
      point.ci_lower_95 === null || point.ci_lower_95 === undefined
        ? 0
        : point.estimate - point.ci_lower_95,
    );

    const trace = {
      type: "scatter",
      mode: "lines+markers",
      name: "Event Study",
      x: sorted.map((point) => point.event_time),
      y: estimates,
      error_y: {
        type: "data",
        symmetric: false,
        array: upperErrors,
        arrayminus: lowerErrors,
        color: "#52616f",
        thickness: 1.2,
        width: 4,
      },
      line: {
        color: "#2364aa",
        width: 2.5,
      },
      marker: {
        color: sorted.map((point) => (point.is_reference ? "#c44900" : "#2364aa")),
        size: 7,
      },
      customdata: sorted.map((point) => [
        formatEstimate(point.standard_error),
        point.is_reference ? "reference" : "",
      ]),
      hovertemplate:
        "event time %{x}<br>estimate %{y:.4f}<br>std. error %{customdata[0]} %{customdata[1]}<extra></extra>",
    };

    const layout = {
      margin: { t: 18, r: 26, b: 52, l: 68 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
      xaxis: {
        title: "Event Time",
        zeroline: false,
        tickfont: { color: "#65717f" },
        dtick: 1,
      },
      yaxis: {
        title: "Estimate",
        gridcolor: "#e6ebf1",
        zeroline: false,
        tickfont: { color: "#65717f" },
      },
      shapes: [
        {
          type: "line",
          x0: sorted[0].event_time,
          x1: sorted[sorted.length - 1].event_time,
          y0: 0,
          y1: 0,
          line: { color: "#9aa6b2", width: 1, dash: "dot" },
        },
        {
          type: "line",
          x0: -1,
          x1: -1,
          y0: 0,
          y1: 1,
          yref: "paper",
          line: { color: "#c44900", width: 1, dash: "dot" },
        },
      ],
      hoverlabel: {
        bgcolor: "#ffffff",
        bordercolor: "#c8d1dc",
        font: { color: "#1f2933" },
      },
    };

    Plotly.react(els.chart, [trace], layout, {
      displayModeBar: false,
      responsive: true,
    });
  }

  function renderEventStudyTable(points) {
    els.eventBody.replaceChildren();
    for (const point of [...points].sort((a, b) => a.event_time - b.event_time)) {
      const tr = document.createElement("tr");
      tr.append(
        tableCell(point.is_reference ? `${point.event_time} (ref.)` : point.event_time),
        tableCell(formatEstimate(point.estimate)),
        tableCell(formatEstimate(point.standard_error)),
        tableCell(
          point.ci_lower_95 === null || point.ci_upper_95 === null
            ? "-"
            : `${formatEstimate(point.ci_lower_95)} - ${formatEstimate(point.ci_upper_95)}`,
        ),
        tableCell(formatNumber(point.observation_count)),
      );
      els.eventBody.append(tr);
    }
  }

  function tableCell(value) {
    const td = document.createElement("td");
    td.textContent = value;
    return td;
  }

  function activateView(viewTarget) {
    document.querySelectorAll(".tab-button").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.viewTarget === viewTarget);
    });
    document.querySelectorAll(".app-view").forEach((view) => {
      view.classList.toggle("is-hidden", view.id !== viewTarget);
    });
    if (viewTarget === "analysis-view" && state.options) {
      Plotly.Plots.resize(els.chart);
    }
  }

  function initMapSelector() {
    const panel = document.getElementById("analysis-map-panel");
    if (!panel || !window.RBIRegionMap) {
      return;
    }
    state.mapSelector = window.RBIRegionMap.create({
      root: panel,
      mapUrl: panel.dataset.mapSrc,
      regions: state.options.regions,
      labels: true,
      selections: {
        treatments: state.treatments,
        controls: state.controls,
      },
      callbacks: {
        select: (region, mode) => {
          if (mode === "treatment") {
            addTreatmentRegion(region, { replaceOpposite: true });
            return;
          }
          if (mode === "control") {
            addControlRegion(region, { replaceOpposite: true });
          }
        },
        clearSelection: clearRegionSelection,
        setStatus: setAnalysisStatus,
      },
    });
  }

  function bindEvents() {
    document.querySelectorAll(".tab-button").forEach((button) => {
      button.addEventListener("click", () => {
        activateView(button.dataset.viewTarget);
        window.history.replaceState(
          null,
          "",
          button.dataset.viewTarget === "analysis-view" ? "#analysis" : "#dashboard",
        );
      });
    });

    els.table.addEventListener("change", () => {
      populateOutcomeControls();
    });
    els.startPeriod.addEventListener("change", () => {
      ensurePeriodOrder();
      syncTreatmentPeriodChoices();
    });
    els.endPeriod.addEventListener("change", () => {
      ensurePeriodOrder();
      syncTreatmentPeriodChoices();
    });
    els.treatmentSido.addEventListener("change", () => {
      populateSigunguPicker(els.treatmentSido, els.treatmentSigungu);
    });
    els.controlSido.addEventListener("change", () => {
      populateSigunguPicker(els.controlSido, els.controlSigungu);
    });
    els.addTreatment.addEventListener("click", () => addTreatmentRegion());
    els.addControl.addEventListener("click", () => addControlRegion());
    els.run.addEventListener("click", () => runAnalysis(false));
    els.rerun.addEventListener("click", () => runAnalysis(true));
  }

  async function init() {
    if (!els.table) {
      return;
    }
    bindEvents();
    try {
      const options = await apiJson("/api/analysis/options");
      state.options = options;
      populateAnalysisTables();
      populateRegionPicker(els.treatmentSido, els.treatmentSigungu, "전북", "임실군");
      populateRegionPicker(els.controlSido, els.controlSigungu, "전북", "고창군");
      addDefaultRegions();
      syncTreatmentPeriodChoices();
      renderSelectedRegions();
      initMapSelector();
      if (window.location.hash === "#analysis") {
        activateView("analysis-view");
      }
      els.optionsStatus.textContent = `${options.tables.length}개 테이블`;
      setAnalysisStatus("분석 조건을 선택하세요");
      setBadge("");
    } catch (error) {
      els.optionsStatus.textContent = "불러오기 실패";
      setAnalysisStatus(error.message, true);
      Plotly.purge(els.chart);
      els.chart.innerHTML = '<div class="empty-state">분석 옵션 초기화 실패</div>';
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
