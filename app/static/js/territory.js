(function () {
  "use strict";

  const mapElement = document.getElementById("territory-map");
  if (!mapElement || typeof L === "undefined") {
    return;
  }

  const searchForm = document.getElementById("territory-search-form");
  const searchInput = document.getElementById("territory-location-query");
  const searchStatus = document.getElementById("territory-search-status");
  const searchResults = document.getElementById("territory-search-results");
  const basemapSelect = document.getElementById("territory-basemap");
  const satelliteControls = document.getElementById("territory-satellite-controls");
  const dateInput = document.getElementById("territory-date");
  const compareDateInput = document.getElementById("territory-compare-date");
  const compareToggle = document.getElementById("territory-compare-toggle");
  const swipeControl = document.getElementById("territory-swipe-control");
  const swipeRange = document.getElementById("territory-swipe-range");
  const swipeDivider = document.getElementById("territory-swipe-divider");
  const comparisonLabels = document.getElementById("territory-comparison-labels");
  const comparisonLeftLabel = document.getElementById(
    "territory-comparison-left-label"
  );
  const comparisonRightLabel = document.getElementById(
    "territory-comparison-right-label"
  );
  const areaButton = document.getElementById("territory-area-button");
  const selectionTitle = document.getElementById("territory-selection-title");
  const selectionDetail = document.getElementById("territory-selection-detail");
  const analysisLayerSelect = document.getElementById(
    "territory-analysis-layer"
  );
  const analyticsButton = document.getElementById(
    "territory-analytics-button"
  );
  const analyticsStatus = document.getElementById(
    "territory-analytics-status"
  );
  const analyticsResults = document.getElementById(
    "territory-analytics-results"
  );
  const analysisLegend = document.getElementById(
    "territory-analysis-legend"
  );
  const mapLayerName = document.getElementById("territory-map-layer-name");
  const mapDateLabel = document.getElementById("territory-map-date-label");
  const mapMessage = document.getElementById("territory-map-message");
  const searchUrl = searchForm.dataset.searchUrl;
  const analyticsUrl = searchForm.dataset.analyticsUrl;
  const questionForm = document.getElementById("territory-question-form");
  const questionInput = document.getElementById("territory-question");
  const questionStatus = document.getElementById("territory-question-status");
  const researchConversation = document.getElementById(
    "territory-research-conversation"
  );
  const researchContext = document.getElementById("territory-ai-context");
  const researchUrl = questionForm.dataset.researchUrl;
  const csrfToken = document.getElementById("territory-csrf-token").value;
  const minimumSatelliteDate = "2002-07-03";
  const unavailableSatelliteDateMessage =
    "MODIS Aqua está disponible desde el 03/07/2002 hasta ayer. " +
    "Elegí una fecha dentro de ese período.";
  const noDataPixelThreshold = 12;
  const tileUrlTemplate =
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/" +
    "MODIS_Aqua_CorrectedReflectance_TrueColor/default/{date}/" +
    "GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpeg";
  const referenceTileUrlTemplate =
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/" +
    "BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/" +
    "{z}/{y}/{x}.jpeg";
  const ndviWmsUrl =
    "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/";
  const worldCoverWmsUrl = "https://titiler.terrascope.be/wms";

  const map = L.map(mapElement, {
    center: [15, 0],
    zoom: 2,
    minZoom: 2,
    maxZoom: 12,
    worldCopyJump: true,
    zoomControl: true
  });

  L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);

  const selectionLayer = L.layerGroup().addTo(map);
  const primaryPane = map.createPane("territoryPrimaryPane");
  primaryPane.style.zIndex = "300";
  primaryPane.style.pointerEvents = "none";
  const comparePane = map.createPane("territoryComparePane");
  comparePane.style.zIndex = "310";
  comparePane.style.pointerEvents = "none";
  const analysisPane = map.createPane("territoryAnalysisPane");
  analysisPane.style.zIndex = "420";
  analysisPane.style.pointerEvents = "none";

  const geographicLayer = L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }
  );
  const satelliteReferenceLayer = L.tileLayer(referenceTileUrlTemplate, {
    minZoom: 2,
    maxZoom: 12,
    maxNativeZoom: 8,
    attribution:
      'Reference imagery &copy; <a href="https://earthdata.nasa.gov/">NASA EOSDIS GIBS</a> · Blue Marble'
  });
  satelliteReferenceLayer.addTo(map);

  let satelliteLayer = null;
  let comparisonLayer = null;
  let analysisLayer = null;
  let comparisonActive = false;
  let areaSelectionActive = false;
  let firstAreaCorner = null;
  let selectedTerritory = null;
  let conversationHistory = [];
  let researchRequestInProgress = false;
  let tileLoadGeneration = 0;
  let tileLoadTimer = null;
  let analyticsRequestGeneration = 0;
  let analyticsRequestInProgress = false;
  let analyticsResult = null;

  const SatelliteGridLayer = L.GridLayer.extend({
    createTile: function (coords, done) {
      const tile = L.DomUtil.create("canvas", "leaflet-tile");
      const size = this.getTileSize();
      tile.width = size.x;
      tile.height = size.y;
      const context = tile.getContext("2d", { willReadFrequently: true });
      const workingCanvas = document.createElement("canvas");
      workingCanvas.width = size.x;
      workingCanvas.height = size.y;
      const workingContext = workingCanvas.getContext("2d", {
        willReadFrequently: true
      });
      const requests = this.options.dates.map(function (date) {
        return new Promise(function (resolve) {
          const image = new Image();
          image.crossOrigin = "anonymous";
          image.onload = function () {
            resolve(image);
          };
          image.onerror = function () {
            resolve(null);
          };
          image.src = tileUrlTemplate
            .replace("{date}", encodeURIComponent(date))
            .replace("{z}", coords.z)
            .replace("{y}", coords.y)
            .replace("{x}", coords.x);
        });
      });

      Promise.all(requests).then(function (images) {
        const availableImages = images.filter(Boolean);
        if (!availableImages.length) {
          done(
            new Error("NASA GIBS no devolvió mosaicos para esta ventana."),
            tile
          );
          return;
        }

        try {
          for (
            let imageIndex = availableImages.length - 1;
            imageIndex >= 0;
            imageIndex -= 1
          ) {
            workingContext.clearRect(0, 0, size.x, size.y);
            workingContext.drawImage(
              availableImages[imageIndex],
              0,
              0,
              size.x,
              size.y
            );
            const pixels = workingContext.getImageData(0, 0, size.x, size.y);
            for (let index = 0; index < pixels.data.length; index += 4) {
              // GIBS encodes unavailable swaths as near-black pixels in opaque JPEG tiles.
              if (
                pixels.data[index] <= noDataPixelThreshold &&
                pixels.data[index + 1] <= noDataPixelThreshold &&
                pixels.data[index + 2] <= noDataPixelThreshold
              ) {
                pixels.data[index + 3] = 0;
              }
            }
            workingContext.putImageData(pixels, 0, 0);
            context.drawImage(workingCanvas, 0, 0);
          }
          done(null, tile);
        } catch (error) {
          done(error, tile);
        }
      }).catch(function (error) {
        done(error, tile);
      });

      return tile;
    }
  });

  function localDateString(date) {
    const adjusted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return adjusted.toISOString().slice(0, 10);
  }

  function formatDate(dateString) {
    if (!dateString) {
      return "";
    }
    const parts = dateString.split("-").map(Number);
    return new Intl.DateTimeFormat("es-AR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      timeZone: "UTC"
    }).format(new Date(Date.UTC(parts[0], parts[1] - 1, parts[2])));
  }

  function isSatelliteDateAvailable(dateString) {
    return Boolean(
      dateString &&
      dateString >= minimumSatelliteDate &&
      dateString <= dateInput.max
    );
  }

  function getSatelliteCompositeDates(endDate) {
    const dates = [];
    const date = new Date(endDate + "T00:00:00Z");
    for (let offset = 0; offset < 3; offset += 1) {
      const dateString = date.toISOString().slice(0, 10);
      if (dateString >= minimumSatelliteDate) {
        dates.push(dateString);
      }
      date.setUTCDate(date.getUTCDate() - 1);
    }
    return dates;
  }

  function makeSatelliteLayer(date, paneName) {
    return new SatelliteGridLayer({
      date: date,
      dates: getSatelliteCompositeDates(date),
      pane: paneName || "territoryPrimaryPane",
      minZoom: 2,
      maxZoom: 12,
      maxNativeZoom: 9,
      attribution:
        'Imagery &copy; <a href="https://earthdata.nasa.gov/">NASA EOSDIS GIBS</a> · MODIS Aqua'
    });
  }

  function addAnalysisLegendTitle(text) {
    const title = document.createElement("strong");
    title.textContent = text;
    analysisLegend.appendChild(title);
  }

  function updateAnalysisLegend(layerName) {
    analysisLegend.replaceChildren();
    if (layerName === "none") {
      analysisLegend.hidden = true;
      return;
    }

    analysisLegend.hidden = false;
    if (layerName === "ndvi") {
      addAnalysisLegendTitle("NDVI mensual · escala NASA");
      const gradient = document.createElement("div");
      gradient.className = "territory-ndvi-gradient";
      const labels = document.createElement("div");
      labels.className = "territory-ndvi-labels";
      labels.textContent = "−1 · menor verdor                         +1 · mayor verdor";
      analysisLegend.append(gradient, labels);
      return;
    }

    const classes = [
      ["Árboles", "#006400"],
      ["Matorral", "#FFBB22"],
      ["Pastizal", "#FFFF4C"],
      ["Cultivos", "#F096FF"],
      ["Construido", "#FA0000"],
      ["Suelo desnudo", "#B4B4B4"],
      ["Nieve / hielo", "#F0F0F0"],
      ["Agua", "#0064C8"],
      ["Humedal", "#0096A0"],
      ["Manglar", "#00CF75"],
      ["Musgo / líquenes", "#FAE6A0"]
    ];
    addAnalysisLegendTitle(
      layerName === "worldcover-2020"
        ? "ESA WorldCover 2020"
        : "ESA WorldCover 2021"
    );
    const list = document.createElement("div");
    list.className = "territory-cover-legend";
    classes.forEach(function (item) {
      const entry = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.style.backgroundColor = item[1];
      const label = document.createElement("span");
      label.textContent = item[0];
      entry.append(swatch, label);
      list.appendChild(entry);
    });
    analysisLegend.appendChild(list);
  }

  function updateAnalysisLayer() {
    if (analysisLayer) {
      map.removeLayer(analysisLayer);
      analysisLayer = null;
    }

    const layerName = analysisLayerSelect.value;
    updateAnalysisLegend(layerName);
    if (layerName === "none") {
      mapLayerName.textContent = basemapSelect.value === "satellite"
        ? "MODIS Aqua · composición visual de hasta 3 días · color real"
        : "Mapa geográfico · OpenStreetMap";
      return;
    }

    let url = worldCoverWmsUrl;
    let params = {
      service: "WMS",
      request: "GetMap",
      version: "1.3.0",
      crs: L.CRS.EPSG3857,
      format: "image/png",
      transparent: true,
      pane: "territoryAnalysisPane",
      opacity: 0.78,
      attribution:
        'Imagery &copy; <a href="https://esa-worldcover.org/">ESA WorldCover</a>'
    };

    if (layerName === "ndvi") {
      url = ndviWmsUrl;
      const ndviDate = analyticsResult &&
        analyticsResult.vegetation &&
        analyticsResult.vegetation.primary
        ? analyticsResult.vegetation.primary.date
        : dateInput.value;
      params.layers = "MODIS_Terra_L3_NDVI_Monthly";
      params.styles = "default";
      params.time = ndviDate
        ? ndviDate.slice(0, 7) + "-01"
        : "";
      params.attribution =
        'Imagery &copy; <a href="https://earthdata.nasa.gov/">NASA EOSDIS GIBS</a> · MODIS Terra NDVI';
      mapLayerName.textContent =
        "NASA MODIS Terra · NDVI mensual sobre la capa base";
    } else {
      const year = layerName === "worldcover-2020" ? 2020 : 2021;
      params.layers = "esa-worldcover-map-10m-" + year +
        (year === 2020 ? "-v1_map" : "-v2_map");
      params.styles = "";
      params.time = year + "-01-01";
      mapLayerName.textContent =
        "ESA WorldCover " + year + " · cobertura del suelo sobre la capa base";
    }

    const layer = L.tileLayer.wms(url, params);
    analysisLayer = layer;
    layer.on("tileload", function () {
      if (analysisLayer === layer) {
        hideMapMessage();
      }
    });
    layer.on("tileerror", function () {
      if (analysisLayer === layer) {
        showMapMessage(
          "No se pudo cargar la capa analítica. La selección de otra capa base " +
          "o fecha no elimina el resultado calculado."
        );
      }
    });
    layer.addTo(map);
  }

  function showMapMessage(message) {
    mapMessage.textContent = message;
    mapMessage.hidden = false;
  }

  function hideMapMessage() {
    mapMessage.hidden = true;
  }

  function watchSatelliteTiles(layer, date) {
    tileLoadGeneration += 1;
    const generation = tileLoadGeneration;
    let loadedAnyTile = false;
    window.clearTimeout(tileLoadTimer);
    showMapMessage("Cargando mosaicos satelitales de NASA…");

    layer.on("tileload", function () {
      if (generation !== tileLoadGeneration) {
        return;
      }
      loadedAnyTile = true;
      hideMapMessage();
    });

    layer.on("tileerror", function () {
      if (generation === tileLoadGeneration && !loadedAnyTile) {
        showMapMessage("NASA GIBS no devolvió mosaicos para esta vista o fecha.");
      }
    });

    tileLoadTimer = window.setTimeout(function () {
      if (generation === tileLoadGeneration && !loadedAnyTile) {
        showMapMessage(
          "No se recibieron mosaicos para " + formatDate(date) +
          ". Probá otra fecha o verificá la conexión con NASA GIBS."
        );
      }
    }, 15000);
  }

  function updateMapDateLabel() {
    if (comparisonActive) {
      mapDateLabel.textContent =
        formatDate(compareDateInput.value) + "  |  " +
        formatDate(dateInput.value);
      updateComparisonLabels();
    } else {
      mapDateLabel.textContent = formatDate(dateInput.value);
    }
  }

  function updateComparisonLabels() {
    comparisonLeftLabel.textContent =
      "Comparación · hasta " + formatDate(compareDateInput.value);
    comparisonRightLabel.textContent =
      "Principal · hasta " + formatDate(dateInput.value);
  }

  function updateSatelliteDate() {
    const date = dateInput.value;
    if (satelliteLayer) {
      map.removeLayer(satelliteLayer);
      satelliteLayer = null;
    }

    if (!date) {
      return;
    }

    if (!isSatelliteDateAvailable(date)) {
      showMapMessage(unavailableSatelliteDateMessage);
      updateMapDateLabel();
      return;
    }

    satelliteLayer = makeSatelliteLayer(date);
    if (basemapSelect.value === "satellite") {
      satelliteLayer.addTo(map);
      watchSatelliteTiles(satelliteLayer, date);
    }
    updateMapDateLabel();
  }

  function updateComparisonClip() {
    const value = Number(swipeRange.value);
    comparePane.style.clipPath = "inset(0 " + (100 - value) + "% 0 0)";
    primaryPane.style.clipPath = "inset(0 0 0 " + value + "%)";
    swipeDivider.style.left = value + "%";
  }

  function deactivateComparison() {
    if (comparisonLayer) {
      map.removeLayer(comparisonLayer);
      comparisonLayer = null;
    }
    comparisonActive = false;
    swipeControl.hidden = true;
    swipeDivider.hidden = true;
    comparisonLabels.hidden = true;
    compareToggle.textContent = "Activar comparación";
    comparePane.style.clipPath = "";
    primaryPane.style.clipPath = "";
    updateMapDateLabel();
  }

  function activateComparison() {
    if (comparisonActive) {
      deactivateComparison();
    }

    const firstDate = dateInput.value;
    const secondDate = compareDateInput.value;
    if (!secondDate) {
      showMapMessage("Elegí una segunda fecha para comparar.");
      compareDateInput.focus();
      return;
    }
    if (
      !isSatelliteDateAvailable(firstDate) ||
      !isSatelliteDateAvailable(secondDate)
    ) {
      showMapMessage(unavailableSatelliteDateMessage);
      return;
    }
    if (firstDate === secondDate) {
      showMapMessage("Elegí dos fechas distintas para compararlas.");
      compareDateInput.focus();
      return;
    }
    if (basemapSelect.value !== "satellite") {
      basemapSelect.value = "satellite";
      updateBasemap();
    }

    if (comparisonLayer) {
      map.removeLayer(comparisonLayer);
    }
    comparisonLayer = makeSatelliteLayer(secondDate, "territoryComparePane");
    comparisonLayer.addTo(map);
    comparisonActive = true;
    swipeControl.hidden = false;
    swipeDivider.hidden = false;
    comparisonLabels.hidden = false;
    compareToggle.textContent = "Desactivar comparación";
    updateComparisonClip();
    updateMapDateLabel();
    hideMapMessage();
  }

  function updateBasemap() {
    if (comparisonActive) {
      deactivateComparison();
    }

    if (basemapSelect.value === "geographic") {
      if (satelliteLayer && map.hasLayer(satelliteLayer)) {
        map.removeLayer(satelliteLayer);
      }
      if (map.hasLayer(satelliteReferenceLayer)) {
        map.removeLayer(satelliteReferenceLayer);
      }
      if (!map.hasLayer(geographicLayer)) {
        geographicLayer.addTo(map);
      }
      satelliteControls.hidden = true;
      mapLayerName.textContent = "Mapa geográfico · OpenStreetMap";
      hideMapMessage();
      updateAnalysisLayer();
      return;
    }

    if (map.hasLayer(geographicLayer)) {
      map.removeLayer(geographicLayer);
    }
    if (!map.hasLayer(satelliteReferenceLayer)) {
      satelliteReferenceLayer.addTo(map);
    }
    satelliteControls.hidden = false;
    mapLayerName.textContent =
      "MODIS Aqua · composición visual de hasta 3 días · color real";
    updateSatelliteDate();
    updateAnalysisLayer();
  }

  function addSelectionRow(label, value) {
    const row = document.createElement("div");
    row.className = "territory-selection-row";

    const labelElement = document.createElement("span");
    labelElement.textContent = label;
    const valueElement = document.createElement("strong");
    valueElement.textContent = value;

    row.append(labelElement, valueElement);
    selectionDetail.appendChild(row);
  }

  function formatCoordinate(value) {
    return Number(value).toFixed(4) + "°";
  }

  function updateAnalyticsButton() {
    const datesAreValid = isSatelliteDateAvailable(dateInput.value) &&
      (
        !comparisonActive ||
        isSatelliteDateAvailable(compareDateInput.value)
      );
    analyticsButton.disabled = !selectedTerritory ||
      !datesAreValid ||
      analyticsRequestInProgress;
  }

  function clearAnalyticsResults(message) {
    analyticsRequestGeneration += 1;
    analyticsResult = null;
    analyticsResults.replaceChildren();
    analyticsResults.hidden = true;
    analyticsStatus.textContent = message ||
      (selectedTerritory
        ? "La selección cambió. Ejecutá el análisis para actualizar los indicadores."
        : "Seleccioná un punto o un área para calcular indicadores.");
    updateAnalyticsButton();
    updateAnalysisLayer();
  }

  function formatAnalyticsNumber(value, digits) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "Sin datos";
    }
    return new Intl.NumberFormat("es-AR", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    }).format(number);
  }

  function appendAnalyticsCard(grid, title, value, subtitle, valueClass) {
    const card = document.createElement("article");
    card.className = "territory-analytics-card";
    const heading = document.createElement("h3");
    heading.textContent = title;
    const mainValue = document.createElement("strong");
    mainValue.className = "territory-analytics-value" +
      (valueClass ? " " + valueClass : "");
    mainValue.textContent = value;
    const detail = document.createElement("span");
    detail.className = "territory-analytics-subtitle";
    detail.textContent = subtitle;
    card.append(heading, mainValue, detail);
    grid.appendChild(card);
    return card;
  }

  function appendLandCoverCard(grid, summary) {
    const card = document.createElement("article");
    card.className = "territory-analytics-card";
    const heading = document.createElement("h3");
    heading.textContent = "Cobertura del suelo · " + summary.year;
    const water = document.createElement("strong");
    water.className = "territory-analytics-value";
    water.textContent =
      formatAnalyticsNumber(summary.water_percentage, 1) + "%";
    const waterLabel = document.createElement("span");
    waterLabel.className = "territory-analytics-subtitle";
    waterLabel.textContent =
      "Agua permanente · muestra clasificada " +
      formatAnalyticsNumber(summary.classified_coverage_percentage, 1) +
      "%";
    const list = document.createElement("div");
    list.className = "territory-cover-list";

    (summary.classes || []).slice(0, 5).forEach(function (item) {
      const row = document.createElement("div");
      row.className = "territory-cover-row";
      const label = document.createElement("span");
      label.textContent = item.label;
      const track = document.createElement("span");
      track.className = "territory-cover-track";
      const bar = document.createElement("span");
      bar.className = "territory-cover-bar";
      const percentage = Math.max(
        0,
        Math.min(100, Number(item.percentage) || 0)
      );
      bar.style.width = percentage + "%";
      bar.style.backgroundColor = item.color;
      track.appendChild(bar);
      const value = document.createElement("strong");
      value.textContent = formatAnalyticsNumber(percentage, 1) + "%";
      row.append(label, track, value);
      list.appendChild(row);
    });

    card.append(heading, water, waterLabel, list);
    grid.appendChild(card);
  }

  function renderAnalytics(result) {
    analyticsResults.replaceChildren();
    analyticsResults.hidden = false;

    const heading = document.createElement("div");
    heading.className = "territory-analytics-heading";
    const headingText = document.createElement("div");
    const eyebrow = document.createElement("span");
    eyebrow.className = "territory-section-label";
    eyebrow.textContent = "INDICADORES SATELITALES";
    const title = document.createElement("h2");
    title.textContent = "Resumen de observación";
    const selection = document.createElement("p");
    selection.textContent =
      (result.selection && result.selection.name) ||
      "Área seleccionada";
    headingText.append(eyebrow, title, selection);
    heading.appendChild(headingText);
    analyticsResults.appendChild(heading);

    const grid = document.createElement("div");
    grid.className = "territory-analytics-grid";
    const vegetation = result.vegetation || {};
    const primary = vegetation.primary;
    if (primary) {
      const period = primary.date ? formatDate(primary.date) : "período solicitado";
      appendAnalyticsCard(
        grid,
        "NDVI medio · " + period,
        formatAnalyticsNumber(primary.mean_ndvi, 3),
        "Mín. " + formatAnalyticsNumber(primary.minimum_ndvi, 3) +
        " · máx. " + formatAnalyticsNumber(primary.maximum_ndvi, 3) +
        " · cobertura válida " +
        formatAnalyticsNumber(primary.coverage_percentage, 1) + "%"
      );
    }

    const comparison = vegetation.comparison;
    if (comparison) {
      appendAnalyticsCard(
        grid,
        "NDVI medio · comparación " +
          (comparison.date ? formatDate(comparison.date) : ""),
        formatAnalyticsNumber(comparison.mean_ndvi, 3),
        "Mín. " + formatAnalyticsNumber(comparison.minimum_ndvi, 3) +
        " · máx. " + formatAnalyticsNumber(comparison.maximum_ndvi, 3) +
        " · cobertura válida " +
        formatAnalyticsNumber(comparison.coverage_percentage, 1) + "%"
      );
      const delta = Number(vegetation.delta_mean);
      appendAnalyticsCard(
        grid,
        "Diferencia de NDVI medio",
        formatAnalyticsNumber(delta, 3),
        "Comparación menos período principal; no representa causalidad.",
        Number.isFinite(delta)
          ? delta > 0
            ? "is-positive"
            : delta < 0
              ? "is-negative"
              : ""
          : ""
      );
    }

    const landCover = result.land_cover || {};
    (landCover.maps || []).forEach(function (summary) {
      appendLandCoverCard(grid, summary);
    });
    if (landCover.comparison) {
      appendAnalyticsCard(
        grid,
        "Diferencia cartográfica · 2020–2021",
        formatAnalyticsNumber(
          landCover.comparison.changed_percentage,
          1
        ) + "%",
        "Muestra con clases distintas entre mapas."
      );
    }
    analyticsResults.appendChild(grid);

    const warnings = Array.from(new Set(
      (result.warnings || []).concat(vegetation.warnings || [])
    ));
    warnings.forEach(function (warning) {
      const warningElement = document.createElement("p");
      warningElement.className = "territory-analytics-warning";
      warningElement.textContent = warning;
      analyticsResults.appendChild(warningElement);
    });

    if (landCover.comparison_note) {
      const comparisonNote = document.createElement("p");
      comparisonNote.className = "territory-analytics-note";
      comparisonNote.textContent = landCover.comparison_note;
      analyticsResults.appendChild(comparisonNote);
    }

    if (result.method_note) {
      const methodNote = document.createElement("p");
      methodNote.className = "territory-analytics-note";
      methodNote.textContent = result.method_note;
      analyticsResults.appendChild(methodNote);
    }

    const sources = document.createElement("div");
    sources.className = "territory-analytics-sources";
    (result.sources || []).forEach(function (source) {
      if (!source.name || !source.url) {
        return;
      }
      const link = document.createElement("a");
      link.className = "territory-analytics-source";
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = source.name;
      sources.appendChild(link);
    });
    if (sources.childElementCount) {
      analyticsResults.appendChild(sources);
    }
  }

  async function runTerritoryAnalytics() {
    if (!selectedTerritory) {
      analyticsStatus.textContent =
        "Primero seleccioná un punto o un área en el mapa.";
      return;
    }
    if (!isSatelliteDateAvailable(dateInput.value)) {
      analyticsStatus.textContent = unavailableSatelliteDateMessage;
      return;
    }
    if (
      comparisonActive &&
      (
        !isSatelliteDateAvailable(compareDateInput.value) ||
        compareDateInput.value === dateInput.value
      )
    ) {
      analyticsStatus.textContent =
        "La comparación requiere dos fechas disponibles y distintas.";
      return;
    }

    const generation = ++analyticsRequestGeneration;
    analyticsRequestInProgress = true;
    updateAnalyticsButton();
    analyticsStatus.textContent =
      "Consultando NASA MODIS y ESA WorldCover para la selección…";

    try {
      const response = await fetch(analyticsUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken
        },
        body: JSON.stringify({
          selection: selectedTerritory,
          date: dateInput.value,
          compare_active: comparisonActive,
          comparison_date: compareDateInput.value
        })
      });
      const payload = await response.json();
      if (!response.ok || !payload.success || !payload.analysis) {
        throw new Error(
          payload.error || "No se pudo completar el análisis territorial."
        );
      }
      if (generation !== analyticsRequestGeneration) {
        return;
      }

      analyticsResult = payload.analysis;
      renderAnalytics(analyticsResult);
      updateAnalysisLayer();
      analyticsStatus.textContent =
        (
          (analyticsResult.warnings || []).length ||
          ((analyticsResult.vegetation || {}).warnings || []).length
        )
          ? "Análisis listo con productos parciales; revisá las advertencias."
          : "Análisis listo. Las estimaciones y su resolución están detalladas abajo.";
    } catch (error) {
      if (generation === analyticsRequestGeneration) {
        analyticsStatus.textContent =
          error.message || "Falló el análisis satelital territorial.";
      }
    } finally {
      analyticsRequestInProgress = false;
      updateAnalyticsButton();
    }
  }

  function addResearchMessage(role, content, sourceText) {
    const emptyState = researchConversation.querySelector(
      ".territory-chat-empty"
    );
    if (emptyState) {
      emptyState.remove();
    }

    const message = document.createElement("article");
    message.className = "territory-chat-message" +
      (role === "user" ? " is-user" : "");

    const label = document.createElement("strong");
    label.textContent = role === "user" ? "TU PREGUNTA" : "CLAUDE";
    const text = document.createElement("p");
    text.textContent = content;
    message.append(label, text);

    if (sourceText) {
      const source = document.createElement("small");
      source.className = "territory-chat-source";
      source.textContent = sourceText;
      message.appendChild(source);
    }

    researchConversation.appendChild(message);
    while (researchConversation.children.length > 8) {
      researchConversation.firstElementChild.remove();
    }
    researchConversation.scrollTop = researchConversation.scrollHeight;
  }

  function resetResearchConversation(message) {
    conversationHistory = [];
    researchConversation.replaceChildren();
    const emptyState = document.createElement("p");
    emptyState.className = "territory-chat-empty";
    emptyState.textContent = message ||
      "Preguntá qué muestra la comparación y cómo se relaciona con " +
      "el historial climático, sin asumir causalidad.";
    researchConversation.appendChild(emptyState);
    questionStatus.textContent =
      "La IA usa datos de NASA GIBS y el reanálisis climático de Open-Meteo.";
  }

  function updateResearchContext() {
    const submitButton = questionForm.querySelector('button[type="submit"]');
    if (!selectedTerritory) {
      researchContext.textContent =
        "Seleccioná un punto o área en el mapa para habilitar la consulta.";
      submitButton.disabled = true;
      return;
    }

    if (
      !isSatelliteDateAvailable(dateInput.value) ||
      (
        comparisonActive &&
        !isSatelliteDateAvailable(compareDateInput.value)
      )
    ) {
      researchContext.textContent = unavailableSatelliteDateMessage;
      submitButton.disabled = true;
      return;
    }

    const dates = comparisonActive
      ? formatDate(compareDateInput.value) + " y " + formatDate(dateInput.value)
      : formatDate(dateInput.value);
    const selectionLabel = selectedTerritory.name ||
      (selectedTerritory.type === "area" ? "Área seleccionada" : "Punto seleccionado");
    researchContext.textContent =
      selectionLabel + " · mosaico " + dates +
      " · historial climático hasta " + (new Date().getFullYear() - 1);
    submitButton.disabled = researchRequestInProgress;
  }

  function currentResearchContextKey() {
    return JSON.stringify({
      selection: selectedTerritory,
      date: dateInput.value,
      comparisonDate: comparisonActive ? compareDateInput.value : null
    });
  }

  function setPointSelection(latitude, longitude, name, zoomToPoint) {
    selectionLayer.clearLayers();
    const point = L.latLng(latitude, longitude);
    L.circleMarker(point, {
      radius: 7,
      color: "#eafaff",
      weight: 2,
      fillColor: "#32c7df",
      fillOpacity: 1
    }).addTo(selectionLayer);

    selectionTitle.textContent = name || "Punto seleccionado";
    selectionDetail.replaceChildren();
    addSelectionRow("Latitud", formatCoordinate(latitude));
    addSelectionRow("Longitud", formatCoordinate(longitude));
    if (name) {
      addSelectionRow("Coordenadas", "WGS 84");
    }

    selectedTerritory = {
      type: "point",
      name: name || "Punto seleccionado",
      latitude: Number(latitude),
      longitude: Number(longitude)
    };
    clearAnalyticsResults();
    resetResearchConversation();
    updateResearchContext();

    if (zoomToPoint) {
      map.setView(point, Math.max(map.getZoom(), 6));
    }
  }

  function setAreaSelection(firstCorner, secondCorner) {
    const bounds = L.latLngBounds(firstCorner, secondCorner);
    selectionLayer.clearLayers();
    L.rectangle(bounds, {
      color: "#55d5e5",
      weight: 2,
      fillColor: "#46b8d1",
      fillOpacity: 0.14,
      dashArray: "6 5"
    }).addTo(selectionLayer);
    L.circleMarker(bounds.getCenter(), {
      radius: 5,
      color: "#eafaff",
      weight: 1,
      fillColor: "#32c7df",
      fillOpacity: 1
    }).addTo(selectionLayer);

    selectionTitle.textContent = "Área seleccionada";
    selectionDetail.replaceChildren();
    addSelectionRow(
      "Latitud",
      formatCoordinate(bounds.getSouth()) + " a " + formatCoordinate(bounds.getNorth())
    );
    addSelectionRow(
      "Longitud",
      formatCoordinate(bounds.getWest()) + " a " + formatCoordinate(bounds.getEast())
    );
    selectedTerritory = {
      type: "area",
      name: "Área seleccionada",
      south: bounds.getSouth(),
      north: bounds.getNorth(),
      west: bounds.getWest(),
      east: bounds.getEast()
    };
    clearAnalyticsResults();
    resetResearchConversation();
    updateResearchContext();
    map.fitBounds(bounds, { padding: [25, 25], maxZoom: 8 });
  }

  function setAreaSelectionMode(active) {
    areaSelectionActive = active;
    firstAreaCorner = null;
    areaButton.setAttribute("aria-pressed", String(active));
    areaButton.textContent = active ? "Cancelar selección de área" : "Marcar un área";
    if (active) {
      map.getContainer().style.cursor = "crosshair";
      showMapMessage("Elegí la primera esquina del área en el mapa.");
    } else {
      map.getContainer().style.cursor = "";
      hideMapMessage();
    }
  }

  map.on("click", function (event) {
    if (!areaSelectionActive) {
      setPointSelection(
        event.latlng.lat,
        event.latlng.lng,
        "Punto seleccionado",
        false
      );
      return;
    }

    if (!firstAreaCorner) {
      firstAreaCorner = event.latlng;
      showMapMessage("Ahora elegí la esquina opuesta del área.");
      return;
    }

    setAreaSelection(firstAreaCorner, event.latlng);
    setAreaSelectionMode(false);
  });

  searchForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    const query = searchInput.value.trim();
    if (query.length < 2) {
      searchStatus.textContent = "Ingresá al menos dos caracteres.";
      searchResults.replaceChildren();
      return;
    }

    searchStatus.textContent = "Buscando en el catálogo de localidades…";
    searchResults.replaceChildren();
    const submitButton = searchForm.querySelector('button[type="submit"]');
    submitButton.disabled = true;

    try {
      const response = await fetch(
        searchUrl + "?q=" + encodeURIComponent(query),
        { headers: { Accept: "application/json" }, credentials: "same-origin" }
      );
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "No se pudieron buscar las localidades.");
      }

      if (!payload.locations.length) {
        searchStatus.textContent = "No se encontraron localidades para esa búsqueda.";
        return;
      }

      searchStatus.textContent =
        payload.count + (payload.count === 1
          ? " resultado encontrado."
          : " resultados encontrados.");

      payload.locations.forEach(function (location) {
        const result = document.createElement("button");
        result.type = "button";
        result.className = "territory-search-result";

        const name = document.createElement("strong");
        name.textContent = location.display_name || location.name;
        const region = document.createElement("span");
        region.textContent = location.admin_region || location.country_name || location.country;
        result.append(name, region);

        result.addEventListener("click", function () {
          setAreaSelectionMode(false);
          setPointSelection(
            Number(location.latitude),
            Number(location.longitude),
            location.display_name || location.name,
            true
          );
        });
        searchResults.appendChild(result);
      });
    } catch (error) {
      searchStatus.textContent = error.message || "Falló la búsqueda de localidades.";
    } finally {
      submitButton.disabled = false;
    }
  });

  dateInput.addEventListener("change", function () {
    if (comparisonActive && dateInput.value === compareDateInput.value) {
      deactivateComparison();
      showMapMessage("La comparación se desactivó porque las fechas son iguales.");
    }
    updateSatelliteDate();
    clearAnalyticsResults(
      "La fecha cambió. Ejecutá el análisis para actualizar los indicadores."
    );
    if (selectedTerritory) {
      resetResearchConversation();
      updateResearchContext();
    }
  });

  compareDateInput.addEventListener("change", function () {
    if (comparisonActive) {
      activateComparison();
      clearAnalyticsResults(
        "La fecha de comparación cambió. Volvé a ejecutar el análisis."
      );
      if (selectedTerritory) {
        resetResearchConversation();
        updateResearchContext();
      }
    }
  });

  compareToggle.addEventListener("click", function () {
    const wasActive = comparisonActive;
    if (comparisonActive) {
      deactivateComparison();
    } else {
      activateComparison();
    }
    if (wasActive !== comparisonActive && selectedTerritory) {
      clearAnalyticsResults(
        "Cambió la comparación temporal. Ejecutá el análisis para actualizarlo."
      );
      resetResearchConversation();
      updateResearchContext();
    }
  });

  swipeRange.addEventListener("input", updateComparisonClip);

  basemapSelect.addEventListener("change", updateBasemap);
  analysisLayerSelect.addEventListener("change", updateAnalysisLayer);
  analyticsButton.addEventListener("click", runTerritoryAnalytics);

  areaButton.addEventListener("click", function () {
    setAreaSelectionMode(!areaSelectionActive);
  });

  questionForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    const question = questionInput.value.trim();
    if (!selectedTerritory) {
      questionStatus.textContent =
        "Primero seleccioná un punto o área en el mapa.";
      return;
    }
    if (!question || question.length > 1200) {
      questionStatus.textContent =
        "Escribí una pregunta de hasta 1200 caracteres.";
      return;
    }
    if (
      !isSatelliteDateAvailable(dateInput.value) ||
      (
        comparisonActive &&
        !isSatelliteDateAvailable(compareDateInput.value)
      )
    ) {
      questionStatus.textContent = unavailableSatelliteDateMessage;
      return;
    }

    const contextKey = currentResearchContextKey();
    const history = conversationHistory.slice(-6);
    const submitButton = questionForm.querySelector('button[type="submit"]');
    researchRequestInProgress = true;
    submitButton.disabled = true;
    questionStatus.textContent =
      "Consultando el mosaico satelital y la serie climática…";

    try {
      const response = await fetch(researchUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken
        },
        body: JSON.stringify({
          question: question,
          selection: selectedTerritory,
          date: dateInput.value,
          compare_active: comparisonActive,
          comparison_date: compareDateInput.value,
          conversation_history: history
        })
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "No se pudo consultar a Groq.");
      }

      if (contextKey !== currentResearchContextKey()) {
        questionStatus.textContent =
          "Cambió la selección o el período durante la consulta. " +
          "Revisá el contexto y volvé a preguntar.";
        return;
      }

      addResearchMessage("user", question);
      const sources = (payload.sources || []).join(" · ");
      const climateEndYear = payload.climate_period &&
        payload.climate_period.end_year;
      const sourceText = sources +
        (climateEndYear ? " · reanálisis hasta " + climateEndYear : "");
      addResearchMessage("assistant", payload.answer, sourceText);
      conversationHistory = history.concat([
        { role: "user", content: question },
        { role: "assistant", content: payload.answer }
      ]);
      questionInput.value = "";
      if (payload.climate_available === false) {
        questionStatus.textContent =
          "Groq respondió con la evidencia NASA disponible. " +
          "No se recibieron datos climáticos históricos, así que no se " +
          "infieren tendencias.";
      } else if (payload.climate_profile_type === "monthly_normal") {
        questionStatus.textContent =
          "Groq integró la evidencia NASA con una normal climática mensual " +
          "de la base local; no representa una tendencia anual.";
      } else {
        questionStatus.textContent =
          "Groq integró evidencia visual y climática disponible; " +
          "la interpretación no demuestra causalidad.";
      }
    } catch (error) {
      questionStatus.textContent =
        error.message || "Falló la consulta de investigación territorial.";
    } finally {
      researchRequestInProgress = false;
      updateResearchContext();
    }
  });

  const today = new Date();
  const latestDate = new Date(today);
  latestDate.setDate(today.getDate() - 1);
  const initialDate = new Date(today);
  initialDate.setDate(today.getDate() - 2);
  const initialDateString = localDateString(initialDate);
  const latestDateString = localDateString(latestDate);

  dateInput.min = minimumSatelliteDate;
  compareDateInput.min = minimumSatelliteDate;
  dateInput.max = latestDateString;
  compareDateInput.max = latestDateString;
  dateInput.value = initialDateString;

  const previousYearDate = new Date(initialDate);
  previousYearDate.setFullYear(previousYearDate.getFullYear() - 1);
  compareDateInput.value = localDateString(previousYearDate);

  satelliteLayer = makeSatelliteLayer(initialDateString);
  satelliteLayer.addTo(map);
  watchSatelliteTiles(satelliteLayer, initialDateString);
  updateMapDateLabel();
  updateAnalysisLayer();
  updateAnalyticsButton();
  updateResearchContext();

  window.setTimeout(function () {
    map.invalidateSize();
  }, 0);
})();
