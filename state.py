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
    "conversation_history": [],
    "finances": {
        "monthly_limit": 10000.0,
        "current_invoice": 0.0,
        "expenses": {},
        "invoice_history": {},
    },
    "gym": {
        "current_plan": "A",
        "active_session": None,
        "history": [],
    }
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

    # Financial summary
    fin_summary = get_financial_summary_from_state(state)
    fin_str = (
        f"Limite: {fmt_brl(fin_summary['limit'])} | "
        f"Fatura: {fmt_brl(fin_summary['invoice'])} | "
        f"Budget livre: {fmt_brl(fin_summary['available_free'])} | "
        f"Gasto no ciclo: {fmt_brl(fin_summary['total_cycle'])} ({fin_summary['pct_used']}%) | "
        f"{'🚨 NEGATIVO' if fin_summary['is_negative'] else 'Disponível'}: {fmt_brl(abs(fin_summary['remaining']))} | "
        f"Ciclo desde: {fin_summary['cycle_start']}"
    )

    # Gym state
    gym = state.get("gym", {})
    next_plan = gym.get("current_plan", "A")
    active_session = gym.get("active_session")
    gym_exercises = GYM_PLANS[next_plan]
    gym_lines = [f"  {i}. {ex['name']} — {ex['sets']}" for i, ex in enumerate(gym_exercises, 1)]
    gym_str = f"Próximo treino: {'**Treino ' + next_plan + '**'}\n" + "\n".join(gym_lines)
    if active_session:
        gym_str += f"\n  (Sessão ativa: Treino {active_session['plan']} em andamento)"

    return f"""Bloco 1 próxima sessão: {next_b1}
  (Cirurgia: {ci}/{len(CIRURGIA_TOPICS)} | Clínica: {cli}/{len(CLINICA_TOPICS)})
Bloco 2 próxima sessão: {next_b2} (índice {b2i}/{len(PSZ_TOPICS)})
Bloco 4 próximas 2 aulas: {next_b4_1} / {next_b4_2} (módulo: {b4_module})
Distribuição semanal registrada: {weekly_str}
Banco de revisões:
{rev_str}
Controle financeiro: {fin_str}
Academia: {gym_str}"""


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


# ── Planos de treino ─────────────────────────────────────────────────────────

GYM_PLANS = {
    "A": [
        {"name": "Leg Press 90°",                  "sets": "3x (15→12→10)"},
        {"name": "Cadeira Extensora",               "sets": "3x (15→12→10)"},
        {"name": "Remada Baixa com Haste V",        "sets": "3x (15→12→10)"},
        {"name": "Tríceps Corda",                   "sets": "3x (15→12→10)"},
        {"name": "Elevação Quadril com Peso Livre", "sets": "3x (15→12→10)"},
        {"name": "Pullover no Chão",                "sets": "3x (15→12→10)"},
        {"name": "Panturrilha",                     "sets": "3x máximo"},
    ],
    "B": [
        {"name": "Cadeira Flexora",                   "sets": "3x (15→12→10)"},
        {"name": "Abdução de Quadril",                "sets": "3x (15→12→10)"},
        {"name": "Supino no Aparelho",                "sets": "3x (15→12→10)"},
        {"name": "Desenvolvimento Máquina",           "sets": "3x (15→12→10)"},
        {"name": "Abdução Concha com Miniband",       "sets": "3x (15→12→10)"},
        {"name": "Puxar Elástico na Linha do Peito",  "sets": "3x (15→12→10)"},
        {"name": "Sit Up com Pés Apoiados",           "sets": "3x10"},
    ],
}


def _default_gym() -> dict:
    return {"current_plan": "A", "active_session": None, "history": []}


def start_gym_session(plan: str = None) -> dict:
    """Inicia sessão de treino. Retorna a sessão criada."""
    import pytz, datetime as _dt
    from config import TIMEZONE
    state = load_state()
    gym = state.setdefault("gym", _default_gym())
    if plan is None:
        plan = gym.get("current_plan", "A")
    date_str = _dt.datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
    session = {"date": date_str, "plan": plan, "loads": {}, "completed": False}
    gym["active_session"] = session
    save_state(state)
    return session


def get_active_gym_session() -> dict:
    return load_state().get("gym", {}).get("active_session")


def record_exercise_load(exercise_num: int, weight: float) -> str:
    """Registra carga de um exercício. Retorna nome do exercício."""
    state = load_state()
    gym = state.setdefault("gym", _default_gym())
    session = gym.get("active_session")
    if not session:
        return None
    session["loads"][str(exercise_num)] = weight
    gym["active_session"] = session
    save_state(state)
    return GYM_PLANS[session["plan"]][exercise_num - 1]["name"]


def finish_gym_session() -> tuple:
    """Finaliza sessão ativa. Retorna (sessão_concluída, sessão_anterior_do_mesmo_plano)."""
    state = load_state()
    gym = state.setdefault("gym", _default_gym())
    session = gym.get("active_session")
    if not session:
        return None, None
    # Pega sessão anterior ANTES de salvar a atual
    prev = _get_prev_session(gym, session["plan"])
    session["completed"] = True
    gym.setdefault("history", []).append(session)
    gym["active_session"] = None
    gym["current_plan"] = "B" if session["plan"] == "A" else "A"
    save_state(state)
    return session, prev


def get_last_gym_session(plan: str) -> dict:
    """Retorna a última sessão concluída de um plano."""
    gym = load_state().get("gym", _default_gym())
    return _get_prev_session(gym, plan)


def _get_prev_session(gym: dict, plan: str) -> dict:
    for s in reversed(gym.get("history", [])):
        if s.get("plan") == plan and s.get("completed"):
            return s
    return None


def get_gym_progression(plan: str) -> list:
    """Retorna histórico de cargas de todas as sessões de um plano."""
    gym = load_state().get("gym", _default_gym())
    return [s for s in gym.get("history", []) if s.get("plan") == plan and s.get("completed")]


# ── Utilitários de formatação ─────────────────────────────────────────────────

def fmt_brl(amount: float) -> str:
    """Formata float como moeda brasileira, ex: R$1.200,50"""
    return "R${:,.2f}".format(amount).replace(",", "X").replace(".", ",").replace("X", ".")


# ── Controle financeiro ───────────────────────────────────────────────────────

def get_cycle_start(today=None):
    """Retorna a data de início do ciclo financeiro atual (dia 28 do mês anterior ou atual)."""
    from datetime import date
    if today is None:
        import pytz
        from config import TIMEZONE
        import datetime as _dt
        tz = pytz.timezone(TIMEZONE)
        today = _dt.datetime.now(tz).date()
    if today.day >= 28:
        return today.replace(day=28)
    else:
        if today.month == 1:
            return today.replace(year=today.year - 1, month=12, day=28)
        else:
            return today.replace(month=today.month - 1, day=28)


def set_invoice(amount: float) -> None:
    """Define o valor da fatura do cartão do mês atual."""
    import pytz
    import datetime as _dt
    from config import TIMEZONE
    state = load_state()
    fin = state.setdefault("finances", _default_finances())
    fin["current_invoice"] = amount
    tz = pytz.timezone(TIMEZONE)
    month_key = _dt.datetime.now(tz).strftime("%Y-%m")
    fin.setdefault("invoice_history", {})[month_key] = amount
    save_state(state)


def record_expense(amount: float, note: str = "", date_str: str = None) -> dict:
    """Registra um gasto e retorna o resumo financeiro atualizado."""
    import pytz
    import datetime as _dt
    from config import TIMEZONE
    state = load_state()
    fin = state.setdefault("finances", _default_finances())
    if date_str is None:
        tz = pytz.timezone(TIMEZONE)
        date_str = _dt.datetime.now(tz).strftime("%Y-%m-%d")
    day_expenses = fin.setdefault("expenses", {}).setdefault(date_str, [])
    day_expenses.append({"amount": amount, "note": note})
    save_state(state)
    return get_financial_summary_from_state(state)


def get_financial_summary(today=None) -> dict:
    """Retorna o resumo financeiro do ciclo atual."""
    state = load_state()
    return get_financial_summary_from_state(state, today)


def get_financial_summary_from_state(state: dict, today=None) -> dict:
    import datetime as _dt
    import pytz
    from config import TIMEZONE
    tz = pytz.timezone(TIMEZONE)
    if today is None:
        today = _dt.datetime.now(tz).date()

    fin = state.get("finances", _default_finances())
    limit = fin.get("monthly_limit", 10000.0)
    invoice = fin.get("current_invoice", 0.0)
    expenses = fin.get("expenses", {})

    cycle_start = get_cycle_start(today)
    yesterday = today - _dt.timedelta(days=1)

    total_cycle = 0.0
    yesterday_total = 0.0
    d = cycle_start
    while d <= today:
        d_str = d.strftime("%Y-%m-%d")
        day_sum = sum(e["amount"] for e in expenses.get(d_str, []))
        total_cycle += day_sum
        if d == yesterday:
            yesterday_total = day_sum
        d += _dt.timedelta(days=1)

    available_free = max(limit - invoice, 0.0)
    remaining = available_free - total_cycle
    pct_used = round(total_cycle / available_free * 100) if available_free > 0 else 0

    return {
        "limit": limit,
        "invoice": invoice,
        "available_free": available_free,
        "total_cycle": total_cycle,
        "remaining": remaining,
        "pct_used": pct_used,
        "yesterday_total": yesterday_total,
        "cycle_start": cycle_start.strftime("%d/%m/%Y"),
        "is_negative": remaining < 0,
    }


def _default_finances() -> dict:
    return {
        "monthly_limit": 10000.0,
        "current_invoice": 0.0,
        "expenses": {},
        "invoice_history": {},
    }


def get_monthly_summary_data(year: int, month: int) -> dict:
    """
    Retorna contagem de dias com cada atividade no mês especificado.
    Inclui total de dias registrados.
    """
    import calendar as cal_mod
    state = load_state()
    days = state.get("activity_tracking", {}).get("days", {})
    counts = {"academia": 0, "yoga": 0, "estudo": 0, "dias_registrados": 0}
    days_in_month = cal_mod.monthrange(year, month)[1]
    for day in range(1, days_in_month + 1):
        date_str = f"{year:04d}-{month:02d}-{day:02d}"
        if date_str in days:
            counts["dias_registrados"] += 1
            for activity in ("academia", "yoga", "estudo"):
                if days[date_str].get(activity):
                    counts[activity] += 1
    return counts
