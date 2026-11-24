const form = document.querySelector("[data-probability-form]");

if (form) {
  const fields = [...form.querySelectorAll("[data-saved-value]")];
  const saveButton = form.querySelector("[data-save-probabilities]");
  const picker = document.querySelector("[data-entry-picker]");
  const row = picker.elements.voce;
  const currentRow = [...row.options].find(option => option.defaultSelected).value;
  let unsaved = false;
  let leaving = false;

  function probabilityValue(raw) {
    const value = raw.trim();
    if (!/^[0-9]+(?:[,.][0-9]+)?$/.test(value)) return value;
    const [integer, fraction = ""] = value.split(/[,.]/);
    const whole = integer.replace(/^0+(?=[0-9])/, "");
    const decimal = fraction.replace(/0+$/, "");
    return decimal ? whole + "." + decimal : whole;
  }

  function updateSaveButton() {
    unsaved = fields.some(field => probabilityValue(field.value) !== probabilityValue(field.dataset.savedValue));
    saveButton.disabled = !unsaved;
  }

  form.addEventListener("input", updateSaveButton);
  form.addEventListener("change", updateSaveButton);
  form.addEventListener("submit", (event) => {
    updateSaveButton();
    if (unsaved) leaving = true;
    else event.preventDefault();
  });
  row.addEventListener("change", () => {
    if (unsaved && !window.confirm("Cambiare voce senza salvare le modifiche?")) {
      row.value = currentRow;
      return;
    }
    leaving = true;
    picker.requestSubmit();
  });
  window.addEventListener("pageshow", () => {
    leaving = false;
    row.value = currentRow;
    updateSaveButton();
  });
  window.addEventListener("beforeunload", (event) => {
    if (unsaved && !leaving) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  updateSaveButton();
}

const matrix = document.querySelector("[data-matrix]");

if (matrix) {
  const controls = matrix.querySelector("[data-controls]");
  const table = matrix.querySelector("[data-table]");
  const viewport = matrix.querySelector("[data-viewport]");
  const empty = matrix.querySelector("[data-no-columns]");
  const kind = matrix.querySelector("[data-kind]");
  const positive = matrix.querySelector("input[data-positive]");
  const metric = matrix.querySelector("[data-metric-select]");
  const orientation = matrix.querySelector("[data-orientation]");
  const zoom = matrix.querySelector("[data-zoom]");
  const zoomLabel = matrix.querySelector("[data-zoom-label]");
  const columns = new Map();

  for (const cell of table.querySelectorAll("[data-col]")) {
    const id = cell.dataset.col;
    if (!columns.has(id)) columns.set(id, []);
    columns.get(id).push(cell);
  }

  function filter() {
    let visible = 0;
    for (const cells of columns.values()) {
      const header = cells[0];
      const show = (!kind.value || header.dataset.kind === kind.value) &&
        (!positive.checked || header.dataset.positive === "1");
      for (const cell of cells) cell.hidden = !show;
      if (show) visible += 1;
    }
    empty.hidden = visible > 0;
    viewport.hidden = visible === 0;
  }

  kind.addEventListener("change", filter);
  positive.addEventListener("change", filter);
  orientation.addEventListener("change", () => {
    table.classList.toggle("vertical", orientation.value === "vertical");
  });
  zoom.addEventListener("input", () => {
    table.style.zoom = Number(zoom.value) / 100;
    zoomLabel.value = zoom.value + "%";
  });
  metric.addEventListener("change", () => {
    const risk = metric.value === "r";
    matrix.dataset.metric = metric.value;
    for (const value of table.querySelectorAll("[data-risk]")) value.hidden = !risk;
    for (const value of table.querySelectorAll("[data-probability]")) value.hidden = risk;
    matrix.querySelector("[data-legend]").hidden = !risk;
    table.setAttribute("aria-label", risk ? "Matrice dei rischi" : "Matrice delle probabilità");
  });
  controls.hidden = false;
  filter();

  const fullscreen = matrix.querySelector("[data-fullscreen]");
  if (document.fullscreenEnabled && matrix.requestFullscreen) {
    fullscreen.hidden = false;
    fullscreen.addEventListener("click", async () => {
      try {
        if (document.fullscreenElement === matrix) {
          await document.exitFullscreen();
        } else {
          await matrix.requestFullscreen();
        }
      } catch {
        // Keep ordinary scrolling available if fullscreen is blocked by the browser.
      }
    });
    document.addEventListener("fullscreenchange", () => {
      fullscreen.textContent = document.fullscreenElement === matrix ? "Esci da schermo intero" : "Schermo intero";
    });
  }

  let drag;
  viewport.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.pointerType !== "mouse" || event.target === viewport) return;
    drag = {
      pointer: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      left: viewport.scrollLeft,
      top: viewport.scrollTop,
    };
    viewport.setPointerCapture(event.pointerId);
  });
  viewport.addEventListener("pointermove", (event) => {
    if (!drag || drag.pointer !== event.pointerId) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (!viewport.classList.contains("dragging") && Math.hypot(dx, dy) < 5) return;
    viewport.classList.add("dragging");
    viewport.scrollLeft = drag.left - dx;
    viewport.scrollTop = drag.top - dy;
  });
  for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) {
    viewport.addEventListener(event, () => {
      drag = undefined;
      viewport.classList.remove("dragging");
    });
  }
}
