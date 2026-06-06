# Spec — `trade_intel` (Eje 6: Comercio exterior & cadena)

> Estado: **nuevo** · Fase: 5 · v1 2026-05-28 · Doctrina de Casa v1 §8

## 1. Propósito
Resiliencia comercial: **diversificación y posición en cadenas de valor**, no volumen
exportado. Foco en zonas francas y remesas (rasgos estructurales RD).

## 2. Fuentes (vía `shared/data`)
BCRD sector externo (balanza de pagos, exportaciones, remesas), DGA/aduanas (comercio por producto).

## 3. Índices
Concentración de exportaciones (**HHI**), dependencia de importaciones, dinámica de zonas
francas, exposición a remesas, capacidad de **upgrading** (Gereffi GVC; Hausmann complejidad;
Krugman geografía; base Ricardo/Heckscher-Ohlin).

## 4. Modelo de datos
`TradeFlow` (producto, dirección, valor, período, socio, fuente/linaje), `TradeScore`
(concentración/dependencia/resiliencia). PK UUID.

## 5. API — `/api/v1/trade-intel`
`GET /flows` · `GET /concentration` · `GET /score`.

## 6. Eventos
- **Publica** `trade.updated` → consumido por `sector_intel` (resiliencia/MRS) y por el IRMP (dimensión externa).

## 7. Doctrina codificada (§8)
Diversificación > volumen; upgrading dinámico > ventaja comparativa estática; medir
dependencia, no solo apertura.

## 8. Criterios de aceptación
- Tests de HHI y métricas de dependencia; consistencia de clasificación de productos; cobertura ≥80%.

## 9. Límites / dependencias
Depende de calidad/oportunidad de aduanas; no modela barreras no arancelarias finas ni precios de transferencia.
