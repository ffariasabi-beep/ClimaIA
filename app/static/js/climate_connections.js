function appendInlineContent(container, text) {
  const formatting = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let currentIndex = 0;

  for (const match of text.matchAll(formatting)) {
    const token = match[0];
    const start = match.index;

    container.append(
      document.createTextNode(text.slice(currentIndex, start))
    );

    let element;
    if (token.startsWith("**")) {
      element = document.createElement("strong");
      element.textContent = token.slice(2, -2);
    } else if (token.startsWith("*")) {
      element = document.createElement("em");
      element.textContent = token.slice(1, -1);
    } else {
      element = document.createElement("code");
      element.textContent = token.slice(1, -1);
    }

    container.append(element);
    currentIndex = start + token.length;
  }

  container.append(document.createTextNode(text.slice(currentIndex)));
}

function isTableRow(line) {
  return /^\s*\|.*\|\s*$/.test(line);
}

function parseTableRow(line) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map(
    (cell) => cell.trim()
  );
}

function isTableSeparator(cells) {
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function appendMarkdownTable(parent, lines) {
  const rows = lines.map(parseTableRow);
  if (rows.length < 2) {
    const paragraph = document.createElement("p");
    appendInlineContent(paragraph, lines.join(" "));
    parent.append(paragraph);
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "report-table-wrapper";
  const table = document.createElement("table");
  table.className = "report-table";
  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");

  for (const cell of rows[0]) {
    const header = document.createElement("th");
    appendInlineContent(header, cell);
    headerRow.append(header);
  }
  head.append(headerRow);
  table.append(head);

  const body = document.createElement("tbody");
  for (const row of rows.slice(1)) {
    if (isTableSeparator(row)) {
      continue;
    }

    const tableRow = document.createElement("tr");
    for (const cell of row) {
      const tableCell = document.createElement("td");
      appendInlineContent(tableCell, cell);
      tableRow.append(tableCell);
    }
    body.append(tableRow);
  }

  table.append(body);
  wrapper.append(table);
  parent.append(wrapper);
}

function renderMarkdownReport(sourceId, outputId) {
  const source = document.getElementById(sourceId);
  const output = document.getElementById(outputId);
  if (!source || !output) {
    return;
  }

  const lines = source.textContent.trim().split(/\r?\n/);
  let currentContainer = output;
  let currentList = null;
  let currentListType = null;
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      currentList = null;
      currentListType = null;
      index += 1;
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      currentList = null;
      currentListType = null;
      const section = document.createElement("section");
      section.className = "report-section-card";
      const headingElement = document.createElement(
        heading[1].length <= 2 ? "h2" : "h3"
      );
      appendInlineContent(headingElement, heading[2]);
      section.append(headingElement);
      output.append(section);
      currentContainer = section;
      index += 1;
      continue;
    }

    if (isTableRow(line)) {
      currentList = null;
      currentListType = null;
      const tableLines = [];
      while (index < lines.length && isTableRow(lines[index].trim())) {
        tableLines.push(lines[index].trim());
        index += 1;
      }
      appendMarkdownTable(currentContainer, tableLines);
      continue;
    }

    const unorderedItem = line.match(/^[-*]\s+(.+)$/);
    const orderedItem = line.match(/^\d+[.)]\s+(.+)$/);
    const listItem = unorderedItem || orderedItem;
    if (listItem) {
      const listType = unorderedItem ? "ul" : "ol";
      if (!currentList || currentListType !== listType) {
        currentList = document.createElement(listType);
        currentContainer.append(currentList);
        currentListType = listType;
      }

      const item = document.createElement("li");
      appendInlineContent(item, listItem[1]);
      currentList.append(item);
      index += 1;
      continue;
    }

    currentList = null;
    currentListType = null;
    const paragraphLines = [line];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !/^#{1,4}\s+/.test(lines[index].trim())
      && !isTableRow(lines[index].trim())
      && !/^[-*]\s+/.test(lines[index].trim())
      && !/^\d+[.)]\s+/.test(lines[index].trim())
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }

    const paragraph = document.createElement("p");
    appendInlineContent(paragraph, paragraphLines.join(" "));
    currentContainer.append(paragraph);
  }

  source.hidden = true;
}

renderMarkdownReport("ai-report-source", "ai-report-content");
renderMarkdownReport(
  "observatory-ai-report-source",
  "observatory-ai-report-content"
);

function initializeConnectionsMap() {
  const element = document.getElementById("climate-connections-map");
  if (!element || typeof L === "undefined") {
    return;
  }

  const targetLatitude = Number(element.dataset.targetLat);
  const targetLongitude = Number(element.dataset.targetLon);
  if (
    !Number.isFinite(targetLatitude) ||
    !Number.isFinite(targetLongitude) ||
    Math.abs(targetLatitude) > 90 ||
    Math.abs(targetLongitude) > 180
  ) {
    return;
  }

  const target = {
    latitude: targetLatitude,
    longitude: targetLongitude,
    name: element.dataset.targetName || "Localidad de referencia",
    country: element.dataset.targetCountry || ""
  };
  const matches = Array.from(
    document.querySelectorAll(".match-card[data-lat][data-lon]")
  ).map(function (card) {
    return {
      latitude: Number(card.dataset.lat),
      longitude: Number(card.dataset.lon),
      name: card.dataset.name || "Localidad",
      country: card.dataset.country || "",
      distance: card.dataset.distance || ""
    };
  }).filter(function (location) {
    return Number.isFinite(location.latitude) &&
      Number.isFinite(location.longitude) &&
      Math.abs(location.latitude) <= 90 &&
      Math.abs(location.longitude) <= 180;
  });

  const map = L.map(element, {
    center: [target.latitude, target.longitude],
    zoom: 2,
    minZoom: 2,
    maxZoom: 10,
    worldCopyJump: true
  });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);
  L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);

  const points = [target].concat(matches);
  const bounds = L.latLngBounds([]);
  points.forEach(function (location) {
    bounds.extend([location.latitude, location.longitude]);
  });

  matches.forEach(function (location) {
    L.polyline([
      [target.latitude, target.longitude],
      [location.latitude, location.longitude]
    ], {
      color: "#65d5f5",
      opacity: 0.48,
      weight: 1.5
    }).addTo(map);
  });

  function makePopup(location, isTarget) {
    const popup = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = location.name +
      (location.country ? ", " + location.country : "");
    popup.appendChild(name);

    const detail = document.createElement("p");
    detail.textContent = isTarget
      ? "Localidad de referencia"
      : "Distancia climática normalizada: " + location.distance;
    popup.appendChild(detail);
    return popup;
  }

  L.circleMarker([target.latitude, target.longitude], {
    radius: 9,
    color: "#fff2df",
    weight: 2,
    fillColor: "#ffaf70",
    fillOpacity: 1
  }).bindPopup(makePopup(target, true)).addTo(map);

  matches.forEach(function (location) {
    L.circleMarker([location.latitude, location.longitude], {
      radius: 6,
      color: "#e3fbff",
      weight: 1.5,
      fillColor: "#65d5f5",
      fillOpacity: 0.95
    }).bindPopup(makePopup(location, false)).addTo(map);
  });

  if (points.length > 1) {
    map.fitBounds(bounds, { padding: [32, 32], maxZoom: 4 });
  }
  window.setTimeout(function () {
    map.invalidateSize();
  }, 0);
}

initializeConnectionsMap();
