# Agenda, disponibilidade e reagendamentos

## Convenções

- A API canônica local é `http://localhost:5000/api/v1`; o frontend usa `VITE_API_BASE_URL`.
- Intervalos são semiabertos: `start_a < end_b && end_a > start_b`.
- `weekday` segue ISO 8601: `1` é segunda-feira e `7` é domingo.
- Slots começam no início de cada faixa e avançam em uma grade isolada de 30 minutos.
- O schema legado não possui fuso por clínica; horários de agenda são tratados como horário civil local (naive). Configurações multi-fuso exigirão adicionar o fuso da clínica antes de converter para UTC.
- Consultas novas exigem `duration_minutes`, exclusivamente `30` ou `60`. Consultas legadas recebem `30` na migration.
- Ocupam agenda os status `SCHEDULED`, `CONFIRMED`, `IN_PROGRESS` e `RESCHEDULED`. `COMPLETED`, `CANCELLED` e `NO_SHOW` não ocupam slots futuros.

## Endpoints

### Disponibilidade semanal

- `GET /doctor-availabilities?doctor_profile_id=` — médico vê apenas a própria; admin vê médicos da clínica.
- `POST /doctor-availabilities` — `{doctor_profile_id?, weekday, start_time: "HH:MM", end_time: "HH:MM"}`.
- `PUT /doctor-availabilities/{id}` — mesmo formato.
- `DELETE /doctor-availabilities/{id}`.
- `GET /doctor-availabilities/slots?doctor_profile_id=&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&duration_minutes=` — no máximo 31 dias.

Faixas adjacentes são aceitas; faixas sobrepostas e faixas que cruzam meia-noite são rejeitadas. Médico nunca escolhe outro perfil. Recepção acessa somente slots calculados e recebe `403` nos endpoints de escrita.

### Consultas

`POST /appointments` agora exige:

```json
{
  "patient_id": 1,
  "doctor_profile_id": 2,
  "scheduled_at": "2026-10-05T09:00:00",
  "duration_minutes": 60,
  "notes": "opcional"
}
```

Criação e `PUT /appointments/{id}/reschedule` revalidam clínica, paciente, médico, duração, contenção integral na disponibilidade, bloqueios e consultas ativas. Reagendamento preserva a duração quando ela é omitida. A confirmação resolve uma pendência aberta na mesma transação.

### Bloqueios

- CRUD: `GET|POST /schedule-blocks` e `PUT|DELETE /schedule-blocks/{id}`.
- Parcial: envie `start_time` e `end_time`.
- Dia inteiro ou vários dias: envie `all_day: true`, `start_date` e `end_date`. `end_date` é inclusiva na API e vira internamente o início do dia seguinte, mantendo o intervalo semiaberto.

Bloqueios não movem ou cancelam consultas. Criação/edição retorna `affected_appointments` e cria ou atualiza uma única pendência aberta por consulta. Cada pendência guarda o tipo e o identificador da entidade que a originou; ao mover, reduzir ou remover um bloqueio, a pendência é encerrada somente se a consulta não continuar inválida por disponibilidade, outro bloqueio ou conflito ativo.

### Fila interna

- `GET /reschedule-pendings` — pendências abertas da clínica por padrão.
- `GET /reschedule-pendings/count` — contador persistente.
- `GET /reschedule-pendings/{id}/suggestions` — até 10 slots nos próximos 60 dias, mesmo médico e duração.

A fila contém somente dados operacionais (paciente, médico, horário, duração e motivo); não serializa prontuários, diagnóstico, documentos ou IA. É visível a `RECEPTIONIST` e `CLINIC_ADMIN`.

## Autorização e concorrência

- `DOCTOR`: CRUD da própria disponibilidade e dos próprios bloqueios; própria agenda.
- `CLINIC_ADMIN`: agenda, disponibilidade, bloqueios e fila somente da própria clínica.
- `RECEPTIONIST`: leitura de slots, criação/reagendamento e fila; nunca escreve disponibilidade ou bloqueios.
- `SUPER_ADMIN`: preserva leituras globais existentes; operações que precisam de escopo exigem `clinic_id` explícito, sem escolher clínica arbitrariamente.

As mutações relacionadas usam uma transação e repetem a validação antes do commit. Falhas de SQLAlchemy/integridade executam rollback e retornam erro controlado; constraints e índices protegem os domínios persistidos e a unicidade de pendência aberta. SQLite ainda não oferece bloqueio de linha equivalente ao PostgreSQL; em alta concorrência, a implantação deve preferir PostgreSQL e pode complementar com isolamento/locking específico do banco.

## Erros

- `400`: payload, ID ou data malformados; contexto de clínica global ausente.
- `403`: perfil sem permissão.
- `404`: recurso inexistente ou fora do escopo, sem enumeração entre clínicas.
- `409`: colisão com bloqueio, consulta ou faixa semanal.
- `422`: duração ou regra de intervalo inválida, inclusive consulta parcialmente fora da disponibilidade.
