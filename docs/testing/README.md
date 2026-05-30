# Testing Guides

Guías de testing manual. **Son obligatorias y sirven como protocolo de aceptación del humano.** El agente corre los tests automatizados; el humano valida UX y edge cases reales siguiendo estas guías.

## Guías existentes

_Ninguna todavía. La primera será `01-health-endpoint_testing.md` al cerrar Día 1._

## Convenciones

- **Un archivo por feature** con prefijo cronológico `NN-feature_testing.md`, mismo número que `docs/features/NN-feature.md`.
- Cada guía debe incluir:
  - **Pre-requisitos** — variables de entorno, servicios externos, datos de prueba
  - **Happy path** — el flujo esperado paso a paso
  - **Edge cases preventivos** — escenarios que el agente no puede probar (red real, secretos válidos, latencia, rate limits reales)
  - **Workarounds** si hay blockers técnicos (ej. cómo simular un rate limit de Groq sin gastar quota)
  - **Verificación en logs / DB** — qué grep, qué `request_id` buscar, qué métrica revisar
- Si el agente se topa con un blocker durante implementación, documentarlo aquí para que el próximo no tropiece.

## Template

Ver [TEMPLATE.md](TEMPLATE.md).
