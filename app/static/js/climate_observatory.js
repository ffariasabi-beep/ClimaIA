function initializeClimateObservatory() {
  const dataElement = document.getElementById("observatory-regions-data");
  if (!dataElement) {
    return;
  }

  const regions = JSON.parse(dataElement.textContent);
  const globe = document.getElementById("observatory-globe");
  const globeCanvas = document.getElementById("observatory-globe-canvas");
  const globeContext = globeCanvas.getContext("2d");
  const markerContainer = document.getElementById("observatory-markers");
  const markers = Array.from(
    document.querySelectorAll(".observatory-marker")
  );
  const regionButtons = Array.from(
    document.querySelectorAll(".observatory-region-button")
  );
  const regionElement = document.getElementById("observatory-region");
  const cityElement = document.getElementById("observatory-city");
  const temperatureElement = document.getElementById(
    "observatory-temperature"
  );
  const humidityElement = document.getElementById("observatory-humidity");
  const precipitationElement = document.getElementById(
    "observatory-precipitation"
  );
  const precipitationTodayElement = document.getElementById(
    "observatory-precipitation-today"
  );
  const windElement = document.getElementById("observatory-wind");
  const feelsLikeElement = document.getElementById(
    "observatory-feels-like"
  );
  const timeElement = document.getElementById("observatory-time");
  const selectedLocationInput = document.getElementById(
    "observatory-ai-location-id"
  );
  const selectedLocationIndexInput = document.getElementById(
    "observatory-ai-location-index"
  );

  let yaw = 0;
  let pitch = 0;
  let pointerStartX = 0;
  let pointerStartY = 0;
  let startYaw = 0;
  let startPitch = 0;
  let dragging = false;
  let dragDistance = 0;
  let suppressClick = false;

  const degreesToRadians = Math.PI / 180;
  const landmasses = [
    [
      [-168, 70], [-150, 72], [-132, 58], [-125, 50], [-123, 40],
      [-114, 32], [-105, 24], [-97, 17], [-88, 16], [-82, 9], [-78, 8],
      [-77, 18], [-83, 25], [-80, 31], [-73, 40], [-66, 45], [-58, 52],
      [-62, 59], [-78, 62], [-91, 70], [-112, 74], [-136, 72], [-153, 66],
      [-168, 70]
    ],
    [
      [-52, 60], [-45, 59], [-38, 67], [-42, 78], [-53, 83], [-61, 77],
      [-58, 68], [-52, 60]
    ],
    [
      [-81, 12], [-72, 10], [-65, 5], [-55, 2], [-47, -5], [-37, -8],
      [-42, -20], [-50, -29], [-54, -39], [-62, -53], [-70, -55],
      [-76, -39], [-73, -20], [-80, -5], [-81, 12]
    ],
    [
      [-10, 36], [-9, 44], [-5, 50], [2, 51], [5, 58], [14, 55], [20, 60],
      [28, 57], [34, 50], [42, 48], [48, 41], [40, 35], [33, 37], [27, 35],
      [23, 39], [17, 37], [11, 42], [5, 41], [0, 36], [-10, 36]
    ],
    [
      [-17, 36], [-5, 36], [8, 37], [20, 33], [31, 31], [34, 22], [43, 12],
      [50, 11], [42, -1], [39, -12], [31, -23], [19, -35], [12, -34],
      [4, -26], [-4, -17], [-11, -2], [-17, 14], [-17, 36]
    ],
    [
      [35, 32], [43, 38], [53, 35], [59, 28], [68, 25], [76, 30], [80, 20],
      [88, 22], [93, 14], [105, 8], [111, 1], [121, 5], [127, 15], [121, 22],
      [114, 25], [110, 31], [120, 35], [129, 42], [141, 44], [151, 59],
      [166, 61], [178, 52], [164, 47], [149, 45], [139, 37], [130, 32],
      [122, 24], [116, 18], [109, 12], [103, 5], [96, 7], [91, 12], [83, 8],
      [78, 17], [72, 21], [65, 24], [57, 25], [50, 30], [44, 34], [35, 32]
    ],
    [
      [28, 50], [38, 51], [48, 50], [58, 52], [70, 53], [85, 55],
      [100, 56], [115, 55], [130, 53], [145, 49], [158, 54], [170, 59],
      [178, 64], [170, 67], [155, 67], [140, 69], [125, 71], [108, 72],
      [90, 71], [75, 68], [62, 66], [52, 62], [42, 59], [33, 56], [28, 50]
    ],
    [
      [130, 32], [136, 35], [141, 40], [145, 44], [142, 35], [137, 31],
      [130, 32]
    ],
    [
      [112, -11], [122, -10], [132, -12], [141, -16], [153, -27], [147, -39],
      [136, -44], [124, -40], [115, -32], [112, -22], [112, -11]
    ],
    [[47, -13], [50, -17], [49, -24], [46, -26], [44, -18], [47, -13]]
  ];

  function formatValue(value, unit) {
    if (value === null || value === undefined || value === "") {
      return "--";
    }

    const number = Number(value);
    return Number.isFinite(number) ? `${number}${unit}` : "--";
  }

  function project(longitude, latitude, centerX, centerY, radius) {
    const longitudeRadians = (longitude + yaw) * degreesToRadians;
    const latitudeRadians = latitude * degreesToRadians;
    const pitchRadians = pitch * degreesToRadians;
    const cosLatitude = Math.cos(latitudeRadians);
    const east = cosLatitude * Math.sin(longitudeRadians);
    const north = Math.sin(latitudeRadians);
    const towardCamera = cosLatitude * Math.cos(longitudeRadians);
    const rotatedNorth = (
      north * Math.cos(pitchRadians)
      - towardCamera * Math.sin(pitchRadians)
    );
    const depth = (
      north * Math.sin(pitchRadians)
      + towardCamera * Math.cos(pitchRadians)
    );

    return {
      x: centerX + east * radius,
      y: centerY - rotatedNorth * radius,
      depth
    };
  }

  function drawGraticule(context, centerX, centerY, radius) {
    context.lineWidth = 0.7;
    context.strokeStyle = "rgba(197, 231, 244, .24)";

    for (let latitude = -60; latitude <= 60; latitude += 30) {
      context.beginPath();
      let drawing = false;
      for (let longitude = -180; longitude <= 180; longitude += 3) {
        const point = project(longitude, latitude, centerX, centerY, radius);
        if (point.depth > 0) {
          if (drawing) context.lineTo(point.x, point.y);
          else context.moveTo(point.x, point.y);
          drawing = true;
        } else {
          drawing = false;
        }
      }
      context.stroke();
    }

    for (let longitude = -150; longitude <= 180; longitude += 30) {
      context.beginPath();
      let drawing = false;
      for (let latitude = -90; latitude <= 90; latitude += 3) {
        const point = project(longitude, latitude, centerX, centerY, radius);
        if (point.depth > 0) {
          if (drawing) context.lineTo(point.x, point.y);
          else context.moveTo(point.x, point.y);
          drawing = true;
        } else {
          drawing = false;
        }
      }
      context.stroke();
    }

    context.beginPath();
    let drawing = false;
    for (let longitude = -180; longitude <= 180; longitude += 3) {
      const point = project(longitude, 0, centerX, centerY, radius);
      if (point.depth > 0) {
        if (drawing) context.lineTo(point.x, point.y);
        else context.moveTo(point.x, point.y);
        drawing = true;
      } else {
        drawing = false;
      }
    }
    context.lineWidth = 1.15;
    context.strokeStyle = "rgba(219, 240, 248, .38)";
    context.stroke();
  }

  function drawLandmass(context, coordinates, centerX, centerY, radius) {
    context.beginPath();
    let drawing = false;

    for (let index = 0; index < coordinates.length; index += 1) {
      const start = coordinates[index];
      const end = coordinates[(index + 1) % coordinates.length];
      for (let step = 0; step <= 6; step += 1) {
        if (index > 0 && step === 0) continue;
        const fraction = step / 6;
        const longitude = start[0] + (end[0] - start[0]) * fraction;
        const latitude = start[1] + (end[1] - start[1]) * fraction;
        const point = project(longitude, latitude, centerX, centerY, radius);

        if (point.depth > 0) {
          if (drawing) context.lineTo(point.x, point.y);
          else context.moveTo(point.x, point.y);
          drawing = true;
        } else if (drawing) {
          context.closePath();
          drawing = false;
        }
      }
    }

    if (drawing) context.closePath();
    context.fillStyle = "#69a981";
    context.fill();
    context.lineWidth = 0.8;
    context.strokeStyle = "rgba(194, 231, 170, .7)";
    context.stroke();
  }

  function updateMarkers(centerX, centerY, radius) {
    for (const marker of markers) {
      const index = Number(marker.dataset.observatoryIndex);
      const region = regions[index];
      if (!region) continue;

      const longitude = Number(region.longitude);
      const latitude = Number(region.latitude);
      if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) {
        marker.style.visibility = "hidden";
        continue;
      }

      const point = project(longitude, latitude, centerX, centerY, radius);
      const temperature = region.temperature === null
        || region.temperature === undefined
        ? Number.NaN
        : Number(region.temperature);
      const heat = Number.isFinite(temperature)
        ? Math.max(0, Math.min(1, (temperature + 10) / 55))
        : 0.5;

      marker.style.left = `${point.x}px`;
      marker.style.top = `${point.y}px`;
      marker.style.visibility = point.depth > 0.025 ? "visible" : "hidden";
      marker.style.opacity = String(0.55 + Math.max(0, point.depth) * 0.45);
      marker.style.zIndex = String(Math.round(10 + point.depth * 10));
      marker.style.setProperty(
        "--marker-color",
        `hsl(${210 - heat * 200} 88% 63%)`
      );
      marker.title = `${region.city}, ${region.country} · ${formatValue(
        region.temperature,
        " °C"
      )}`;
    }
  }

  function drawGlobe() {
    const width = globe.clientWidth || 300;
    const height = globe.clientHeight || width;
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    const pixelWidth = Math.round(width * pixelRatio);
    const pixelHeight = Math.round(height * pixelRatio);

    if (globeCanvas.width !== pixelWidth || globeCanvas.height !== pixelHeight) {
      globeCanvas.width = pixelWidth;
      globeCanvas.height = pixelHeight;
    }

    const context = globeContext;
    if (!context) return;

    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);

    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(width, height) * 0.455;

    const ocean = context.createRadialGradient(
      centerX - radius * 0.34,
      centerY - radius * 0.4,
      radius * 0.04,
      centerX,
      centerY,
      radius * 1.12
    );
    ocean.addColorStop(0, "#4e9bc0");
    ocean.addColorStop(0.42, "#17628b");
    ocean.addColorStop(0.78, "#0b3b62");
    ocean.addColorStop(1, "#041326");

    context.save();
    context.beginPath();
    context.arc(centerX, centerY, radius, 0, Math.PI * 2);
    context.shadowColor = "rgba(2, 10, 24, .65)";
    context.shadowBlur = 20;
    context.shadowOffsetX = 8;
    context.shadowOffsetY = 11;
    context.fillStyle = ocean;
    context.fill();
    context.restore();

    context.save();
    context.beginPath();
    context.arc(centerX, centerY, radius, 0, Math.PI * 2);
    context.clip();
    for (const landmass of landmasses) {
      drawLandmass(context, landmass, centerX, centerY, radius);
    }
    drawGraticule(context, centerX, centerY, radius);

    const shading = context.createLinearGradient(
      centerX - radius,
      centerY - radius * 0.2,
      centerX + radius,
      centerY + radius * 0.2
    );
    shading.addColorStop(0, "rgba(204, 241, 255, .09)");
    shading.addColorStop(0.48, "rgba(5, 18, 38, .02)");
    shading.addColorStop(1, "rgba(1, 8, 23, .48)");
    context.fillStyle = shading;
    context.fillRect(
      centerX - radius,
      centerY - radius,
      radius * 2,
      radius * 2
    );

    const edgeShade = context.createRadialGradient(
      centerX,
      centerY,
      radius * 0.62,
      centerX,
      centerY,
      radius
    );
    edgeShade.addColorStop(0, "rgba(1, 8, 22, 0)");
    edgeShade.addColorStop(1, "rgba(1, 8, 22, .42)");
    context.fillStyle = edgeShade;
    context.fillRect(
      centerX - radius,
      centerY - radius,
      radius * 2,
      radius * 2
    );
    context.restore();

    context.beginPath();
    context.arc(centerX, centerY, radius, 0, Math.PI * 2);
    context.lineWidth = 1.4;
    context.strokeStyle = "rgba(190, 231, 255, .75)";
    context.stroke();

    updateMarkers(centerX, centerY, radius);
  }

  function orientGlobe(region) {
    const longitude = Number(region.longitude);
    const latitude = Number(region.latitude);
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) {
      return;
    }

    yaw = -longitude;
    pitch = Math.max(-80, Math.min(80, latitude));
    drawGlobe();
  }

  function selectRegion(index, moveGlobe) {
    const region = regions[index];
    if (!region) {
      return;
    }

    regionElement.textContent = region.region;
    cityElement.textContent = `${region.city}, ${region.country}`;
    if (selectedLocationInput) {
      selectedLocationInput.value = region.geoname_id || "";
    }
    if (selectedLocationIndexInput) {
      selectedLocationIndexInput.value = String(index);
    }
    temperatureElement.textContent = formatValue(region.temperature, "°");
    humidityElement.textContent = formatValue(region.humidity, "%");
    precipitationElement.textContent = formatValue(
      region.precipitation,
      " mm"
    );
    if (precipitationTodayElement) {
      precipitationTodayElement.textContent = (
        `Acumulado hoy: ${formatValue(region.precipitation_today, " mm")}`
      );
    }
    windElement.textContent = formatValue(region.wind_speed, " km/h");
    feelsLikeElement.textContent = formatValue(region.feels_like, "°");
    timeElement.textContent = region.time
      ? `Hora local consultada: ${region.time}`
      : "Hora local no disponible";

    for (const button of [...markers, ...regionButtons]) {
      const selected = Number(button.dataset.observatoryIndex) === index;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    }

    if (moveGlobe) {
      orientGlobe(region);
    }
  }

  function attachMarkerSelection(marker) {
    marker.addEventListener("click", () => {
      selectRegion(Number(marker.dataset.observatoryIndex), true);
    });
  }

  function addOrUpdateRegion(region) {
    const regionIndex = regions.findIndex(
      (item) => item.geoname_id
        && String(item.geoname_id) === String(region.geoname_id)
    );
    const index = regionIndex >= 0 ? regionIndex : regions.length;
    regions[index] = region;

    let marker = markers.find(
      (item) => Number(item.dataset.observatoryIndex) === index
    );

    if (!marker) {
      marker = document.createElement("button");
      marker.className = "observatory-marker";
      marker.type = "button";
      marker.dataset.observatoryIndex = String(index);
      marker.setAttribute("aria-label", `${region.city}, ${region.country}`);
      markerContainer.append(marker);
      markers.push(marker);
      attachMarkerSelection(marker);
    }

    selectRegion(index, true);
  }

  for (const marker of markers) {
    attachMarkerSelection(marker);
  }

  for (const button of regionButtons) {
    button.addEventListener("click", () => {
      selectRegion(Number(button.dataset.observatoryIndex), true);
    });
  }

  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(drawGlobe).observe(globe);
  } else {
    window.addEventListener("resize", drawGlobe);
  }
  const initialRegionIndex = Number(
    selectedLocationIndexInput
      ? selectedLocationIndexInput.value
      : 0
  );
  selectRegion(
    Number.isInteger(initialRegionIndex)
      && initialRegionIndex >= 0
      && initialRegionIndex < regions.length
      ? initialRegionIndex
      : 0,
    true
  );

  globe.addEventListener("pointerdown", (event) => {
    if (event.button !== undefined && event.button !== 0) {
      return;
    }
    if (event.target.closest(".observatory-marker")) {
      return;
    }

    dragging = true;
    dragDistance = 0;
    pointerStartX = event.clientX;
    pointerStartY = event.clientY;
    startYaw = yaw;
    startPitch = pitch;
    globe.classList.add("is-dragging");
    globe.setPointerCapture(event.pointerId);
  });

  globe.addEventListener("pointermove", (event) => {
    if (!dragging) {
      return;
    }

    const deltaX = event.clientX - pointerStartX;
    const deltaY = event.clientY - pointerStartY;
    dragDistance = Math.max(dragDistance, Math.abs(deltaX), Math.abs(deltaY));
    yaw = startYaw + deltaX * 0.6;
    pitch = Math.max(-85, Math.min(85, startPitch - deltaY * 0.45));
    drawGlobe();
  });

  function finishDragging(event) {
    if (!dragging) {
      return;
    }

    dragging = false;
    globe.classList.remove("is-dragging");
    suppressClick = dragDistance > 5;

    if (globe.hasPointerCapture(event.pointerId)) {
      globe.releasePointerCapture(event.pointerId);
    }

    if (suppressClick) {
      window.setTimeout(() => {
        suppressClick = false;
      }, 0);
    }
  }

  globe.addEventListener("pointerup", finishDragging);
  globe.addEventListener("pointercancel", finishDragging);
  globe.addEventListener(
    "click",
    (event) => {
      if (suppressClick) {
        event.preventDefault();
        event.stopPropagation();
        suppressClick = false;
      }
    },
    true
  );

  globe.addEventListener("keydown", (event) => {
    const turn = event.key === "ArrowLeft" || event.key === "ArrowRight";
    const tilt = event.key === "ArrowUp" || event.key === "ArrowDown";
    if (!turn && !tilt) {
      return;
    }

    event.preventDefault();
    if (event.key === "ArrowLeft") yaw -= 10;
    if (event.key === "ArrowRight") yaw += 10;
    if (event.key === "ArrowUp") pitch = Math.min(85, pitch + 8);
    if (event.key === "ArrowDown") pitch = Math.max(-85, pitch - 8);
    drawGlobe();
  });

  const searchForm = document.getElementById(
    "observatory-location-search-form"
  );
  const searchInput = document.getElementById("observatory-location-query");
  const searchMessage = document.getElementById("observatory-search-message");
  const searchResults = document.getElementById(
    "observatory-search-results"
  );

  async function loadCatalogLocation(location, resultButton) {
    resultButton.disabled = true;
    searchMessage.textContent = `Consultando el clima de ${location.display_name}...`;

    try {
      const response = await fetch(
        `/api/locations/${encodeURIComponent(location.geoname_id)}/weather`,
        { headers: { Accept: "application/json" } }
      );
      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(
          data.error || "No se pudo consultar el clima de la localidad."
        );
      }

      const current = data.weather.current;
      addOrUpdateRegion({
        region: location.admin_region || location.country_name,
        city: location.name,
        country: location.country_name,
        latitude: location.latitude,
        longitude: location.longitude,
        geoname_id: location.geoname_id,
        temperature: current.temperature,
        humidity: current.humidity,
        feels_like: current.feels_like,
        precipitation: current.precipitation,
        precipitation_today: current.precipitation_today,
        wind_speed: current.wind_speed,
        time: current.time
      });

      searchMessage.textContent = `${location.display_name} seleccionada desde la base de localidades.`;
      searchResults.replaceChildren();
    } catch (error) {
      searchMessage.textContent = error.message;
      resultButton.disabled = false;
    }
  }

  if (searchForm) {
    searchForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = searchInput.value.trim();
      searchResults.replaceChildren();

      if (query.length < 2) {
        searchMessage.textContent = "Ingresá al menos dos caracteres.";
        return;
      }

      const searchButton = searchForm.querySelector("button");
      searchButton.disabled = true;
      searchMessage.textContent = "Buscando en el catálogo de localidades...";

      try {
        const response = await fetch(
          `/api/locations/search?q=${encodeURIComponent(query)}`,
          { headers: { Accept: "application/json" } }
        );
        const data = await response.json();

        if (!response.ok || !data.success) {
          throw new Error(data.error || "No se pudieron buscar localidades.");
        }

        if (!data.locations.length) {
          searchMessage.textContent = "No se encontraron localidades. Probá con otro nombre.";
          return;
        }

        searchMessage.textContent = `Elegí una de las ${data.count} localidades encontradas:`;
        for (const location of data.locations) {
          const button = document.createElement("button");
          button.className = "observatory-search-result";
          button.type = "button";
          button.textContent = location.display_name;
          if (location.admin_region) {
            button.textContent += ` · ${location.admin_region}`;
          }
          button.addEventListener("click", () => {
            loadCatalogLocation(location, button);
          });
          searchResults.append(button);
        }
      } catch (error) {
        searchMessage.textContent = error.message;
      } finally {
        searchButton.disabled = false;
      }
    });
  }

  const aiForm = document.getElementById("observatory-ai-form");
  if (aiForm) {
    aiForm.addEventListener("submit", () => {
      const button = aiForm.querySelector("button");
      button.disabled = true;
      button.textContent = "Interpretando los datos...";
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeClimateObservatory);
} else {
  initializeClimateObservatory();
}
