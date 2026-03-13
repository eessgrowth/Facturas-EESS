/* global INVOICE_DATA */

const data = window.INVOICE_DATA || { invoices: [] };

const state = {
  platform: "",
  brand: "",
  month: "",
  search: "",
};

const controls = {
  platform: document.getElementById("campaign-platform-filter"),
  brand: document.getElementById("campaign-brand-filter"),
  month: document.getElementById("campaign-month-filter"),
  search: document.getElementById("campaign-search"),
  clear: document.getElementById("campaign-clear-filters"),
};

const kpiTotal = document.getElementById("campaign-kpi-total");
const kpiUnique = document.getElementById("campaign-kpi-unique");
const kpiLines = document.getElementById("campaign-kpi-lines");
const campaignResultsCount = document.getElementById("campaign-results-count");
const campaignLinesCount = document.getElementById("campaign-lines-count");
const campaignBars = document.getElementById("campaign-bars");
const campaignTableBody = document.getElementById("campaign-table-body");

const clpFormatter = new Intl.NumberFormat("es-CL", {
  style: "currency",
  currency: "CLP",
  maximumFractionDigits: 0,
});

const monthFormatter = new Intl.DateTimeFormat("es-CL", {
  month: "long",
  year: "numeric",
});

function normalizeText(value) {
  return String(value ?? "").trim();
}

function getMonthKey(value) {
  const raw = normalizeText(value);
  const monthMatch = raw.match(/^(\d{4})-(\d{2})$/);
  if (monthMatch) {
    const [, year, month] = monthMatch;
    if (Number(month) >= 1 && Number(month) <= 12) return `${year}-${month}`;
  }

  const dateMatch = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateMatch) {
    const [, year, month] = dateMatch;
    if (Number(month) >= 1 && Number(month) <= 12) return `${year}-${month}`;
  }

  return "";
}

function getInvoiceMonthKey(invoice) {
  return (
    getMonthKey(invoice?.month) ||
    getMonthKey(invoice?.periodStart) ||
    getMonthKey(invoice?.invoiceDate) ||
    ""
  );
}

function toMonthLabel(monthKey) {
  const normalized = getMonthKey(monthKey);
  if (!normalized) return "-";
  const [year, month] = normalized.split("-").map(Number);
  const date = new Date(year, month - 1, 1);
  return monthFormatter.format(date);
}

function formatCLP(value) {
  return clpFormatter.format(value || 0);
}

function toSortedUnique(values) {
  return Array.from(new Set(values.map(normalizeText).filter(Boolean))).sort((a, b) => a.localeCompare(b, "es"));
}

function esc(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function extractCampaignRows() {
  const invoices = Array.isArray(data.invoices) ? data.invoices : [];
  const rows = [];

  invoices.forEach((invoice) => {
    const details = Array.isArray(invoice.details) ? invoice.details : [];
    const monthKey = getInvoiceMonthKey(invoice);
    details.forEach((detail) => {
      const campaignName = normalizeText(detail?.description);
      const amount = Number(detail?.amount || 0);
      if (!campaignName || !Number.isFinite(amount)) return;

      rows.push({
        campaignName,
        amount,
        platform: normalizeText(invoice.platform) || "-",
        brand: normalizeText(invoice.brand) || "-",
        monthKey,
      });
    });
  });

  return rows;
}

const allRows = extractCampaignRows();

function fillSelect(select, options, allLabel) {
  if (!select) return;
  select.innerHTML = "";

  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = allLabel;
  select.append(allOption);

  options.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value.startsWith("20") ? toMonthLabel(value) : value;
    select.append(option);
  });
}

function buildFilterOptions() {
  fillSelect(controls.platform, toSortedUnique(allRows.map((row) => row.platform)), "Todos los proveedores");
  fillSelect(controls.brand, toSortedUnique(allRows.map((row) => row.brand)), "Todas las marcas");
  fillSelect(
    controls.month,
    toSortedUnique(allRows.map((row) => row.monthKey)).sort((a, b) => b.localeCompare(a)),
    "Todos los meses"
  );
}

function getFilteredRows() {
  const search = normalizeText(state.search).toLocaleLowerCase("es");
  return allRows.filter((row) => {
    if (state.platform && row.platform !== state.platform) return false;
    if (state.brand && row.brand !== state.brand) return false;
    if (state.month && row.monthKey !== state.month) return false;
    if (search && !row.campaignName.toLocaleLowerCase("es").includes(search)) return false;
    return true;
  });
}

function buildCampaignSummary(rows) {
  const campaignMap = new Map();

  rows.forEach((row) => {
    const current = campaignMap.get(row.campaignName) || {
      campaignName: row.campaignName,
      totalAmount: 0,
      lines: 0,
    };
    current.totalAmount += row.amount;
    current.lines += 1;
    campaignMap.set(row.campaignName, current);
  });

  return Array.from(campaignMap.values()).sort((a, b) => b.totalAmount - a.totalAmount);
}

function renderKpis(rows, campaigns) {
  const total = rows.reduce((sum, row) => sum + row.amount, 0);
  kpiTotal.textContent = formatCLP(total);
  kpiUnique.textContent = String(campaigns.length);
  kpiLines.textContent = String(rows.length);
}

function renderBars(campaigns) {
  if (!campaigns.length) {
    campaignBars.innerHTML = '<p class="empty">No hay campañas para los filtros seleccionados.</p>';
    return;
  }

  const maxAmount = campaigns[0].totalAmount || 1;
  const topCampaigns = campaigns.slice(0, 25);
  campaignBars.innerHTML = topCampaigns
    .map((campaign) => {
      const width = Math.max(2, Math.round((campaign.totalAmount / maxAmount) * 100));
      return `
        <article class="campaign-bar-item">
          <div class="campaign-bar-head">
            <p title="${esc(campaign.campaignName)}">${esc(campaign.campaignName)}</p>
            <strong>${formatCLP(campaign.totalAmount)}</strong>
          </div>
          <div class="campaign-bar-track">
            <span style="width: ${width}%"></span>
          </div>
          <small>${campaign.lines} línea${campaign.lines === 1 ? "" : "s"}</small>
        </article>
      `;
    })
    .join("");
}

function renderTable(rows) {
  campaignLinesCount.textContent = `${rows.length} línea${rows.length === 1 ? "" : "s"}`;
  if (!rows.length) {
    campaignTableBody.innerHTML = "";
    return;
  }

  const sortedRows = [...rows].sort((a, b) => b.amount - a.amount);
  campaignTableBody.innerHTML = sortedRows
    .map(
      (row, index) => `
      <tr>
        <td>${index + 1}</td>
        <td>${esc(row.campaignName)}</td>
        <td>${esc(row.platform)}</td>
        <td>${esc(row.brand)}</td>
        <td>${esc(toMonthLabel(row.monthKey))}</td>
        <td class="amount">${formatCLP(row.amount)}</td>
      </tr>`
    )
    .join("");
}

function render() {
  const filteredRows = getFilteredRows();
  const campaigns = buildCampaignSummary(filteredRows);

  campaignResultsCount.textContent = `${campaigns.length} campaña${campaigns.length === 1 ? "" : "s"}`;
  renderKpis(filteredRows, campaigns);
  renderBars(campaigns);
  renderTable(filteredRows);
}

function attachEvents() {
  controls.platform?.addEventListener("change", (event) => {
    state.platform = event.target.value;
    render();
  });

  controls.brand?.addEventListener("change", (event) => {
    state.brand = event.target.value;
    render();
  });

  controls.month?.addEventListener("change", (event) => {
    state.month = event.target.value;
    render();
  });

  controls.search?.addEventListener("input", (event) => {
    state.search = event.target.value;
    render();
  });

  controls.clear?.addEventListener("click", () => {
    state.platform = "";
    state.brand = "";
    state.month = "";
    state.search = "";

    if (controls.platform) controls.platform.value = "";
    if (controls.brand) controls.brand.value = "";
    if (controls.month) controls.month.value = "";
    if (controls.search) controls.search.value = "";
    render();
  });
}

buildFilterOptions();
attachEvents();
render();
