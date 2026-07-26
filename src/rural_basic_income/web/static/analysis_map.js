(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const ZOOM_SIDOS = new Set(["서울", "부산", "대구", "인천", "광주", "대전", "울산"]);
  const MIN_ZOOM = 1;
  const MAX_ZOOM = 6;
  const LABEL_ZOOM_DAMPING = 0.72;
  const SVG_VIEWPORTS = new WeakMap();

  function regionId(region) {
    return `${region.region_sido}::${region.region_sigungu}`;
  }

  function featureRegion(feature) {
    return {
      region_sido: feature.properties.region_sido,
      region_sigungu: feature.properties.region_sigungu,
    };
  }

  function regionLabel(region) {
    return `${region.region_sido} ${region.region_sigungu}`;
  }

  function loadMap(url) {
    return fetch(url).then((response) => {
      if (!response.ok) {
        throw new Error(`지도 파일을 불러오지 못했습니다: ${response.status}`);
      }
      return response.json();
    });
  }

  function computeBounds(features) {
    const bounds = {
      minX: Infinity,
      minY: Infinity,
      maxX: -Infinity,
      maxY: -Infinity,
    };
    for (const feature of features) {
      extendBounds(feature.geometry.coordinates, bounds);
    }
    return bounds;
  }

  function extendBounds(coords, bounds) {
    if (!Array.isArray(coords)) {
      return;
    }
    if (typeof coords[0] === "number") {
      bounds.minX = Math.min(bounds.minX, coords[0]);
      bounds.maxX = Math.max(bounds.maxX, coords[0]);
      bounds.minY = Math.min(bounds.minY, coords[1]);
      bounds.maxY = Math.max(bounds.maxY, coords[1]);
      return;
    }
    for (const item of coords) {
      extendBounds(item, bounds);
    }
  }

  function createProjection(bounds, options = {}) {
    const width = options.width || 1000;
    const ratio = (bounds.maxY - bounds.minY) / (bounds.maxX - bounds.minX);
    const rawHeight = Math.round(width * ratio);
    const minHeight = options.minHeight || 640;
    const maxHeight = options.maxHeight || 1240;
    const height = Math.max(minHeight, Math.min(maxHeight, rawHeight));
    const padding = options.padding || 14;
    const scale = Math.min(
      (width - padding * 2) / (bounds.maxX - bounds.minX),
      (height - padding * 2) / (bounds.maxY - bounds.minY),
    );
    const mapWidth = (bounds.maxX - bounds.minX) * scale;
    const mapHeight = (bounds.maxY - bounds.minY) * scale;
    const offsetX = (width - mapWidth) / 2;
    const offsetY = (height - mapHeight) / 2;

    return {
      width,
      height,
      project(point) {
        return [
          offsetX + (point[0] - bounds.minX) * scale,
          offsetY + (bounds.maxY - point[1]) * scale,
        ];
      },
    };
  }

  function geometryPath(geometry, projection) {
    if (!geometry) {
      return "";
    }
    if (geometry.type === "Polygon") {
      return polygonPath(geometry.coordinates, projection);
    }
    if (geometry.type === "MultiPolygon") {
      return geometry.coordinates
        .map((polygon) => polygonPath(polygon, projection))
        .join(" ");
    }
    return "";
  }

  function polygonPath(polygon, projection) {
    return polygon
      .map((ring) => {
        const commands = ring.map((point, index) => {
          const [x, y] = projection.project(point);
          return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
        });
        return `${commands.join(" ")} Z`;
      })
      .join(" ");
  }

  function createBoundsLabel(features, text, projection, className) {
    const bounds = computeBounds(features);
    if (!Number.isFinite(bounds.minX)) {
      return null;
    }
    const [x, y] = projection.project([
      (bounds.minX + bounds.maxX) / 2,
      (bounds.minY + bounds.maxY) / 2,
    ]);
    const label = document.createElementNS(SVG_NS, "text");
    label.classList.add("map-label");
    if (className) {
      label.classList.add(className);
    }
    label.dataset.baseFontSize = className === "is-sido-label"
      ? "20"
      : className === "is-zoom-label"
        ? "16"
        : "12";
    label.dataset.baseStrokeWidth = className === "is-sido-label" ? "4" : "3";
    label.setAttribute("x", x.toFixed(1));
    label.setAttribute("y", y.toFixed(1));
    label.textContent = text;
    return label;
  }

  function createLabel(feature, region, projection, zoom) {
    return createBoundsLabel(
      [feature],
      region.region_sigungu,
      projection,
      zoom ? "is-zoom-label" : "",
    );
  }

  function selectionSets(selections) {
    const sets = {};
    for (const [key, regions] of Object.entries(selections || {})) {
      sets[key] = new Set((regions || []).map(regionId));
    }
    return sets;
  }

  function selectionClass(group) {
    const classes = {
      controls: "control",
      series: "series",
      treatment: "treatment",
      treatments: "treatment",
      control: "control",
    };
    return classes[group] || group;
  }

  function create(config) {
    const instance = {
      root: config.root,
      callbacks: config.callbacks || {},
      features: [],
      mode: "treatment",
      selections: selectionSets(config.selections),
      labels: config.labels !== false,
      projection: config.projection || {},
      zoomProjection: config.zoomProjection || {},
      els: {},
    };

    function updateSelections(selections) {
      instance.selections = selectionSets(selections);
      refreshRegionClasses();
    }

    function setMode(mode) {
      instance.mode = mode;
      instance.root.querySelectorAll("[data-map-mode]").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.mapMode === mode);
      });
    }

    function setHoverText(text) {
      if (instance.els.hover) {
        instance.els.hover.textContent = text || "";
      }
    }

    function isZoomSido(region) {
      return ZOOM_SIDOS.has(region.region_sido);
    }

    function renderMap(svg, features, options = {}) {
      svg.replaceChildren();
      if (!features.length) {
        return;
      }

      const bounds = computeBounds(features);
      const projection = createProjection(bounds, options.projection || {});
      svg.setAttribute("viewBox", `0 0 ${projection.width} ${projection.height}`);

      const sortedFeatures = [...features].sort((a, b) =>
        regionLabel(featureRegion(a)).localeCompare(regionLabel(featureRegion(b))),
      );
      const labelQueue = [];
      const zoomSidoLabels = new Set();
      for (const feature of sortedFeatures) {
        const region = featureRegion(feature);
        const path = document.createElementNS(SVG_NS, "path");
        path.setAttribute("d", geometryPath(feature.geometry, projection));
        path.dataset.mapRegionId = regionId(region);
        path.dataset.sido = region.region_sido;
        path.dataset.sigungu = region.region_sigungu;
        path.classList.add("map-region");
        if (!options.zoom && isZoomSido(region)) {
          path.classList.add("is-zoom-entry");
        }
        path.setAttribute("role", "button");
        path.setAttribute("tabindex", "0");
        path.setAttribute(
          "aria-label",
          options.zoom || !isZoomSido(region)
            ? regionLabel(region)
            : `${region.region_sido} 확대`,
        );

        const title = document.createElementNS(SVG_NS, "title");
        title.textContent =
          options.zoom || !isZoomSido(region)
            ? regionLabel(region)
            : `${region.region_sido} 확대`;
        path.append(title);

        path.addEventListener("click", (event) => {
          if (shouldSuppressClick(svg)) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          handleRegionClick(feature, options);
        });
        path.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            handleRegionClick(feature, options);
          }
        });
        path.addEventListener("mouseenter", () => {
          setHoverText(
            options.zoom || !isZoomSido(region)
              ? regionLabel(region)
              : `${region.region_sido} 확대`,
          );
        });
        path.addEventListener("mouseleave", () => setHoverText(""));

        svg.append(path);
        if (instance.labels) {
          if (!options.zoom && isZoomSido(region)) {
            zoomSidoLabels.add(region.region_sido);
          } else {
            labelQueue.push({ feature, region });
          }
        }
      }

      for (const item of labelQueue) {
        const label = createLabel(item.feature, item.region, projection, options.zoom);
        if (label) {
          svg.append(label);
        }
      }
      for (const sido of zoomSidoLabels) {
        const sidoFeatures = features.filter(
          (feature) => feature.properties.region_sido === sido,
        );
        const label = createBoundsLabel(
          sidoFeatures,
          sido,
          projection,
          "is-sido-label",
        );
        if (label) {
          svg.append(label);
        }
      }
      installViewportControls(svg, projection);
      refreshRegionClasses(svg);
    }

    function installViewportControls(svg, projection) {
      let viewport = SVG_VIEWPORTS.get(svg);
      const base = {
        x: 0,
        y: 0,
        width: projection.width,
        height: projection.height,
      };
      if (!viewport) {
        viewport = {
          base,
          x: 0,
          y: 0,
          width: projection.width,
          height: projection.height,
          pointers: new Map(),
          drag: null,
          lastPinchDistance: null,
          suppressClickUntil: 0,
        };
        SVG_VIEWPORTS.set(svg, viewport);
        bindViewportEvents(svg);
      } else {
        viewport.base = base;
        viewport.x = 0;
        viewport.y = 0;
        viewport.width = projection.width;
        viewport.height = projection.height;
        viewport.pointers.clear();
        viewport.drag = null;
        viewport.lastPinchDistance = null;
        viewport.suppressClickUntil = 0;
      }
      applyViewport(svg, viewport);
    }

    function bindViewportEvents(svg) {
      svg.addEventListener("wheel", (event) => {
        event.preventDefault();
        const viewport = SVG_VIEWPORTS.get(svg);
        const anchor = clientPointToSvg(svg, event.clientX, event.clientY, viewport);
        const factor = event.deltaY < 0 ? 0.82 : 1.22;
        zoomViewport(svg, viewport, anchor, factor);
      }, { passive: false });

      svg.addEventListener("dblclick", (event) => {
        event.preventDefault();
        resetViewport(svg);
      });

      svg.addEventListener("pointerdown", (event) => {
        if (event.button !== undefined && event.button !== 0) {
          return;
        }
        const viewport = SVG_VIEWPORTS.get(svg);
        viewport.pointers.set(event.pointerId, {
          x: event.clientX,
          y: event.clientY,
        });
        viewport.lastPinchDistance = null;
        if (viewport.pointers.size === 1 && canPan(viewport)) {
          viewport.drag = {
            pointerId: event.pointerId,
            startClientX: event.clientX,
            startClientY: event.clientY,
            startX: viewport.x,
            startY: viewport.y,
            startWidth: viewport.width,
            startHeight: viewport.height,
            moved: false,
            captured: false,
          };
          svg.classList.add("is-panning");
        } else {
          viewport.drag = null;
        }
        if (viewport.pointers.size > 1) {
          capturePointer(svg, event.pointerId);
        }
      });

      svg.addEventListener("pointermove", (event) => {
        const viewport = SVG_VIEWPORTS.get(svg);
        if (!viewport || !viewport.pointers.has(event.pointerId)) {
          return;
        }
        event.preventDefault();
        viewport.pointers.set(event.pointerId, {
          x: event.clientX,
          y: event.clientY,
        });
        if (
          viewport.pointers.size === 1 &&
          viewport.drag &&
          viewport.drag.pointerId === event.pointerId &&
          canPan(viewport)
        ) {
          const movedDistance = Math.hypot(
            event.clientX - viewport.drag.startClientX,
            event.clientY - viewport.drag.startClientY,
          );
          if (movedDistance > 4 && !viewport.drag.captured) {
            capturePointer(svg, event.pointerId);
            viewport.drag.captured = true;
          }
          panViewport(svg, viewport, event.clientX, event.clientY);
          return;
        }
        if (viewport.pointers.size !== 2) {
          return;
        }
        viewport.drag = null;
        const points = [...viewport.pointers.values()];
        const distance = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
        const center = {
          x: (points[0].x + points[1].x) / 2,
          y: (points[0].y + points[1].y) / 2,
        };
        if (viewport.lastPinchDistance) {
          const anchor = clientPointToSvg(svg, center.x, center.y, viewport);
          zoomViewport(svg, viewport, anchor, viewport.lastPinchDistance / distance);
        }
        viewport.lastPinchDistance = distance;
      });

      const clearPointer = (event) => {
        const viewport = SVG_VIEWPORTS.get(svg);
        if (!viewport) {
          return;
        }
        if (viewport.drag?.pointerId === event.pointerId) {
          if (viewport.drag.moved) {
            viewport.suppressClickUntil = Date.now() + 250;
          }
          viewport.drag = null;
          svg.classList.remove("is-panning");
        }
        releasePointer(svg, event.pointerId);
        viewport.pointers.delete(event.pointerId);
        viewport.lastPinchDistance = null;
      };
      svg.addEventListener("pointerup", clearPointer);
      svg.addEventListener("pointercancel", clearPointer);
      svg.addEventListener("pointerleave", clearPointer);
    }

    function capturePointer(svg, pointerId) {
      try {
        svg.setPointerCapture(pointerId);
      } catch (_) {
        // Some browsers reject capture for a pointer that already ended.
      }
    }

    function releasePointer(svg, pointerId) {
      try {
        if (svg.hasPointerCapture(pointerId)) {
          svg.releasePointerCapture(pointerId);
        }
      } catch (_) {
        // Pointer capture release is best-effort cleanup.
      }
    }

    function resetViewport(svg) {
      const viewport = SVG_VIEWPORTS.get(svg);
      viewport.x = viewport.base.x;
      viewport.y = viewport.base.y;
      viewport.width = viewport.base.width;
      viewport.height = viewport.base.height;
      applyViewport(svg, viewport);
    }

    function clientPointToSvg(svg, clientX, clientY, viewport) {
      const rect = svg.getBoundingClientRect();
      return {
        x: viewport.x + ((clientX - rect.left) / rect.width) * viewport.width,
        y: viewport.y + ((clientY - rect.top) / rect.height) * viewport.height,
      };
    }

    function zoomViewport(svg, viewport, anchor, factor) {
      const currentZoom = viewport.base.width / viewport.width;
      const nextZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, currentZoom / factor));
      const nextWidth = viewport.base.width / nextZoom;
      const nextHeight = viewport.base.height / nextZoom;
      const anchorRatioX = (anchor.x - viewport.x) / viewport.width;
      const anchorRatioY = (anchor.y - viewport.y) / viewport.height;
      viewport.width = nextWidth;
      viewport.height = nextHeight;
      viewport.x = anchor.x - nextWidth * anchorRatioX;
      viewport.y = anchor.y - nextHeight * anchorRatioY;
      clampViewport(viewport);
      applyViewport(svg, viewport);
    }

    function clampViewport(viewport) {
      viewport.x = Math.max(
        viewport.base.x,
        Math.min(viewport.x, viewport.base.x + viewport.base.width - viewport.width),
      );
      viewport.y = Math.max(
        viewport.base.y,
        Math.min(viewport.y, viewport.base.y + viewport.base.height - viewport.height),
      );
    }

    function applyViewport(svg, viewport) {
      svg.setAttribute(
        "viewBox",
        `${viewport.x.toFixed(1)} ${viewport.y.toFixed(1)} ${viewport.width.toFixed(1)} ${viewport.height.toFixed(1)}`,
      );
      updateLabelScale(svg, viewport);
      svg.classList.toggle("is-zoomed", canPan(viewport));
    }

    function currentZoom(viewport) {
      return viewport.base.width / viewport.width;
    }

    function canPan(viewport) {
      return currentZoom(viewport) > MIN_ZOOM + 0.01;
    }

    function shouldSuppressClick(svg) {
      const viewport = SVG_VIEWPORTS.get(svg);
      return viewport ? Date.now() < viewport.suppressClickUntil : false;
    }

    function panViewport(svg, viewport, clientX, clientY) {
      const rect = svg.getBoundingClientRect();
      const deltaX = ((clientX - viewport.drag.startClientX) / rect.width) *
        viewport.drag.startWidth;
      const deltaY = ((clientY - viewport.drag.startClientY) / rect.height) *
        viewport.drag.startHeight;
      if (Math.hypot(clientX - viewport.drag.startClientX, clientY - viewport.drag.startClientY) > 4) {
        viewport.drag.moved = true;
      }
      viewport.x = viewport.drag.startX - deltaX;
      viewport.y = viewport.drag.startY - deltaY;
      clampViewport(viewport);
      applyViewport(svg, viewport);
    }

    function updateLabelScale(svg, viewport) {
      const zoom = currentZoom(viewport);
      const labelUnitScale = 1 / Math.pow(zoom, LABEL_ZOOM_DAMPING);
      svg.querySelectorAll(".map-label").forEach((label) => {
        const baseFontSize = Number(label.dataset.baseFontSize || 12);
        const baseStrokeWidth = Number(label.dataset.baseStrokeWidth || 3);
        label.style.fontSize = `${baseFontSize * labelUnitScale}px`;
        label.style.strokeWidth = `${baseStrokeWidth * labelUnitScale}px`;
      });
    }

    function handleRegionClick(feature, options) {
      const region = featureRegion(feature);
      if (!options.zoom && isZoomSido(region)) {
        openZoom(region.region_sido);
        return;
      }
      applyRegionSelection(region);
    }

    function applyRegionSelection(region) {
      if (instance.mode === "clear") {
        instance.callbacks.clearSelection?.(region);
        return;
      }
      instance.callbacks.select?.(region, instance.mode);
    }

    function openZoom(sido) {
      const zoomFeatures = instance.features.filter(
        (feature) => feature.properties.region_sido === sido,
      );
      instance.els.stage.classList.add("has-zoom");
      instance.els.zoomPanel.classList.remove("is-hidden");
      instance.els.zoomTitle.textContent = `${sido} 확대`;
      instance.els.zoomSvg.setAttribute("aria-label", `${sido} 확대 지도`);
      renderMap(instance.els.zoomSvg, zoomFeatures, {
        zoom: true,
        projection: {
          width: 720,
          minHeight: 380,
          maxHeight: 720,
          padding: 20,
          ...instance.zoomProjection,
        },
      });
    }

    function closeZoom() {
      instance.els.stage.classList.remove("has-zoom");
      instance.els.zoomPanel.classList.add("is-hidden");
      instance.els.zoomSvg.replaceChildren();
    }

    function refreshRegionClasses(scope) {
      const root = scope || instance.root;
      if (!root) {
        return;
      }
      root.querySelectorAll(".map-region").forEach((path) => {
        const id = path.dataset.mapRegionId;
        let selected = false;
        const knownSelectionClasses = new Set(
          Object.keys(instance.selections).map(selectionClass),
        );
        for (const className of knownSelectionClasses) {
          path.classList.remove(`is-${className}`);
        }
        for (const [group, ids] of Object.entries(instance.selections)) {
          const inGroup = ids.has(id);
          selected = selected || inGroup;
          path.classList.toggle(`is-${selectionClass(group)}`, inGroup);
        }
        path.classList.toggle("is-selected", selected);
      });
    }

    async function init() {
      instance.els = {
        mapSvg: instance.root.querySelector("[data-map-svg]"),
        zoomSvg: instance.root.querySelector("[data-map-zoom-svg]"),
        zoomPanel: instance.root.querySelector("[data-map-zoom-panel]"),
        zoomTitle: instance.root.querySelector("[data-map-zoom-title]"),
        zoomClose: instance.root.querySelector("[data-map-zoom-close]"),
        stage: instance.root.querySelector("[data-map-stage]"),
        loading: instance.root.querySelector("[data-map-loading]"),
        hover: instance.root.querySelector("[data-map-hover]"),
      };

      instance.root.querySelectorAll("[data-map-mode]").forEach((button) => {
        button.addEventListener("click", () => setMode(button.dataset.mapMode));
        if (button.classList.contains("is-active")) {
          instance.mode = button.dataset.mapMode;
        }
      });
      instance.els.zoomClose.addEventListener("click", closeZoom);

      try {
        const availableIds = new Set((config.regions || []).map(regionId));
        const geojson = await loadMap(config.mapUrl);
        instance.features = geojson.features.filter((feature) =>
          availableIds.has(regionId(featureRegion(feature))),
        );
        renderMap(instance.els.mapSvg, instance.features, {
          projection: {
            width: 1000,
            minHeight: 780,
            maxHeight: 1240,
            padding: 10,
            ...instance.projection,
          },
        });
        instance.els.loading.classList.add("is-hidden");
      } catch (error) {
        instance.els.loading.textContent = error.message;
        instance.callbacks.setStatus?.(error.message, true);
      }
    }

    init();

    return {
      updateSelections,
      closeZoom,
    };
  }

  window.RBIRegionMap = Object.freeze({
    create,
  });
})();
