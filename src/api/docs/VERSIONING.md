# Versionamento da API — AegisDerm

## Política

Seguimos [Semantic Versioning](https://semver.org/lang/pt-BR/):

| Tipo | Quando |
|------|--------|
| **MAJOR** (v2.0) | Mudanças incompatíveis com versões anteriores |
| **MINOR** (v1.1) | Novas features retrocompatíveis |
| **PATCH** (v1.0.1) | Bug fixes e melhorias internas |

## Versão Atual

**v1.0.0** — Lançamento inicial (14/05/2026)

## Ciclo de Suporte

- Major: suportada por **24 meses**
- Minor: suportada por **12 meses**
- Patch: substituída pelo próximo patch

## Convenção de URL

A versão fica no path: `/api/v1/...`

Quando uma v2 for lançada, `/api/v1/...` continuará funcional pelo prazo de suporte.

## Deprecação

Antes de fazer uma breaking change:

1. Anunciar **12 meses** antes do corte
2. Adicionar header `Deprecation: true` nas respostas das rotas afetadas
3. Manter as duas versões durante a transição

```python
# Exemplo de decorator de deprecação
from functools import wraps
from flask import request, g

def deprecated(message: str, sunset_date: str = None):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            resp = f(*args, **kwargs)
            # Flask retorna tuple (response, status_code) ou Response
            if isinstance(resp, tuple):
                response, *rest = resp
            else:
                response, rest = resp, []
            # Adicionar headers de deprecação
            from flask import make_response
            r = make_response(response, *rest)
            r.headers["Deprecation"] = "true"
            if sunset_date:
                r.headers["Sunset"] = sunset_date
            r.headers["Link"] = f'<https://docs.aegisderm.com/migration>; rel="deprecation"'
            return r
        return wrapper
    return decorator
```

## Roadmap

| Versão | Data prevista | Descrição |
|--------|--------------|-----------|
| v1.0.0 | 14/05/2026 | Lançamento inicial — gestão clínica + IA |
| v1.1.0 | 21/05/2026 | Paginação cursor-based, filtros avançados |
| v1.2.0 | 28/05/2026 | Refresh tokens, rate limiting por usuário |
| v1.3.0 | 30/06/2026 | Relatórios PDF, exportação CSV |
| v2.0.0 | 2027 | Redesign de endpoints, webhooks, GraphQL |

## Changelog

### v1.0.0 (14/05/2026)

**Novidades:**
- Autenticação JWT com roles (DOCTOR, RECEPTIONIST, CLINIC_ADMIN, SUPER_ADMIN)
- CRUD completo de pacientes com paginação
- Agendamentos com detecção de conflitos
- Prontuários médicos com upload de documentos
- Análise de IA para diagnóstico dermatológico (ensemble de 5 modelos ResNet50)
- Bloqueios de agenda
- Dashboard de métricas
- Rate limiting (10 req/min no login, 20 req/min na IA)
- Documentação Swagger em `/docs`

**Removido:**
- Endpoints legados `/api/v1/predict` e `/api/v1/health` (substituídos por `/api/v1/ai/analyze`)
