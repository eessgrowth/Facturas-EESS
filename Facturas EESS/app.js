/* global INVOICE_DATA */

const data = window.INVOICE_DATA || { invoices: [], brands: [], platforms: [] };

const state = {
  platform: [],
  month: [],
  brand: [],
};

const FILTERS = {
  platform: { rootId: "platform-filter", allLabel: "Todos los proveedores" },
  month: { rootId: "month-filter", allLabel: "Todos los meses" },
  brand: { rootId: "brand-filter", allLabel: "Todas las marcas" },
};

const filterUis = {};
const filterOptions = { platform: [], month: [], brand: [] };
const kpiTotal = document.getElementById("kpi-total");
const kpiMeta = document.getElementById("kpi-meta");
const kpiGoogle = document.getElementById("kpi-google");
const kpiZeppelin = document.getElementById("kpi-zeppelin");
const invoiceList = document.getElementById("invoices-list");
const resultsCount = document.getElementById("results-count");

const clpFormatter = new Intl.NumberFormat("es-CL", {
  style: "currency",
  currency: "CLP",
  maximumFractionDigits: 0,
});

const monthFormatter = new Intl.DateTimeFormat("es-CL", {
  month: "long",
  year: "numeric",
});

const dateFormatter = new Intl.DateTimeFormat("es-CL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

function esc(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatCLP(value) {
  return clpFormatter.format(value || 0);
}

function toMonthLabel(monthKey) {
  const isoDate = `${monthKey}-01`;
  return monthFormatter.format(new Date(`${isoDate}T00:00:00`));
}

function formatDate(isoDate) {
  if (!isoDate) return "-";
  return dateFormatter.format(new Date(`${isoDate}T00:00:00`));
}

function platformClass(platform) {
  if (platform === "Meta") return "platform-meta";
  if (platform === "Google Ads") return "platform-google";
  return "platform-zeppelin";
}

function fileButton(invoice) {
  const filePath = invoice.documentFile || invoice.pdfFile || "";
  if (!filePath) return "";

  const lower = filePath.toLowerCase();
  const label = lower.endsWith(".xlsx") ? "Descargar Excel" : "Descargar PDF";
  return `<a class="btn" href="${esc(encodeURI(filePath))}" download>${label}</a>`;
}

function closeAllFilters(exceptKey = null) {
  Object.entries(filterUis).forEach(([key, ui]) => {
    const shouldClose = key !== exceptKey;
    if (shouldClose) {
      ui.root.classList.remove("open");
      ui.button.setAttribute("aria-expanded", "false");
    }
  });
}

function updateFilterButtonLabel(filterKey) {
  const selected = state[filterKey];
  const ui = filterUis[filterKey];
  const def = FILTERS[filterKey];
  const labels = new Map(filterOptions[filterKey].map((opt) => [opt.value, opt.label]));

  if (!selected.length) {
    ui.label.textContent = def.allLabel;
    return;
  }

  if (selected.length === 1) {
    ui.label.textContent = labels.get(selected[0]) || selected[0];
    return;
  }

  ui.label.textContent = `${selected.length} seleccionados`;
}

function syncStateFromFilter(filterKey) {
  const ui = filterUis[filterKey];
  state[filterKey] = Array.from(ui.menu.querySelectorAll('input[type="checkbox"]:checked')).map(
    (input) => input.value
  );
}

function buildFilterDropdown(filterKey) {
  const def = FILTERS[filterKey];
  const root = document.getElementById(def.rootId);

  root.innerHTML = "";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "multiselect-btn";
  button.setAttribute("aria-haspopup", "listbox");
  button.setAttribute("aria-expanded", "false");

  const label = document.createElement("span");
  label.className = "multiselect-label";
  const caret = document.createElement("span");
  caret.className = "multiselect-caret";
  caret.textContent = "▾";

  button.append(label, caret);

  const menu = document.createElement("div");
  menu.className = "multiselect-menu";
  menu.setAttribute("role", "listbox");
  menu.setAttribute("aria-multiselectable", "true");

  filterOptions[filterKey].forEach((opt) => {
    const option = document.createElement("label");
    option.className = "multiselect-option";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = opt.value;
    input.checked = state[filterKey].includes(opt.value);
    input.addEventListener("change", () => {
      syncStateFromFilter(filterKey);
      updateFilterButtonLabel(filterKey);
      render();
    });

    const text = document.createElement("span");
    text.textContent = opt.label;

    option.append(input, text);
    menu.append(option);
  });

  button.addEventListener("click", () => {
    const isOpen = root.classList.contains("open");
    closeAllFilters(filterKey);
    if (!isOpen) {
      root.classList.add("open");
      button.setAttribute("aria-expanded", "true");
    } else {
      root.classList.remove("open");
      button.setAttribute("aria-expanded", "false");
    }
  });

  root.append(button, menu);
  filterUis[filterKey] = { root, button, label, menu };
  updateFilterButtonLabel(filterKey);
}

function buildFilters() {
  filterOptions.platform = data.platforms.map((platform) => ({ value: platform, label: platform }));
  filterOptions.month = Array.from(new Set(data.invoices.map((item) => item.month)))
    .sort()
    .map((month) => ({ value: month, label: toMonthLabel(month) }));
  filterOptions.brand = data.brands.map((brand) => ({ value: brand, label: brand }));

  buildFilterDropdown("platform");
  buildFilterDropdown("month");
  buildFilterDropdown("brand");
}

function getFilteredInvoices() {
  return data.invoices.filter((invoice) => {
    const platformMatch = !state.platform.length || state.platform.includes(invoice.platform);
    const monthMatch = !state.month.length || state.month.includes(invoice.month);
    const brandMatch = !state.brand.length || state.brand.includes(invoice.brand);
    return platformMatch && monthMatch && brandMatch;
  });
}

function renderKpis(filteredInvoices) {
  const totalMeta = filteredInvoices
    .filter((item) => item.platform === "Meta")
    .reduce((sum, item) => sum + item.totalAmount, 0);
  const totalGoogle = filteredInvoices
    .filter((item) => item.platform === "Google Ads")
    .reduce((sum, item) => sum + item.totalAmount, 0);
  const totalZeppelin = filteredInvoices
    .filter((item) => item.platform === "Agencia Zeppelin")
    .reduce((sum, item) => sum + item.totalAmount, 0);
  const consolidatedTotal = totalMeta + totalGoogle + totalZeppelin;

  kpiTotal.textContent = formatCLP(consolidatedTotal);
  kpiMeta.textContent = formatCLP(totalMeta);
  kpiGoogle.textContent = formatCLP(totalGoogle);
  if (kpiZeppelin) kpiZeppelin.textContent = formatCLP(totalZeppelin);
}

function googleDetailsTable(invoice) {
  const rows = invoice.details
    .map(
      (row) => `
      <tr>
        <td>${esc(row.description)}</td>
        <td>${row.quantity ?? "-"}</td>
        <td>${row.unit ? esc(row.unit) : "-"}</td>
        <td class="amount">${formatCLP(row.amount)}</td>
      </tr>`
    )
    .join("");

  return `
    <details class="details">
      <summary>Detalle de cargos (${invoice.details.length} líneas)</summary>
      <div>
        <table>
          <thead>
            <tr>
              <th>Descripción</th>
              <th>Cantidad</th>
              <th>Unidad</th>
              <th class="amount">Monto</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </details>
  `;
}

function metaDetailsTable(invoice) {
  const rows = invoice.details
    .map(
      (row) => `
      <tr>
        <td>${formatDate(row.date)}</td>
        <td>${esc(row.transactionId)}</td>
        <td>${esc(row.paymentMethod)}</td>
        <td>${esc(row.status)}</td>
        <td class="amount">${formatCLP(row.amount)}</td>
      </tr>`
    )
    .join("");

  return `
    <details class="details">
      <summary>Detalle de transacciones (${invoice.details.length} líneas)</summary>
      <div>
        <table>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>ID transacción</th>
              <th>Método de pago</th>
              <th>Estado</th>
              <th class="amount">Monto</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </details>
  `;
}

function zeppelinDetailsTable(invoice) {
  const rows = invoice.details
    .map(
      (row) => `
      <tr>
        <td>${esc(row.concept || "-")}</td>
        <td>${esc(row.purchaseOrder || "-")}</td>
        <td>${esc(row.supplierInvoice || "-")}</td>
        <td class="amount">${formatCLP(row.amount)}</td>
      </tr>`
    )
    .join("");

  return `
    <details class="details">
      <summary>Detalle de pago proveedor (${invoice.details.length} línea${invoice.details.length === 1 ? "" : "s"})</summary>
      <div>
        <table>
          <thead>
            <tr>
              <th>Concepto</th>
              <th>N° OC</th>
              <th>N° Factura</th>
              <th class="amount">Inversión</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </details>
  `;
}

function renderInvoices(filteredInvoices) {
  resultsCount.textContent = `${filteredInvoices.length} factura${filteredInvoices.length === 1 ? "" : "s"}`;

  if (!filteredInvoices.length) {
    invoiceList.innerHTML = '<p class="empty">No hay facturas para los filtros seleccionados.</p>';
    return;
  }

  const sorted = [...filteredInvoices].sort((a, b) => {
    if (a.invoiceDate > b.invoiceDate) return -1;
    if (a.invoiceDate < b.invoiceDate) return 1;
    return b.totalAmount - a.totalAmount;
  });

  invoiceList.innerHTML = sorted
    .map((invoice) => {
      const summary = invoice.summaryBreakdown
        .map(
          (item) => `
          <div class="summary-item">
            <p>${esc(item.label)}</p>
            <strong>${formatCLP(item.amount)}</strong>
          </div>`
        )
        .join("");

      let detailBlock = metaDetailsTable(invoice);
      if (invoice.platform === "Google Ads") detailBlock = googleDetailsTable(invoice);
      if (invoice.platform === "Agencia Zeppelin") detailBlock = zeppelinDetailsTable(invoice);

      const notes = (invoice.notes || [])
        .map((note) => `<p class="note">${esc(note)}</p>`)
        .join("");

      return `
        <article class="invoice">
          <div class="invoice-head">
            <div>
              <div class="chip-row">
                <span class="chip ${platformClass(invoice.platform)}">${esc(invoice.platform)}</span>
                <span class="chip">${esc(invoice.brand)}</span>
                <span class="chip">${toMonthLabel(invoice.month)}</span>
              </div>
              <h4>${esc(invoice.id)}</h4>
              <div class="invoice-meta">
                <span>Fecha: ${formatDate(invoice.invoiceDate)}</span>
                <span>Periodo: ${formatDate(invoice.periodStart)} - ${formatDate(invoice.periodEnd)}</span>
                <span>Cuenta: ${esc(invoice.accountId || "-")}</span>
              </div>
            </div>
            <div>
              <p><strong>${formatCLP(invoice.totalAmount)}</strong></p>
              ${fileButton(invoice)}
            </div>
          </div>
          <div class="invoice-body">
            <div class="summary">${summary}</div>
            ${detailBlock}
            ${notes}
          </div>
        </article>
      `;
    })
    .join("");
}

function render() {
  const filtered = getFilteredInvoices();
  renderKpis(filtered);
  renderInvoices(filtered);
}

function attachEvents() {
  document.addEventListener("click", (event) => {
    const clickedInsideAnyFilter = Object.values(filterUis).some((ui) => ui.root.contains(event.target));
    if (!clickedInsideAnyFilter) closeAllFilters();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAllFilters();
  });
}

buildFilters();
attachEvents();
render();
