# Exec Plans

Documentos técnicos que bajan una intención de producto a cambios concretos en código. Cada exec plan describe el "qué" y el "cómo" antes de empezar a implementar.

## Planes

| # | Plan | Estado | Descripción |
|---|---|---|---|
| 01 | [MVP email-triage (7 días)](01-mvp-email-triage.md) | 🚧 | Plan día por día para llegar al MVP desplegado |

Estados: 📋 propuesto · 🚧 en progreso · ✅ entregado · ❌ descartado

## Cuándo crear un exec plan

Obligatorio si la feature:
- Toca ≥3 archivos
- Introduce una dependencia nueva
- Cambia un patrón arquitectónico
- Tiene impacto en deploy o infra

No hace falta para:
- Fixes triviales
- Refactors cosméticos
- Cambios de documentación

## Convenciones

- **Nombre:** `NN-feature.md` con prefijo cronológico (`01-`, `02-`, …). El mismo número se reusa para `docs/features/NN-*.md` y `docs/testing/NN-*_testing.md`.
- **Antes de codear:** el plan debe estar revisado por el humano.
- **Estado al inicio:** 📋. Cambia a 🚧 cuando arranca implementación, ✅ al merge, ❌ si se descarta.

## Template mínimo

```markdown
# NN. [Nombre de la feature]

**Estado:** 📋 propuesto
**Estimación:** X hrs

## Intención
[1-2 párrafos: qué resuelve, para quién]

## Alcance
- Incluido: ...
- Fuera: ...

## Cambios concretos
| Archivo | Cambio |
|---|---|

## Decisiones de diseño
| Decisión | Alternativa descartada | Razón |
|---|---|---|

## Riesgos / Open questions
- ...

## Done cuando
- [ ] Tests pasan
- [ ] `docs/features/NN-x.md` actualizado
- [ ] `docs/testing/NN-x_testing.md` actualizado
- [ ] Humano validó con la guía de testing
```
