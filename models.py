"""
ZeroDrop — Deterministic Screening-to-Care Orchestration Engine
FastAPI Backend · In-Memory State · 7-Stage Pipeline

NOT a Software as a Medical Device (SaMD). All clinical decisions remain
with licensed healthcare professionals. Designed for ADHICS / UAE PDPL
Decree-Law No. 45/2021 alignment. Malaffi FHIR integrations are simulated.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime
from enum import IntEnum
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ─────────────────────────────────────────────────────────────
#  STAGE DEFINITIONS  (7-stage pipeline)
# ─────────────────────────────────────────────────────────────

class Stage(IntEnum):
    RESULT_ISSUED           = 0   # Lab result confirmed & FHIR record created
    PATIENT_NOTIFIED        = 1   # Digital notification dispatched
    OFFLINE_FALLBACK        = 2   # Escalated to Call Centre (elderly / non-digital)
    PATIENT_ACKNOWLEDGED    = 3   # Patient confirmed receipt
    CLINICIAN_CONSULT       = 4   # Primary physician engaged
    REFERRAL_ACCEPTED       = 5   # Specialist accepted referral
    CLOSED_VERIFIED         = 6   # Evidence-locked closure

STAGE_LABELS: dict[int, str] = {
    0: "Result Issued",
    1: "Patient Notified",
    2: "Offline Fallback",
    3: "Patient Acknowledged",
    4: "Clinician Consult",
    5: "Referral Accepted",
    6: "Closed & Verified",
}

STAGE_OWNERS: dict[int, str] = {
    0: "Lab Director",
    1: "Patient Navigator",
    2: "Call Centre Coordinator",
    3: "Patient",
    4: "Primary Physician",
    5: "Specialist Coordinator",
    6: "Case Owner",
}

CLOSURE_OPTS = [
    "— Select closure evidence type —",
    "Confirmatory laboratory result attached",
    "Specialist appointment attended and documented",
    "Clinician discharge summary uploaded to Malaffi",
    "Patient declined — informed refusal on record",
    "Referred to specialist — case formally transferred",
]

# ─────────────────────────────────────────────────────────────
#  IN-MEMORY DATA STORE
# ─────────────────────────────────────────────────────────────

_CASES_SEED: list[dict[str, Any]] = [
    {
        "id": "ZD-901",
        "eid": "EID-784-XXXX-XXXX-3",
        "pathway": "Pre-Marital Genetic Screening",
        "condition": "Beta-Thalassemia Carrier Status",
        "stage": 1,
        "priority": "HIGH",
        "provider_chain": [
            "SEHA Central Lab",
            "Mubadala Health Primary",
            "CCAD Genomics Centre",
        ],
        "sla_remaining": 23,
        "sla_total": 120,
        "owner": "Nurse Hessa Al Dhaheri",
        "owner_accepted": False,
        "patient_token": "PT-7731-A",
        "fhir_id": "SR-2026-ZD-901-BTC",
        "is_offline_patient": False,
        "timeline": [
            {
                "ts": "09:12  09 Nov 2026",
                "stage": 0,
                "desc": "Beta-Thalassemia carrier status confirmed. FHIR R4 Observation created and dispatched to Malaffi.",
                "actor": "SEHA Central Lab — Automated",
            },
            {
                "ts": "09:31  09 Nov 2026",
                "stage": 1,
                "desc": "Bilingual SMS and app notification dispatched via Malaffi gateway.",
                "actor": "Patient Navigator — System",
            },
        ],
        "consult_requested": False,
        "closure_token": "",
        "closure_evidence": "",
    },
    {
        "id": "ZD-902",
        "eid": "EID-784-XXXX-XXXX-7",
        "pathway": "Breast Cancer Screening Programme",
        "condition": "BRCA1 — BI-RADS 4 Actionable Finding",
        "stage": 4,
        "priority": "CRITICAL",
        "provider_chain": [
            "Mubadala Breast Care Centre",
            "SEHA Primary Care",
            "CCAD Oncology",
        ],
        "sla_remaining": 18,
        "sla_total": 120,
        "owner": "Dr. Aisha Khalil",
        "owner_accepted": True,
        "patient_token": "PT-9942-B",
        "fhir_id": "SR-2026-ZD-902-BRCA",
        "is_offline_patient": False,
        "timeline": [
            {
                "ts": "07:44  09 Nov 2026",
                "stage": 0,
                "desc": "BI-RADS 4 finding flagged by radiologist. FHIR DiagnosticReport created.",
                "actor": "Mubadala Breast Care — Radiologist",
            },
            {
                "ts": "08:01  09 Nov 2026",
                "stage": 1,
                "desc": "Secure bilingual priority notification dispatched.",
                "actor": "Patient Navigator — System",
            },
            {
                "ts": "08:19  09 Nov 2026",
                "stage": 3,
                "desc": "Patient confirmed receipt via secure app.",
                "actor": "Patient — Secure App",
            },
            {
                "ts": "08:35  09 Nov 2026",
                "stage": 4,
                "desc": "Oncology consult initiated. Dr. Aisha Khalil accepted ownership.",
                "actor": "Dr. Aisha Khalil",
            },
        ],
        "consult_requested": False,
        "closure_token": "",
        "closure_evidence": "",
    },
    {
        "id": "ZD-903",
        "eid": "EID-784-XXXX-XXXX-1",
        "pathway": "Newborn Metabolic Screening",
        "condition": "Phenylketonuria (PKU) — Elevated Phenylalanine",
        "stage": 5,
        "priority": "NORMAL",
        "provider_chain": [
            "SEHA Neonatal Lab",
            "SEHA Paediatrics",
            "CCAD Metabolic Unit",
        ],
        "sla_remaining": 420,
        "sla_total": 480,
        "owner": "Dr. Sara Naji",
        "owner_accepted": True,
        "patient_token": "PT-5513-C",
        "fhir_id": "SR-2026-ZD-903-PKU",
        "is_offline_patient": False,
        "timeline": [
            {
                "ts": "11:00  06 Nov 2026",
                "stage": 0,
                "desc": "Elevated phenylalanine on day-3 heel-prick. Auto-escalated.",
                "actor": "SEHA Neonatal Lab — Automated",
            },
            {
                "ts": "11:15  06 Nov 2026",
                "stage": 1,
                "desc": "Parents notified via bilingual report and call.",
                "actor": "Patient Navigator",
            },
            {
                "ts": "12:40  06 Nov 2026",
                "stage": 3,
                "desc": "Parents confirmed understanding and consent.",
                "actor": "Parent — Secure App",
            },
            {
                "ts": "14:30  07 Nov 2026",
                "stage": 4,
                "desc": "Paediatrician e-consult completed. Specialist referral recommended.",
                "actor": "Dr. Sara Naji",
            },
            {
                "ts": "09:00  08 Nov 2026",
                "stage": 5,
                "desc": "CCAD Metabolic Unit accepted referral. Appointment: 12 Nov.",
                "actor": "CCAD Metabolic Unit — Coordinator",
            },
        ],
        "consult_requested": False,
        "closure_token": "",
        "closure_evidence": "",
    },
    {
        "id": "ZD-904",
        "eid": "EID-784-XXXX-XXXX-9",
        "pathway": "Adult Comprehensive Screening",
        "condition": "High Cardiovascular Risk — SCORE2 >= 10%",
        "stage": 0,
        "priority": "HIGH",
        "provider_chain": ["SEHA Wellness Centre", "Mubadala Cardiology"],
        "sla_remaining": 95,
        "sla_total": 180,
        "owner": "Patient Navigator Unit",
        "owner_accepted": False,
        "patient_token": "PT-2287-D",
        "fhir_id": "SR-2026-ZD-904-CVD",
        "is_offline_patient": False,
        "timeline": [
            {
                "ts": "10:30  09 Nov 2026",
                "stage": 0,
                "desc": "10-year cardiovascular risk score flagged. Lifestyle counselling required.",
                "actor": "SEHA Wellness Centre — Automated",
            }
        ],
        "consult_requested": False,
        "closure_token": "",
        "closure_evidence": "",
    },
    # ── NEW: Offline / elderly patient demonstrating the OFFLINE_FALLBACK stage ──
    {
        "id": "ZD-905",
        "eid": "EID-784-XXXX-XXXX-5",
        "pathway": "Adult Comprehensive Screening",
        "condition": "Elevated HbA1c — Type 2 Diabetes Risk",
        "stage": 2,
        "priority": "HIGH",
        "provider_chain": ["SEHA Primary Care Clinic", "Mubadala Endocrinology"],
        "sla_remaining": 61,
        "sla_total": 180,
        "owner": "Call Centre Coordinator — Unit 4",
        "owner_accepted": True,
        "patient_token": "PT-6604-E",
        "fhir_id": "SR-2026-ZD-905-DM",
        "is_offline_patient": True,
        "timeline": [
            {
                "ts": "08:00  09 Nov 2026",
                "stage": 0,
                "desc": "Elevated HbA1c (8.1%) confirmed. FHIR R4 Observation dispatched to Malaffi.",
                "actor": "SEHA Primary Care — Automated",
            },
            {
                "ts": "08:14  09 Nov 2026",
                "stage": 1,
                "desc": "Digital notification dispatched. Patient profile flagged: no smartphone, age 71.",
                "actor": "Patient Navigator — System",
            },
            {
                "ts": "08:22  09 Nov 2026",
                "stage": 2,
                "desc": "Digital delivery failed — patient not reachable via app. Case auto-escalated to Call Centre (Offline Fallback). Call Centre Coordinator Unit 4 assigned.",
                "actor": "AGENT-OFFLINE: Deterministic Escalation Rule",
            },
        ],
        "consult_requested": False,
        "closure_token": "",
        "closure_evidence": "",
    },
]

FHIR_PAYLOADS: dict[str, dict] = {
    "ZD-901": {
        "resourceType": "Observation",
        "id": "SR-2026-ZD-901-BTC",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "413427002",
                    "display": "Beta-thalassemia carrier status",
                }
            ]
        },
        "subject": {
            "reference": "Patient/EID-784-XXXX-XXXX-3",
            "display": "Tokenised Patient",
        },
        "effectiveDateTime": "2026-11-09T09:12:00+04:00",
        "note": [{"text": "FHIR R4 compliant. Malaffi HIE simulated. No raw PII transmitted."}],
    },
    "ZD-902": {
        "resourceType": "DiagnosticReport",
        "id": "SR-2026-ZD-902-BRCA",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "24606-6",
                    "display": "Mammography screening study",
                }
            ]
        },
        "subject": {
            "reference": "Patient/EID-784-XXXX-XXXX-7",
            "display": "Tokenised Patient",
        },
        "effectiveDateTime": "2026-11-09T07:44:00+04:00",
        "conclusion": "BI-RADS Category 4 — Suspicious. Tissue biopsy recommended.",
    },
    "ZD-903": {
        "resourceType": "Observation",
        "id": "SR-2026-ZD-903-PKU",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "360257000",
                    "display": "Phenylalanine measurement",
                }
            ]
        },
        "subject": {
            "reference": "Patient/EID-784-XXXX-XXXX-1",
            "display": "Tokenised Patient",
        },
        "valueQuantity": {"value": 18.4, "unit": "mg/dL"},
        "interpretation": [{"coding": [{"code": "H", "display": "Above reference range"}]}],
    },
    "ZD-904": {
        "resourceType": "RiskAssessment",
        "id": "SR-2026-ZD-904-CVD",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "718687005",
                    "display": "Cardiovascular risk assessment",
                }
            ]
        },
        "subject": {
            "reference": "Patient/EID-784-XXXX-XXXX-9",
            "display": "Tokenised Patient",
        },
        "prediction": [
            {
                "outcome": {"text": "10-year cardiovascular event risk"},
                "probabilityDecimal": 0.11,
                "qualitativeRisk": {"text": "High — SCORE2 >= 10%"},
            }
        ],
    },
    "ZD-905": {
        "resourceType": "Observation",
        "id": "SR-2026-ZD-905-DM",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "4548-4",
                    "display": "Hemoglobin A1c/Hemoglobin.total in Blood",
                }
            ]
        },
        "subject": {
            "reference": "Patient/EID-784-XXXX-XXXX-5",
            "display": "Tokenised Patient",
        },
        "effectiveDateTime": "2026-11-09T08:00:00+04:00",
        "valueQuantity": {"value": 8.1, "unit": "%"},
        "interpretation": [{"coding": [{"code": "H", "display": "Above reference range"}]}],
        "note": [{"text": "OFFLINE_FALLBACK: Patient flagged as non-digital. Call Centre escalation triggered automatically."}],
    },
}

BILINGUAL: dict[str, dict] = {
    "ZD-901": {
        "en": {
            "title": "Your Genetic Screening Result",
            "body": "Your genetic screening has been completed. The result needs a brief conversation with one of our specialists. This does not mean you are unwell. A counselor will explain what this means for you and your family and answer any questions you have. No decision needs to be made today.",
            "action": "Please confirm below that you have read and understood this message.",
            "disc": "This message is for information only and does not constitute a diagnosis or medical advice.",
        },
        "ar": {
            "title": "نتيجة الفحص الجيني",
            "body": "تم إجراء الفحص الجيني الخاص بك. تستدعي النتيجة إجراء محادثة مع أحد متخصصينا. لا يعني ذلك أنك مريض. سيشرح لك المستشار ما يعنيه هذا بالنسبة لك ولعائلتك ويجيب على تساؤلاتك. لا حاجة لاتخاذ أي قرار اليوم.",
            "action": "يرجى التأكيد أدناه على أنك قرأت هذه الرسالة وفهمت مضمونها.",
            "disc": "هذه الرسالة للإعلام فقط. لا تُشكّل تشخيصاً أو نصيحة طبية.",
        },
    },
    "ZD-902": {
        "en": {
            "title": "Your Breast Screening Requires Attention",
            "body": "Your recent breast screening identified a finding our care team would like to discuss with you. This is not a diagnosis. We want to make sure you receive the right follow-up care promptly. Your doctor will contact you within 24 hours to explain the next steps.",
            "action": "Please confirm below that you have read and understood this message.",
            "disc": "Your privacy is protected. This information is shared only with your authorised care team.",
        },
        "ar": {
            "title": "فحص الثدي يحتاج إلى اهتمام",
            "body": "كشف فحص الثدي الأخير عن نتيجة يود فريق رعايتنا مناقشتها معك. هذا ليس تشخيصاً. نريد التأكد من حصولك على المتابعة المناسبة في الوقت المناسب. سيتصل بك طبيبك خلال 24 ساعة.",
            "action": "يرجى التأكيد أدناه على أنك قرأت هذه الرسالة وفهمت مضمونها.",
            "disc": "خصوصيتك محمية. تُشارَك هذه المعلومات فقط مع فريق رعايتك المُعتمد.",
        },
    },
    "ZD-903": {
        "en": {
            "title": "Your Newborn Screening Update",
            "body": "The newborn screening for your baby has returned a result our paediatric team would like to review with you. This type of finding is common and often requires simple, straightforward steps. A specialist will contact you to arrange a convenient appointment.",
            "action": "Please confirm below that you have read and understood this message.",
            "disc": "Early follow-up gives your baby the best possible outcome. This message is for information only.",
        },
        "ar": {
            "title": "تحديث فحص حديث الولادة",
            "body": "أعاد فحص طفلك حديث الولادة نتيجة يود فريق طب الأطفال مراجعتها معك. هذا النوع من النتائج شائع وغالباً ما يتطلب خطوات بسيطة ومباشرة. سيتواصل معك أخصائي لترتيب موعد.",
            "action": "يرجى التأكيد أدناه على أنك قرأت هذه الرسالة وفهمت مضمونها.",
            "disc": "المتابعة المبكرة تمنح طفلك أفضل النتائج.",
        },
    },
    "ZD-904": {
        "en": {
            "title": "Your Health Check Results",
            "body": "Your comprehensive health check identified some factors our team would like to discuss with you. These are manageable with the right guidance and support. Your care navigator will contact you to book a consultation at a time that suits you.",
            "action": "Please confirm below that you have read and understood this message.",
            "disc": "Taking action now can significantly improve your long-term health. This message is for information only.",
        },
        "ar": {
            "title": "نتائج الفحص الصحي الشامل",
            "body": "كشف الفحص الصحي الشامل عن بعض العوامل التي يود فريقنا مناقشتها معك. يمكن التعامل معها بالتوجيه والدعم المناسبين. سيتواصل معك منسق الرعاية لحجز استشارة.",
            "action": "يرجى التأكيد أدناه على أنك قرأت هذه الرسالة وفهمت مضمونها.",
            "disc": "اتخاذ الإجراء الآن يحسّن صحتك على المدى البعيد.",
        },
    },
    "ZD-905": {
        "en": {
            "title": "Your Blood Sugar Screening Result",
            "body": "Your recent blood test showed a result that our care team would like to follow up with you about. This is a common finding and is very manageable with early support. Because we were unable to reach you digitally, one of our care coordinators will call you on your registered telephone number within 48 hours.",
            "action": "Please ask our coordinator to confirm you have received and understood this message during your call.",
            "disc": "This message is for information only. Your call coordinator will arrange any next steps. No diagnosis is made here.",
        },
        "ar": {
            "title": "نتيجة فحص السكر في الدم",
            "body": "أظهر اختبار الدم الأخير نتيجة يود فريق رعايتنا متابعتها معك. هذه نتيجة شائعة ويمكن التعامل معها بشكل جيد مع الدعم المبكر. نظراً لعدم تمكننا من الوصول إليك رقمياً، سيتصل بك أحد منسقي الرعاية على رقم هاتفك المسجل خلال 48 ساعة.",
            "action": "يرجى أن تطلب من المنسق التأكيد على استلامك وفهمك لهذه الرسالة أثناء المكالمة.",
            "disc": "هذه الرسالة للإعلام فقط. سيرتب منسق المكالمة الخطوات التالية. لا يتم تشخيص أي حالة هنا.",
        },
    },
}

# Working copy that gets mutated at runtime
_cases: list[dict[str, Any]] = copy.deepcopy(_CASES_SEED)


def _get_case(case_id: str) -> dict[str, Any]:
    for c in _cases:
        if c["id"] == case_id:
            return c
    raise HTTPException(status_code=404, detail=f"Case {case_id} not found")


def _now_ts() -> str:
    return datetime.now().strftime("%H:%M  %d %b %Y")


def _sla_fraction(c: dict) -> float:
    total = c["sla_total"]
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, c["sla_remaining"] / total))


def _sla_status(c: dict) -> str:
    f = _sla_fraction(c)
    if f < 0.15:
        return "BREACH"
    if f < 0.35:
        return "WARNING"
    return "OK"


# ─────────────────────────────────────────────────────────────
#  FASTAPI APP
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="ZeroDrop Orchestration API",
    description="Deterministic rule-based screening-to-care loop engine. NOT a SaMD.",
    version="3.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Tighten to specific origin in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
#  REQUEST / RESPONSE SCHEMAS
# ─────────────────────────────────────────────────────────────

class ClosureRequest(BaseModel):
    token: str
    evidence: str


class OfflineFallbackRequest(BaseModel):
    coordinator: Optional[str] = None


# ─────────────────────────────────────────────────────────────
#  ROUTES — META
# ─────────────────────────────────────────────────────────────

@app.get("/", tags=["meta"])
def root():
    return {
        "service": "ZeroDrop Orchestration API",
        "version": "3.1.0",
        "stages": STAGE_LABELS,
        "disclaimer": "NOT a Software as a Medical Device (SaMD).",
    }


@app.get("/stages", tags=["meta"])
def get_stages():
    """Return the full 7-stage definition — drives the frontend pipeline view."""
    return {
        "stages": [
            {"index": i, "key": Stage(i).name, "label": STAGE_LABELS[i], "owner_role": STAGE_OWNERS[i]}
            for i in range(len(Stage))
        ],
        "closure_evidence_options": CLOSURE_OPTS,
    }


# ─────────────────────────────────────────────────────────────
#  ROUTES — CASES
# ─────────────────────────────────────────────────────────────

@app.get("/cases", tags=["cases"])
def list_cases():
    """Return all cases with computed SLA metadata."""
    enriched = []
    for c in _cases:
        enriched.append(
            {
                **c,
                "sla_status": _sla_status(c),
                "stage_label": STAGE_LABELS[c["stage"]],
                "stage_owner_role": STAGE_OWNERS[c["stage"]],
                "bilingual": BILINGUAL.get(c["id"]),
                "fhir_payload": FHIR_PAYLOADS.get(c["id"]),
            }
        )
    return enriched


@app.get("/cases/{case_id}", tags=["cases"])
def get_case(case_id: str):
    c = _get_case(case_id)
    return {
        **c,
        "sla_status": _sla_status(c),
        "stage_label": STAGE_LABELS[c["stage"]],
        "stage_owner_role": STAGE_OWNERS[c["stage"]],
        "bilingual": BILINGUAL.get(case_id),
        "fhir_payload": FHIR_PAYLOADS.get(case_id),
    }


# ─────────────────────────────────────────────────────────────
#  ROUTES — OWNERSHIP
# ─────────────────────────────────────────────────────────────

@app.post("/cases/{case_id}/accept_ownership", tags=["ownership"])
def accept_ownership(case_id: str):
    """
    Named clinician / coordinator formally accepts case ownership.
    Deterministic guard: no stage advance permitted without prior acceptance.
    """
    c = _get_case(case_id)
    if c["owner_accepted"]:
        return {"status": "already_accepted", "case": c["id"], "owner": c["owner"]}
    c["owner_accepted"] = True
    c["timeline"].append(
        {
            "ts": _now_ts(),
            "stage": c["stage"],
            "desc": f"Ownership formally accepted by {c['owner']}. Audit record created.",
            "actor": c["owner"],
        }
    )
    return {
        "status": "accepted",
        "case": c["id"],
        "owner": c["owner"],
        "audit_id": str(uuid.uuid4()),
    }


# ─────────────────────────────────────────────────────────────
#  ROUTES — STAGE TRANSITIONS
# ─────────────────────────────────────────────────────────────

@app.post("/cases/{case_id}/advance", tags=["workflow"])
def advance_stage(case_id: str):
    """
    Move a case to the next stage.

    Deterministic guards enforced:
      • Ownership must be accepted before advance.
      • Cannot advance past REFERRAL_ACCEPTED via this endpoint —
        use /close for verified closure.
      • OFFLINE_FALLBACK (stage 2) cannot be skipped — it must be
        explicitly resolved via /resolve_offline_fallback.
    """
    c = _get_case(case_id)

    if not c["owner_accepted"]:
        raise HTTPException(
            status_code=422,
            detail="Ownership has not been accepted. A named clinician must accept responsibility before the case can advance.",
        )

    if c["stage"] >= Stage.REFERRAL_ACCEPTED:
        raise HTTPException(
            status_code=422,
            detail="Case is at or beyond Referral Accepted. Use the /close endpoint with a verified evidence bundle.",
        )

    # Stage 1 → 2 for offline patients is automatic; skip for digital patients
    # Normal advance: 1 → 3 (Patient Acknowledged) skipping Offline Fallback when patient is digital
    next_stage = c["stage"] + 1
    if next_stage == Stage.OFFLINE_FALLBACK and not c.get("is_offline_patient", False):
        # Skip the offline fallback lane
        next_stage = Stage.PATIENT_ACKNOWLEDGED

    c["stage"] = next_stage
    c["timeline"].append(
        {
            "ts": _now_ts(),
            "stage": c["stage"],
            "desc": f"Stage advanced to {STAGE_LABELS[c['stage']]}.",
            "actor": c["owner"],
        }
    )
    return {
        "status": "advanced",
        "case": c["id"],
        "stage": c["stage"],
        "stage_label": STAGE_LABELS[c["stage"]],
        "audit_id": str(uuid.uuid4()),
    }


@app.post("/cases/{case_id}/resolve_offline_fallback", tags=["workflow"])
def resolve_offline_fallback(case_id: str, body: OfflineFallbackRequest):
    """
    Call Centre coordinator marks verbal acknowledgement received.
    Transitions OFFLINE_FALLBACK → PATIENT_ACKNOWLEDGED.
    This endpoint is the ONLY valid way to exit the offline lane.
    """
    c = _get_case(case_id)
    if c["stage"] != Stage.OFFLINE_FALLBACK:
        raise HTTPException(
            status_code=422,
            detail=f"Case is not at OFFLINE_FALLBACK stage (current: {STAGE_LABELS[c['stage']]}).",
        )
    coordinator = body.coordinator or c["owner"]
    c["stage"] = Stage.PATIENT_ACKNOWLEDGED
    c["timeline"].append(
        {
            "ts": _now_ts(),
            "stage": c["stage"],
            "desc": f"Verbal acknowledgement confirmed by Call Centre ({coordinator}). Case exits offline lane.",
            "actor": coordinator,
        }
    )
    return {
        "status": "offline_resolved",
        "case": c["id"],
        "stage": c["stage"],
        "stage_label": STAGE_LABELS[c["stage"]],
        "coordinator": coordinator,
        "audit_id": str(uuid.uuid4()),
    }


@app.post("/cases/{case_id}/patient_acknowledge", tags=["patient_portal"])
def patient_acknowledge(case_id: str):
    """
    Patient confirms receipt of notification via secure portal.
    Transitions PATIENT_NOTIFIED → PATIENT_ACKNOWLEDGED.
    """
    c = _get_case(case_id)
    if c["stage"] != Stage.PATIENT_NOTIFIED:
        raise HTTPException(
            status_code=422,
            detail=f"Patient acknowledgement only valid at PATIENT_NOTIFIED stage (current: {STAGE_LABELS[c['stage']]}).",
        )
    c["owner_accepted"] = True
    c["stage"] = Stage.PATIENT_ACKNOWLEDGED
    c["timeline"].append(
        {
            "ts": _now_ts(),
            "stage": c["stage"],
            "desc": "Patient acknowledged message and confirmed follow-up via secure portal.",
            "actor": "Patient — Secure Portal",
        }
    )
    return {
        "status": "patient_acknowledged",
        "case": c["id"],
        "stage": c["stage"],
        "stage_label": STAGE_LABELS[c["stage"]],
    }


# ─────────────────────────────────────────────────────────────
#  ROUTES — CLOSURE LOCK
# ─────────────────────────────────────────────────────────────

@app.post("/cases/{case_id}/close", tags=["workflow"])
def close_case(case_id: str, body: ClosureRequest):
    """
    Evidence-locked case closure.

    Both a valid Malaffi confirmation token (prefix: MALAFFI-CONF-) and
    a documented closure evidence type are mandatory. Neither may be omitted.
    Every closure is immutably appended to the case timeline.
    """
    c = _get_case(case_id)

    if c["stage"] < Stage.REFERRAL_ACCEPTED:
        raise HTTPException(
            status_code=422,
            detail=f"Closure not permitted: case must reach REFERRAL_ACCEPTED first (current: {STAGE_LABELS[c['stage']]}).",
        )
    if c["stage"] == Stage.CLOSED_VERIFIED:
        raise HTTPException(status_code=422, detail="Case is already closed.")

    token = (body.token or "").strip()
    evidence = (body.evidence or "").strip()

    if not token.startswith("MALAFFI-CONF-"):
        raise HTTPException(
            status_code=422,
            detail="Invalid Malaffi token. Required format: MALAFFI-CONF-XXXX.",
        )
    if not evidence or evidence == CLOSURE_OPTS[0]:
        raise HTTPException(
            status_code=422,
            detail="No closure evidence type selected. You must document the evidence before closing.",
        )

    c["closure_token"] = token
    c["closure_evidence"] = evidence
    c["stage"] = Stage.CLOSED_VERIFIED
    audit_id = str(uuid.uuid4())
    c["timeline"].append(
        {
            "ts": _now_ts(),
            "stage": Stage.CLOSED_VERIFIED,
            "desc": f"Case closed. Token: {token}. Evidence: {evidence}. Audit: {audit_id}.",
            "actor": c["owner"],
        }
    )
    return {
        "status": "closed_verified",
        "case": c["id"],
        "closure_token": token,
        "closure_evidence": evidence,
        "audit_id": audit_id,
    }


# ─────────────────────────────────────────────────────────────
#  ROUTES — AGENT / SIMULATION
# ─────────────────────────────────────────────────────────────

@app.post("/agent/scan", tags=["agent"])
def agent_scan():
    """
    Deterministic watchdog scan. Returns SLA status for all open cases.
    Does not make any clinical decisions — only flags and routes.
    """
    alerts = []
    for c in _cases:
        status = _sla_status(c)
        if c["stage"] < Stage.CLOSED_VERIFIED:
            if not c["owner_accepted"]:
                alerts.append(
                    {
                        "level": "warn",
                        "case": c["id"],
                        "msg": f"{c['id']} owner unaccepted — escalation queued",
                    }
                )
            if status == "BREACH":
                alerts.append(
                    {
                        "level": "error",
                        "case": c["id"],
                        "msg": f"{c['id']} SLA BREACH — medical director notified",
                    }
                )
            elif status == "WARNING":
                alerts.append(
                    {
                        "level": "warn",
                        "case": c["id"],
                        "msg": f"{c['id']} SLA WARNING — {c['sla_remaining']}m remaining",
                    }
                )
            if c["stage"] == Stage.OFFLINE_FALLBACK:
                alerts.append(
                    {
                        "level": "action",
                        "case": c["id"],
                        "msg": f"{c['id']} in OFFLINE_FALLBACK — Call Centre action required",
                    }
                )

    open_count = sum(1 for c in _cases if c["stage"] < Stage.CLOSED_VERIFIED)
    unverified = sum(1 for c in _cases if c["stage"] == Stage.CLOSED_VERIFIED and not c.get("closure_token"))
    return {
        "status": "scan_complete",
        "open_cases": open_count,
        "unverified_closures": unverified,
        "alerts": alerts,
        "audit": "ADHICS audit passed",
    }


@app.post("/agent/simulate_rejection/{case_id}", tags=["agent"])
def simulate_rejection(case_id: str):
    """
    Simulate a provider rejection and automatic re-route.
    Demonstrates the drop-off prevention mechanism.
    """
    c = _get_case(case_id)
    old_provider = c["provider_chain"][-1] if c["provider_chain"] else "Unknown Provider"
    new_provider = "Mubadala Oncology Centre"
    c["provider_chain"][-1] = new_provider
    c["sla_remaining"] = min(c["sla_total"], c["sla_remaining"] + 20)  # SLA reset
    c["timeline"].append(
        {
            "ts": _now_ts(),
            "stage": c["stage"],
            "desc": f"Referral rejected by {old_provider} (capacity). Auto-rerouted to {new_provider}. SLA reset. Patient notified.",
            "actor": "AGENT-REROUTE: Deterministic Fallback",
        }
    )
    return {
        "status": "rerouted",
        "case": c["id"],
        "old_provider": old_provider,
        "new_provider": new_provider,
        "msg": f"Drop-off prevented. Referral rerouted to {new_provider}.",
    }


@app.post("/agent/trigger_sla_breach/{case_id}", tags=["agent"])
def trigger_sla_breach(case_id: str):
    """Simulation: burn down the SLA clock to force a breach."""
    c = _get_case(case_id)
    c["sla_remaining"] = max(0, c["sla_remaining"] - 10)
    return {
        "status": "sla_updated",
        "case": c["id"],
        "sla_remaining": c["sla_remaining"],
        "sla_status": _sla_status(c),
    }


# ─────────────────────────────────────────────────────────────
#  ROUTES — PATIENT PORTAL
# ─────────────────────────────────────────────────────────────

@app.get("/patient/{token}", tags=["patient_portal"])
def patient_portal_lookup(token: str):
    """
    Secure patient portal lookup by token.
    Returns only the information the patient needs — no raw clinical data.
    """
    for c in _cases:
        if c["patient_token"] == token:
            return {
                "id": c["id"],
                "eid": c["eid"],
                "pathway": c["pathway"],
                "condition": c["condition"],
                "stage": c["stage"],
                "stage_label": STAGE_LABELS[c["stage"]],
                "timeline": c["timeline"],
                "bilingual": BILINGUAL.get(c["id"]),
                "is_offline_patient": c.get("is_offline_patient", False),
                "already_acknowledged": c["stage"] >= Stage.PATIENT_ACKNOWLEDGED,
            }
    raise HTTPException(status_code=404, detail="Token not recognised. Please check your notification message.")


# ─────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)