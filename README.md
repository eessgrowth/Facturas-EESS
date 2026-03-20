# Dashboard de Facturas

App web estática para visualizar facturas de `Meta` y `Google Ads` con:

- KPIs de inversión total (`Meta + Google Ads`, `Meta`, `Google Ads`)
- KPI adicional para `Agencia Zeppelin`
- Filtros por `plataforma`, `mes`, `año` y `marca`
- Detalle por factura (líneas de cargo / transacciones)
- Resumen por `Razón Social` usando mapeo de campañas desde la hoja `Razón social` en `Facturación EESS.xlsx`
- Descarga de respaldo (`PDF` o `Excel`)

## Archivos clave

- `index.html`: estructura de la app
- `campaigns.html`: vista de gasto por nombre de campaña
- `reason-social-detail.html`: detalle de razón social aperturado por proyecto/campaña/ID (con exportación XLSX/PDF)
- `styles.css`: estilos
- `app.js`: lógica de filtros y render
- `campaigns.js`: lógica de filtros y visualización por campaña
- `reason-social-detail.js`: lógica de la tabla detallada por razón social
- `scripts/build_invoice_data.py`: extracción y normalización de datos desde PDFs
- `scripts/build_invoice_data.py`: extracción y normalización de datos desde PDFs y Excel (`Facturación EESS.xlsx`)
- `data/invoices.json` y `data/invoices.js`: dataset generado

## Uso

1. Regenerar datos (si cambias o agregas PDFs en `pdfs/` o comprobantes de Meta en `Facturas Meta/<marca>/<mes>/`):

```bash
python3 scripts/build_invoice_data.py
```

2. Levantar servidor local:

```bash
python3 -m http.server 8000
```

3. Abrir:

```text
http://localhost:8000
```

4. Vista alternativa de campañas:

```text
http://localhost:8000/campaigns.html
```

5. Vista detallada por razón social:

```text
http://localhost:8000/reason-social-detail.html
```
