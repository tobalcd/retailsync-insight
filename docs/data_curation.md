# Registro de curación de datos

Cambios manuales sobre los datos migrados, con fecha, motivo y valores originales.
Regla: toda curación se documenta aquí; nada se cambia en silencio.

---

## 2026-06-10 — `mobility_zones` Madrid: eje Castellana → `business`

**Qué:** dos zonas MITMA de Madrid reetiquetadas de `residencial_premium` a
`business` (tipo + `traffic_profile` business canónico del dataset + peak_hours).

| zona_mitma | lat, lng | avg_daily_visitors | tipo ANTES | tipo DESPUÉS |
|---|---|---|---|---|
| 2807906 | 40.438, -3.695 | 287.215 | residencial_premium | business |
| 2807908 | 40.460, -3.680 | 445.189 | residencial_premium | business |

**Por qué:** el snapshot MITMA del frontend etiqueta por centroide de distrito y
no contiene NINGUNA zona `business` en Madrid; el eje Castellana
(AZCA–Nuevos Ministerios y Plaza Castilla–Cuatro Torres) figura como residencial.
Eso hacía estructuralmente imposible que el detector de audiencia oculta
identificara el patrón "ejecutivo en tránsito" (caso de control Madrid+banca):
ninguna ponderación puede extraer una señal que el dato no contiene.
Reetiquetar es conocimiento del mundo real (es el principal distrito financiero
de España), no un ajuste de pesos al caso de prueba.

**Efecto colateral asumido:** estas zonas cambian para TODOS los sectores
(p. ej. alimentación pondera `business` 0,35 vs residencial 0,9). Aceptado:
si la zona es de oficinas, lo correcto es que pese así en todos los análisis.

**Fix de fondo (roadmap, no hoy):** sustituir el snapshot sintético por
zonificación MITMA real más fina; esta curación es un parche documentado.

**Cómo revertir:**
```sql
update mobility_zones set tipo='residencial_premium'
 where city_slug='madrid' and zona_mitma in ('2807906','2807908');
-- (y restaurar traffic_profile residencial_premium + peak_hours 12:00-14:00/12:00-15:00)
```
