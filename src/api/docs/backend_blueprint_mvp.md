# Blueprint Técnico Completo do Backend (MVP Intermediário)

## 1) Resumo executivo
Este blueprint define a evolução do backend Flask atual (focado em inferência dermatológica) para um backend clínico multi-clínica com controle de acesso por perfis, prontuário versionado/auditável e integração segura com IA como apoio à decisão.

Objetivo do MVP (≈ 1 mês, 1 dev):
- Preservar os endpoints existentes `POST /api/v1/predict` e `GET /api/v1/health` sem quebra.
- Introduzir banco relacional e módulos clínicos mínimos.
- Garantir isolamento de dados por clínica (`clinic_id`) e auditoria.
- Entregar contrato de API consumível por frontend Vue 3 separado.

Perfis:
- Super Admin
- Admin da Clínica
- Médico
- Recepcionista

Princípios:
- Segurança e LGPD por padrão.
- Controle de acesso explícito por recurso/ação.
- Toda operação clínica sensível com trilha de auditoria.
- IA como pré-análise, não diagnóstico definitivo.

---

## 2) Decisões técnicas recomendadas

### Stack complementar (mantendo Flask)
- **Banco:** PostgreSQL (local via Docker para dev).
- **ORM:** SQLAlchemy 2.x (com Flask-SQLAlchemy opcional só para integração simples).
- **Migrations:** Alembic (via Flask-Migrate).
- **Auth:** JWT (access + refresh), hash de senha com Argon2 ou bcrypt.
- **Autorização:** RBAC + escopo por clínica (e validações contextuais por médico).
- **Validação:** Marshmallow ou Pydantic (recomendação: Marshmallow com Flask para menor fricção).
- **Upload de arquivos:** armazenamento local para MVP (`/storage`) com metadados em tabela.
- **Auditoria:** tabela `audit_logs` + interceptadores por serviço/camada de aplicação.
- **Swagger/OpenAPI:** manter `/docs`; evoluir para OpenAPI 3 com versionamento por tags/modulos.

### Convenções gerais
- UTC para timestamps.
- Soft delete para entidades administrativas, hard delete proibido em dados clínicos.
- IDs UUID em todas entidades novas.
- `clinic_id` obrigatório em entidades multi-tenant.

---

## 3) Arquitetura backend proposta

Arquitetura por camadas + módulos de domínio:
1. **API Layer (controllers/blueprints)**
   - parsing HTTP, autenticação de token, autorização base.
2. **Application Layer (services/use_cases)**
   - regras de negócio, orquestração de casos de uso.
3. **Domain/Model Layer**
   - entidades, enums, regras invariantes.
4. **Infrastructure Layer**
   - ORM/repos, storage de arquivos, integração IA existente.
5. **Cross-cutting**
   - auditoria, logs estruturados, tratamento de erro, paginação, RBAC.

Fluxo exemplo (consulta):
`Request -> Auth Middleware -> Permission Guard -> Service -> Repository -> DB -> Audit Trail -> Response`.

---

## 4) Estrutura futura de pastas

```text
src/
  api/
    app.py
    config/
      settings.py
      security.py
    common/
      enums/
      exceptions/
      pagination/
      responses/
      decorators/
      validators/
    infra/
      db/
        base.py
        session.py
        models/
      repositories/
      storage/
      audit/
      ai/
        prediction_adapter.py
    modules/
      auth/
        controller.py
        service.py
        schemas.py
      clinics/
      units/
      roles_permissions/
      users/
      doctors/
      specialties/
      patients/
      appointments/
      schedule_blocks/
      medical_records/
      medical_record_versions/
      documents/
      ai_analyses/
      dashboards/
      audit_logs/
      health/
    docs/
      openapi.yaml
      backend_blueprint_mvp.md
  models/  # preservar modelos IA atuais
  training/ # preservar treinamento
```

---

## 5) Modelo de dados proposto (MVP)

### 5.1 Entidades principais

1. **clinics**
- id (UUID PK)
- legal_name, trade_name
- cnpj (opcional MVP)
- status (active/inactive)
- created_at, updated_at

2. **units**
- id, clinic_id(FK)
- name, phone, email
- address_line, number, district, city, state, cep
- created_at, updated_at

3. **roles**
- id, code (`SUPER_ADMIN`, `CLINIC_ADMIN`, `DOCTOR`, `RECEPTIONIST`)
- name, description

4. **permissions**
- id, code (`patients.read`, `medical_records.write`...)
- description

5. **role_permissions**
- role_id, permission_id

6. **users**
- id
- full_name, email(unique), password_hash
- phone
- is_active
- last_login_at
- created_at, updated_at

7. **user_clinic_roles** (vínculo multi-clínica do usuário)
- id
- user_id, clinic_id, role_id
- unit_id (opcional)
- status
- created_at

8. **specialties**
- id, clinic_id (ou global com nullable; para MVP: por clínica)
- name, code

9. **doctors**
- id, user_id(FK users), clinic_id, unit_id
- crm_number, crm_state
- specialty_id
- is_active

10. **patients_master** (registro civil único da pessoa)
- id
- full_name
- cpf (único global, criptografável/tokenizável)
- birth_date
- blood_type
- email
- phone
- marital_status
- address_line, number, district, city, state, cep
- created_at, updated_at

11. **clinic_patients** (vínculo paciente x clínica)
- id
- clinic_id
- patient_master_id
- local_code (prontuário interno)
- is_active
- created_at

12. **appointments**
- id
- clinic_id, unit_id
- doctor_id
- clinic_patient_id
- scheduled_start, scheduled_end
- status (`SCHEDULED`,`CONFIRMED`,`CANCELLED`,`NO_SHOW`,`IN_PROGRESS`,`COMPLETED`)
- reason
- cancellation_reason
- created_by_user_id
- updated_by_user_id
- created_at, updated_at

13. **schedule_blocks**
- id
- clinic_id, doctor_id
- start_at, end_at
- reason
- created_by_user_id

14. **medical_records**
- id
- clinic_id
- clinic_patient_id
- appointment_id (nullable)
- doctor_id
- record_datetime
- status (`DRAFT`,`SIGNED`)
- current_version_number
- created_at, updated_at

15. **medical_record_versions**
- id
- medical_record_id
- version_number
- anamnesis
- physical_exam
- diagnostic_hypotheses
- diagnosis
- conduct
- prescription_guidance
- requested_exams
- evolution
- doctor_name_snapshot
- doctor_crm_snapshot
- edited_by_user_id
- edited_at
- change_reason

16. **documents**
- id
- clinic_id
- clinic_patient_id
- medical_record_id (nullable)
- uploaded_by_user_id
- category (`EXAM`,`PHOTO`,`REPORT`,`OTHER`)
- filename_original, filename_storage
- mime_type, size_bytes, checksum
- storage_path
- created_at

17. **ai_analyses**
- id
- clinic_id
- clinic_patient_id
- appointment_id (nullable)
- requested_by_user_id
- image_document_id (FK documents)
- model_name, model_version
- result_label, confidence
- raw_result_json
- disclaimer_text
- created_at

18. **audit_logs**
- id
- clinic_id (nullable em eventos globais)
- actor_user_id (nullable em eventos de sistema)
- action (`CREATE`,`UPDATE`,`DELETE`,`LOGIN`,`EXPORT`...)
- resource_type
- resource_id
- before_json
- after_json
- ip_address
- user_agent
- created_at

19. **refresh_tokens**
- id
- user_id
- token_hash
- expires_at
- revoked_at
- created_at

---

## 6) Relacionamentos principais
- clinic 1:N units
- clinic N:N users (via user_clinic_roles)
- clinic 1:N doctors
- user 1:1 doctor (quando perfil médico)
- patients_master N:N clinics (via clinic_patients)
- doctor 1:N appointments
- clinic_patient 1:N appointments
- clinic_patient 1:N medical_records
- medical_record 1:N medical_record_versions
- clinic_patient 1:N documents
- clinic_patient 1:N ai_analyses
- user 1:N audit_logs

---

## 7) Estratégia multi-clínica
- Todas as tabelas de domínio clínico possuem `clinic_id`.
- Usuário autenticado opera no contexto de uma clínica ativa (`X-Clinic-Id` header ou claim no JWT).
- Cada query obrigatoriamente filtra por `clinic_id` do contexto.
- Super Admin pode trocar contexto global para gestão de clínicas.
- Índices compostos por (`clinic_id`, campos de busca principais).

---

## 8) Estratégia para médico em mais de uma clínica
- Um `user` pode ter múltiplos vínculos em `user_clinic_roles` com papel DOCTOR.
- Tabela `doctors` terá um registro por clínica (CRM repetível com restrições conforme regra local).
- Ao logar, médico escolhe clínica ativa (ou recebe default) para escopo de dados.

---

## 9) Estratégia para pacientes em mais de uma clínica
- Pessoa única em `patients_master` (CPF único).
- Vínculo por clínica em `clinic_patients`, com código interno distinto por clínica.
- Clínicas não enxergam dados de vínculo de outras clínicas.

---

## 10) Estratégia de autenticação e autorização

### Autenticação
- `POST /api/v1/auth/login` retorna `access_token` (curto, ex: 15 min) + `refresh_token` (ex: 7 dias).
- Refresh com rotação de token.
- Logout revoga refresh token.

### Autorização
- RBAC por role base + checagem contextual:
  - recepcionista sem acesso a prontuário/IA/documentos sensíveis.
  - médico pode ler pacientes da clínica e editar somente registros sob seu ato médico (ou via regras do admin).
- Decorators:
  - `@require_auth`
  - `@require_permissions([...])`
  - `@require_clinic_scope`

---

## 11) Matriz de permissões (resumo)

| Módulo/Ação | Super Admin | Admin Clínica | Médico | Recepcionista |
|---|---|---|---|---|
| Clínicas CRUD | ✅ | ❌ | ❌ | ❌ |
| Unidades CRUD (da clínica) | 👁️ global | ✅ | ❌ | ❌ |
| Usuários CRUD (da clínica) | 👁️ global | ✅ | ❌ | ❌ |
| Especialidades CRUD | 👁️ global | ✅ | leitura | ❌ |
| Pacientes CRUD cadastral | ❌ | ✅ | leitura/edição limitada | ✅ |
| Meus pacientes | ❌ | ✅ | ✅ | ❌ |
| Todos pacientes clínica | ❌ | ✅ | ✅ | ✅ (sem sensíveis) |
| Agenda/consultas CRUD operacional | ❌ | ✅ | ✅ (sua agenda) | ✅ |
| Bloqueio de agenda | ❌ | ✅ | ✅ (próprio) | ❌ |
| Prontuário criar/editar | ❌ | ✅ | ✅ | ❌ |
| Documentos médicos sensíveis | ❌ | ✅ | ✅ | ❌ |
| IA análises visualizar | ❌ | ✅ | ✅ | ❌ |
| IA upload solicitação | ❌ | ✅ | ✅ | ❌ |
| Dashboard clínica | 👁️ global | ✅ | ❌ | ❌ |
| Dashboard médico | ❌ | ✅ | ✅ | ❌ |
| Logs auditoria | 👁️ global | ✅ clínica | leitura limitada | ❌ |

---

## 12) Estratégia de auditoria e LGPD
- Auditar: login, CRUD clínico, acesso a prontuário, upload/download documento, análise IA.
- Guardar `before_json/after_json` para UPDATE sensível.
- Mascaramento de CPF/telefone em logs exibidos (ex.: `***.***.***-**`).
- Trilha de quem viu prontuário (evento `READ_MEDICAL_RECORD`).
- Política de retenção definida por config.
- Minimização de dados no response para perfis restritos.

---

## 13) Estratégia de versionamento de prontuário
- `medical_records` guarda metadados e `current_version_number`.
- Conteúdo clínico apenas em `medical_record_versions` imutável.
- Edição gera nova versão (nunca sobrescrever versão anterior).
- Endpoint de diff simples (opcional MVP+) pode comparar versões.
- Campo obrigatório `change_reason` para rastreabilidade.

---

## 14) Estratégia de integração da IA existente
- Preservar pipeline atual em `prediction_service.py`.
- Criar adapter de aplicação: `ai/prediction_adapter.py` para encapsular chamada atual.
- Novo fluxo clínico:
  1) upload de imagem como `document`;
  2) solicitar análise IA vinculando `clinic_id` + `clinic_patient_id`;
  3) salvar resultado em `ai_analyses` com `raw_result_json`.
- Manter endpoint legado `/api/v1/predict` para compatibilidade com frontend atual.
- Adicionar disclaimer padrão em cada resposta de IA.

---

## 15) Contrato oficial da API por módulo (MVP)

Base URL: `/api/v1`

### 15.1 Auth
1. **POST /auth/login**
- Perfis: público
- Objetivo: autenticar usuário
- Payload: `{ "email": "...", "password": "...", "clinic_id": "uuid(opcional)" }`
- 200: tokens + perfil + clínicas disponíveis
- Erros: 401 inválido, 423 usuário inativo, 400 validação

2. **POST /auth/refresh**
- Perfis: autenticado
- Payload: `{ "refresh_token": "..." }`
- 200: novo access/refresh
- Erros: 401 token inválido/expirado

3. **POST /auth/logout**
- Perfis: autenticado
- Payload: `{ "refresh_token": "..." }`
- 204 sem body

4. **GET /auth/me**
- Perfis: autenticado
- 200: dados do usuário, role atual, permissões e clínica ativa

### 15.2 Clinics
- **GET /clinics** (Super Admin)
- **POST /clinics** (Super Admin)
- **GET /clinics/{id}** (Super Admin)
- **PATCH /clinics/{id}** (Super Admin)
- **DELETE /clinics/{id}** (Super Admin, soft delete)

Payload create/update: `legal_name`, `trade_name`, `status`.
Erros: 404, 409 duplicidade, 403.

### 15.3 Units
- CRUD completo `/clinics/{clinic_id}/units`
- Perfis: Admin Clínica (Super Admin com escopo)

### 15.4 Users
- CRUD `/clinics/{clinic_id}/users`
- Campos: nome, email, telefone, role, status, senha inicial
- Perfis: Admin Clínica

### 15.5 Roles/Permissions
- **GET /roles**
- **GET /permissions**
- **GET /me/permissions**
- Sem custom role no MVP (somente leitura/config pré-definida)

### 15.6 Specialties
- CRUD `/clinics/{clinic_id}/specialties`
- Perfis: Admin Clínica (médico leitura)

### 15.7 Doctors
- CRUD `/clinics/{clinic_id}/doctors`
- Campos: user_id, crm_number, crm_state, specialty_id, unit_id
- Perfis: Admin Clínica

### 15.8 Patients
1. **POST /clinics/{clinic_id}/patients**
- Perfis: Admin, Recepcionista
- Payload obrigatório:
  - full_name, cpf, address_line, cep, phone, birth_date, blood_type, email, marital_status
- 201: patient + clinic_patient_id

2. **GET /clinics/{clinic_id}/patients**
- Perfis: Admin, Médico, Recepcionista
- Filtros: name, cpf, birth_date, q

3. **GET /clinics/{clinic_id}/patients/{clinic_patient_id}**
- Perfis: Admin, Médico, Recepcionista (campos sensíveis filtrados por perfil)

4. **PATCH /clinics/{clinic_id}/patients/{clinic_patient_id}**
- Perfis: Admin, Recepcionista

5. **DELETE /clinics/{clinic_id}/patients/{clinic_patient_id}**
- Perfis: Admin (desativação)

6. **GET /clinics/{clinic_id}/patients/my**
- Perfis: Médico
- Objetivo: listar pacientes com consultas do médico logado

### 15.9 Appointments
1. **POST /clinics/{clinic_id}/appointments** (criar)
2. **PATCH /clinics/{clinic_id}/appointments/{id}/reschedule**
3. **PATCH /clinics/{clinic_id}/appointments/{id}/cancel**
4. **PATCH /clinics/{clinic_id}/appointments/{id}/confirm**
5. **PATCH /clinics/{clinic_id}/appointments/{id}/no-show**
6. **PATCH /clinics/{clinic_id}/appointments/{id}/start**
7. **PATCH /clinics/{clinic_id}/appointments/{id}/finish**
8. **GET /clinics/{clinic_id}/appointments** (filtros por doctor_id, patient_id, status, date_from/to)

Perfis:
- Admin: todos
- Recepcionista: todos exceto start/finish clínico (opcional bloquear)
- Médico: start/finish e gestão da própria agenda

### 15.10 Schedule Blocks
1. **POST /clinics/{clinic_id}/doctors/{doctor_id}/schedule-blocks**
2. **DELETE /clinics/{clinic_id}/doctors/{doctor_id}/schedule-blocks/{block_id}**
3. **GET /clinics/{clinic_id}/doctors/{doctor_id}/schedule-blocks**

Perfis:
- Médico (apenas próprio doctor_id)
- Admin (qualquer médico da clínica)

### 15.11 Medical Records
1. **POST /clinics/{clinic_id}/patients/{clinic_patient_id}/medical-records**
2. **PATCH /clinics/{clinic_id}/medical-records/{record_id}** (gera nova versão)
3. **GET /clinics/{clinic_id}/patients/{clinic_patient_id}/medical-records**
4. **GET /clinics/{clinic_id}/medical-records/{record_id}**
5. **GET /clinics/{clinic_id}/medical-records/{record_id}/versions**
6. **GET /clinics/{clinic_id}/medical-records/{record_id}/versions/{version_number}**

Perfis:
- Admin, Médico

Payload clínico (create/update):
- anamnesis
- physical_exam
- diagnostic_hypotheses
- diagnosis
- conduct
- prescription_guidance
- requested_exams
- evolution
- record_datetime
- doctor_id
- doctor_crm_snapshot
- change_reason (obrigatório em update)

### 15.12 Documents/Attachments
1. **POST /clinics/{clinic_id}/patients/{clinic_patient_id}/documents** (multipart)
2. **GET /clinics/{clinic_id}/patients/{clinic_patient_id}/documents**
3. **GET /clinics/{clinic_id}/documents/{document_id}/download**
4. **DELETE /clinics/{clinic_id}/documents/{document_id}** (soft)

Perfis:
- Upload/listar: Admin, Médico
- Download: Admin, Médico
- Recepcionista: sem acesso

### 15.13 AI Analyses
1. **POST /clinics/{clinic_id}/patients/{clinic_patient_id}/ai-analyses**
- opção A: multipart `file`
- opção B: `document_id` já enviado

2. **GET /clinics/{clinic_id}/patients/{clinic_patient_id}/ai-analyses**
3. **GET /clinics/{clinic_id}/ai-analyses/{analysis_id}**

Perfis:
- Admin, Médico

Resposta inclui:
- label, confidence, created_at, model_version
- `disclaimer`: "Resultado de apoio à decisão médica; não constitui diagnóstico definitivo."

### 15.14 Dashboards
1. **GET /clinics/{clinic_id}/dashboards/clinic** (Admin)
2. **GET /clinics/{clinic_id}/dashboards/doctor/me** (Médico)

Indicadores MVP:
- total pacientes, consultas por status, no-show rate, análises IA por período.

### 15.15 Audit Logs
1. **GET /clinics/{clinic_id}/audit-logs** (Admin)
- filtros: actor_user_id, action, resource_type, date_from/to

2. **GET /audit-logs/platform** (Super Admin)

### 15.16 Health/Status
1. **GET /health** (público)
2. **GET /health/detailed** (autenticado admin/super admin)

### 15.17 Compatibilidade IA legada
1. **POST /predict** (público/compatível atual)
2. **GET /health** já coberto acima

---

## 16) Padrões de request/response/error

### Sucesso (padrão)
```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": {},
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-04-29T12:00:00Z"
  }
}
```

### Erro (padrão)
```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid payload",
    "details": [
      {"field": "cpf", "issue": "invalid format"}
    ]
  },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-04-29T12:00:00Z"
  }
}
```

Códigos de erro recomendados:
- VALIDATION_ERROR (400)
- UNAUTHORIZED (401)
- FORBIDDEN (403)
- NOT_FOUND (404)
- CONFLICT (409)
- BUSINESS_RULE_VIOLATION (422)
- INTERNAL_ERROR (500)

---

## 17) Padrão de paginação, filtros e busca
- Query params padrão:
  - `page` (default 1)
  - `per_page` (default 20, max 100)
  - `sort_by`
  - `sort_order` (`asc|desc`)
  - `q` (busca textual)
- Response paginado:
```json
{
  "success": true,
  "data": [],
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 235,
    "total_pages": 12
  }
}
```

---

## 18) Padrão de nomenclatura DTOs/Schemas
- `CreateXRequestSchema`
- `UpdateXRequestSchema`
- `XResponseSchema`
- `XListItemSchema`
- `PaginatedXResponseSchema`

Exemplos:
- `CreatePatientRequestSchema`
- `MedicalRecordVersionResponseSchema`

---

## 19) Como o frontend Vue deve consumir
- Axios com interceptors:
  - inclui `Authorization: Bearer <token>`
  - inclui `X-Clinic-Id` da clínica ativa
  - renova token automático no 401 (refresh flow)
- Mapa de rotas frontend por módulo (auth, pacientes, agenda, prontuário, IA).
- Guard de rota por permissão (`meta.permissions`).
- Estratégia de cache simples por tela (SWR manual ou Pinia store).
- Upload via multipart para documentos e IA.

---

## 20) Ordem recomendada de implementação backend (1 mês)

### Semana 1
1. Base infra: DB + ORM + Alembic + config + app factory.
2. Auth (login, refresh, me) + RBAC base.
3. Clinics/Units/Users/Doctors/Specialties (CRUD essencial).

### Semana 2
4. Patients + vínculo multi-clínica.
5. Appointments + Schedule Blocks.
6. Audit log transversal mínimo.

### Semana 3
7. Medical Records + versionamento.
8. Documents upload/list.

### Semana 4
9. AI Analyses integrado ao serviço atual.
10. Dashboards básicos.
11. Hardening (validação, testes mínimos, OpenAPI).

---

## 21) Riscos técnicos
- Complexidade de autorização contextual (risco alto).
- Versionamento de prontuário mal definido pode gerar inconsistência.
- Upload local sem política de retenção pode crescer rapidamente.
- IA síncrona pode degradar latência em horário de pico.
- Falhas de isolamento multi-clínica por query sem `clinic_id`.

Mitigações:
- testes de permissão e tenancy obrigatórios.
- linters/review checklist para `clinic_id` em repositórios.
- limites de upload e validação MIME.

---

## 22) O que preservar da API atual
- Endpoint e contrato de `POST /api/v1/predict` atual.
- Endpoint `GET /api/v1/health` atual.
- Serviço de inferência em `prediction_service.py`.
- Estrutura de modelos/pesos em `src/models/`.
- Swagger em `/docs` (evoluir sem quebrar rota).

---

## 23) O que evitar para não quebrar frontend atual
- Não alterar path/método de `/api/v1/predict`.
- Não remover campo esperado no JSON de resposta atual de IA.
- Não exigir autenticação imediatamente no endpoint legado de predict (nesta transição).
- Evitar renomear `/api/v1/health`.

---

## 24) Próxima fase sugerida
1. Congelar este blueprint e validar com frontend.
2. Derivar backlog técnico em issues por módulo.
3. Definir OpenAPI inicial (`openapi.yaml`) com exemplos.
4. Implementar vertical slice: Auth -> Patients -> Appointment -> Medical Record -> AI Analysis.
5. Adicionar testes de contrato para impedir regressão do endpoint legado de IA.

---

## 25) Observações finais
- Este blueprint atende ao escopo de planejamento sem implementar funcionalidades.
- Mantém separação frontend/backend e preserva os endpoints atuais da IA.
- É viável para MVP intermediário em ~1 mês por 1 pessoa com foco disciplinado no escopo.
