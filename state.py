import json
import os

STATE_FILE = "state.json"


DEFAULT_STATE = {
    "study_blocks": {
        "block1": {
            "current_specialty": "cirurgia",
            "cirurgia_index": 0,
            "clinica_index": 0,
        },
        "block2": {
            "topic_index": 0
        },
        "block3": {
            "current_month_day": None,
            "completed_months": []
        },
        "block4": {
            "current_module": "dermatologia",
            "derma_index": 0,
            "resp_index": 0,
        }
    },
    "weekly_schedule": {},
    "revision_bank": {},
    "conversation_history": []
}

CIRURGIA_TOPICS = [
    "abdome agudo inflamatório", "abdome agudo isquêmico", "abdome agudo obstrutivo",
    "abdome agudo perfurativo", "abordagem inicial ao ABCDE", "afecções benignas das vias biliares",
    "afecções pancreáticas", "afecções urológicas benignas", "aneurismas", "cuidados pré-operatórios",
    "doença arterial periférica", "doença inflamatória intestinal", "hemorragia digestiva",
    "queimaduras", "síndrome disfágica", "síndrome dispéptica", "trauma abdominal",
    "trauma face e pescoço", "luxações e lesões ligamentares",
    "tendinites/tenossinovites/fasceítes/bursites", "polipose intestinal", "oftalmologia"
]

CLINICA_TOPICS = [
    "infecção do trato urinário", "parasitoses", "arritmia/síncope/PCR", "valvopatias",
    "HAS", "IC", "farmacodermia", "doenças infectoparasitárias com acometimento dermatológico",
    "diabetes", "demências", "cirrose/insuficiência hepática/hepatite", "infecções do SNC",
    "tuberculose", "pneumonia e síndromes gripais", "infecções de pele e partes moles",
    "HIV no adulto", "síndromes febris", "glomerulopatias", "DHE", "cefaleia",
    "síndromes neurológicas e fraqueza muscular", "AVC", "onco-hematologia",
    "anemia e hemoglobinopatias", "embolia pulmonar e hipertensão pulmonar",
    "distúrbios obstrutivos", "doenças pulmonares intersticiais",
    "artrites e diagnósticos diferenciais", "vasculites", "sepse", "infecções fúngicas",
    "tumores do SNC", "vertigens"
]

PSZ_TOPICS = [
    "queixas mais comuns no PS — parte 1 (de 2)", "queixas mais comuns no PS — parte 2 (de 2)",
    "emergências respiratórias", "emergências gastrointestinais e hepáticas",
    "emergências urológicas e nefrológicas", "emergências infecciosas",
    "emergências metabólicas e reumatológicas", "emergências hematológicas e oncológicas",
    "emergências psiquiátricas", "causas externas", "emergências cirúrgicas",
    "emergências vasculares", "emergências cardiológicas", "emergências neurológicas",
    "paciente grave", "atendimento ao trauma", "procedimentos", "intubação na emergência",
    "ventilação mecânica", "gasometria", "cuidados paliativos", "UTI"
]

DERMA_CLASSES = [
    "Aula 1 — Suspeição precoce (50min)",
    "Aula 2 — Hierarquização de hipóteses (55min)",
    "Aula 3 — Viés de ancoragem (55min)",
    "Aula 4 — A navalha de Ockham (55min)"
]

RESP_CLASSES = [f"Aula {i+1} — Módulo Respiratório (50min)" for i in range(5)]


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = _deep_merge(DEFAULT_STATE.copy(), data)
        return merged
    return _deep_copy(DEFAULT_STATE)


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, default=str)


def update_state(updates: dict) -> dict:
    state = load_state()
    _deep_merge(state, updates)
    save_state(state)
    return state


def format_state_for_prompt(state: dict) -> str:
    b1 = state["study_blocks"]["block1"]
    b2 = state["study_blocks"]["block2"]
    b4 = state["study_blocks"]["block4"]

    ci = b1["cirurgia_index"]
    cli = b1["clinica_index"]
    specialty = b1["current_specialty"]

    if specialty == "cirurgia":
        next_b1 = f"Cirurgia — {CIRURGIA_TOPICS[ci]}" if ci < len(CIRURGIA_TOPICS) else "Cirurgia CONCLUÍDA, iniciar Clínica Médica"
    else:
        next_b1 = f"Clínica Médica — {CLINICA_TOPICS[cli]}" if cli < len(CLINICA_TOPICS) else "Clínica Médica CONCLUÍDA"

    b2i = b2["topic_index"]
    next_b2 = PSZ_TOPICS[b2i] if b2i < len(PSZ_TOPICS) else "Bloco 2 CONCLUÍDO"

    b4_module = b4["current_module"]
    di = b4["derma_index"]
    ri = b4["resp_index"]
    if b4_module == "dermatologia":
        next_b4_1 = DERMA_CLASSES[di] if di < len(DERMA_CLASSES) else "Derma concluído — passar para Respiratório"
        next_b4_2 = DERMA_CLASSES[di + 1] if di + 1 < len(DERMA_CLASSES) else "—"
    elif b4_module == "respiratorio":
        next_b4_1 = RESP_CLASSES[ri] if ri < len(RESP_CLASSES) else "Respiratório concluído"
        next_b4_2 = RESP_CLASSES[ri + 1] if ri + 1 < len(RESP_CLASSES) else "—"
    else:
        next_b4_1 = "TODOS OS MÓDULOS CONCLUÍDOS"
        next_b4_2 = "—"

    revision_bank = state.get("revision_bank", {})
    if revision_bank:
        rev_lines = []
        for area, topics in revision_bank.items():
            if topics:
                rev_lines.append(f"  {area}: {', '.join(topics)}")
        rev_str = "\n".join(rev_lines) if rev_lines else "  (vazio)"
    else:
        rev_str = "  (vazio)"

    weekly = state.get("weekly_schedule", {})
    weekly_str = json.dumps(weekly, ensure_ascii=False) if weekly else "{}"

    return f"""Bloco 1 próxima sessão: {next_b1}
  (Cirurgia: {ci}/{len(CIRURGIA_TOPICS)} | Clínica: {cli}/{len(CLINICA_TOPICS)})
Bloco 2 próxima sessão: {next_b2} (índice {b2i}/{len(PSZ_TOPICS)})
Bloco 4 próximas 2 aulas: {next_b4_1} / {next_b4_2} (módulo: {b4_module})
Distribuição semanal registrada: {weekly_str}
Banco de revisões:
{rev_str}"""


def _deep_merge(base: dict, updates: dict) -> dict:
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _deep_copy(obj):
    return json.loads(json.dumps(obj))
