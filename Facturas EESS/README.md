# Dashboard de Facturas

App web estática para visualizar facturas de `Meta` y `Google Ads` con:

- KPIs de inversión total (`Meta + Google Ads`, `Meta`, `Google Ads`)
- KPI adicional para `Agencia Zeppelin`
- Filtros por `plataforma`, `mes` y `marca`
- Detalle por factura (líneas de cargo / transacciones)
- Descarga de respaldo (`PDF` o `Excel`)

## Archivos clave

- `index.html`: estructura de la app
- `styles.css`: estilos
- `app.js`: lógica de filtros y render
- `scripts/build_invoice_data.py`: extracción y normalización de datos desde PDFs
- `scripts/build_invoice_data.py`: extracción y normalización de datos desde PDFs y Excel (`Facturación EESS.xlsx`)
- `data/invoices.json` y `data/invoices.js`: dataset generado

## Uso

1. Regenerar datos (si cambias o agregas PDFs en `pdfs/`):

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
