(function () {
  const STORAGE_KEY = "rbi-ui-language";
  const DEFAULT_LANGUAGE = "ko";
  const SUPPORTED_LANGUAGES = new Set(["ko", "en"]);

  const KO_TO_EN = new Map([
    ["지역 지표 시계열", "Regional Indicator Time Series"],
    ["화면 선택", "View selection"],
    ["정보", "Info"],
    ["지표", "Indicators"],
    ["분석", "Analysis"],
    ["저장된 지표", "Saved Indicators"],
    ["저장된 분석", "Saved Analyses"],
    ["정보 글 목록", "Info post list"],
    ["정보 글 본문", "Info post body"],
    ["정보 글 작성", "Write info post"],
    ["새 글 작성", "New Post"],
    ["새로고침", "Refresh"],
    ["글 없음", "No Post"],
    ["아직 선택된 글이 없습니다.", "No post is selected yet."],
    ["새 글", "New Post"],
    ["돌아가기", "Back"],
    ["제목", "Title"],
    ["본문", "Body"],
    ["저장", "Save"],
    ["조회 조건과 지도", "Query controls and map"],
    ["조회 조건", "Query controls"],
    ["시도", "Province"],
    ["시군구", "City/County/District"],
    ["추가", "Add"],
    ["초기화", "Reset"],
    ["테이블", "Table"],
    ["정규화", "Normalization"],
    ["원자료", "Raw"],
    ["기준월=100", "Base month = 100"],
    ["정규화 기준월", "Normalization Base Month"],
    ["변수", "Variables"],
    ["전체", "All"],
    ["지역", "Regions"],
    ["지도 선택", "Map Selection"],
    ["지표 지도 선택", "Indicator map selection"],
    ["지표 지도 선택 모드", "Indicator map mode"],
    ["그래프 지역", "Chart region"],
    ["선택", "Select"],
    ["선택 해제", "Clear selection"],
    ["해제", "Clear"],
    ["전국 시군구 지도", "National city/county/district map"],
    ["지도 불러오는 중", "Loading map"],
    ["시도 확대 지도", "Province zoom map"],
    ["확대", "Zoom"],
    ["닫기", "Close"],
    ["시계열 그래프", "Time Series Chart"],
    ["인구", "Population"],
    ["지표 저장", "Save Indicator"],
    ["저장 업데이트", "Update Saved"],
    ["조회", "Query"],
    ["불러오는 중", "Loading"],
    ["데이터 상태", "Data Status"],
    ["기간", "Period"],
    ["행", "Rows"],
    ["필터", "Filters"],
    ["분석 조건", "Analysis Setup"],
    ["시작월", "Start Month"],
    ["종료월", "End Month"],
    ["처리지역", "Treatment Regions"],
    ["처리 시작월", "Treatment Start Month"],
    ["비교지역", "Control Regions"],
    ["분석 지도 선택", "Analysis map selection"],
    ["분석 지도 선택 모드", "Analysis map mode"],
    ["처리", "Treatment"],
    ["비교", "Control"],
    ["분석 실행", "Run Analysis"],
    ["캐시 무시 실행", "Force Rerun"],
    ["분석 저장", "Save Analysis"],
    ["분석 결과", "Analysis Results"],
    ["분석 조건을 선택하세요", "Select analysis conditions"],
    ["TWFE 추정치", "TWFE Estimate"],
    ["표준오차", "Standard Error"],
    ["관측치", "Observations"],
    ["Event Study 결과 없음", "No Event Study Results"],
    ["정보 글을 불러오는 중", "Loading info posts"],
    ["정보 글을 불러오지 못했습니다.", "Could not load info posts."],
    ["정보 API를 찾지 못했습니다. 웹 서버를 재시작하세요.", "Info API was not found. Restart the web server."],
    ["요청 실패", "Request failed"],
    ["새 글을 작성하세요", "Write a new post"],
    ["저장된 정보 글이 없습니다.", "No info posts saved."],
    ["새 글을 작성하면 여기에 본문이 표시됩니다.", "Write a new post to show its body here."],
    ["본문 없음", "No body"],
    ["본문을 불러오는 중", "Loading body"],
    ["제목과 본문을 입력하세요", "Enter a title and body"],
    ["저장하는 중", "Saving"],
    ["저장했습니다", "Saved"],
    ["선택할 수 없는 지역입니다", "This region cannot be selected"],
    ["이미 선택된 지역입니다", "This region is already selected"],
    ["선택된 지역이 아닙니다", "This region is not selected"],
    ["지역 없음", "No Regions"],
    ["변수 없음", "No Variables"],
    ["필터 없음", "No Filters"],
    ["연령 또는 성별을 하나 이상 선택하세요", "Select at least one age or sex filter"],
    ["조회 실패", "Query failed"],
    ["저장할 지표 결과가 없습니다", "No indicator result to save"],
    ["저장 이름", "Save name"],
    ["저장된 지표를 업데이트했습니다", "Updated saved indicator"],
    ["지표를 저장했습니다", "Saved indicator"],
    ["저장된 지표 없음", "No saved indicators"],
    ["불러오기", "Load"],
    ["삭제", "Delete"],
    ["저장된 지표를 불러오는 중", "Loading saved indicators"],
    ["저장된 지표를 불러왔습니다", "Loaded saved indicator"],
    ["초기화 실패", "Initialization failed"],
    ["조건이 변경되었습니다. 다시 분석하세요", "Conditions changed. Run the analysis again."],
    ["분석에 사용할 수 없는 지역입니다", "This region cannot be used for analysis"],
    ["이미 추가된 처리지역입니다", "This treatment region is already added"],
    ["비교지역에 들어간 지역은 처리지역으로 추가할 수 없습니다", "A control region cannot also be a treatment region"],
    ["처리지역을 추가했습니다", "Added treatment region"],
    ["이미 추가된 비교지역입니다", "This control region is already added"],
    ["처리지역에 들어간 지역은 비교지역으로 추가할 수 없습니다", "A treatment region cannot also be a control region"],
    ["비교지역을 추가했습니다", "Added control region"],
    ["지역 선택을 해제했습니다", "Cleared region selection"],
    ["처리지역 없음", "No treatment regions"],
    ["비교지역 없음", "No control regions"],
    ["처리지역을 하나 이상 선택하세요", "Select at least one treatment region"],
    ["비교지역을 하나 이상 선택하세요", "Select at least one control region"],
    ["시작월은 종료월보다 늦을 수 없습니다", "Start month cannot be later than end month"],
    ["처리 시작월은 분석 기간 안에 있어야 합니다", "Treatment start month must be inside the analysis period"],
    ["캐시를 무시하고 분석을 요청하는 중", "Requesting analysis without cache"],
    ["분석을 요청하는 중", "Requesting analysis"],
    ["같은 분석이 이미 실행 중입니다", "The same analysis is already running"],
    ["분석 작업을 큐에 넣었습니다", "Analysis job queued"],
    ["분석 작업이 실패했습니다", "Analysis job failed"],
    ["저장된 분석을 불러왔습니다", "Loaded saved analysis"],
    ["분석 완료", "Analysis complete"],
    ["분석", "Analysis"],
    ["저장할 분석 결과가 없습니다", "No analysis result to save"],
    ["분석 조건을 찾을 수 없습니다", "Analysis specification was not found"],
    ["저장된 분석을 업데이트했습니다", "Updated saved analysis"],
    ["분석을 저장했습니다", "Saved analysis"],
    ["저장된 분석 없음", "No saved analyses"],
    ["저장된 분석을 불러오는 중", "Loading saved analyses"],
    ["불러오기 실패", "Load failed"],
    ["분석 옵션 초기화 실패", "Failed to initialize analysis options"],
    ["데이터 없음", "No data"],
    ["1차 처치지역", "Phase 1 Treatment"],
    ["2차 처치지역", "Phase 2 Treatment"],
    ["1차 시행지역", "Phase 1 Treatment"],
    ["2차 시행지역", "Phase 2 Treatment"],
    ["1차 실행지역", "Phase 1 Treatment"],
    ["2차 실행지역", "Phase 2 Treatment"],
    ["2026년 2월 첫 지급 지역. 곡성군은 2026년 3월 말에 2월분 포함 지급.", "First paid in February 2026. Gokseong-gun received the February payment together at the end of March 2026."],
    ["2026년 6월 11일 추가 선정, 2026년 8월부터 지급.", "Additional selections announced on June 11, 2026. Payments start in August 2026."],
    ["시작", "Start"],
    ["첫 지급", "First Payment"],
    ["남자", "Male"],
    ["여자", "Female"],
    ["성별", "Sex"],
    ["연령", "Age"],
    ["계약종별", "Contract Type"],
    ["세대수", "Households"],
    ["전입", "Inflow"],
    ["전출", "Outflow"],
    ["총 전입", "Total Inflow"],
    ["총 전출", "Total Outflow"],
    ["30만 이상 지역발 전입", "Inflow from 300k+ Regions"],
    ["30만 이상 지역행 전출", "Outflow to 300k+ Regions"],
    ["인구감소지역발 전입", "Inflow from Declining Regions"],
    ["인구감소지역행 전출", "Outflow to Declining Regions"],
    ["기타 지역발 전입", "Inflow from Other Regions"],
    ["기타 지역행 전출", "Outflow to Other Regions"],
    ["순이동", "Net Migration"],
    ["시군구내 이동", "Within-Region Migration"],
    ["시도내 시군구간 전입", "Within-Province Inflow"],
    ["시도내 시군구간 전출", "Within-Province Outflow"],
    ["시도간 전입", "Inter-Province Inflow"],
    ["시도간 전출", "Inter-Province Outflow"],
    ["결제금액", "Payment Amount"],
    ["결제건수", "Payment Count"],
    ["고객호수", "Customer Count"],
    ["전력사용량", "Power Usage"],
    ["전기요금", "Electricity Bill"],
    ["평균단가", "Average Unit Cost"],
    ["계약전력", "Contract Power"],
    ["생활인구", "Living Population"],
    ["주민등록인구", "Registered Population"],
    ["체류인구", "Stay Population"],
    ["외국인", "Foreign Population"],
    ["생활인구 비공개", "Living Population Suppressed"],
    ["주민등록인구 비공개", "Registered Population Suppressed"],
    ["체류인구 비공개", "Stay Population Suppressed"],
    ["외국인 비공개", "Foreign Population Suppressed"],
    ["주택용", "Residential"],
    ["일반용", "General"],
    ["산업용", "Industrial"],
    ["농사용", "Agricultural"],
    ["교육용", "Educational"],
    ["가로등", "Streetlight"],
    ["심야", "Late Night"],
    ["미상", "Unknown"],
    ["60세 이상", "60+"],
    ["80세 이상", "80+"],
  ]);

  const EN_TO_KO = new Map(Array.from(KO_TO_EN, ([ko, en]) => [en, ko]));

  const KO_PATTERNS = [
    [/^1차 시행지역 (\d+)곳$/, "Phase 1 Treatment: $1 regions"],
    [/^2차 시행지역 (\d+)곳$/, "Phase 2 Treatment: $1 regions"],
    [/^1차 실행지역 (\d+)곳$/, "Phase 1 Treatment: $1 regions"],
    [/^2차 실행지역 (\d+)곳$/, "Phase 2 Treatment: $1 regions"],
    [/^1차 처치지역 (\d+)곳$/, "Phase 1 Treatment: $1 regions"],
    [/^2차 처치지역 (\d+)곳$/, "Phase 2 Treatment: $1 regions"],
    [/^(\d+)개 글$/, "$1 posts"],
    [/^(\d+)개 테이블$/, "$1 tables"],
    [/^(\d+)개 저장됨$/, "$1 saved"],
    [/^(\d+)개 변수$/, "$1 variables"],
    [/^(\d+)개 선$/, "$1 lines"],
    [/^(\d+)개 관측치$/, "$1 observations"],
    [/^(\d+)개 관측치 · (\d+)개 지역$/, "$1 observations · $2 regions"],
    [/^(.+) 외 (\d+)개 지역$/, "$1 plus $2 regions"],
    [/^(.+) 외 처리 (\d+) \/ 비교 (\d+)$/, "$1 plus $2 treatment / $3 control"],
    [/^수정 (.+)$/, "Updated $1"],
    [/^분석 작업 상태: (.+)$/, "Analysis job status: $1"],
    [/^결과 cache key: (.+)$/, "Result cache key: $1"],
    [/^시작 (.+)$/, "Start $1"],
    [/^첫 지급 (.+)$/, "First payment $1"],
    [/^(.+) 확대$/, "$1 zoom"],
    [/^(.+) 확대 지도$/, "$1 zoom map"],
    [/^(.+) (\d+)곳$/, "$1: $2 regions"],
  ];

  const EN_PATTERNS = [
    [/^Phase 1 Treatment: (\d+) regions$/, "1차 시행지역 $1곳"],
    [/^Phase 2 Treatment: (\d+) regions$/, "2차 시행지역 $1곳"],
    [/^(\d+) posts$/, "$1개 글"],
    [/^(\d+) tables$/, "$1개 테이블"],
    [/^(\d+) saved$/, "$1개 저장됨"],
    [/^(\d+) variables$/, "$1개 변수"],
    [/^(\d+) lines$/, "$1개 선"],
    [/^(\d+) observations$/, "$1개 관측치"],
    [/^(\d+) observations · (\d+) regions$/, "$1개 관측치 · $2개 지역"],
    [/^(.+) plus (\d+) regions$/, "$1 외 $2개 지역"],
    [/^(.+) plus (\d+) treatment \/ (\d+) control$/, "$1 외 처리 $2 / 비교 $3"],
    [/^Updated (.+)$/, "수정 $1"],
    [/^Analysis job status: (.+)$/, "분석 작업 상태: $1"],
    [/^Result cache key: (.+)$/, "결과 cache key: $1"],
    [/^Start (.+)$/, "시작 $1"],
    [/^First payment (.+)$/, "첫 지급 $1"],
    [/^(.+) zoom$/, "$1 확대"],
    [/^(.+) zoom map$/, "$1 확대 지도"],
    [/^(.+): (\d+) regions$/, "$1 $2곳"],
  ];

  let language = normalizeLanguage(localStorage.getItem(STORAGE_KEY));
  let observer = null;
  let applying = false;
  let scheduled = false;

  function normalizeLanguage(value) {
    return SUPPORTED_LANGUAGES.has(value) ? value : DEFAULT_LANGUAGE;
  }

  function translateCore(text, targetLanguage) {
    const exactMap = targetLanguage === "en" ? KO_TO_EN : EN_TO_KO;
    if (exactMap.has(text)) {
      return exactMap.get(text);
    }

    const patterns = targetLanguage === "en" ? KO_PATTERNS : EN_PATTERNS;
    for (const [pattern, replacement] of patterns) {
      if (pattern.test(text)) {
        return text.replace(pattern, replacement);
      }
    }
    return text;
  }

  const SIDO_LABELS_EN = new Map([
    ["서울", "Seoul"],
    ["부산", "Busan"],
    ["대구", "Daegu"],
    ["인천", "Incheon"],
    ["광주", "Gwangju"],
    ["대전", "Daejeon"],
    ["울산", "Ulsan"],
    ["세종", "Sejong"],
    ["경기", "Gyeonggi"],
    ["강원", "Gangwon"],
    ["충북", "Chungbuk"],
    ["충남", "Chungnam"],
    ["전북", "Jeonbuk"],
    ["전남", "Jeonnam"],
    ["경북", "Gyeongbuk"],
    ["경남", "Gyeongnam"],
    ["제주", "Jeju"],
  ]);

  const INITIALS = [
    "g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "",
    "j", "jj", "ch", "k", "t", "p", "h",
  ];
  const VOWELS = [
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae",
    "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i",
  ];
  const FINALS = [
    "", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "p", "l",
    "l", "l", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k",
    "t", "p", "t",
  ];

  function romanizeSyllable(char) {
    const code = char.charCodeAt(0);
    if (code < 0xac00 || code > 0xd7a3) {
      return char;
    }
    const offset = code - 0xac00;
    const initial = Math.floor(offset / 588);
    const vowel = Math.floor((offset % 588) / 28);
    const final = offset % 28;
    return `${INITIALS[initial]}${VOWELS[vowel]}${FINALS[final]}`;
  }

  function capitalize(value) {
    return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
  }

  function romanizeKorean(value) {
    return capitalize(
      String(value || "")
        .split("")
        .map((char) => romanizeSyllable(char))
        .join("")
        .replace(/\s+/g, " ")
        .trim(),
    );
  }

  function englishSigunguLabel(sigungu) {
    const value = String(sigungu || "");
    if (!value) {
      return "";
    }
    const cityDistrictMatch = value.match(/^(.+시)(.+구)$/);
    if (cityDistrictMatch) {
      return `${englishSigunguLabel(cityDistrictMatch[1])} ${englishSigunguLabel(cityDistrictMatch[2])}`;
    }
    if (value.endsWith("시")) {
      return `${romanizeKorean(value.slice(0, -1))}-si`;
    }
    if (value.endsWith("군")) {
      return `${romanizeKorean(value.slice(0, -1))}-gun`;
    }
    if (value.endsWith("구")) {
      return `${romanizeKorean(value.slice(0, -1))}-gu`;
    }
    return romanizeKorean(value);
  }

  function regionLabel(region) {
    if (!region || language !== "en") {
      return region?.region_sigungu || region?.region_sido || "";
    }
    if (region.region_sigungu) {
      return englishSigunguLabel(region.region_sigungu);
    }
    return SIDO_LABELS_EN.get(region.region_sido) || romanizeKorean(region.region_sido);
  }

  function translateText(text, targetLanguage = language) {
    const match = text.match(/^(\s*)(.*?)(\s*)$/s);
    if (!match || !match[2]) {
      return text;
    }
    const translated = translateCore(match[2], targetLanguage);
    if (translated === match[2]) {
      return text;
    }
    return `${match[1]}${translated}${match[3]}`;
  }

  function shouldSkipElement(element) {
    if (!element) {
      return true;
    }
    return Boolean(
      element.closest(
        "script, style, noscript, svg, .markdown-body, [data-i18n-skip]",
      ),
    );
  }

  function translateTextNode(node) {
    const parent = node.parentElement;
    if (shouldSkipElement(parent)) {
      return;
    }
    const translated = translateText(node.nodeValue || "");
    if (translated !== node.nodeValue) {
      node.nodeValue = translated;
    }
  }

  function translateAttributes(root) {
    const elements = root.querySelectorAll?.("[title], [aria-label], [placeholder]") || [];
    for (const element of elements) {
      if (shouldSkipElement(element)) {
        continue;
      }
      for (const attribute of ["title", "aria-label", "placeholder"]) {
        if (!element.hasAttribute(attribute)) {
          continue;
        }
        const value = element.getAttribute(attribute);
        const translated = translateText(value || "");
        if (translated !== value) {
          element.setAttribute(attribute, translated);
        }
      }
    }
  }

  function translateTextNodes(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }
    for (const node of nodes) {
      translateTextNode(node);
    }
  }

  function updateToggle() {
    const toggle = document.getElementById("language-toggle");
    if (!toggle) {
      return;
    }
    toggle.dataset.language = language;
    toggle.setAttribute("aria-pressed", String(language === "en"));
  }

  function apply(root = document.body) {
    if (!root) {
      return;
    }
    applying = true;
    document.documentElement.lang = language;
    translateTextNodes(root);
    translateAttributes(root);
    updateToggle();
    applying = false;
  }

  function scheduleApply() {
    if (scheduled || applying) {
      return;
    }
    scheduled = true;
    window.requestAnimationFrame(() => {
      scheduled = false;
      apply();
    });
  }

  function setLanguage(nextLanguage) {
    language = normalizeLanguage(nextLanguage);
    localStorage.setItem(STORAGE_KEY, language);
    apply();
    window.dispatchEvent(
      new CustomEvent("rbi:languagechange", {
        detail: { language },
      }),
    );
  }

  function toggleLanguage() {
    setLanguage(language === "ko" ? "en" : "ko");
  }

  function init() {
    const toggle = document.getElementById("language-toggle");
    if (toggle) {
      toggle.addEventListener("click", toggleLanguage);
    }
    observer = new MutationObserver(() => {
      if (language === "en") {
        scheduleApply();
      }
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["title", "aria-label", "placeholder"],
    });
    apply();
  }

  window.RBII18n = {
    apply,
    getLanguage: () => language,
    regionLabel,
    setLanguage,
    t: translateText,
    toggle: toggleLanguage,
  };

  document.addEventListener("DOMContentLoaded", init);
})();
