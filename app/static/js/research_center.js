(function () {
  const root = document.getElementById("research-center");
  if (!root) {
    return;
  }

  const messages = document.getElementById("research-messages");
  const form = document.getElementById("research-chat-form");
  const questionInput = document.getElementById("research-question");
  const sendButton = document.getElementById("research-send-button");
  const newButton = document.getElementById("research-new-button");
  const statusElement = document.getElementById("research-status");
  const saveForm = document.getElementById("research-save-form");
  const saveTitle = document.getElementById("research-save-title");
  const saveDescription = document.getElementById("research-save-description");
  const saveButton = document.getElementById("research-save-button");
  const saveStatus = document.getElementById("research-save-status");
  const historyList = document.getElementById("research-history-list");
  const csrfToken = document.getElementById("research-csrf-token").value;
  const colors = ["#68d2e8", "#a99bff", "#ffba76", "#81dfa9", "#ff8295"];

  let investigationId = null;
  let investigationStatus = "draft";
  let isBusy = false;

  function endpoint(template, id) {
    return template.replace(/0$/, encodeURIComponent(String(id)));
  }

  async function requestJson(url, options) {
    const response = await fetch(url, options);
    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      throw new Error("El servidor devolvió una respuesta inválida.");
    }

    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new Error("El servidor devolvió una respuesta inválida.");
    }

    if (!response.ok || payload.success === false) {
      throw new Error(
        payload.error || "No se pudo completar la solicitud."
      );
    }
    return payload;
  }

  function setStatus(message, isError) {
    statusElement.textContent = message || "";
    statusElement.classList.toggle("error", Boolean(isError));
  }

  function setBusy(busy) {
    isBusy = busy;
    sendButton.disabled = busy;
    questionInput.disabled = busy;
    newButton.disabled = busy;
    sendButton.textContent = busy ? "Procesando…" : "Investigar";
    root.classList.toggle("is-processing", busy);
  }

  function clearMessages() {
    messages.replaceChildren();
  }

  function createMessage(role, text) {
    const emptyState = messages.querySelector(".research-empty-state");
    if (emptyState) {
      emptyState.remove();
    }

    const message = document.createElement("article");
    message.className = `research-message research-message-${role}`;

    const label = document.createElement("div");
    label.className = "research-message-role";
    label.textContent = role === "user" ? "Tu consulta" : "ClimaIA";

    const content = document.createElement("div");
    content.className = "research-message-content";
    if (text) {
      content.textContent = text;
    }

    message.append(label, content);
    messages.append(message);
    messages.scrollTop = messages.scrollHeight;
    return { message, content };
  }

  function appendInline(parent, text) {
    const inlinePattern = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|`[^`]+`)/g;
    let currentIndex = 0;

    for (const match of text.matchAll(inlinePattern)) {
      const token = match[0];
      const start = match.index;
      parent.append(document.createTextNode(text.slice(currentIndex, start)));

      let element;
      if (token.startsWith("**") || token.startsWith("__")) {
        element = document.createElement("strong");
        element.textContent = token.slice(2, -2);
      } else if (token.startsWith("*")) {
        element = document.createElement("em");
        element.textContent = token.slice(1, -1);
      } else {
        element = document.createElement("code");
        element.textContent = token.slice(1, -1);
      }
      parent.append(element);
      currentIndex = start + token.length;
    }
    parent.append(document.createTextNode(text.slice(currentIndex)));
  }

  function parseTableRow(line) {
    return line.trim().replace(/^\||\|$/g, "").split("|").map(
      (cell) => cell.trim()
    );
  }

  function appendMarkdownTable(parent, lines) {
    const rows = lines.map(parseTableRow);
    if (rows.length < 2) {
      const paragraph = document.createElement("p");
      appendInline(paragraph, lines.join(" "));
      parent.append(paragraph);
      return;
    }

    const tableWrap = document.createElement("div");
    tableWrap.className = "research-table-wrap";
    const table = document.createElement("table");
    table.className = "research-table";
    const head = document.createElement("thead");
    const headerRow = document.createElement("tr");

    for (const cell of rows[0]) {
      const header = document.createElement("th");
      header.scope = "col";
      appendInline(header, cell);
      headerRow.append(header);
    }
    head.append(headerRow);
    table.append(head);

    const body = document.createElement("tbody");
    for (const row of rows.slice(1)) {
      if (row.every((cell) => /^:?-{3,}:?$/.test(cell))) {
        continue;
      }
      const tableRow = document.createElement("tr");
      for (let index = 0; index < rows[0].length; index += 1) {
        const cell = document.createElement("td");
        appendInline(cell, row[index] || "");
        tableRow.append(cell);
      }
      body.append(tableRow);
    }
    table.append(body);
    tableWrap.append(table);
    parent.append(tableWrap);
  }

  function appendMarkdown(parent, text) {
    const lines = String(text || "").split(/\r?\n/);
    let index = 0;

    while (index < lines.length) {
      const line = lines[index].trim();
      if (!line) {
        index += 1;
        continue;
      }

      if (/^\|.*\|$/.test(line)) {
        const tableLines = [];
        while (index < lines.length && /^\s*\|.*\|\s*$/.test(lines[index])) {
          tableLines.push(lines[index].trim());
          index += 1;
        }
        appendMarkdownTable(parent, tableLines);
        continue;
      }

      const heading = line.match(/^(#{1,4})\s+(.+)$/);
      if (heading) {
        const element = document.createElement(
          heading[1].length <= 2 ? "h3" : "h4"
        );
        appendInline(element, heading[2]);
        parent.append(element);
        index += 1;
        continue;
      }

      const unordered = line.match(/^[-*]\s+(.+)$/);
      const ordered = line.match(/^\d+[.)]\s+(.+)$/);
      if (unordered || ordered) {
        const list = document.createElement(unordered ? "ul" : "ol");
        while (index < lines.length) {
          const itemLine = lines[index].trim();
          const item = itemLine.match(
            unordered ? /^[-*]\s+(.+)$/ : /^\d+[.)]\s+(.+)$/
          );
          if (!item) {
            break;
          }
          const listItem = document.createElement("li");
          appendInline(listItem, item[1]);
          list.append(listItem);
          index += 1;
        }
        parent.append(list);
        continue;
      }

      const paragraphLines = [];
      while (index < lines.length && lines[index].trim()) {
        const candidate = lines[index].trim();
        if (
          /^\|.*\|$/.test(candidate)
          || /^(#{1,4})\s+/.test(candidate)
          || /^[-*]\s+/.test(candidate)
          || /^\d+[.)]\s+/.test(candidate)
        ) {
          break;
        }
        paragraphLines.push(candidate);
        index += 1;
      }

      if (paragraphLines.length) {
        const paragraph = document.createElement("p");
        appendInline(paragraph, paragraphLines.join(" "));
        parent.append(paragraph);
      } else {
        index += 1;
      }
    }
  }

  function svgElement(tag, attributes) {
    const element = document.createElementNS(
      "http://www.w3.org/2000/svg",
      tag
    );
    Object.entries(attributes || {}).forEach(([name, value]) => {
      element.setAttribute(name, String(value));
    });
    return element;
  }

  function appendChart(parent, chart) {
    if (
      !chart
      || !Array.isArray(chart.labels)
      || !Array.isArray(chart.datasets)
      || chart.labels.length === 0
    ) {
      return;
    }

    const prepared = chart.datasets
      .filter((dataset) => dataset && Array.isArray(dataset.data))
      .map((dataset) => ({
        label: String(dataset.label || "Serie"),
        unit: String(dataset.unit || ""),
        data: chart.labels.map((_, index) => {
          const value = dataset.data[index];
          return Number.isFinite(value) ? Number(value) : null;
        })
      }));
    const allValues = prepared.flatMap((dataset) =>
      dataset.data.filter(Number.isFinite)
    );
    if (!prepared.length || !allValues.length) {
      return;
    }

    const card = document.createElement("div");
    card.className = "research-chart";
    const heading = document.createElement("h5");
    heading.textContent = chart.title || "Visualización de datos";
    card.append(heading);

    const width = 760;
    const height = 250;
    const left = 54;
    const right = 18;
    const top = 14;
    const bottom = 42;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const isBar = chart.type === "bar";
    let minimum = Math.min(...allValues);
    let maximum = Math.max(...allValues);
    if (isBar) {
      minimum = Math.min(0, minimum);
      maximum = Math.max(0, maximum);
    }
    if (minimum === maximum) {
      const padding = Math.abs(minimum) * 0.1 || 1;
      minimum -= padding;
      maximum += padding;
    }
    const y = (value) => (
      top + (maximum - value) / (maximum - minimum) * plotHeight
    );
    const x = (index) => (
      left + (chart.labels.length === 1
        ? plotWidth / 2
        : index / (chart.labels.length - 1) * plotWidth)
    );

    const svg = svgElement("svg", {
      viewBox: `0 0 ${width} ${height}`,
      role: "img",
      "aria-label": chart.title || "Gráfico climático"
    });

    for (let tick = 0; tick <= 4; tick += 1) {
      const value = maximum - (maximum - minimum) * tick / 4;
      const yPosition = y(value);
      svg.append(svgElement("line", {
        x1: left,
        x2: width - right,
        y1: yPosition,
        y2: yPosition,
        stroke: "#253b55",
        "stroke-width": 1
      }));
      const tickLabel = svgElement("text", {
        x: left - 8,
        y: yPosition + 3,
        fill: "#8298b4",
        "font-size": 9,
        "text-anchor": "end"
      });
      tickLabel.textContent = new Intl.NumberFormat("es-AR", {
        maximumFractionDigits: 1
      }).format(value);
      svg.append(tickLabel);
    }

    const zeroY = y(0);
    if (minimum < 0 && maximum > 0) {
      svg.append(svgElement("line", {
        x1: left,
        x2: width - right,
        y1: zeroY,
        y2: zeroY,
        stroke: "#60768f",
        "stroke-width": 1.2
      }));
    }

    const labelStep = Math.max(1, Math.ceil(chart.labels.length / 9));
    chart.labels.forEach((label, index) => {
      if (index % labelStep !== 0 && index !== chart.labels.length - 1) {
        return;
      }
      const labelX = isBar
        ? left + (index + 0.5) * plotWidth / chart.labels.length
        : x(index);
      const labelElement = svgElement("text", {
        x: labelX,
        y: height - 15,
        fill: "#8298b4",
        "font-size": 9,
        "text-anchor": "middle"
      });
      const fullLabel = String(label);
      labelElement.textContent = fullLabel.length > 12
        ? `${fullLabel.slice(0, 11)}…`
        : fullLabel;
      const title = svgElement("title");
      title.textContent = fullLabel;
      labelElement.append(title);
      svg.append(labelElement);
    });

    if (isBar) {
      const groupWidth = plotWidth / chart.labels.length;
      const barWidth = Math.max(
        2,
        Math.min(30, groupWidth * 0.72 / prepared.length)
      );
      const baseline = y(0);
      prepared.forEach((dataset, datasetIndex) => {
        dataset.data.forEach((value, labelIndex) => {
          if (!Number.isFinite(value)) {
            return;
          }
          const center = left + (
            labelIndex + 0.5
          ) * groupWidth;
          const offset = (
            datasetIndex - (prepared.length - 1) / 2
          ) * barWidth;
          const valueY = y(value);
          const bar = svgElement("rect", {
            x: center + offset - barWidth * 0.42,
            y: Math.min(valueY, baseline),
            width: barWidth * 0.84,
            height: Math.max(1, Math.abs(baseline - valueY)),
            rx: 2,
            fill: colors[datasetIndex % colors.length],
            opacity: 0.86
          });
          const title = svgElement("title");
          title.textContent = `${dataset.label} · ${chart.labels[labelIndex]}: ${value} ${dataset.unit}`;
          bar.append(title);
          svg.append(bar);
        });
      });
    } else {
      prepared.forEach((dataset, datasetIndex) => {
        const color = colors[datasetIndex % colors.length];
        let segment = [];
        const drawSegment = () => {
          if (segment.length > 1) {
            const path = svgElement("polyline", {
              points: segment.map((point) => point.join(",")).join(" "),
              fill: "none",
              stroke: color,
              "stroke-width": 2.4,
              "stroke-linecap": "round",
              "stroke-linejoin": "round"
            });
            svg.append(path);
          }
          segment = [];
        };

        dataset.data.forEach((value, index) => {
          if (!Number.isFinite(value)) {
            drawSegment();
            return;
          }
          const point = [x(index), y(value)];
          segment.push(point);
          const circle = svgElement("circle", {
            cx: point[0],
            cy: point[1],
            r: dataset.data.length > 35 ? 2 : 3.2,
            fill: color,
            stroke: "#091425",
            "stroke-width": 1.4
          });
          const title = svgElement("title");
          title.textContent = `${dataset.label} · ${chart.labels[index]}: ${value} ${dataset.unit}`;
          circle.append(title);
          svg.append(circle);
        });
        drawSegment();
      });
    }

    card.append(svg);
    const legend = document.createElement("div");
    legend.className = "research-chart-legend";
    prepared.forEach((dataset, index) => {
      const item = document.createElement("span");
      item.className = "research-legend-item";
      const dot = document.createElement("span");
      dot.className = "research-legend-dot";
      dot.style.backgroundColor = colors[index % colors.length];
      const label = document.createElement("span");
      label.textContent = dataset.unit
        ? `${dataset.label} (${dataset.unit})`
        : dataset.label;
      item.append(dot, label);
      legend.append(item);
    });
    card.append(legend);
    parent.append(card);
  }

  function appendDataTable(parent, tableData) {
    if (
      !tableData
      || !Array.isArray(tableData.columns)
      || !Array.isArray(tableData.rows)
    ) {
      return;
    }

    const wrapper = document.createElement("div");
    wrapper.className = "research-table-wrap";
    const table = document.createElement("table");
    table.className = "research-table";
    const head = document.createElement("thead");
    const headerRow = document.createElement("tr");
    tableData.columns.forEach((column) => {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = String(column);
      headerRow.append(cell);
    });
    head.append(headerRow);
    table.append(head);

    const body = document.createElement("tbody");
    tableData.rows.slice(0, 100).forEach((row) => {
      const tableRow = document.createElement("tr");
      tableData.columns.forEach((_, index) => {
        const cell = document.createElement("td");
        const value = Array.isArray(row) ? row[index] : "";
        cell.textContent = value === null || value === undefined
          ? "—"
          : String(value);
        tableRow.append(cell);
      });
      body.append(tableRow);
    });
    table.append(body);
    wrapper.append(table);
    parent.append(wrapper);
  }

  function appendStats(parent, stats) {
    if (!stats || typeof stats !== "object" || Array.isArray(stats)) {
      return;
    }
    const entries = Object.entries(stats).filter(([, value]) => (
      value === null
      || ["string", "number", "boolean"].includes(typeof value)
    ));
    if (!entries.length) {
      return;
    }

    const grid = document.createElement("div");
    grid.className = "research-stat-grid";
    entries.slice(0, 8).forEach(([key, value]) => {
      const item = document.createElement("div");
      item.className = "research-stat-item";
      const label = document.createElement("span");
      label.textContent = key.replace(/_/g, " ");
      const metric = document.createElement("strong");
      metric.textContent = value === null ? "No disponible" : String(value);
      item.append(label, metric);
      grid.append(item);
    });
    parent.append(grid);
  }

  function appendResults(parent, results) {
    if (!Array.isArray(results)) {
      return;
    }

    results.forEach((result) => {
      if (!result || typeof result !== "object") {
        return;
      }
      const card = document.createElement("section");
      card.className = "research-result-card";

      const heading = document.createElement("h4");
      heading.textContent = result.title || "Resultado del análisis";
      card.append(heading);

      if (result.summary) {
        const summary = document.createElement("p");
        summary.className = "research-result-summary";
        summary.textContent = result.summary;
        card.append(summary);
      }
      if (result.period && typeof result.period === "object") {
        const periodText = Object.entries(result.period).map(
          ([key, value]) => {
            if (typeof value === "string") {
              return value;
            }
            if (
              value
              && typeof value === "object"
              && typeof value.start === "string"
              && typeof value.end === "string"
            ) {
              const label = key === "first"
                ? "Primer período"
                : key === "second"
                  ? "Segundo período"
                  : key;
              return `${label}: ${value.start} – ${value.end}`;
            }
            return "";
          }
        ).filter(Boolean).join(" · ");
        if (periodText) {
          const period = document.createElement("p");
          period.className = "research-result-summary";
          period.textContent = `Período: ${periodText}`;
          card.append(period);
        }
      }
      if (result.locations && Array.isArray(result.locations)) {
        const names = result.locations.map((location) => {
          if (!location || typeof location !== "object") {
            return "";
          }
          const name = location.name || "Localidad";
          return location.country_name
            ? `${name}, ${location.country_name}`
            : name;
        }).filter(Boolean);
        if (names.length) {
          const places = document.createElement("p");
          places.className = "research-result-summary";
          places.textContent = `Localidades: ${names.join(" · ")}`;
          card.append(places);
        }
      }
      if (result.source) {
        const source = document.createElement("p");
        source.className = "research-result-source";
        source.textContent = `Fuente: ${result.source}`;
        card.append(source);
      }
      if (result.warning) {
        const warning = document.createElement("p");
        warning.className = "research-result-warning";
        warning.textContent = result.warning;
        card.append(warning);
      }
      appendStats(card, result.trend);
      appendStats(card, result.statistics);
      appendStats(card, result.correlation);
      appendStats(card, result.coverage);
      if (result.patterns && Array.isArray(result.patterns)) {
        const patternList = document.createElement("ul");
        patternList.className = "research-pattern-list";
        result.patterns.forEach((pattern) => {
          if (!pattern || typeof pattern !== "object") {
            return;
          }
          const item = document.createElement("li");
          const details = Array.isArray(pattern.years)
            ? pattern.years.map((entry) => (
              typeof entry === "object" && entry
                ? Object.entries(entry).map(([key, value]) => (
                  `${key.replace(/_/g, " ")}: ${value}`
                )).join(", ")
                : String(entry)
            )).join(" · ")
            : "";
          item.textContent = details
            ? `${pattern.name || "Patrón"}: ${details}`
            : (pattern.name || "Patrón identificado");
          patternList.append(item);
        });
        if (patternList.childElementCount) {
          card.append(patternList);
        }
      }
      if (result.chart) {
        appendChart(card, result.chart);
      }
      if (Array.isArray(result.charts)) {
        result.charts.forEach((chart) => appendChart(card, chart));
      }
      if (result.table) {
        appendDataTable(card, result.table);
      }
      parent.append(card);
    });
  }

  function renderAssistant(content, answer, results) {
    content.replaceChildren();
    appendMarkdown(content, answer);
    appendResults(content, results);
    messages.scrollTop = messages.scrollHeight;
  }

  function showMessageError(content, error) {
    content.textContent = error || "No se pudo completar la investigación.";
    content.parentElement.classList.add("research-message-error");
  }

  function updateSaveForm(show, title) {
    if (!show) {
      saveForm.hidden = true;
      return;
    }
    if (!saveTitle.value.trim() && title) {
      saveTitle.value = title.slice(0, 180);
    }
    saveForm.hidden = false;
  }

  function historyItem(investigation) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "research-history-item";
    button.dataset.investigationId = investigation.id;

    const title = document.createElement("strong");
    title.textContent = investigation.title || "Investigación sin título";
    const meta = document.createElement("span");
    meta.className = "research-history-meta";
    const date = document.createElement("small");
    const parsedDate = new Date(investigation.updated_at);
    date.textContent = Number.isNaN(parsedDate.getTime())
      ? ""
      : parsedDate.toLocaleDateString("es-AR");
    const state = document.createElement("small");
    state.className = `research-history-status ${investigation.status}`;
    state.textContent = investigation.status === "saved"
      ? "Guardada"
      : "Borrador";
    meta.append(date, state);
    button.append(title, meta);
    return button;
  }

  async function refreshHistory() {
    const data = await requestJson(root.dataset.historyUrl);
    const investigations = data.investigations || [];
    historyList.replaceChildren();
    if (!investigations.length) {
      const empty = document.createElement("p");
      empty.className = "research-muted";
      empty.id = "research-history-empty";
      empty.textContent = "Tus investigaciones van a aparecer acá.";
      historyList.append(empty);
    } else {
      investigations.forEach((investigation) => {
        historyList.append(historyItem(investigation));
      });
    }

    const saved = investigations.filter((item) => item.status === "saved");
    document.getElementById("research-saved-count").textContent = (
      Number.isFinite(data.saved_count) ? data.saved_count : saved.length
    );
    const uniqueLocations = new Set(
      saved.flatMap((item) => (item.locations || []).map(
        (location) => String(location.geoname_id || location.name || "")
      ))
    );
    document.getElementById("research-locality-count").textContent = (
      uniqueLocations.size
    );

    const current = investigations.find(
      (item) => Number(item.id) === Number(investigationId)
    );
    if (current) {
      investigationStatus = current.status;
      if (current.status === "saved") {
        updateSaveForm(false);
      }
    }
  }

  function wait(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  async function pollJob(jobId, investigationKey, content) {
    let attempts = 0;
    let consecutiveFailures = 0;
    const maximumAttempts = 240;

    while (attempts < maximumAttempts) {
      await wait(1500);
      attempts += 1;

      let data;
      try {
        data = await requestJson(endpoint(root.dataset.jobUrlTemplate, jobId));
        consecutiveFailures = 0;
      } catch (error) {
        consecutiveFailures += 1;
        if (consecutiveFailures >= 4) {
          throw error;
        }
        setStatus("Reintentando conexión con la investigación…");
        continue;
      }

      const job = data.job;
      if (job.status === "completed") {
        renderAssistant(content, job.answer, job.results);
        setStatus("Investigación completada.");
        try {
          await refreshHistory();
        } catch (error) {
          setStatus("Resultado completado; no se pudo actualizar el historial.");
        }
        return;
      }
      if (job.status === "error") {
        showMessageError(content, job.error);
        setStatus("La investigación no pudo completarse.", true);
        return;
      }
      if (Number(investigationId) === Number(investigationKey)) {
        setStatus(
          job.status === "queued"
            ? "Esperando turno para investigar…"
            : "Consultando registros y preparando resultados…"
        );
      }
    }

    throw new Error(
      "La investigación sigue en proceso. Podés volver a abrirla desde el historial."
    );
  }

  async function startQuestion(question) {
    const cleanQuestion = String(question || "").trim();
    if (!cleanQuestion || isBusy) {
      return;
    }

    setBusy(true);
    setStatus("Iniciando investigación…");
    updateSaveForm(false);
    const { content } = createMessage("user", cleanQuestion);
    const pending = createMessage(
      "assistant",
      "La investigación está en cola. Voy a consultar los datos climáticos disponibles."
    );
    pending.message.classList.add("research-message-processing");

    try {
      const payload = {
        question: cleanQuestion,
        investigation_id: investigationId
      };
      const response = await requestJson(root.dataset.messageUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken
        },
        body: JSON.stringify(payload)
      });
      investigationId = response.investigation_id;
      investigationStatus = response.status === "saved" ? "saved" : "draft";
      try {
        await refreshHistory();
      } catch (error) {
        setStatus("La consulta empezó, pero no se pudo actualizar el historial.");
      }
      await pollJob(response.job_id, investigationId, pending.content);
      const completed = !pending.message.classList.contains(
        "research-message-error"
      );
      if (completed && investigationStatus !== "saved") {
        updateSaveForm(true, cleanQuestion);
      }
    } catch (error) {
      showMessageError(pending.content, error.message);
      setStatus(error.message, true);
    } finally {
      pending.message.classList.remove("research-message-processing");
      setBusy(false);
    }
  }

  async function openInvestigation(id) {
    if (isBusy) {
      setStatus("Esperá a que termine la consulta actual antes de cambiar de investigación.", true);
      return;
    }

    setStatus("Cargando investigación…");
    try {
      const data = await requestJson(
        endpoint(root.dataset.sessionUrlTemplate, id)
      );
      investigationId = data.investigation.id;
      investigationStatus = data.investigation.status;
      clearMessages();
      const reports = data.messages || [];
      let activeJob = null;
      let latestQuestion = "";
      let latestCompletedQuestion = "";
      let hasCompleted = false;

      reports.forEach((report) => {
        if (!report.question) {
          return;
        }
        latestQuestion = report.question;
        createMessage("user", report.question);
        const response = createMessage("assistant", "");
        if (report.status === "completed") {
          renderAssistant(response.content, report.answer, report.results);
          hasCompleted = true;
          latestCompletedQuestion = report.question;
        } else if (report.status === "error") {
          showMessageError(response.content, report.error);
        } else {
          response.message.classList.add("research-message-processing");
          response.content.textContent = "La investigación sigue en proceso…";
          activeJob = {
            id: report.id,
            content: response.content
          };
        }
      });

      if (!reports.length) {
        const empty = document.createElement("div");
        empty.className = "research-empty-state";
        const title = document.createElement("h3");
        title.textContent = "Borrador sin consultas";
        const text = document.createElement("p");
        text.textContent = "Escribí una pregunta para continuar esta investigación.";
        empty.append(title, text);
        messages.append(empty);
      }

      questionInput.value = "";
      updateSaveForm(
        hasCompleted && investigationStatus !== "saved",
        latestCompletedQuestion || latestQuestion
      );
      if (activeJob) {
        setBusy(true);
        setStatus("Retomando la consulta pendiente…");
        try {
          await pollJob(activeJob.id, investigationId, activeJob.content);
          if (investigationStatus !== "saved") {
            updateSaveForm(true, latestQuestion);
          }
        } catch (error) {
          showMessageError(activeJob.content, error.message);
          setStatus(error.message, true);
        } finally {
          activeJob.content.parentElement.classList.remove(
            "research-message-processing"
          );
          setBusy(false);
        }
      } else {
        setStatus("");
      }
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = questionInput.value;
    questionInput.value = "";
    startQuestion(question);
  });

  document.querySelectorAll("[data-research-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      questionInput.value = button.dataset.researchPrompt || "";
      questionInput.focus();
    });
  });

  newButton.addEventListener("click", () => {
    if (isBusy) {
      return;
    }
    investigationId = null;
    investigationStatus = "draft";
    clearMessages();
    const empty = document.createElement("div");
    empty.className = "research-empty-state";
    const title = document.createElement("h3");
    title.textContent = "Investigá con evidencia";
    const text = document.createElement("p");
    text.textContent = "Preguntá por localidades, variables y períodos. Cada cifra y gráfico se construye con resultados de herramientas de ClimaIA.";
    empty.append(title, text);
    messages.append(empty);
    questionInput.value = "";
    updateSaveForm(false);
    setStatus("");
    questionInput.focus();
  });

  historyList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-investigation-id]");
    if (button) {
      openInvestigation(button.dataset.investigationId);
    }
  });

  saveForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!investigationId || saveButton.disabled) {
      return;
    }
    saveButton.disabled = true;
    saveStatus.textContent = "Guardando…";
    try {
      const data = await requestJson(
        endpoint(root.dataset.saveUrlTemplate, investigationId),
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken
          },
          body: JSON.stringify({
            title: saveTitle.value,
            description: saveDescription.value
          })
        }
      );
      investigationStatus = data.investigation.status;
      saveStatus.textContent = "Investigación guardada.";
      setStatus("La investigación quedó guardada en tu historial.");
      updateSaveForm(false);
      try {
        await refreshHistory();
      } catch (error) {
        setStatus("Guardado correctamente; no se pudo actualizar el historial.");
      }
    } catch (error) {
      saveStatus.textContent = error.message;
      setStatus(error.message, true);
    } finally {
      saveButton.disabled = false;
    }
  });

})();
