/* global INVOICE_DATA */

const data = window.INVOICE_DATA || { reasonSocialRows: [] };

const state = {
  platform: "",
  brand: "",
  month: "",
  year: "",
  legalEntity: "",
  search: "",
};

const controls = {
  platform: document.getElementById("rsd-platform-filter"),
  brand: document.getElementById("rsd-brand-filter"),
  month: document.getElementById("rsd-month-filter"),
  year: document.getElementById("rsd-year-filter"),
  legalEntity: document.getElementById("rsd-legal-filter"),
  search: document.getElementById("rsd-search"),
  clear: document.getElementById("rsd-clear-filters"),
};

const kpiTotal = document.getElementById("rsd-kpi-total");
const kpiRows = document.getElementById("rsd-kpi-rows");
const kpiCampaigns = document.getElementById("rsd-kpi-campaigns");
const resultsCount = document.getElementById("rsd-results-count");
const tableBody = document.getElementById("rsd-table-body");
const exportXlsxBtn = document.getElementById("rsd-export-xlsx");
const exportPdfBtn = document.getElementById("rsd-export-pdf");
let currentFilteredRows = [];
const expandedRowIds = new Set();

const clpFormatter = new Intl.NumberFormat("es-CL", {
  style: "currency",
  currency: "CLP",
  maximumFractionDigits: 0,
});

const usdFormatter = new Intl.NumberFormat("es-CL", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const monthFormatter = new Intl.DateTimeFormat("es-CL", {
  month: "long",
  year: "numeric",
});

function normalizeText(value) {
  return String(value ?? "").trim();
}

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

function toOptionalNumber(value) {
  if (value === null || value === undefined) return null;
  const text = normalizeText(value);
  if (!text) return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatOptionalCLP(value) {
  const num = toOptionalNumber(value);
  if (num === null) return "-";
  return formatCLP(num);
}

function formatUSD(value) {
  const num = toOptionalNumber(value);
  if (num === null) return "-";
  return usdFormatter.format(num);
}

function formatDate(value) {
  const raw = normalizeText(value);
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return raw || "-";
  const [_, year, month, day] = m;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  return date.toLocaleDateString("es-CL", { timeZone: "UTC" });
}

function getExportFileBaseName() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `detalle_razon_social_${yyyy}-${mm}-${dd}`;
}

function toExportRows(rows) {
  return [...rows].sort((a, b) => b.amount - a.amount);
}

function buildXlsxBodyWithOutline(rows) {
  const sortedRows = toExportRows(rows);
  const body = [];
  const outlineRows = [];

  sortedRows.forEach((row) => {
    body.push([
      toMonthLabel(row.monthKey),
      row.legalEntity,
      row.platform,
      row.comuna,
      row.project,
      row.campaignName,
      row.referenceId,
      formatDate(row.paymentDate),
      row.paymentReference || "-",
      row.chargeCode || "",
      toOptionalNumber(row.chargeAmountOriginal),
      toOptionalNumber(row.chargeAmountUsd),
      row.chargeAmountValidation || "-",
      row.amount,
    ]);
    outlineRows.push({ level: 0 });

    const splits = Array.isArray(row.splitAssignments) ? row.splitAssignments : [];
    if (splits.length <= 1) return;

    splits.forEach((split, splitIndex) => {
      body.push([
        toMonthLabel(row.monthKey),
        split.legalEntity,
        row.platform,
        split.comuna,
        split.project,
        `Apertura ${splitIndex + 1}/${splits.length} - ${row.campaignName}`,
        row.referenceId,
        formatDate(row.paymentDate),
        row.paymentReference || "-",
        row.chargeCode || "",
        toOptionalNumber(row.chargeAmountOriginal),
        toOptionalNumber(row.chargeAmountUsd),
        row.chargeAmountValidation || "-",
        split.amount,
      ]);
      outlineRows.push({ level: 1, hidden: true });
    });
  });

  return { body, outlineRows, sortedRows };
}

function exportTableXlsx(rows) {
  if (!rows.length) return;
  if (!window.XLSX) {
    window.alert("No fue posible cargar la librería de exportación XLSX.");
    return;
  }

  const { body, outlineRows, sortedRows } = buildXlsxBodyWithOutline(rows);
  const headers = [
    "Mes",
    "Razón social",
    "Plataforma",
    "Comuna",
    "Proyecto",
    "Nombre de campaña",
    "ID transacción / N° factura",
    "Fecha de pago",
    "N° referencia",
    "Código (Descripción del cobro)",
    "Monto moneda origen",
    "Monto US$",
    "Validación monto",
    "Monto",
  ];

  const totalAmount = sortedRows.reduce((sum, row) => sum + row.amount, 0);
  body.push(["-", "TOTAL", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", totalAmount]);
  outlineRows.push({ level: 0 });

  const worksheet = window.XLSX.utils.aoa_to_sheet([headers, ...body]);
  worksheet["!cols"] = [
    { wch: 18 },
    { wch: 30 },
    { wch: 14 },
    { wch: 20 },
    { wch: 20 },
    { wch: 40 },
    { wch: 30 },
    { wch: 16 },
    { wch: 16 },
    { wch: 28 },
    { wch: 18 },
    { wch: 14 },
    { wch: 16 },
    { wch: 16 },
  ];
  worksheet["!outline"] = { above: false, left: false };
  worksheet["!rows"] = [{}];
  outlineRows.forEach((meta) => {
    worksheet["!rows"].push(meta);
  });
  for (let rowIndex = 2; rowIndex <= body.length + 1; rowIndex += 1) {
    const originCell = worksheet[`K${rowIndex}`];
    if (originCell && typeof originCell.v === "number") originCell.z = '"$"#,##0';
    const usdCell = worksheet[`L${rowIndex}`];
    if (usdCell && typeof usdCell.v === "number") usdCell.z = '"US$"#,##0.00';
    const amountCell = worksheet[`N${rowIndex}`];
    if (amountCell) amountCell.z = '"$"#,##0';
  }

  const workbook = window.XLSX.utils.book_new();
  window.XLSX.utils.book_append_sheet(workbook, worksheet, "Detalle RS");
  window.XLSX.writeFile(workbook, `${getExportFileBaseName()}.xlsx`);
}

function exportTablePdf(rows) {
  if (!rows.length) return;
  const jsPdfApi = window.jspdf?.jsPDF;
  if (!jsPdfApi) {
    window.alert("No fue posible cargar la librería de exportación PDF.");
    return;
  }

  const doc = new jsPdfApi({ orientation: "landscape", unit: "pt", format: "a4" });
  if (typeof doc.autoTable !== "function") {
    window.alert("No fue posible cargar la librería de tablas para PDF.");
    return;
  }

  const sortedRows = toExportRows(rows);
  const totalAmount = sortedRows.reduce((sum, row) => sum + row.amount, 0);
  const body = sortedRows.map((row) => [
    toMonthLabel(row.monthKey),
    row.legalEntity,
    row.platform,
    row.comuna,
    row.project,
    row.campaignName,
    row.referenceId,
    formatDate(row.paymentDate),
    row.paymentReference || "-",
    row.chargeCode || "-",
    formatOptionalCLP(row.chargeAmountOriginal),
    formatUSD(row.chargeAmountUsd),
    row.chargeAmountValidation || "-",
    formatCLP(row.amount),
  ]);
  body.push(["-", "TOTAL", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", formatCLP(totalAmount)]);

  doc.setFontSize(13);
  doc.text("Detalle por Razón Social", 40, 36);
  doc.setFontSize(10);
  doc.text(`Generado: ${new Date().toLocaleDateString("es-CL")}`, 40, 54);

  doc.autoTable({
    startY: 68,
    head: [
      [
        "Mes",
        "Razón social",
        "Plataforma",
        "Comuna",
        "Proyecto",
        "Nombre de campaña",
        "ID transacción / N° factura",
        "Fecha de pago",
        "N° referencia",
        "Código (Descripción del cobro)",
        "Monto moneda origen",
        "Monto US$",
        "Validación monto",
        "Monto",
      ],
    ],
    body,
    styles: { fontSize: 8, cellPadding: 5 },
    headStyles: { fillColor: [31, 31, 31] },
    columnStyles: { 10: { halign: "right" }, 11: { halign: "right" }, 13: { halign: "right" } },
    didParseCell(hookData) {
      if (hookData.section === "body" && hookData.row.index === body.length - 1) {
        hookData.cell.styles.fontStyle = "bold";
        hookData.cell.styles.fillColor = [243, 243, 243];
      }
    },
  });

  doc.save(`${getExportFileBaseName()}.pdf`);
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

function toMonthLabel(monthKey) {
  const normalized = getMonthKey(monthKey);
  if (!normalized) return "-";
  const [year, month] = normalized.split("-").map(Number);
  const date = new Date(year, month - 1, 1);
  return monthFormatter.format(date);
}

function toSortedUnique(values) {
  return Array.from(new Set(values.map(normalizeText).filter(Boolean))).sort((a, b) => a.localeCompare(b, "es"));
}

function fillSelect(select, options, allLabel, mapLabel = null) {
  if (!select) return;
  select.innerHTML = "";

  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = allLabel;
  select.append(allOption);

  options.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = mapLabel ? mapLabel(value) : value;
    select.append(option);
  });
}

function extractRows() {
  const sourceRows = Array.isArray(data.reasonSocialRows) ? data.reasonSocialRows : [];
  return sourceRows
    .map((row, index) => {
      const platform = normalizeText(row.platform);
      const monthKey = getMonthKey(row.month) || getMonthKey(row.invoiceDate);
      const year = monthKey ? monthKey.slice(0, 4) : "";
      const referenceType =
        normalizeText(row.referenceType) || (platform === "Meta" ? "transactionId" : "invoiceNumber");
      const referenceId = normalizeText(row.referenceId || row.invoiceId);
      const paymentDate = normalizeText(row.paymentDate || row.invoiceDate);
      const paymentReference = normalizeText(row.paymentReference);
      const chargeCode = normalizeText(row.chargeCode);
      const chargeAmountOriginal = toOptionalNumber(row.chargeAmountOriginal);
      const chargeAmountUsd = toOptionalNumber(row.chargeAmountUsd);
      const chargeAmountValidation = normalizeText(row.chargeAmountValidation) || "Sin match";
      const splitAssignmentsRaw = Array.isArray(row.splitAssignments) ? row.splitAssignments : [];
      const splitAssignments =
        splitAssignmentsRaw.length > 0
          ? splitAssignmentsRaw
              .map((splitRow) => ({
                legalEntity: normalizeText(splitRow.legalEntity) || "Sin asignar",
                comuna: normalizeText(splitRow.comuna) || "Sin asignar",
                project: normalizeText(splitRow.project) || "Sin asignar",
                amount: Number(splitRow.amount || 0),
              }))
          : [];
      const normalizedSplitAssignments =
        splitAssignments.length > 0
          ? splitAssignments
          : [
              {
                legalEntity: normalizeText(row.legalEntity) || "Sin asignar",
                comuna: normalizeText(row.comuna) || "Sin asignar",
                project: normalizeText(row.project) || "Sin asignar",
                amount: Number(row.amount || 0),
              },
            ];

      return {
        rowId: `${normalizeText(row.invoiceId)}|${platform}|${normalizeText(row.brand)}|${normalizeText(row.campaignName)}|${referenceId}|${index}`,
        legalEntity: normalizeText(row.legalEntity) || "Sin asignar",
        platform: platform || "-",
        brand: normalizeText(row.brand) || "-",
        monthKey,
        year,
        comuna: normalizeText(row.comuna) || "Sin asignar",
        project: normalizeText(row.project) || "Sin asignar",
        campaignName: normalizeText(row.campaignName) || "-",
        referenceType,
        referenceId: referenceId || "-",
        paymentDate: paymentDate || "-",
        paymentReference: paymentReference || "-",
        chargeCode: chargeCode || "-",
        chargeAmountOriginal,
        chargeAmountUsd,
        chargeAmountValidation,
        amount: Number(row.amount || 0),
        splitAssignments: normalizedSplitAssignments,
      };
    })
    .filter((row) => row.platform === "Meta" || row.platform === "Google Ads");
}

const allRows = extractRows();

function buildFilterOptions() {
  fillSelect(controls.platform, toSortedUnique(allRows.map((row) => row.platform)), "Todos los proveedores");
  fillSelect(controls.brand, toSortedUnique(allRows.map((row) => row.brand)), "Todas las marcas");
  fillSelect(
    controls.month,
    toSortedUnique(allRows.map((row) => row.monthKey)).sort((a, b) => b.localeCompare(a)),
    "Todos los meses",
    (monthKey) => toMonthLabel(monthKey)
  );
  fillSelect(
    controls.year,
    toSortedUnique(allRows.map((row) => row.year)).sort((a, b) => b.localeCompare(a)),
    "Todos los años"
  );
  fillSelect(controls.legalEntity, toSortedUnique(allRows.map((row) => row.legalEntity)), "Todas las razones sociales");
}

function getFilteredRows() {
  const search = normalizeText(state.search).toLocaleLowerCase("es");
  return allRows.filter((row) => {
    if (state.platform && row.platform !== state.platform) return false;
    if (state.brand && row.brand !== state.brand) return false;
    if (state.month && row.monthKey !== state.month) return false;
    if (state.year && row.year !== state.year) return false;
    if (state.legalEntity && row.legalEntity !== state.legalEntity) return false;

    if (search) {
      const haystack = [
        row.legalEntity,
        row.platform,
        row.comuna,
        row.project,
        row.campaignName,
        row.referenceId,
        row.paymentDate,
        row.paymentReference,
        row.chargeCode,
        row.chargeAmountValidation,
        row.brand,
      ]
        .join(" ")
        .toLocaleLowerCase("es");
      if (!haystack.includes(search)) return false;
    }
    return true;
  });
}

function render(rows) {
  currentFilteredRows = toExportRows(rows);
  const visibleRows = currentFilteredRows;
  const total = visibleRows.reduce((sum, row) => sum + row.amount, 0);
  const uniqueCampaigns = new Set(visibleRows.map((row) => row.campaignName).filter(Boolean)).size;

  kpiTotal.textContent = formatCLP(total);
  kpiRows.textContent = String(visibleRows.length);
  kpiCampaigns.textContent = String(uniqueCampaigns);
  resultsCount.textContent = `${visibleRows.length} fila${visibleRows.length === 1 ? "" : "s"}`;
  if (exportXlsxBtn) exportXlsxBtn.disabled = visibleRows.length === 0;
  if (exportPdfBtn) exportPdfBtn.disabled = visibleRows.length === 0;

  if (!visibleRows.length) {
    tableBody.innerHTML = '<tr><td colspan="14" class="empty">No hay filas para los filtros seleccionados.</td></tr>';
    return;
  }

  tableBody.innerHTML = visibleRows
    .map((row) => {
      const splitRows = Array.isArray(row.splitAssignments) ? row.splitAssignments : [];
      const hasSplit = splitRows.length > 1;
      const isExpanded = hasSplit && expandedRowIds.has(row.rowId);
      const toggleButton = hasSplit
        ? `<button class="rsd-expand-toggle" type="button" data-row-id="${esc(row.rowId)}" aria-expanded="${isExpanded ? "true" : "false"}">${isExpanded ? "Ocultar apertura" : `Aperturar (${splitRows.length})`}</button>`
        : "";
      const mainRow = `
      <tr class="rsd-main-row">
        <td>${esc(toMonthLabel(row.monthKey))}</td>
        <td>${esc(row.legalEntity)}</td>
        <td>${esc(row.platform)}</td>
        <td>${esc(row.comuna)}</td>
        <td>${esc(row.project)}</td>
        <td>
          <div class="rsd-campaign-cell">
            <span>${esc(row.campaignName)}</span>
            ${toggleButton}
          </div>
        </td>
        <td>${esc(row.referenceId)}</td>
        <td>${esc(formatDate(row.paymentDate))}</td>
        <td>${esc(row.paymentReference)}</td>
        <td>${esc(row.chargeCode)}</td>
        <td class="amount">${formatOptionalCLP(row.chargeAmountOriginal)}</td>
        <td class="amount">${formatUSD(row.chargeAmountUsd)}</td>
        <td>${esc(row.chargeAmountValidation)}</td>
        <td class="amount">${formatCLP(row.amount)}</td>
      </tr>`;

      if (!isExpanded) return mainRow;

      const breakdownRows = splitRows
        .map(
          (splitRow, splitIndex) => `
      <tr class="rsd-split-row">
        <td>${esc(toMonthLabel(row.monthKey))}</td>
        <td>${esc(splitRow.legalEntity)}</td>
        <td>${esc(row.platform)}</td>
        <td>${esc(splitRow.comuna)}</td>
        <td>${esc(splitRow.project)}</td>
        <td><span class="rsd-split-label">Apertura ${splitIndex + 1}/${splitRows.length}</span> ${esc(row.campaignName)}</td>
        <td>${esc(row.referenceId)}</td>
        <td>${esc(formatDate(row.paymentDate))}</td>
        <td>${esc(row.paymentReference)}</td>
        <td>${esc(row.chargeCode)}</td>
        <td class="amount">${formatOptionalCLP(row.chargeAmountOriginal)}</td>
        <td class="amount">${formatUSD(row.chargeAmountUsd)}</td>
        <td>${esc(row.chargeAmountValidation)}</td>
        <td class="amount">${formatCLP(splitRow.amount)}</td>
      </tr>`
        )
        .join("");

      return mainRow + breakdownRows;
    })
    .join("");
}

function attachEvents() {
  controls.platform?.addEventListener("change", (event) => {
    state.platform = event.target.value;
    render(getFilteredRows());
  });
  controls.brand?.addEventListener("change", (event) => {
    state.brand = event.target.value;
    render(getFilteredRows());
  });
  controls.month?.addEventListener("change", (event) => {
    state.month = event.target.value;
    render(getFilteredRows());
  });
  controls.year?.addEventListener("change", (event) => {
    state.year = event.target.value;
    render(getFilteredRows());
  });
  controls.legalEntity?.addEventListener("change", (event) => {
    state.legalEntity = event.target.value;
    render(getFilteredRows());
  });
  controls.search?.addEventListener("input", (event) => {
    state.search = event.target.value;
    render(getFilteredRows());
  });
  tableBody?.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest(".rsd-expand-toggle");
    if (!button) return;
    const rowId = normalizeText(button.dataset.rowId);
    if (!rowId) return;
    if (expandedRowIds.has(rowId)) {
      expandedRowIds.delete(rowId);
    } else {
      expandedRowIds.add(rowId);
    }
    render(getFilteredRows());
  });
  controls.clear?.addEventListener("click", () => {
    state.platform = "";
    state.brand = "";
    state.month = "";
    state.year = "";
    state.legalEntity = "";
    state.search = "";

    if (controls.platform) controls.platform.value = "";
    if (controls.brand) controls.brand.value = "";
    if (controls.month) controls.month.value = "";
    if (controls.year) controls.year.value = "";
    if (controls.legalEntity) controls.legalEntity.value = "";
    if (controls.search) controls.search.value = "";
    expandedRowIds.clear();

    render(getFilteredRows());
  });
  exportXlsxBtn?.addEventListener("click", () => {
    exportTableXlsx(currentFilteredRows);
  });
  exportPdfBtn?.addEventListener("click", () => {
    exportTablePdf(currentFilteredRows);
  });
}

buildFilterOptions();
attachEvents();
render(getFilteredRows());
