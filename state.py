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


def advance_block(block: str, steps: int = 1) -> None:
    state = load_state()
    b1 = state["study_blocks"]["block1"]
    b2 = state["study_blocks"]["block2"]
    b4 = state["study_blocks"]["block4"]

    if block == "block1_cirurgia":
        b1["cirurgia_index"] = min(b1["cirurgia_index"] + steps, len(CIRURGIA_TOPICS))
        if b1["cirurgia_index"] >= len(CIRURGIA_TOPICS):
            b1["current_specialty"] = "clinica"
    elif block == "block1_clinica":
        b1["clinica_index"] = min(b1["clinica_index"] + steps, len(CLINICA_TOPICS))
    elif block == "block2":
        b2["topic_index"] = min(b2["topic_index"] + steps, len(PSZ_TOPICS))
    elif block == "block4_derma":
        b4["derma_index"] = min(b4["derma_index"] + steps, len(DERMA_CLASSES))
        if b4["derma_index"] >= len(DERMA_CLASSES):
            b4["current_module"] = "respiratorio"
    elif block == "block4_resp":
        b4["resp_index"] = min(b4["resp_index"] + steps, len(RESP_CLASSES))
        if b4["resp_index"] >= len(RESP_CLASSES):
            b4["current_module"] = "done"

    save_state(state)


def add_to_revision_bank(area: str, topic: str) -> None:
    state = load_state()
    bank = state.setdefault("revision_bank", {})
    topics = bank.setdefault(area, [])
    if topic not in topics:
        topics.append(topic)
    save_state(state)


def remove_from_revision_bank(area: str, topic: str) -> None:
    state = load_state()
    bank = state.get("revision_bank", {})
    if area in bank and topic in bank[area]:
        bank[area].remove(topic)
        if not bank[area]:
            del bank[area]
    save_state(state)


# ── Rastreamento de atividades ────────────────────────────────────────────────

ACTIVITY_GOALS = {"academia": 2, "yoga": 3, "estudo": 3}


def record_activities(date_str: str, academia: bool, yoga: bool, estudo: bool) -> None:
    state = load_state()
    tracking = state.setdefault("activity_tracking", {"days": {}})
    tracking["days"][date_str] = {
        "academia": academia,
        "yoga": yoga,
        "estudo": estudo,
    }
    save_state(state)


def get_weekly_summary_data(week_start_date) -> dict:
    """Retorna contagem de atividades para a semana a partir de week_start_date (date)."""
    from datetime import timedelta
    state = load_state()
    days = state.get("activity_tracking", {}).get("days", {})
    counts = {"academia": 0, "yoga": 0, "estudo": 0}
    for i in range(7):
        d = (week_start_date + timedelta(days=i)).strftime("%Y-%m-%d")
        if d in days:
            for activity in counts:
                if days[d].get(activity):
                    counts[activity] += 1
    return counts


def get_week_so_far_data(today) -> dict:
    """Retorna contagem de atividades desde a segunda-feira até hoje."""
    from datetime import timedelta
    monday = today - timedelta(days=today.weekday())
    return get_weekly_summary_data(monday)
