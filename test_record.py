import requests

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJmcmVzaCI6ZmFsc2UsImlhdCI6MTc3NzQ4NzE4NCwianRpIjoiNjc0YmYxMDUtYzMzYy00MTNkLTkyOGItZTRmMDhmMjE0ZmIyIiwidHlwZSI6ImFjY2VzcyIsInN1YiI6IjMiLCJuYmYiOjE3Nzc0ODcxODQsImNzcmYiOiI4NWZiMGU5YS00OGI0LTQ2NjYtYTViNC0zZTgxZWI4Y2JiZjQiLCJleHAiOjE3Nzc0ODgwODQsInJvbGUiOiJET0NUT1IiLCJjbGluaWNfaWQiOjF9.lVnXSI5SsMKmf1EjLTUJPwAKmw885DrOf5fEoUFtRjE"

payload = {
    "patient_id": 1,
    "appointment_id": 1,
    "anamnesis": "Paciente relata alteracao em pinta no braco ha algumas semanas.",
    "physical_exam": "Lesao pigmentada assimetrica em membro superior.",
    "diagnostic_hypothesis": "Nevo atipico; avaliar melanoma.",
    "diagnosis": "Em avaliacao.",
    "conduct": "Solicitada analise complementar por IA.",
    "prescriptions": "Fotoprotecao.",
    "exams_requested": "Dermatoscopia.",
    "evolution": "Primeiro registro."
}

response = requests.post(
    "http://localhost:5000/api/v1/medical-records",
    headers={"Authorization": f"Bearer {TOKEN}"},
    json=payload
)

print(response.status_code)
print(response.text)