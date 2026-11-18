"""
ZeroDrop — models.py (v4 · Dynamic Care Navigator + Operational AI Watchdog)
Models, contextual state machine, deterministic watchdog rules and FastAPI routes.
Run:  uvicorn models:app --reload --port 8000

Operational tool only: not SaMD, no clinical inference. All "AI" is transparent,
threshold-based rules (time elapsed, missed calls, dwell limits, rejections).
Identifiers are tokenised. All Malaffi integrations are simulated.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ═══════════════ CONSTANTS ═══════════════
# Stage indices are unchanged (Stage 4 = consult, Stage 6 = closed).
# Index 2 is now ESCALATED_UNREACHABLE (the former offline-fallback stage).
STAGES = ["ISSUED", "PATIENT_NOTIFIED", "ESCALATED_UNREACHABLE", "PATIENT_ACKNOWLEDGED",
          "CLINICIAN_CONSULT", "REFERRAL_ACCEPTED", "CLOSED_VERIFIED"]
STAGE_DISPLAY = ["Result Issued", "Patient Notified", "Escalated: Unreachable", "Acknowledged",
                 "Clinician Consult", "Referral Accepted", "Closed & Verified"]
STAGE_OWNER = ["Lab Director", "Patient Navigator", "Call Centre Coordinator", "Patient",
               "Primary Physician", "Specialist Coordinator", "Case Owner"]
MISSED = "MISSED_APPOINTMENT_RECOVERY"          # side-branch of stage 4
MAX_CALL_ATTEMPTS = 3
CLOSURE_EVIDENCE_OPTIONS = [
    "— Select closure evidence type —",
    "Confirmatory laboratory result attached",
    "Specialist appointment attended and documented",
    "Clinician discharge summary uploaded to Malaffi",
    "Patient declined — informed refusal on record",
    "Referred to specialist — case formally transferred",
]

# Watchdog thresholds (all tunable, all shown to the UI for explainability)
ELDERLY_AGE = 65
RISK_ALERT_PCT = 50
RISK_HIGH_PCT = 70
OWNER_ACCEPT_MIN = 30
REFERRAL_RESPONSE_H = 2
DWELL_LIMIT_H = {0: 1, 1: 4, 2: 8, 3: 6, 4: 24, 5: 48}
TS_FMT = "%H:%M  %d %b %Y"

DISCLAIMER = ("ZeroDrop is an operational workflow orchestration and SLA tracking platform. It is not a "
              "Software as a Medical Device (SaMD) and makes no clinical diagnoses. Designed for alignment "
              "with UAE Federal Decree-Law No. 45 of 2021 (PDPL) and ADHICS. Malaffi integrations are simulated.")

# ═══════════════ BILINGUAL MESSAGES (pre-validated, non-diagnostic) ═══════════════
_ACT_EN = "Please confirm below that you have read and understood this message."
_ACT_AR = "يرجى التأكيد أدناه على أنك قرأت هذه الرسالة وفهمت مضمونها."
BILINGUAL_MESSAGES: dict = {
    "ZD-901": {
        "en": {"title": "Your Genetic Screening Result",
               "body": "Your genetic screening has been completed. The result needs a brief conversation with one of our specialists. This does not mean you are unwell. A counselor will explain what this means for you and your family and answer any questions you have. No decision needs to be made today.",
               "action": _ACT_EN,
               "disclaimer": "This message is for information only. It does not constitute a diagnosis or medical advice."},
        "ar": {"title": "نتيجة الفحص الجيني",
               "body": "تم إجراء الفحص الجيني الخاص بك. تستدعي النتيجة إجراء محادثة مع أحد متخصصينا. لا يعني ذلك أنك مريض. سيشرح لك المستشار ما يعنيه هذا بالنسبة لك ولعائلتك ويجيب على تساؤلاتك. لا حاجة لاتخاذ أي قرار اليوم.",
               "action": _ACT_AR, "disclaimer": "هذه الرسالة للإعلام فقط. لا تُشكّل تشخيصاً أو نصيحة طبية."},
    },
    "ZD-902": {
        "en": {"title": "Your Breast Screening Requires Attention",
               "body": "Your recent breast screening identified a finding our care team would like to discuss with you. This is not a diagnosis. We want to make sure you receive the right follow-up care promptly. Your doctor will contact you within 24 hours to explain the next steps.",
               "action": _ACT_EN,
               "disclaimer": "Your privacy is protected. This information is shared only with your authorised care team."},
        "ar": {"title": "فحص الثدي يحتاج إلى اهتمام",
               "body": "كشف فحص الثدي الأخير عن نتيجة يود فريق رعايتنا مناقشتها معك. هذا ليس تشخيصاً. نريد التأكد من حصولك على المتابعة المناسبة في الوقت المناسب. سيتصل بك طبيبك خلال 24 ساعة لشرح الخطوات التالية.",
               "action": _ACT_AR, "disclaimer": "خصوصيتك محمية. تُشارَك هذه المعلومات فقط مع فريق رعايتك المُعتمد."},
    },
    "ZD-903": {
        "en": {"title": "Your Newborn Screening Update",
               "body": "The newborn screening for your baby has returned a result our paediatric team would like to review with you. This type of finding is common and often requires simple, straightforward steps. A specialist will contact you to arrange a convenient appointment.",
               "action": _ACT_EN,
               "disclaimer": "Early follow-up gives your baby the best possible outcome. This message is for information only."},
        "ar": {"title": "تحديث فحص حديث الولادة",
               "body": "أعاد فحص طفلك حديث الولادة نتيجة يود فريق طب الأطفال مراجعتها معك. هذا النوع من النتائج شائع وغالباً ما يتطلب خطوات بسيطة ومباشرة. سيتواصل معك أخصائي لترتيب موعد في وقت مناسب.",
               "action": _ACT_AR, "disclaimer": "المتابعة المبكرة تمنح طفلك أفضل النتائج. هذه الرسالة للإعلام فقط."},
    },
    "ZD-904": {
        "en": {"title": "Your Health Check Results",
               "body": "Your comprehensive health check identified some factors our team would like to discuss with you. These are manageable with the right guidance and support. Your care navigator will contact you to book a consultation at a time that suits you.",
               "action": _ACT_EN,
               "disclaimer": "Taking action now can significantly improve your long-term health. This message is for information only."},
        "ar": {"title": "نتائج الفحص الصحي الشامل",
               "body": "كشف الفحص الصحي الشامل عن بعض العوامل التي يود فريقنا مناقشتها معك. يمكن التعامل معها بالتوجيه والدعم المناسبين. سيتواصل معك منسق الرعاية لحجز استشارة في الوقت المناسب.",
               "action": _ACT_AR, "disclaimer": "اتخاذ الإجراء الآن يحسّن صحتك على المدى البعيد. هذه الرسالة للإعلام فقط."},
    },
}


def bilingual(cid: str) -> dict:
    return {lang: {**v, "disc": v["disclaimer"]} for lang, v in BILINGUAL_MESSAGES.get(cid, {}).items()}


# ═══════════════ FHIR R4 MOCK PAYLOADS (simulated Malaffi, no real data) ═══════════════
def _meta(t): return {"profile": [f"http://hl7.org/fhir/StructureDefinition/{t}"]}
def _cd(sys, code, disp): return {"coding": [{"system": sys, "code": code, "display": disp}]}

FHIR_PAYLOADS: dict = {
    "ZD-901": {"resourceType": "Observation", "id": "SR-2026-ZD-901-BTC", "meta": _meta("Observation"), "status": "final",
               "code": _cd("http://snomed.info/sct", "413427002", "Beta-thalassemia carrier status"),
               "subject": {"reference": "Patient/EID-784-XXXX-XXXX-3", "display": "Tokenised Patient (ZD-901)"},
               "performer": [{"reference": "Organization/SEHA-Central-Lab"}],
               "valueCodeableConcept": {"coding": [{"code": "carrier", "display": "Carrier status confirmed"}]},
               "note": [{"text": "FHIR R4 compliant resource. Malaffi HIE simulated endpoint. No raw PII transmitted or stored."}]},
    "ZD-902": {"resourceType": "DiagnosticReport", "id": "SR-2026-ZD-902-BRCA", "meta": _meta("DiagnosticReport"), "status": "final",
               "code": _cd("http://loinc.org", "24606-6", "Mammography screening study"),
               "subject": {"reference": "Patient/EID-784-XXXX-XXXX-7", "display": "Tokenised Patient (ZD-902)"},
               "performer": [{"reference": "Organization/Mubadala-Breast-Care"}],
               "conclusion": "BI-RADS Category 4 — Suspicious. Tissue biopsy recommended.",
               "note": [{"text": "FHIR R4 compliant. Priority escalation trigger activated."}]},
    "ZD-903": {"resourceType": "Observation", "id": "SR-2026-ZD-903-PKU", "meta": _meta("Observation"), "status": "final",
               "code": _cd("http://snomed.info/sct", "360257000", "Phenylalanine measurement"),
               "subject": {"reference": "Patient/EID-784-XXXX-XXXX-1", "display": "Tokenised Patient (ZD-903)"},
               "performer": [{"reference": "Organization/SEHA-Neonatal-Lab"}],
               "valueQuantity": {"value": 18.4, "unit": "mg/dL", "system": "http://unitsofmeasure.org", "code": "mg/dL"},
               "interpretation": [{"coding": [{"code": "H", "display": "Above reference range"}]}],
               "note": [{"text": "Elevated phenylalanine on day-3 heel-prick. Metabolic specialist referral triggered automatically."}]},
    "ZD-904": {"resourceType": "RiskAssessment", "id": "SR-2026-ZD-904-CVD", "meta": _meta("RiskAssessment"), "status": "final",
               "code": _cd("http://snomed.info/sct", "718687005", "Cardiovascular risk assessment"),
               "subject": {"reference": "Patient/EID-784-XXXX-XXXX-9", "display": "Tokenised Patient (ZD-904)"},
               "performer": {"reference": "Organization/SEHA-Wellness-Centre"},
               "prediction": [{"outcome": {"text": "10-year cardiovascular event risk"}, "probabilityDecimal": 0.11,
                               "qualitativeRisk": {"text": "High — SCORE2 >= 10%"}}],
               "note": [{"text": "Lifestyle counselling and pharmacotherapy discussion indicated. Referral to Mubadala Cardiology recommended."}]},
}


# ═══════════════ HELPERS ═══════════════
def now_() -> datetime: return datetime.now().replace(microsecond=0)
def hrs(a: datetime, b: datetime) -> float: return (b - a).total_seconds() / 3600
def slot(n: datetime, days: int) -> datetime:      # mock appointment slot: 09:00, N days ahead
    return (n + timedelta(days=days)).replace(hour=9, minute=0, second=0)


# ═══════════════ MODELS ═══════════════
class Event(BaseModel):
    stage: int
    ts: str
    actor: str
    desc: str


class Case(BaseModel):
    id: str
    eid: str                         # tokenised Emirates ID
    pathway: str
    condition: str
    stage: int = 0
    priority: str = "NORMAL"
    provider_chain: List[str]
    referral_start: int              # index of first specialist in chain
    referral_idx: int                # current referral target pointer
    sla_total: int                   # minutes
    sla_deadline: datetime
    owner: str
    owner_accepted: bool = False
    patient_token: str
    fhir_id: str
    patient_age: int
    missed_calls: int = 0
    no_show_count: int = 0
    branch: str = ""                 # "" | MISSED_APPOINTMENT_RECOVERY
    escalated: bool = False
    navigator_dispatched: bool = False
    issued_at: datetime
    stage_entered_at: datetime
    last_contact_at: Optional[datetime] = None
    appointment: Optional[datetime] = None
    appointment_status: str = "NONE"   # NONE | SCHEDULED | ATTENDED | MISSED
    referral_status: str = "NONE"      # NONE | PENDING | ACCEPTED | EXHAUSTED
    referral_since: Optional[datetime] = None
    rejected_by: List[str] = []
    closure_token: str = ""
    closure_evidence: str = ""
    timeline: List[Event] = []

    def note(self, actor: str, desc: str, n: datetime) -> None:
        self.timeline.append(Event(stage=self.stage, ts=n.strftime(TS_FMT), actor=actor, desc=desc))

    def enter(self, stage: int, n: datetime) -> None:
        self.stage, self.stage_entered_at = stage, n
        self.sla_deadline = n + timedelta(minutes=self.sla_total)

    def reset_sla(self, n: datetime) -> None:
        self.sla_deadline = n + timedelta(minutes=self.sla_total)

    def sla_fraction(self, n: datetime) -> float:
        return max(0.0, min(1.0, (self.sla_deadline - n).total_seconds() / (self.sla_total * 60)))

    def state(self) -> str: return self.branch or STAGES[self.stage]
    def target(self) -> Optional[str]:
        return self.provider_chain[self.referral_idx] if self.referral_idx < len(self.provider_chain) else None

    def bump_priority(self) -> None:
        order = ["NORMAL", "HIGH", "CRITICAL"]
        self.priority = order[min(order.index(self.priority) + 1, 2)]


# ═══════════════ CONTEXTUAL ACTIONS (replaces the single "advance" button) ═══════════════
def _a(key, label, style): return {"key": key, "label": label, "style": style}


def available_actions(c: Case) -> List[dict]:
    s, out = c.stage, []
    if s == 0:
        out.append(_a("dispatch_notification", "Dispatch Notification", "primary"))
    elif s == 1:
        out += [_a("log_call_no_answer", f"Log Call – No Answer ({c.missed_calls}/{MAX_CALL_ATTEMPTS})", "danger"),
                _a("patient_reached", "Patient Reached", "green")]
    elif s == 2:
        out.append(_a("confirm_verbal_ack", "Confirm Verbal Acknowledgement", "primary"))
    elif s == 3:
        out.append(_a("start_consult", "Begin Clinician Consult", "primary"))
    elif s == 4:
        if c.branch == MISSED:
            out.append(_a("reschedule_appointment", "Reschedule (Recovery)", "primary"))
        elif c.appointment_status == "NONE":
            out.append(_a("schedule_appointment", "Schedule Appointment", "primary"))
        elif c.appointment_status == "SCHEDULED":
            out += [_a("mark_attended", "Mark Attended", "green"), _a("mark_no_show", "Log No-Show", "danger"),
                    _a("reschedule_appointment", "Reschedule", "secondary")]
        elif c.appointment_status == "ATTENDED":
            if c.referral_status == "NONE":
                out.append(_a("submit_referral", f"Submit Referral → {c.target() or '—'}", "primary"))
            elif c.referral_status == "PENDING":
                out += [_a("provider_accepts", "Provider Accepts", "green"),
                        _a("provider_rejects", "Provider Rejects (Capacity Full)", "danger")]
            elif c.referral_status == "EXHAUSTED":
                out.append(_a("restart_referral_chain", "Restart Referral Chain", "secondary"))
    if 1 <= s <= 4 and not c.navigator_dispatched:
        out.append(_a("dispatch_navigator", "Dispatch Physical Navigator", "secondary"))
    return out                       # stage 5 → Closure Lock only; stage 6 → none


def _r(level, msg, toast=False): return {"level": level, "message": msg, "toast": toast}


def reroute_referral(c: Case, n: datetime, actor: str = "Routing Agent") -> dict:
    """Capacity bounce: specialist rejects → auto-route to next provider in chain."""
    rejected = c.target()
    c.rejected_by.append(rejected)
    c.referral_idx += 1
    c.reset_sla(n)
    nxt = c.target()
    if nxt is None:
        c.referral_status = "EXHAUSTED"
        c.note(actor, f"{rejected} rejected referral (capacity full). No further providers — manual placement required.", n)
        return _r("error", f"{c.id} · {rejected} at capacity · provider chain exhausted", True)
    c.referral_status, c.referral_since = "PENDING", n
    c.note(actor, f"{rejected} rejected referral (capacity full). Auto-rerouted to {nxt}. SLA reset.", n)
    return _r("action", f"{c.id} · {rejected} at capacity → auto-rerouted to {nxt} · SLA reset", True)


def apply_action(c: Case, key: str, actor: str, n: datetime) -> dict:
    if key not in {a["key"] for a in available_actions(c)}:
        raise HTTPException(409, f"Action '{key}' is not permitted in state {c.state()}.")
    if key == "dispatch_notification":
        c.enter(1, n)
        c.note("Patient Navigator — System", "Bilingual SMS and app notification dispatched via Malaffi patient gateway.", n)
        return _r("info", f"{c.id} · bilingual notification dispatched")
    if key == "log_call_no_answer":
        c.missed_calls += 1
        if c.missed_calls >= MAX_CALL_ATTEMPTS:
            c.escalated = True
            c.bump_priority()
            c.enter(2, n)
            c.note(actor, f"Call {c.missed_calls}/{MAX_CALL_ATTEMPTS} unanswered. Branched to ESCALATED_UNREACHABLE — call-centre fallback.", n)
            return _r("warn", f"{c.id} · 3 unanswered calls → ESCALATED_UNREACHABLE", True)
        c.note(actor, f"Call attempt {c.missed_calls}/{MAX_CALL_ATTEMPTS} — no answer.", n)
        return _r("warn", f"{c.id} · call {c.missed_calls}/{MAX_CALL_ATTEMPTS} unanswered")
    if key in ("patient_reached", "confirm_verbal_ack"):
        c.last_contact_at = n
        c.enter(3, n)
        c.note(actor, "Patient reached; receipt and understanding confirmed" + (" verbally." if key == "confirm_verbal_ack" else "."), n)
        return _r("success", f"{c.id} · patient acknowledged")
    if key == "start_consult":
        c.enter(4, n)
        c.note(actor, "Clinician consult initiated.", n)
        return _r("action", f"{c.id} · clinician consult started")
    if key in ("schedule_appointment", "reschedule_appointment"):
        was_missed = c.branch == MISSED
        c.appointment = slot(n, 1 if key == "reschedule_appointment" else 3)
        c.appointment_status, c.branch = "SCHEDULED", ""
        c.reset_sla(n)
        c.note(actor, f"Appointment {'rescheduled (recovery)' if was_missed or key.startswith('res') else 'scheduled'} for {c.appointment.strftime('%a %d %b, %H:%M')} (mock slot).", n)
        return _r("action", f"{c.id} · appointment set {c.appointment.strftime('%a %d %b %H:%M')}")
    if key == "mark_attended":
        c.appointment_status, c.last_contact_at = "ATTENDED", n
        c.note(actor, "Patient attended appointment.", n)
        return _r("success", f"{c.id} · appointment attended")
    if key == "mark_no_show":
        c.appointment_status, c.branch = "MISSED", MISSED
        c.no_show_count += 1
        c.bump_priority()
        c.reset_sla(n)
        c.note(actor, f"Appointment missed (no-show #{c.no_show_count}). Branched to {MISSED}.", n)
        return _r("error", f"{c.id} · no-show → {MISSED}", True)
    if key == "submit_referral":
        c.referral_status, c.referral_since = "PENDING", n
        c.note(actor, f"Referral submitted to {c.target()}.", n)
        return _r("action", f"{c.id} · referral submitted to {c.target()}")
    if key == "provider_accepts":
        c.referral_status = "ACCEPTED"
        c.enter(5, n)
        c.note(f"{c.target()} — Coordinator", f"{c.target()} accepted referral.", n)
        return _r("success", f"{c.id} · referral accepted by {c.target()}")
    if key == "provider_rejects":
        return reroute_referral(c, n, actor)
    if key == "restart_referral_chain":
        c.referral_idx, c.rejected_by, c.referral_status = c.referral_start, [], "NONE"
        c.note(actor, "Referral chain restarted by clinician.", n)
        return _r("info", f"{c.id} · referral chain restarted")
    if key == "dispatch_navigator":
        c.navigator_dispatched, c.last_contact_at = True, n
        c.note(actor, "Physical care navigator dispatched to patient.", n)
        return _r("action", f"{c.id} · physical navigator dispatched")
    raise HTTPException(400, "Unknown action")


def auto_detect_missed(cases: List[Case], n: datetime) -> List[str]:
    """Deterministic rule: scheduled appointment + 30 min grace elapsed → no-show branch."""
    msgs = []
    for c in cases:
        if c.stage == 4 and c.appointment_status == "SCHEDULED" and c.appointment and n > c.appointment + timedelta(minutes=30):
            msgs.append(apply_action(c, "mark_no_show", "AI Watchdog — Auto-detect", n)["message"])
    return msgs


# ═══════════════ OPERATIONAL AI WATCHDOG (deterministic, explainable) ═══════════════
SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
BOTTLENECK = {0: "the result has not been dispatched to the patient", 1: "the patient is not responding to notification",
              2: "the call centre has not confirmed contact", 3: "the clinician consult has not started",
              4: "the appointment or referral handoff is incomplete", 5: "closure evidence and Malaffi confirmation are outstanding"}
STAGE_REC = {0: ("Dispatch the notification now", "dispatch_notification"),
             1: ("Try an alternate channel or dispatch a physical navigator", "dispatch_navigator"),
             2: ("Call-centre coordinator to confirm verbal acknowledgement", "confirm_verbal_ack"),
             3: ("Begin the clinician consult", "start_consult"),
             4: ("Chase the appointment/referral owner and confirm the next step", None),
             5: ("Collect the Malaffi token and close via the Closure Lock", None)}


def risk_factors(c: Case, n: datetime) -> List[dict]:
    f = []
    def add(sig, detail, w, grp): f.append({"signal": sig, "detail": detail, "weight": w, "group": grp})
    if c.missed_calls: add("Missed follow-up calls", f"{c.missed_calls} unanswered", min(15 * c.missed_calls, 45), "patient")
    if c.no_show_count: add("Prior missed appointments", f"{c.no_show_count} no-show(s)", min(30 * c.no_show_count, 60), "patient")
    if c.patient_age >= ELDERLY_AGE: add("Elderly patient (engagement proxy)", f"age {c.patient_age}", 15, "patient")
    silent = hrs(c.last_contact_at or c.issued_at, n)
    if silent > 48: add("No patient contact", f"{silent:.0f}h", 25, "ops")
    elif silent > 24: add("No patient contact", f"{silent:.0f}h", 15, "ops")
    frac = c.sla_fraction(n)
    if frac < 0.15: add("SLA pressure", f"{frac:.0%} remaining", 20, "ops")
    elif frac < 0.35: add("SLA pressure", f"{frac:.0%} remaining", 10, "ops")
    dwell, lim = hrs(c.stage_entered_at, n), DWELL_LIMIT_H.get(c.stage)
    if lim and dwell > lim: add("Stage dwell over limit", f"{dwell:.1f}h vs {lim}h limit", 20, "ops")
    if not c.owner_accepted and hrs(c.issued_at, n) * 60 > OWNER_ACCEPT_MIN:
        add("Ownership not accepted", f"{hrs(c.issued_at, n) * 60:.0f} min", 15, "ops")
    if c.rejected_by: add("Capacity rejections", f"{len(c.rejected_by)} provider(s) declined", min(10 * len(c.rejected_by), 20), "ops")
    if c.navigator_dispatched: add("Mitigation: navigator dispatched", "in the field", -20, "mitigation")
    return f


def _plural(n, w): return f"{n} {w}{'' if n == 1 else 's'}"


def analyze_dropoff_risk(cases: List[Case], n: datetime) -> List[dict]:
    out: List[dict] = []
    prov: Dict[str, List[str]] = {}
    valid = lambda c, k: bool(k) and k in {a["key"] for a in available_actions(c)}

    def mk(c, typ, sev, title, exp, rec, key=None, risk=None, factors=None):
        out.append({"id": f"{c.id}:{typ}", "case_id": c.id, "type": typ, "severity": sev, "risk_pct": risk,
                    "title": title, "explanation": exp, "factors": factors or [], "recommended_action": rec,
                    "action_key": key if (key == "accept_ownership" or valid(c, key)) else None})

    for c in cases:
        for p in c.rejected_by: prov.setdefault(p, []).append(c.id)
        if c.stage >= 6: continue
        # 1 — drop-off / no-show risk score (additive, capped at 95)
        f = risk_factors(c, n)
        score = max(0, min(95, sum(x["weight"] for x in f)))
        if score >= RISK_ALERT_PCT:
            behav = []
            if c.patient_age >= ELDERLY_AGE: behav.append(f"is elderly ({c.patient_age})")
            if c.missed_calls: behav.append(f"has missed {_plural(c.missed_calls, 'follow-up call')}")
            if c.no_show_count: behav.append(f"has {_plural(c.no_show_count, 'prior no-show')}")
            ops = [f"{x['signal']} ({x['detail']})" for x in f if x["group"] == "ops"]
            exp = (f"Patient {c.id} " + ", ".join(behav) + "." if behav else "") + \
                  (f" Operational signals: {'; '.join(ops)}." if ops else "")
            if c.navigator_dispatched: rec, key = "Navigator already dispatched — await visit outcome", None
            elif c.no_show_count >= 1 or (c.patient_age >= ELDERLY_AGE and c.missed_calls >= 2): rec, key = "Dispatch physical care navigator", "dispatch_navigator"
            elif c.stage in (1, 2) and c.missed_calls >= 1: rec, key = "Use an alternate channel; auto-escalation to call centre at 3 unanswered calls", None
            elif c.sla_fraction(n) < 0.35: rec, key = "Notify on-call clinician and prioritise outreach", None
            else: rec, key = "Navigator outreach call within 2 hours", None
            hi = score >= RISK_HIGH_PCT
            kind = "No-Show" if c.stage >= 3 else "Drop-off"
            mk(c, "DROPOFF_RISK", "HIGH" if hi else "MEDIUM", f"{'High' if hi else 'Elevated'} Risk of {kind} ({score}%)",
               exp.strip(), rec, key, score, f)
        # 2 — missed appointments
        if c.branch == MISSED:
            mk(c, "MISSED_APPOINTMENT", "HIGH", "Missed Appointment — Recovery Required",
               f"{c.id} missed its appointment (no-show count: {c.no_show_count}) and moved to {MISSED}. The referral cannot progress until a new slot is confirmed.",
               "Reschedule within 24h and dispatch a physical navigator", "reschedule_appointment")
        elif c.appointment_status == "SCHEDULED" and c.appointment and n > c.appointment:
            mk(c, "MISSED_APPOINTMENT", "HIGH", "Appointment Overdue — Possible No-Show",
               f"{c.id} appointment time ({c.appointment.strftime('%a %d %b %H:%M')}) has passed with no attendance recorded.",
               "Confirm attendance or log a no-show", "mark_no_show")
        # 3 — delayed procedure (stage dwell breach)
        dwell, lim = hrs(c.stage_entered_at, n), DWELL_LIMIT_H.get(c.stage)
        if lim and dwell > lim:
            rec, key = STAGE_REC[c.stage]
            mk(c, "DELAYED_PROCEDURE", "HIGH" if dwell > 2 * lim else "MEDIUM",
               f"Delay Detected: {STAGE_DISPLAY[c.stage]} for {dwell:.1f}h (limit {lim}h)",
               f"{c.id} has remained in '{STAGE_DISPLAY[c.stage]}' beyond the {lim}h threshold. Stage owner role: {STAGE_OWNER[c.stage]}. Likely bottleneck: {BOTTLENECK[c.stage]}.",
               rec, key, factors=[x for x in f if x["signal"] == "Stage dwell over limit"])
        # 4 — incomplete handoffs
        if not c.owner_accepted and hrs(c.issued_at, n) * 60 > OWNER_ACCEPT_MIN:
            mk(c, "INCOMPLETE_HANDOFF", "MEDIUM", "Incomplete Handoff: No Owner Has Accepted",
               f"{c.id} is assigned to {c.owner} but ownership has not been accepted. Actions and closure stay blocked until a named clinician accepts.",
               "Assigned owner to accept responsibility", "accept_ownership")
        if c.referral_status == "EXHAUSTED":
            mk(c, "INCOMPLETE_HANDOFF", "CRITICAL", "Referral Chain Exhausted",
               f"All providers in the chain rejected {c.id} for capacity ({', '.join(c.rejected_by)}).",
               "Clinician-led manual placement, or restart the chain", "restart_referral_chain")
        elif c.referral_status == "PENDING" and c.referral_since and hrs(c.referral_since, n) > REFERRAL_RESPONSE_H:
            mk(c, "INCOMPLETE_HANDOFF", "HIGH", "Stalled Referral Handoff",
               f"{c.target()} has not responded to the {c.id} referral for {hrs(c.referral_since, n):.1f}h (limit {REFERRAL_RESPONSE_H}h).",
               "Contact the provider coordinator; re-route if no answer within 1h", None)
    # 5 — provider-level bottleneck
    for p, ids in prov.items():
        out.append({"id": f"SYSTEM:BOTTLENECK:{p}", "case_id": "SYSTEM", "type": "CLINIC_BOTTLENECK", "severity": "MEDIUM",
                    "risk_pct": None, "title": f"Capacity Bottleneck: {p}",
                    "explanation": f"{p} rejected {_plural(len(ids), 'referral')} for capacity ({', '.join(ids)}). New referrals to this provider are likely to bounce.",
                    "factors": [], "recommended_action": "Deprioritise this provider in routing and notify the capacity manager", "action_key": None})
    out.sort(key=lambda a: (SEV_RANK[a["severity"]], -(a["risk_pct"] or 0)))
    return out


# ═══════════════ SEED DATA (all times relative to "now" so the demo is always live) ═══════════════
def seed_cases() -> List[Case]:
    n = now_()
    m = lambda x: n - timedelta(minutes=x)
    ev = lambda st, mins, actor, d: Event(stage=st, ts=m(mins).strftime(TS_FMT), actor=actor, desc=d)
    return [
        Case(id="ZD-901", eid="EID-784-XXXX-XXXX-3", pathway="Pre-Marital Genetic Screening",
             condition="Beta-Thalassemia Carrier Status", stage=1, priority="HIGH",
             provider_chain=["SEHA Central Lab", "Mubadala Health Primary", "CCAD Genomics Centre", "SEHA Genetics Clinic"],
             referral_start=2, referral_idx=2, sla_total=120, sla_deadline=n + timedelta(minutes=23),
             owner="Nurse Hessa Al Dhaheri", owner_accepted=False, patient_token="PT-7731-A", fhir_id="SR-2026-ZD-901-BTC",
             patient_age=29, missed_calls=1, issued_at=m(300), stage_entered_at=m(270),
             timeline=[ev(0, 300, "SEHA Central Lab — Automated", "Beta-Thalassemia carrier status confirmed. FHIR R4 Observation created and dispatched to Malaffi."),
                       ev(1, 270, "Patient Navigator — System", "Bilingual SMS and app notification dispatched via Malaffi patient gateway."),
                       ev(1, 120, "Patient Navigator", "Call attempt 1/3 — no answer.")]),
        Case(id="ZD-902", eid="EID-784-XXXX-XXXX-7", pathway="Breast Cancer Screening Programme",
             condition="BRCA1 — BI-RADS 4 Actionable Finding", stage=4, priority="CRITICAL",
             provider_chain=["Mubadala Breast Care Centre", "SEHA Primary Care", "CCAD Oncology", "Mubadala Oncology Centre"],
             referral_start=2, referral_idx=2, sla_total=180, sla_deadline=n + timedelta(minutes=60),
             owner="Dr. Aisha Khalil", owner_accepted=True, patient_token="PT-9942-B", fhir_id="SR-2026-ZD-902-BRCA",
             patient_age=71, missed_calls=2, no_show_count=1, issued_at=m(300), stage_entered_at=m(180), last_contact_at=m(180),
             appointment=slot(n, 1), appointment_status="SCHEDULED",
             timeline=[ev(0, 300, "Mubadala Breast Care — Radiologist", "BI-RADS 4 finding flagged. FHIR DiagnosticReport created."),
                       ev(1, 285, "Patient Navigator — System", "Secure bilingual priority notification dispatched."),
                       ev(1, 280, "Patient Navigator", "Call attempt 1/3 — no answer."), ev(1, 260, "Patient Navigator", "Call attempt 2/3 — no answer."),
                       ev(3, 200, "Patient — Secure App", "Patient confirmed receipt via secure app."),
                       ev(4, 180, "Dr. Aisha Khalil", "Oncology consult initiated. Ownership accepted."),
                       ev(4, 170, "Dr. Aisha Khalil", "Earlier appointment missed (no-show #1). Rescheduled via recovery path.")]),
        Case(id="ZD-903", eid="EID-784-XXXX-XXXX-1", pathway="Newborn Metabolic Screening",
             condition="Phenylketonuria (PKU) — Elevated Phenylalanine", stage=5, priority="NORMAL",
             provider_chain=["SEHA Neonatal Lab", "SEHA Paediatrics", "CCAD Metabolic Unit", "SEHA Metabolic Clinic"],
             referral_start=2, referral_idx=2, sla_total=480, sla_deadline=n + timedelta(minutes=420),
             owner="Dr. Sara Naji", owner_accepted=True, patient_token="PT-5513-C", fhir_id="SR-2026-ZD-903-PKU",
             patient_age=0, issued_at=m(3000), stage_entered_at=m(1200), last_contact_at=m(1300),
             appointment=slot(n, 2), appointment_status="SCHEDULED", referral_status="ACCEPTED", referral_since=m(1200),
             timeline=[ev(0, 3000, "SEHA Neonatal Lab — Automated", "Elevated phenylalanine on day-3 heel-prick. Auto-escalated to paediatric team."),
                       ev(1, 2985, "Patient Navigator", "Parents notified via bilingual written report and telephone call."),
                       ev(3, 2900, "Parent — Secure App", "Parents confirmed understanding and consent to follow-up."),
                       ev(4, 1500, "Dr. Sara Naji", "Paediatrician e-consult completed. Specialist referral recommended."),
                       ev(5, 1200, "CCAD Metabolic Unit — Coordinator", "CCAD Metabolic Unit accepted referral. Appointment confirmed.")]),
        Case(id="ZD-904", eid="EID-784-XXXX-XXXX-9", pathway="Adult Comprehensive Screening",
             condition="High Cardiovascular Risk — SCORE2 >= 10%", stage=0, priority="HIGH",
             provider_chain=["SEHA Wellness Centre", "Mubadala Cardiology", "CCAD Cardiology"],
             referral_start=1, referral_idx=1, sla_total=180, sla_deadline=n + timedelta(minutes=95),
             owner="Patient Navigator Unit", owner_accepted=False, patient_token="PT-2287-D", fhir_id="SR-2026-ZD-904-CVD",
             patient_age=52, issued_at=m(85), stage_entered_at=m(85),
             timeline=[ev(0, 85, "SEHA Wellness Centre — Automated", "10-year cardiovascular risk score flagged. Lifestyle counselling and pharmacotherapy discussion required.")]),
    ]


DB: Dict[str, Case] = {c.id: c for c in seed_cases()}


def get_case(cid: str) -> Case:
    if cid not in DB: raise HTTPException(404, f"Case {cid} not found")
    return DB[cid]


def to_api(c: Case, n: datetime) -> dict:
    d = c.model_dump(mode="json")
    d.update(sla_seconds=max(0, int((c.sla_deadline - n).total_seconds())), state=c.state(),
             available_actions=available_actions(c), is_offline_patient=c.stage == 2, current_target=c.target(),
             appointment_label=c.appointment.strftime("%a %d %b %Y · %H:%M") if c.appointment else "",
             appointment_epoch=int(c.appointment.timestamp() * 1000) if c.appointment else 0,
             hours_in_stage=round(hrs(c.stage_entered_at, n), 1),
             bilingual=bilingual(c.id), fhir_payload=FHIR_PAYLOADS.get(c.id, {}))
    return d


# ═══════════════ FASTAPI ═══════════════
app = FastAPI(title="ZeroDrop Care Navigator API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ActionIn(BaseModel):
    action: str
    actor: str = "Current User"


class CloseIn(BaseModel):
    token: str
    evidence: str


@app.get("/cases")
def list_cases():
    n = now_()
    return [to_api(c, n) for c in DB.values()]


@app.post("/cases/{cid}/accept_ownership")
def accept_ownership(cid: str):
    c, n = get_case(cid), now_()
    if not c.owner_accepted:
        c.owner_accepted = True
        c.note(c.owner, "Ownership accepted. Audit entry created.", n)
    return {"ok": True, "owner": c.owner}


@app.post("/cases/{cid}/action")
def case_action(cid: str, body: ActionIn):
    c = get_case(cid)
    if not c.owner_accepted:          # ownership guardrail applies to every workflow action
        raise HTTPException(403, "Ownership has not been accepted. A named clinician must accept responsibility.")
    return apply_action(c, body.action, body.actor, now_())


@app.post("/cases/{cid}/patient_acknowledge")
def patient_acknowledge(cid: str):
    c, n = get_case(cid), now_()
    if c.stage not in (1, 2): raise HTTPException(409, "Nothing to acknowledge at this stage.")
    c.last_contact_at = n
    c.enter(3, n)
    c.note("Patient — Secure Portal", "Patient confirmed receipt and understanding via secure portal.", n)
    return {"ok": True}


@app.post("/cases/{cid}/close")           # ── CLOSURE LOCK (unchanged rules) ──
def close_case(cid: str, body: CloseIn):
    c, n = get_case(cid), now_()
    if c.stage != 5:
        raise HTTPException(409, "Closure not permitted: case must reach Referral Accepted first.")
    if not c.owner_accepted:
        raise HTTPException(403, "Ownership has not been accepted.")
    if not body.token.strip().startswith("MALAFFI-CONF-") or body.evidence not in CLOSURE_EVIDENCE_OPTIONS[1:]:
        raise HTTPException(422, "Closure blocked: a valid Malaffi token (MALAFFI-CONF-XXXX) and evidence type are required.")
    c.closure_token, c.closure_evidence = body.token.strip(), body.evidence
    c.enter(6, n)
    c.note(c.owner, f"Case CLOSED & VERIFIED. Token {c.closure_token}. Evidence: {c.closure_evidence}.", n)
    return {"ok": True}


@app.get("/ai/analyze_dropoff_risk")
def ai_analyze():
    n = now_()
    alerts = analyze_dropoff_risk(list(DB.values()), n)
    return {"generated_at": n.isoformat(), "engine": "Deterministic rules v1 — operational only, no clinical inference",
            "thresholds": {"elderly_age": ELDERLY_AGE, "alert_pct": RISK_ALERT_PCT, "high_pct": RISK_HIGH_PCT,
                           "dwell_limit_h": DWELL_LIMIT_H, "max_call_attempts": MAX_CALL_ATTEMPTS},
            "count": len(alerts), "alerts": alerts}


@app.post("/agent/scan")
def agent_scan():
    n = now_()
    auto = auto_detect_missed(list(DB.values()), n)
    smart = analyze_dropoff_risk(list(DB.values()), n)
    alerts = [{"level": "warn", "msg": f"AUTO-ACTION: {m}"} for m in auto]
    alerts += [{"level": "error" if a["severity"] in ("CRITICAL", "HIGH") else "warn",
                "msg": f"{a['case_id']} · {a['title']} → {a['recommended_action']}"} for a in smart]
    unverified = sum(1 for c in DB.values() if c.stage == 6 and not (c.closure_token.startswith("MALAFFI-CONF-") and c.closure_evidence))
    return {"alerts": alerts, "auto_actions": auto, "smart_alerts": len(smart), "unverified_closures": unverified,
            "open_cases": sum(1 for c in DB.values() if c.stage < 6), "audit": "closure lock intact · all closures carry token + evidence"}


@app.post("/agent/simulate_rejection/{cid}")
def simulate_rejection(cid: str):
    c, n = get_case(cid), now_()
    if c.stage != 4 or c.branch:
        raise HTTPException(409, "Rejection can only be simulated during an active Clinician Consult (no recovery branch).")
    if c.referral_status != "PENDING":
        c.appointment_status, c.referral_status, c.referral_since = "ATTENDED", "PENDING", n
        c.note("Simulation", f"Referral submitted to {c.target()} (simulated).", n)
    return reroute_referral(c, n, "Routing Agent (simulated)")


@app.post("/agent/trigger_sla_breach/{cid}")
def trigger_sla_breach(cid: str):
    c, n = get_case(cid), now_()
    c.sla_deadline = n + timedelta(minutes=max(1, int(c.sla_total * 0.1)))
    c.note("AI Watchdog", "SLA breach alert triggered — on-call clinician notified.", n)
    return {"ok": True}


@app.post("/demo/reset")
def demo_reset():
    DB.clear()
    DB.update({c.id: c for c in seed_cases()})
    return {"ok": True}
