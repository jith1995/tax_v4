"""
ITR Tax Finder Engine v0.1
==========================

Purpose
-------
Internal Phase-1 rule engine for an Indian income-tax "Tax Finder" website.

This engine is meant for:
- Internal demo
- CA review
- Rule testing
- Website integration testing

It is NOT a final filing engine and must not be shown as a legal guarantee.

Primary source stack used for rule structure:
- Income-tax Act, 2025, as amended by Finance Act, 2026
- Income-tax Rules, 2026

Design principle:
- Deterministic rules first.
- AI / LLM should only explain the result, not compute tax independently.
- Every uncertainty becomes a warning flag or CA-review trigger.

Main entry point:
    result = run_itr_engine(user_input)

Expected payload:
    See sample_payload.json in this package.

Author note:
    This is a detailed Phase-1 engine. It intentionally supports many flags and
    warning pathways even when exact computation is parked for CA validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# 0. CONFIGURATION
# ============================================================

PHASE = "PHASE_1_INTERNAL_CA_TEST"
ENGINE_VERSION = "0.1.0"

CURRENCY = "INR"

# New regime slabs as per Income-tax Act, 2025 section 202(1)
NEW_REGIME_SLABS = [
    (0, 400000, 0.00),
    (400000, 800000, 0.05),
    (800000, 1200000, 0.10),
    (1200000, 1600000, 0.15),
    (1600000, 2000000, 0.20),
    (2000000, 2400000, 0.25),
    (2400000, None, 0.30),
]

# Phase-1 treatment:
# Old regime exact slab and surcharge/marginal relief can be added later.
OLD_REGIME_SLABS_PLACEHOLDER = None

# Section 156 rebate. For new regime, resident individual gets rebate up to 12L.
NEW_REGIME_REBATE_INCOME_LIMIT = 1200000
NEW_REGIME_REBATE_MAX = 60000

# Old regime basic rebate placeholder under section 156(1)
OLD_REGIME_REBATE_INCOME_LIMIT = 500000
OLD_REGIME_REBATE_MAX = 12500

# Salary deductions
STANDARD_DEDUCTION_NEW_REGIME = 75000
STANDARD_DEDUCTION_OLD_REGIME = 50000

# House property
SELF_OCCUPIED_INTEREST_CAP_NORMAL = 200000
SELF_OCCUPIED_INTEREST_CAP_FALLBACK = 30000

# Deductions under Chapter VIII / old 80C-style basket
SECTION_123_LIMIT = 150000

# Common special rates
SPECIAL_RATE_STCG_EQUITY_196 = 0.20
SPECIAL_RATE_LTCG_GENERAL_197 = 0.125
SPECIAL_RATE_LTCG_EQUITY_198 = 0.125
SPECIAL_RATE_VDA = 0.30
SPECIAL_RATE_WINNINGS = 0.30
SPECIAL_RATE_PATENT_ROYALTY = 0.10
SPECIAL_RATE_CARBON_CREDIT = 0.10
LTCG_EQUITY_EXEMPT_AMOUNT_198 = 125000

# Phase-1 cess/surcharge config
APPLY_HEALTH_EDUCATION_CESS = False
HEALTH_EDUCATION_CESS_RATE = 0.04
APPLY_SURCHARGE = False

# Filing trigger placeholders. Update annually / via rules if needed.
BASIC_EXEMPTION_DEFAULT = 400000  # new regime nil slab threshold for Phase 1
HIGH_VALUE_SAVINGS_DEPOSIT_TRIGGER = 5000000
TDS_TCS_TRIGGER_NON_SENIOR = 25000
TDS_TCS_TRIGGER_SENIOR = 50000

# ITR total income threshold mentioned in Rules for ITR-1 / ITR-4 exclusions
ITR_1_4_TOTAL_INCOME_LIMIT = 5000000

SOURCE_REFERENCES = {
    "act_section_5_scope": "Income-tax Act, 2025, section 5",
    "act_section_6_residence": "Income-tax Act, 2025, section 6",
    "act_section_13_heads": "Income-tax Act, 2025, section 13",
    "act_sections_15_19_salary": "Income-tax Act, 2025, sections 15 to 19",
    "act_sections_20_25_house_property": "Income-tax Act, 2025, sections 20 to 25",
    "act_sections_26_60_pgbp": "Income-tax Act, 2025, sections 26 to 60",
    "act_section_58_presumptive": "Income-tax Act, 2025, section 58",
    "act_section_67_capital_gains": "Income-tax Act, 2025, section 67",
    "act_section_2_101_holding": "Income-tax Act, 2025, section 2(101)",
    "act_sections_196_198_capital_gains_rates": "Income-tax Act, 2025, sections 196 to 198",
    "act_section_194_special_rates": "Income-tax Act, 2025, section 194",
    "act_section_202_new_regime": "Income-tax Act, 2025, section 202",
    "act_section_156_rebate": "Income-tax Act, 2025, section 156",
    "act_chapter_viii_deductions": "Income-tax Act, 2025, Chapter VIII",
    "rules_rule_136_new_regime_option": "Income-tax Rules, 2026, rule 136",
    "rules_rule_164_itr_forms": "Income-tax Rules, 2026, rule 164",
    "rules_rule_8_crew_ship": "Income-tax Rules, 2026, rule 8",
}


# ============================================================
# 1. RESULT MODELS
# ============================================================

@dataclass
class EngineMessage:
    code: str
    severity: str  # info / warning / critical
    message: str
    source: Optional[str] = None


@dataclass
class IncomeHeadSummary:
    salary: float = 0.0
    house_property: float = 0.0
    pgbp: float = 0.0
    capital_gains_normal: float = 0.0
    capital_gains_special: float = 0.0
    other_sources_normal: float = 0.0
    other_sources_special: float = 0.0
    exempt_income: float = 0.0

    @property
    def gross_total_income_before_chapter_deductions(self) -> float:
        return (
            self.salary
            + self.house_property
            + self.pgbp
            + self.capital_gains_normal
            + self.capital_gains_special
            + self.other_sources_normal
            + self.other_sources_special
        )


@dataclass
class TaxBucket:
    normal_slab_income: float = 0.0
    stcg_equity_196: float = 0.0
    ltcg_general_197: float = 0.0
    ltcg_equity_198: float = 0.0
    vda_194: float = 0.0
    winnings_194: float = 0.0
    patent_royalty_194: float = 0.0
    carbon_credit_194: float = 0.0
    other_special: float = 0.0


@dataclass
class EngineResult:
    engine_version: str
    phase: str
    residential_status: Dict[str, Any]
    taxable_scope: Dict[str, Any]
    five_heads_summary: Dict[str, Any]
    exemptions: Dict[str, Any]
    deductions: Dict[str, Any]
    tax_buckets: Dict[str, Any]
    tax_estimate: Dict[str, Any]
    filing_requirement: Dict[str, Any]
    likely_itr_form: Dict[str, Any]
    documents: Dict[str, Any]
    complexity: Dict[str, Any]
    recommendation: Dict[str, Any]
    messages: List[Dict[str, Any]]
    source_map: Dict[str, str]
    raw_debug: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 2. HELPER FUNCTIONS
# ============================================================

def money(value: Any, default: float = 0.0) -> float:
    """Convert incoming numeric value to float safely."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace("₹", "").replace("INR", "")
        if s == "":
            return default
        try:
            return float(s)
        except ValueError:
            return default
    return default


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"yes", "true", "1", "y"}
    if isinstance(value, (int, float)):
        return value != 0
    return default


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def get_nested(d: Dict[str, Any], path: str, default: Any = None) -> Any:
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def days_between(start: Optional[str], end: Optional[str]) -> Optional[int]:
    if not start or not end:
        return None
    try:
        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()
        return (e - s).days
    except Exception:
        return None


def progressive_tax(income: float, slabs: List[Tuple[float, Optional[float], float]]) -> float:
    """Compute slab-based tax."""
    income = max(0.0, money(income))
    tax = 0.0
    for lower, upper, rate in slabs:
        if income <= lower:
            continue
        taxable_in_slab = min(income, upper) - lower if upper is not None else income - lower
        taxable_in_slab = max(0.0, taxable_in_slab)
        tax += taxable_in_slab * rate
        if upper is not None and income <= upper:
            break
    return round(tax, 2)


def add_msg(messages: List[EngineMessage], code: str, severity: str, message: str, source: Optional[str] = None):
    messages.append(EngineMessage(code=code, severity=severity, message=message, source=source))


def unique(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if not item:
            continue
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out


# ============================================================
# 3. RESIDENTIAL STATUS ENGINE
# ============================================================

def determine_residential_status(payload: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    """
    Determines:
    - resident / non_resident
    - ordinary status: ROR / RNOR / NA
    - deemed resident
    - reasons and confidence
    """
    profile = payload.get("profile", {})
    residency = payload.get("residency", {})

    is_individual = profile.get("assessee_type", "individual") == "individual"
    is_indian_citizen = as_bool(profile.get("is_indian_citizen"))
    is_pio = as_bool(profile.get("is_person_of_indian_origin"))
    age = int(money(profile.get("age"), 0))

    current_days = int(money(residency.get("days_in_india_current_tax_year"), 0))
    prev4_days = int(money(residency.get("days_in_india_prev_4_years"), 0))
    prev7_days = residency.get("days_in_india_prev_7_years")
    prev7_days_num = None if prev7_days is None else int(money(prev7_days))
    nr_9_of_10 = residency.get("non_resident_9_of_prev_10_years")
    nr_9_of_10_bool = as_bool(nr_9_of_10) if nr_9_of_10 is not None else None

    left_for_employment = as_bool(residency.get("left_india_for_employment_outside_india"))
    came_for_visit = as_bool(residency.get("came_to_india_for_visit"))
    liable_to_tax_elsewhere = residency.get("liable_to_tax_in_another_country")
    liable_to_tax_elsewhere_bool = as_bool(liable_to_tax_elsewhere) if liable_to_tax_elsewhere is not None else None

    indian_income_ex_foreign = money(residency.get("indian_income_excluding_foreign_sources"))
    indian_income_above_15l = indian_income_ex_foreign > 1500000 if residency.get("indian_income_excluding_foreign_sources") is not None else None

    is_crew_foreign_bound_ship = as_bool(residency.get("is_crew_member_foreign_bound_ship"))
    adjusted_days_note = None

    if is_crew_foreign_bound_ship:
        add_msg(
            messages,
            "CREW_SHIP_REVIEW",
            "warning",
            "Crew member of foreign-bound ship detected. India stay should be adjusted using Continuous Discharge Certificate voyage dates.",
            SOURCE_REFERENCES["rules_rule_8_crew_ship"],
        )
        adjusted_days_note = "Needs voyage-day adjustment as per Rules."

    if not is_individual:
        add_msg(
            messages,
            "NON_INDIVIDUAL_RESIDENCY_PARTIAL",
            "warning",
            "Residential status engine currently has full logic for individuals. Non-individual residence rules require entity-specific handling.",
            SOURCE_REFERENCES["act_section_6_residence"],
        )
        return {
            "status": "needs_entity_residence_review",
            "ordinary_status": None,
            "is_resident": None,
            "is_non_resident": None,
            "is_deemed_resident": False,
            "confidence": "Needs review",
            "reasons": ["Non-individual entity selected."],
            "inputs_used": {
                "assessee_type": profile.get("assessee_type"),
            },
        }

    reasons = []
    confidence = "High"

    resident_by_182 = current_days >= 182
    resident_by_alt = False
    alt_threshold = 60

    # Exceptions to 60-day rule
    if is_indian_citizen and left_for_employment:
        alt_threshold = None
        reasons.append("60-day alternate rule ignored because Indian citizen left India for employment outside India.")
    elif (is_indian_citizen or is_pio) and came_for_visit:
        if indian_income_above_15l is True:
            alt_threshold = 120
            reasons.append("Citizen/PIO visit case with Indian income above ₹15 lakh: 120-day alternate threshold considered.")
        elif indian_income_above_15l is False:
            alt_threshold = None
            reasons.append("Citizen/PIO visit case with Indian income up to ₹15 lakh: alternate 60-day rule ignored.")
        else:
            alt_threshold = None
            confidence = "Medium"
            add_msg(
                messages,
                "INDIAN_INCOME_15L_UNKNOWN",
                "warning",
                "Indian income excluding foreign-source income is unknown, so visit-case residence threshold may require review.",
                SOURCE_REFERENCES["act_section_6_residence"],
            )

    if alt_threshold is not None and current_days >= alt_threshold and prev4_days >= 365:
        resident_by_alt = True

    is_deemed_resident = False
    if (
        is_indian_citizen
        and indian_income_above_15l is True
        and liable_to_tax_elsewhere_bool is False
        and not resident_by_182
        and not resident_by_alt
    ):
        is_deemed_resident = True
        reasons.append("Indian citizen with Indian income above ₹15 lakh and not liable to tax elsewhere: deemed resident path triggered.")

    is_resident = resident_by_182 or resident_by_alt or is_deemed_resident
    if resident_by_182:
        reasons.append("India stay is 182 days or more.")
    if resident_by_alt:
        reasons.append(f"India stay meets alternate threshold of {alt_threshold} days and previous 4-year stay is 365 days or more.")

    if is_resident:
        ordinary_status = "ROR"
        rnor_reasons = []

        if nr_9_of_10_bool is True:
            ordinary_status = "RNOR"
            rnor_reasons.append("Non-resident in 9 out of previous 10 tax years.")
        elif nr_9_of_10 is None:
            confidence = "Medium"
            add_msg(messages, "RNOR_HISTORY_UNKNOWN", "warning", "Previous 10-year non-resident history not provided.", SOURCE_REFERENCES["act_section_6_residence"])

        if prev7_days_num is not None:
            if prev7_days_num <= 729:
                ordinary_status = "RNOR"
                rnor_reasons.append("India stay is 729 days or less in previous 7 tax years.")
        else:
            confidence = "Medium"
            add_msg(messages, "RNOR_PREV7_DAYS_UNKNOWN", "warning", "Previous 7-year India stay days not provided.", SOURCE_REFERENCES["act_section_6_residence"])

        if (
            (is_indian_citizen or is_pio)
            and came_for_visit
            and indian_income_above_15l is True
            and current_days >= 120
            and current_days < 182
        ):
            ordinary_status = "RNOR"
            rnor_reasons.append("Citizen/PIO visit case with 120 to 181 India-stay days and Indian income above ₹15 lakh.")

        if is_deemed_resident:
            ordinary_status = "RNOR"
            rnor_reasons.append("Deemed resident is treated as RNOR for this engine.")

        reasons.extend(rnor_reasons)

        return {
            "status": "resident",
            "ordinary_status": ordinary_status,
            "is_resident": True,
            "is_non_resident": False,
            "is_deemed_resident": is_deemed_resident,
            "confidence": confidence,
            "reasons": reasons,
            "inputs_used": {
                "current_days": current_days,
                "prev4_days": prev4_days,
                "prev7_days": prev7_days_num,
                "is_indian_citizen": is_indian_citizen,
                "is_pio": is_pio,
                "left_for_employment": left_for_employment,
                "came_for_visit": came_for_visit,
                "indian_income_excluding_foreign_sources": indian_income_ex_foreign,
                "liable_to_tax_elsewhere": liable_to_tax_elsewhere_bool,
                "age": age,
            },
            "adjusted_days_note": adjusted_days_note,
        }

    reasons.append("Resident tests not satisfied based on inputs.")
    return {
        "status": "non_resident",
        "ordinary_status": None,
        "is_resident": False,
        "is_non_resident": True,
        "is_deemed_resident": False,
        "confidence": confidence,
        "reasons": reasons,
        "inputs_used": {
            "current_days": current_days,
            "prev4_days": prev4_days,
            "prev7_days": prev7_days_num,
            "is_indian_citizen": is_indian_citizen,
            "is_pio": is_pio,
            "left_for_employment": left_for_employment,
            "came_for_visit": came_for_visit,
            "indian_income_excluding_foreign_sources": indian_income_ex_foreign,
            "liable_to_tax_elsewhere": liable_to_tax_elsewhere_bool,
            "age": age,
        },
        "adjusted_days_note": adjusted_days_note,
    }


# ============================================================
# 4. TAXABLE SCOPE ENGINE
# ============================================================

def determine_taxable_scope(res_status: Dict[str, Any], payload: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    status = res_status.get("status")
    ordinary_status = res_status.get("ordinary_status")
    income = payload.get("income", {})

    has_foreign_income = as_bool(get_nested(income, "foreign_income.has_foreign_income"))
    has_foreign_assets = as_bool(get_nested(income, "foreign_income.has_foreign_assets"))
    has_india_source_income = any([
        money(get_nested(income, "salary.indian_salary_gross")) > 0,
        bool(get_nested(income, "house_property.properties", [])),
        money(get_nested(income, "other_sources.nro_interest")) > 0,
        money(get_nested(income, "other_sources.fd_interest")) > 0,
        bool(get_nested(income, "capital_gains.transactions", [])),
        money(get_nested(income, "pgbp.gross_receipts")) > 0,
    ])

    if status == "resident" and ordinary_status == "ROR":
        scope = "global_income_review"
        description = "Resident and ordinarily resident: global income review is required."
    elif status == "resident" and ordinary_status == "RNOR":
        scope = "india_income_plus_limited_foreign_review"
        description = "RNOR: Indian income is taxable; foreign income generally reviewed only if linked to business controlled in India or profession set up in India."
    elif status == "non_resident":
        scope = "india_income_only"
        description = "Non-resident / NRI: generally India-received, India-accruing, or deemed India-accruing income is considered."
    else:
        scope = "needs_review"
        description = "Taxable scope needs review because residential status is not final."

    warnings = []
    if has_foreign_income:
        warnings.append("Foreign income reported. DTAA / foreign tax credit / foreign disclosure review may be needed.")
        add_msg(messages, "FOREIGN_INCOME_REVIEW", "warning", "Foreign income exists. Needs review based on residential status and DTAA.", SOURCE_REFERENCES["act_section_5_scope"])
    if has_foreign_assets:
        warnings.append("Foreign assets reported. ITR-1/ITR-4 likely not available and disclosure review may be needed.")
        add_msg(messages, "FOREIGN_ASSET_REVIEW", "critical", "Foreign assets exist. Expert review strongly recommended.", SOURCE_REFERENCES["rules_rule_164_itr_forms"])
    if status == "non_resident" and not has_india_source_income:
        warnings.append("No obvious Indian income source found. Filing may be optional unless refund/high-value/TDS triggers apply.")

    return {
        "scope": scope,
        "description": description,
        "has_india_source_income": has_india_source_income,
        "has_foreign_income": has_foreign_income,
        "has_foreign_assets": has_foreign_assets,
        "warnings": warnings,
        "source": SOURCE_REFERENCES["act_section_5_scope"],
    }


# ============================================================
# 5. FIVE HEADS OF INCOME ENGINE
# ============================================================

def compute_salary_income(payload: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    s = get_nested(payload, "income.salary", {}) or {}

    gross_salary = (
        money(s.get("indian_salary_gross"))
        + money(s.get("foreign_salary_gross_taxable_in_india"))
        + money(s.get("bonus"))
        + money(s.get("allowances_taxable"))
        + money(s.get("perquisites_value"))
        + money(s.get("arrears_or_advance_salary"))
        + money(s.get("pension"))
    )

    form16_available = as_bool(s.get("form16_available"))
    multiple_employers = as_bool(s.get("multiple_employers"))
    has_esop = as_bool(s.get("has_esop_or_rsu"))
    foreign_employer = as_bool(s.get("salary_from_foreign_employer"))

    warnings = []
    docs = []

    if gross_salary > 0:
        docs.extend(["Form 16", "Salary slips", "AIS/TIS", "Form 26AS"])
    if not form16_available and gross_salary > 0:
        warnings.append("Form 16 not available. Salary computation may need payslip/manual reconciliation.")
        add_msg(messages, "FORM16_MISSING", "warning", "Form 16 is missing for salary income.", SOURCE_REFERENCES["act_sections_15_19_salary"])
    if multiple_employers:
        warnings.append("Multiple employers. Check duplicate standard deduction, Form 16 reconciliation, and TDS.")
        docs.append("Form 16 from each employer")
    if has_esop:
        warnings.append("ESOP/RSU detected. Perquisite and capital gain review needed.")
        docs.extend(["ESOP/RSU exercise statement", "Employer perquisite statement"])
        add_msg(messages, "ESOP_RSU_REVIEW", "critical", "ESOP/RSU detected. Needs detailed review.", SOURCE_REFERENCES["act_sections_15_19_salary"])
    if foreign_employer:
        warnings.append("Foreign employer salary detected. Residential status and India-service days need review.")
        docs.append("Foreign salary certificate / payslips")

    # Standard deduction is applied later by regime calculator.
    return {
        "gross_salary_before_standard_deduction": round(gross_salary, 2),
        "standard_deduction_new_regime_potential": min(gross_salary, STANDARD_DEDUCTION_NEW_REGIME),
        "standard_deduction_old_regime_potential": min(gross_salary, STANDARD_DEDUCTION_OLD_REGIME),
        "professional_tax_paid": money(s.get("professional_tax_paid")),
        "tds": money(s.get("tds")),
        "warnings": warnings,
        "documents": unique(docs),
        "source": SOURCE_REFERENCES["act_sections_15_19_salary"],
    }


def compute_house_property_income(payload: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    hp = get_nested(payload, "income.house_property", {}) or {}
    properties = as_list(hp.get("properties"))
    docs = []
    warnings = []
    results = []
    total_income = 0.0
    total_loss = 0.0
    self_occupied_count = 0

    for idx, prop in enumerate(properties, start=1):
        if not isinstance(prop, dict):
            continue

        usage = prop.get("usage", "let_out")  # self_occupied / let_out / vacant / deemed_let_out
        is_self_occupied = usage == "self_occupied"
        is_let = usage in {"let_out", "deemed_let_out"}
        is_vacant = usage == "vacant"

        if is_self_occupied:
            self_occupied_count += 1

        expected_rent = money(prop.get("expected_annual_rent"))
        actual_rent = money(prop.get("actual_rent_received_or_receivable"))
        vacancy_adjustment = as_bool(prop.get("vacancy_adjustment_applies"))
        municipal_taxes_paid = money(prop.get("municipal_taxes_paid"))
        interest = money(prop.get("home_loan_interest"))
        preconstruction_interest = money(prop.get("preconstruction_interest_current_year_installment"))
        property_outside_india = as_bool(prop.get("property_outside_india"))
        co_owned = as_bool(prop.get("co_owned"))

        if is_self_occupied:
            annual_value = 0.0
            nav = 0.0
            interest_cap = SELF_OCCUPIED_INTEREST_CAP_NORMAL if as_bool(prop.get("self_occupied_interest_2l_conditions_met"), True) else SELF_OCCUPIED_INTEREST_CAP_FALLBACK
            interest_allowed = min(interest + preconstruction_interest, interest_cap)
            standard_deduction_30 = 0.0
            taxable = -interest_allowed
        elif is_let:
            if vacancy_adjustment and actual_rent < expected_rent:
                annual_value = actual_rent
            else:
                annual_value = max(expected_rent, actual_rent)
            nav = max(0.0, annual_value - municipal_taxes_paid)
            standard_deduction_30 = 0.30 * nav
            interest_allowed = interest + preconstruction_interest
            taxable = nav - standard_deduction_30 - interest_allowed
        else:
            # vacant but not self occupied: Phase-1 conservative handling
            annual_value = max(expected_rent, actual_rent)
            nav = max(0.0, annual_value - municipal_taxes_paid)
            standard_deduction_30 = 0.30 * nav
            interest_allowed = interest + preconstruction_interest
            taxable = nav - standard_deduction_30 - interest_allowed
            warnings.append(f"Property {idx}: vacant property treatment needs CA review.")

        if taxable >= 0:
            total_income += taxable
        else:
            total_loss += taxable

        if property_outside_india:
            warnings.append(f"Property {idx}: foreign property detected.")
            add_msg(messages, "FOREIGN_PROPERTY_REVIEW", "critical", "Foreign house property detected.", SOURCE_REFERENCES["act_section_5_scope"])
        if co_owned:
            warnings.append(f"Property {idx}: co-owned property. Compute only taxpayer share.")
            docs.append("Co-owner share details")

        docs.extend([
            "Rent agreement / rent receipts if let out",
            "Municipal tax payment proof",
            "Home loan interest certificate if loan exists",
        ])

        results.append({
            "property_index": idx,
            "usage": usage,
            "annual_value": round(annual_value, 2),
            "municipal_taxes_paid": round(municipal_taxes_paid, 2),
            "net_annual_value": round(nav, 2),
            "standard_deduction_30_percent": round(standard_deduction_30, 2),
            "interest_allowed_phase1": round(interest_allowed, 2),
            "taxable_house_property_income": round(taxable, 2),
        })

    if self_occupied_count > 2:
        warnings.append("More than two self-occupied properties. Review deemed let-out treatment.")
        add_msg(messages, "MORE_THAN_TWO_SELF_OCCUPIED", "warning", "More than two self-occupied properties detected.", SOURCE_REFERENCES["act_sections_20_25_house_property"])

    net_income = total_income + total_loss
    return {
        "properties": results,
        "net_house_property_income": round(net_income, 2),
        "house_property_loss": round(total_loss, 2),
        "new_regime_loss_setoff_warning": total_loss < 0,
        "warnings": warnings,
        "documents": unique(docs),
        "source": SOURCE_REFERENCES["act_sections_20_25_house_property"],
    }


def compute_pgbp_income(payload: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    p = get_nested(payload, "income.pgbp", {}) or {}

    has_business = as_bool(p.get("has_business_or_profession"))
    has_freelance = as_bool(p.get("has_freelance_or_consulting"))
    has_fno = as_bool(p.get("has_fno_or_intraday"))
    use_presumptive = as_bool(p.get("wants_presumptive_or_special_computation"))

    gross_receipts = money(p.get("gross_receipts"))
    digital_receipts = money(p.get("digital_receipts"))
    cash_receipts = money(p.get("cash_receipts"))
    expenses = money(p.get("business_expenses"))
    net_profit_declared = p.get("net_profit_declared")
    net_profit_declared_val = None if net_profit_declared is None else money(net_profit_declared)

    docs = []
    warnings = []
    result_type = "no_pgbp"
    taxable = 0.0
    presumptive_eligible_phase1 = False

    if not any([has_business, has_freelance, has_fno, gross_receipts > 0]):
        return {
            "has_pgbp": False,
            "taxable_pgbp_income": 0.0,
            "result_type": result_type,
            "warnings": [],
            "documents": [],
            "source": SOURCE_REFERENCES["act_sections_26_60_pgbp"],
        }

    docs.extend(["Business/professional invoices", "Bank statements", "Expense proofs", "TDS certificates"])

    if has_fno:
        warnings.append("F&O / intraday detected. Treat as business route and review audit/loss carry-forward implications.")
        docs.extend(["Broker P&L statement", "Turnover report", "Ledger from broker"])
        add_msg(messages, "FNO_INTRADAY_REVIEW", "critical", "F&O/intraday case detected. CA review recommended.", SOURCE_REFERENCES["act_sections_26_60_pgbp"])

    # Phase-1 presumptive logic. Exact eligibility/threshold should be CA-validated.
    presumptive_type = p.get("presumptive_type")  # small_business / profession / goods_carriage
    if use_presumptive:
        if presumptive_type == "small_business":
            # Old 44AD-like treatment: 6% digital, 8% non-digital. Marked for validation.
            taxable = digital_receipts * 0.06 + max(0.0, gross_receipts - digital_receipts) * 0.08
            result_type = "presumptive_small_business_phase1"
            presumptive_eligible_phase1 = True
        elif presumptive_type == "profession":
            taxable = gross_receipts * 0.50
            result_type = "presumptive_profession_phase1"
            presumptive_eligible_phase1 = True
        elif presumptive_type == "goods_carriage":
            taxable = money(p.get("goods_carriage_presumptive_income"))
            result_type = "presumptive_goods_carriage_phase1"
            presumptive_eligible_phase1 = True
        else:
            warnings.append("Presumptive requested, but presumptive type missing. Used normal profit computation.")
            result_type = "normal_pgbp_due_to_missing_presumptive_type"

    if not presumptive_eligible_phase1:
        if net_profit_declared_val is not None:
            taxable = net_profit_declared_val
            result_type = "normal_pgbp_user_declared_profit"
        else:
            taxable = gross_receipts - expenses
            result_type = "normal_pgbp_receipts_less_expenses"

    if taxable < 0:
        warnings.append("Business/profession loss detected. Loss set-off/carry-forward and audit rules need review.")
        add_msg(messages, "PGBP_LOSS_REVIEW", "warning", "PGBP loss detected.", SOURCE_REFERENCES["act_sections_26_60_pgbp"])

    if as_bool(p.get("books_not_maintained")):
        warnings.append("Books not maintained. Books/audit requirement needs review.")
        add_msg(messages, "BOOKS_NOT_MAINTAINED", "warning", "Business/profession books not maintained.", SOURCE_REFERENCES["act_sections_26_60_pgbp"])

    if use_presumptive:
        add_msg(messages, "PRESUMPTIVE_PHASE1", "info", "Presumptive computation used as Phase-1 approximation. Validate thresholds and eligibility with CA.", SOURCE_REFERENCES["act_section_58_presumptive"])

    return {
        "has_pgbp": True,
        "taxable_pgbp_income": round(taxable, 2),
        "result_type": result_type,
        "presumptive_eligible_phase1": presumptive_eligible_phase1,
        "gross_receipts": round(gross_receipts, 2),
        "expenses": round(expenses, 2),
        "has_fno_or_intraday": has_fno,
        "warnings": warnings,
        "documents": unique(docs),
        "source": SOURCE_REFERENCES["act_sections_26_60_pgbp"],
    }


def classify_holding_period(asset_type: str, holding_months: Optional[float]) -> str:
    if holding_months is None:
        return "unknown"

    asset_type = (asset_type or "").lower()
    twelve_month_assets = {
        "listed_equity",
        "equity_mutual_fund",
        "business_trust_unit",
        "listed_security",
        "zero_coupon_bond",
        "uti_unit",
    }

    if asset_type in twelve_month_assets:
        return "long_term" if holding_months > 12 else "short_term"

    # Act section 2(101): default 24 months
    return "long_term" if holding_months > 24 else "short_term"


def compute_capital_gains(payload: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    cg = get_nested(payload, "income.capital_gains", {}) or {}
    transactions = as_list(cg.get("transactions"))

    docs = []
    warnings = []
    tx_results = []

    tax_bucket = TaxBucket()
    normal_cg = 0.0
    special_cg = 0.0
    total_losses = 0.0

    for idx, tx in enumerate(transactions, start=1):
        if not isinstance(tx, dict):
            continue

        asset_type = tx.get("asset_type", "other_capital_asset")
        sale_value = money(tx.get("sale_value"))
        cost = money(tx.get("cost_of_acquisition"))
        improvement = money(tx.get("cost_of_improvement"))
        transfer_expenses = money(tx.get("transfer_expenses"))
        holding_months = tx.get("holding_months")
        holding_months_val = None if holding_months is None else money(holding_months)

        is_vda = asset_type in {"crypto", "vda", "virtual_digital_asset", "nft"}
        is_equity_stt = asset_type in {"listed_equity", "equity_mutual_fund", "business_trust_unit"} and as_bool(tx.get("stt_paid"))
        is_property = asset_type in {"immovable_property", "land", "building", "land_building", "house_property_sale"}
        is_foreign_asset = as_bool(tx.get("foreign_asset"))
        inherited_or_gifted = as_bool(tx.get("inherited_or_gifted"))

        holding_class = "vda_special" if is_vda else classify_holding_period(asset_type, holding_months_val)
        gain = sale_value - cost - improvement - transfer_expenses

        special_bucket = None
        rate = None

        if is_vda:
            # VDA: only cost allowed, no expense/set-off. User may provide cost only.
            gain = sale_value - cost
            tax_bucket.vda_194 += max(0.0, gain)
            special_bucket = "vda_30_percent"
            rate = SPECIAL_RATE_VDA
            docs.append("Crypto/VDA exchange transaction statement")
            if gain < 0:
                warnings.append(f"Transaction {idx}: VDA loss ignored for set-off/carry-forward in Phase-1 treatment.")
            add_msg(messages, "VDA_SPECIAL_RATE", "warning", "VDA income detected. 30% special rate and no loss set-off treatment applied.", SOURCE_REFERENCES["act_section_194_special_rates"])
        elif holding_class == "short_term" and is_equity_stt:
            tax_bucket.stcg_equity_196 += max(0.0, gain)
            special_bucket = "stcg_equity_20_percent"
            rate = SPECIAL_RATE_STCG_EQUITY_196
        elif holding_class == "long_term" and is_equity_stt:
            tax_bucket.ltcg_equity_198 += max(0.0, gain)
            special_bucket = "ltcg_equity_12_5_percent_above_125000"
            rate = SPECIAL_RATE_LTCG_EQUITY_198
        elif holding_class == "long_term":
            tax_bucket.ltcg_general_197 += max(0.0, gain)
            special_bucket = "ltcg_general_12_5_percent"
            rate = SPECIAL_RATE_LTCG_GENERAL_197
        elif holding_class == "short_term":
            # STCG not covered by special equity route goes to slab.
            tax_bucket.normal_slab_income += gain
            normal_cg += gain
            special_bucket = "normal_slab_stcg"
            rate = None
        else:
            warnings.append(f"Transaction {idx}: holding period unknown. Gain routed to review bucket.")
            tax_bucket.other_special += max(0.0, gain)
            special_bucket = "holding_period_unknown_review"
            rate = None

        if gain >= 0 and special_bucket != "normal_slab_stcg":
            special_cg += gain
        elif gain < 0:
            total_losses += gain
            warnings.append(f"Transaction {idx}: capital loss detected. Set-off/carry-forward needs review.")

        if is_property:
            docs.extend(["Sale deed", "Purchase deed", "Stamp duty value", "Improvement cost proof", "Capital gains calculation statement"])
            warnings.append(f"Transaction {idx}: property sale detected. Exemption/indexation/stamp value review needed.")
        elif asset_type in {"listed_equity", "equity_mutual_fund"}:
            docs.append("Broker capital gains statement")
        elif is_foreign_asset:
            docs.append("Foreign broker statement")
            warnings.append(f"Transaction {idx}: foreign asset sale detected. DTAA/foreign disclosure review needed.")
            add_msg(messages, "FOREIGN_CAPITAL_GAIN_REVIEW", "critical", "Foreign capital gain transaction detected.", SOURCE_REFERENCES["act_section_5_scope"])

        if inherited_or_gifted:
            docs.append("Gift deed / inheritance documents and previous owner cost details")
            warnings.append(f"Transaction {idx}: inherited/gifted asset. Previous owner cost and holding period need review.")

        tx_results.append({
            "transaction_index": idx,
            "asset_type": asset_type,
            "holding_class": holding_class,
            "sale_value": round(sale_value, 2),
            "cost_of_acquisition": round(cost, 2),
            "cost_of_improvement": round(improvement, 2),
            "transfer_expenses": round(transfer_expenses, 2),
            "gain_or_loss_phase1": round(gain, 2),
            "special_bucket": special_bucket,
            "rate": rate,
        })

    return {
        "transactions": tx_results,
        "normal_capital_gains": round(normal_cg, 2),
        "special_capital_gains": round(special_cg, 2),
        "capital_losses": round(total_losses, 2),
        "tax_bucket_delta": asdict(tax_bucket),
        "warnings": warnings,
        "documents": unique(docs),
        "source": SOURCE_REFERENCES["act_sections_196_198_capital_gains_rates"],
    }


def compute_other_sources(payload: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    other = get_nested(payload, "income.other_sources", {}) or {}

    savings_interest = money(other.get("savings_interest"))
    fd_interest = money(other.get("fd_interest"))
    nro_interest = money(other.get("nro_interest"))
    nre_interest = money(other.get("nre_interest"))
    bond_interest = money(other.get("bond_interest"))
    dividend_indian = money(other.get("dividend_indian"))
    dividend_foreign = money(other.get("dividend_foreign"))
    family_pension = money(other.get("family_pension"))
    gifts_taxable = money(other.get("gifts_taxable"))
    other_income = money(other.get("other_income"))

    lottery_winnings = money(other.get("lottery_winnings"))
    online_game_winnings = money(other.get("online_game_winnings"))
    race_horse_winnings = money(other.get("race_horse_winnings"))
    patent_royalty = money(other.get("patent_royalty"))
    carbon_credit_income = money(other.get("carbon_credit_income"))

    # Phase-1: NRE interest treated as exempt flag if user says eligible.
    nre_interest_eligible_exempt = as_bool(other.get("nre_interest_eligible_exempt"), True if nre_interest > 0 else False)
    exempt_income = nre_interest if nre_interest_eligible_exempt else 0.0
    taxable_nre = 0.0 if nre_interest_eligible_exempt else nre_interest

    normal_other = (
        savings_interest
        + fd_interest
        + nro_interest
        + taxable_nre
        + bond_interest
        + dividend_indian
        + dividend_foreign
        + family_pension
        + gifts_taxable
        + other_income
    )

    tax_bucket = TaxBucket()
    tax_bucket.winnings_194 = lottery_winnings + online_game_winnings + race_horse_winnings
    tax_bucket.patent_royalty_194 = patent_royalty
    tax_bucket.carbon_credit_194 = carbon_credit_income

    docs = []
    warnings = []

    if normal_other or tax_bucket.winnings_194 or exempt_income:
        docs.extend(["AIS/TIS", "Form 26AS", "Bank interest certificates"])

    if nro_interest > 0:
        docs.append("NRO interest certificate")
    if nre_interest > 0:
        docs.append("NRE interest certificate")
        if nre_interest_eligible_exempt:
            warnings.append("NRE interest treated as exempt based on user input. Confirm eligibility.")
    if dividend_foreign > 0:
        docs.append("Foreign dividend statement")
        warnings.append("Foreign dividend detected. Residential status and foreign tax credit review may apply.")
    if gifts_taxable > 0:
        docs.append("Gift deed / donor details")
        warnings.append("Taxable gift amount entered. Relative/exemption threshold review needed.")
    if tax_bucket.winnings_194 > 0:
        docs.append("Winning certificate / TDS certificate")
        warnings.append("Lottery/online gaming/race winnings detected. Special-rate tax applies.")
        add_msg(messages, "WINNINGS_SPECIAL_RATE", "warning", "Winnings detected. Special-rate tax route applied.", SOURCE_REFERENCES["act_section_194_special_rates"])

    return {
        "normal_other_sources_income": round(normal_other, 2),
        "special_other_sources_income": round(
            tax_bucket.winnings_194 + tax_bucket.patent_royalty_194 + tax_bucket.carbon_credit_194,
            2,
        ),
        "exempt_income": round(exempt_income, 2),
        "tax_bucket_delta": asdict(tax_bucket),
        "warnings": warnings,
        "documents": unique(docs),
        "source": SOURCE_REFERENCES["act_section_13_heads"],
    }


def compute_five_heads(payload: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    salary = compute_salary_income(payload, messages)
    house = compute_house_property_income(payload, messages)
    pgbp = compute_pgbp_income(payload, messages)
    cg = compute_capital_gains(payload, messages)
    other = compute_other_sources(payload, messages)

    summary = IncomeHeadSummary()
    summary.salary = salary["gross_salary_before_standard_deduction"]
    summary.house_property = house["net_house_property_income"]
    summary.pgbp = pgbp["taxable_pgbp_income"]
    summary.capital_gains_normal = cg["normal_capital_gains"]
    summary.capital_gains_special = cg["special_capital_gains"]
    summary.other_sources_normal = other["normal_other_sources_income"]
    summary.other_sources_special = other["special_other_sources_income"]
    summary.exempt_income = other["exempt_income"]

    bucket = TaxBucket()
    # Normal income
    bucket.normal_slab_income += summary.salary + summary.house_property + summary.pgbp + summary.capital_gains_normal + summary.other_sources_normal

    # Merge capital gains special buckets
    for k, v in cg["tax_bucket_delta"].items():
        setattr(bucket, k, getattr(bucket, k) + money(v))

    # Merge other special buckets
    for k, v in other["tax_bucket_delta"].items():
        setattr(bucket, k, getattr(bucket, k) + money(v))

    docs = unique(
        salary["documents"]
        + house["documents"]
        + pgbp["documents"]
        + cg["documents"]
        + other["documents"]
    )
    warnings = salary["warnings"] + house["warnings"] + pgbp["warnings"] + cg["warnings"] + other["warnings"]

    return {
        "salary": salary,
        "house_property": house,
        "pgbp": pgbp,
        "capital_gains": cg,
        "other_sources": other,
        "summary": asdict(summary),
        "tax_buckets_before_deductions": asdict(bucket),
        "documents": docs,
        "warnings": warnings,
        "source": SOURCE_REFERENCES["act_section_13_heads"],
    }


# ============================================================
# 6. EXEMPTIONS ENGINE
# ============================================================

def compute_exemptions(payload: Dict[str, Any], five_heads: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    """
    Phase-1 exemption engine.

    Most exemptions are not computed deeply here. They are surfaced as:
    - already_excluded/exempt input
    - flags requiring documents
    - capital gains exemption flags
    """
    ex = payload.get("exemptions", {}) or {}
    docs = []
    warnings = []
    total_exempt = 0.0

    # User-entered exempt items
    exempt_agricultural_income = money(ex.get("agricultural_income"))
    exempt_hra = money(ex.get("hra_exemption_claimed"))
    exempt_lta = money(ex.get("lta_exemption_claimed"))
    exempt_gratuity = money(ex.get("gratuity_exemption_claimed"))
    exempt_leave_encashment = money(ex.get("leave_encashment_exemption_claimed"))
    exempt_pension_commutation = money(ex.get("commuted_pension_exemption_claimed"))
    exempt_capital_gains_reinvestment = money(ex.get("capital_gains_reinvestment_exemption_claimed"))

    total_exempt += (
        exempt_agricultural_income
        + exempt_hra
        + exempt_lta
        + exempt_gratuity
        + exempt_leave_encashment
        + exempt_pension_commutation
        + exempt_capital_gains_reinvestment
        + money(get_nested(five_heads, "summary.exempt_income"))
    )

    if exempt_hra > 0:
        docs.extend(["Rent receipts", "Rent agreement", "Landlord PAN if applicable"])
    if exempt_lta > 0:
        docs.append("Travel bills / LTA proof")
    if exempt_gratuity > 0:
        docs.append("Gratuity computation / employer certificate")
    if exempt_leave_encashment > 0:
        docs.append("Leave encashment computation / employer certificate")
    if exempt_pension_commutation > 0:
        docs.append("Pension commutation certificate")
    if exempt_capital_gains_reinvestment > 0:
        docs.extend(["Capital gains exemption investment proof", "Capital Gains Account Scheme proof if applicable"])
        warnings.append("Capital gains reinvestment exemption claimed. Section-specific eligibility and timelines need CA validation.")
    if exempt_agricultural_income > 0:
        docs.append("Agricultural income proof")
        warnings.append("Agricultural income declared. Partial integration / ITR eligibility review may be needed.")

    if total_exempt > 0:
        add_msg(messages, "EXEMPTIONS_PHASE1", "info", "Exemptions are treated based on user input and documents. Detailed formula validation pending.", "Income-tax Act, 2025, Schedules II to VII and relevant sections")

    return {
        "total_exempt_income_or_claimed_exemption": round(total_exempt, 2),
        "breakup": {
            "agricultural_income": exempt_agricultural_income,
            "hra": exempt_hra,
            "lta": exempt_lta,
            "gratuity": exempt_gratuity,
            "leave_encashment": exempt_leave_encashment,
            "commuted_pension": exempt_pension_commutation,
            "capital_gains_reinvestment": exempt_capital_gains_reinvestment,
            "other_exempt_from_heads": money(get_nested(five_heads, "summary.exempt_income")),
        },
        "documents": unique(docs),
        "warnings": warnings,
        "source": "Income-tax Act, 2025 exemptions schedules / sections; Phase-1 user-entered treatment",
    }


# ============================================================
# 7. CHAPTER VIII / CHAPTER VI-A-STYLE DEDUCTIONS ENGINE
# ============================================================

def compute_chapter_deductions(payload: Dict[str, Any], res_status: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    """
    Deductions under new Act Chapter VIII, equivalent product language:
    "Chapter VI-A style deductions".

    Phase-1 returns both:
    - old_regime_potential_deductions
    - new_regime_allowed_deductions

    Under section 202 new regime, Chapter VIII deductions are generally not allowed
    except specific allowed provisions including section 124(1), 124(2), 125(2), 146.
    """
    d = payload.get("deductions", {}) or {}
    profile = payload.get("profile", {})
    assessee_type = profile.get("assessee_type", "individual")
    is_individual = assessee_type == "individual"
    is_huf = assessee_type == "huf"
    is_resident = res_status.get("status") == "resident"

    docs = []
    warnings = []

    # Section 123: 80C-like basket limit
    sec123_raw = (
        money(d.get("life_insurance_premium"))
        + money(d.get("epf_employee"))
        + money(d.get("ppf"))
        + money(d.get("elss"))
        + money(d.get("tax_saver_fd"))
        + money(d.get("nsc"))
        + money(d.get("sukanya_samriddhi"))
        + money(d.get("children_tuition_fees"))
        + money(d.get("home_loan_principal"))
        + money(d.get("other_section_123"))
    )
    sec123_allowed_old = min(sec123_raw, SECTION_123_LIMIT) if (is_individual or is_huf) else 0.0
    if sec123_raw > 0:
        docs.append("Tax-saving investment proofs")

    # Section 124: NPS / pension scheme
    # Phase-1 simplified:
    # - employee/self contribution user-provided as nps_self
    # - employer contribution user-provided as nps_employer
    nps_self = money(d.get("nps_self_contribution"))
    nps_employer = money(d.get("nps_employer_contribution"))
    nps_additional = money(d.get("nps_additional_voluntary"))
    nps_total_old = nps_self + nps_employer + nps_additional
    # New regime: section 124(1) and 124(2) allowed. Treat employer/self based on user classification.
    nps_total_new = nps_self + nps_employer
    if nps_total_old > 0:
        docs.append("NPS contribution statement")
        warnings.append("NPS limit check is simplified in Phase-1. Validate salary/gross income based limits.")

    # Section 125: Agnipath
    agniveer_self = money(d.get("agniveer_corpus_self"))
    agniveer_govt = money(d.get("agniveer_corpus_government"))
    agniveer_old = agniveer_self + agniveer_govt
    # Section 202 allows 125(2), government contribution, under new regime.
    agniveer_new = agniveer_govt
    if agniveer_old > 0:
        docs.append("Agniveer Corpus Fund statement")

    # Section 126: Health insurance
    health_self_family = money(d.get("health_insurance_self_family"))
    health_parents = money(d.get("health_insurance_parents"))
    medical_self_family_senior = money(d.get("medical_expense_self_family_senior"))
    medical_parents_senior = money(d.get("medical_expense_parents_senior"))
    preventive = money(d.get("preventive_health_checkup"))
    health_old = 0.0
    if is_individual or is_huf:
        # Simplified 25k/50k caps with senior medical expenses branch.
        self_family_cap = 50000 if medical_self_family_senior > 0 else 25000
        parent_cap = 50000 if medical_parents_senior > 0 else 25000
        preventive_allowed = min(preventive, 5000)
        health_old += min(health_self_family + medical_self_family_senior + preventive_allowed, self_family_cap)
        health_old += min(health_parents + medical_parents_senior, parent_cap)
    if health_old > 0:
        docs.append("Health insurance premium receipts")
        warnings.append("Health insurance deduction is simplified. Senior citizen and preventive health split should be validated.")

    # Section 127: dependent disability
    dependent_disability = 0.0
    if as_bool(d.get("dependent_disability")):
        dependent_disability = 125000 if as_bool(d.get("dependent_severe_disability")) else 75000
        docs.append("Dependent disability certificate")
        if not is_resident:
            warnings.append("Dependent disability deduction generally needs resident status. Check eligibility.")

    # Section 128: specified disease medical treatment
    specified_disease_paid = money(d.get("specified_disease_medical_treatment_paid"))
    specified_disease_reimbursement = money(d.get("specified_disease_reimbursement"))
    specified_disease_cap = 100000 if as_bool(d.get("specified_disease_senior_citizen")) else 40000
    specified_disease_old = max(0.0, min(specified_disease_paid, specified_disease_cap) - specified_disease_reimbursement)
    if specified_disease_old > 0:
        docs.append("Prescription from specialist / medical treatment proof")

    # Section 129: education loan interest
    education_loan_interest = money(d.get("education_loan_interest"))
    if education_loan_interest > 0:
        docs.append("Education loan interest certificate")

    # Sections 130/131: house property purchase interest, affordable housing etc.
    affordable_housing_interest_130 = money(d.get("affordable_housing_interest_130"))
    affordable_housing_interest_131 = min(money(d.get("affordable_housing_interest_131")), 150000)
    if affordable_housing_interest_130 or affordable_housing_interest_131:
        docs.append("Housing loan sanction letter and interest certificate")
        warnings.append("Affordable housing deduction conditions need validation: sanction date, stamp duty value, first-home condition.")

    # Section 132: EV loan interest
    ev_interest = min(money(d.get("ev_loan_interest")), 150000)
    if ev_interest > 0:
        docs.append("EV loan interest certificate")
        warnings.append("EV loan deduction requires loan sanction period validation.")

    # Section 133: donations
    donations_100 = money(d.get("donations_100_percent"))
    donations_50 = money(d.get("donations_50_percent"))
    donations_subject_to_limit = money(d.get("donations_subject_to_qualifying_limit"))
    # Phase-1: exact qualifying limit not computed. Use direct 100 + 50%.
    donation_old = donations_100 + 0.50 * donations_50
    if donations_subject_to_limit > 0:
        donation_old += 0.50 * donations_subject_to_limit
        warnings.append("Donation subject to qualifying limit simplified at 50%. Need detailed qualifying-limit calculation.")
    if donation_old > 0:
        docs.extend(["Donation receipt", "Form/certificate from donee where applicable"])

    # Section 134: rent paid deduction
    rent_paid_deduction_user = money(d.get("rent_paid_deduction_claim"))
    rent_paid_old = rent_paid_deduction_user
    if rent_paid_old > 0:
        docs.append("Declaration for rent paid / rent receipts")
        warnings.append("Rent paid deduction uses user-entered claim. Compute formula later.")

    # Section 154: self disability
    self_disability = 0.0
    if as_bool(d.get("self_disability")):
        self_disability = 125000 if as_bool(d.get("self_severe_disability")) else 75000
        docs.append("Self disability certificate")
        if not is_resident:
            warnings.append("Self disability deduction generally needs resident status. Check eligibility.")

    # Interest on savings/deposit deductions, mapped via user input since sections differ
    savings_interest_deduction = money(d.get("savings_interest_deduction_claim"))
    senior_deposit_interest_deduction = money(d.get("senior_deposit_interest_deduction_claim"))

    # Section 146 allowed in new regime, but mostly business/IFSC type. Keep as user-entered placeholder.
    section_146_new_allowed = money(d.get("section_146_allowed_deduction"))

    old_total = sum([
        sec123_allowed_old,
        nps_total_old,
        agniveer_old,
        health_old,
        dependent_disability,
        specified_disease_old,
        education_loan_interest,
        affordable_housing_interest_130,
        affordable_housing_interest_131,
        ev_interest,
        donation_old,
        rent_paid_old,
        self_disability,
        savings_interest_deduction,
        senior_deposit_interest_deduction,
        section_146_new_allowed,
    ])

    new_total = sum([
        nps_total_new,
        agniveer_new,
        section_146_new_allowed,
    ])

    if old_total > 0 and new_total < old_total:
        add_msg(
            messages,
            "NEW_REGIME_DEDUCTIONS_RESTRICTED",
            "info",
            "Many Chapter VIII deductions are generally not allowed under new regime. Engine computes both old-potential and new-allowed buckets.",
            SOURCE_REFERENCES["act_section_202_new_regime"],
        )

    return {
        "old_regime_potential": {
            "section_123_80c_style": round(sec123_allowed_old, 2),
            "nps_section_124": round(nps_total_old, 2),
            "agniveer_section_125": round(agniveer_old, 2),
            "health_section_126": round(health_old, 2),
            "dependent_disability_section_127": round(dependent_disability, 2),
            "specified_disease_section_128": round(specified_disease_old, 2),
            "education_loan_section_129": round(education_loan_interest, 2),
            "housing_section_130": round(affordable_housing_interest_130, 2),
            "housing_section_131": round(affordable_housing_interest_131, 2),
            "ev_section_132": round(ev_interest, 2),
            "donations_section_133": round(donation_old, 2),
            "rent_paid_section_134": round(rent_paid_old, 2),
            "self_disability_section_154": round(self_disability, 2),
            "interest_deductions_user_claimed": round(savings_interest_deduction + senior_deposit_interest_deduction, 2),
            "section_146": round(section_146_new_allowed, 2),
            "total": round(old_total, 2),
        },
        "new_regime_allowed": {
            "nps_section_124_1_2": round(nps_total_new, 2),
            "agniveer_govt_section_125_2": round(agniveer_new, 2),
            "section_146": round(section_146_new_allowed, 2),
            "total": round(new_total, 2),
        },
        "documents": unique(docs),
        "warnings": warnings,
        "source": SOURCE_REFERENCES["act_chapter_viii_deductions"],
    }


# ============================================================
# 8. TAX CALCULATION ENGINE
# ============================================================

def compute_tax_buckets_after_regime(
    payload: Dict[str, Any],
    res_status: Dict[str, Any],
    five_heads: Dict[str, Any],
    deductions: Dict[str, Any],
    messages: List[EngineMessage],
) -> Dict[str, Any]:
    """
    Computes Phase-1 tax under new regime.

    Old regime is intentionally kept pending because the user decided to circle
    back to old regime detailed slabs/config later.
    """
    buckets = TaxBucket(**five_heads["tax_buckets_before_deductions"])
    salary_gross = money(get_nested(five_heads, "salary.gross_salary_before_standard_deduction"))

    # Apply salary standard deduction under new regime
    salary_std = min(salary_gross, STANDARD_DEDUCTION_NEW_REGIME)
    buckets.normal_slab_income -= salary_std

    # New regime: house property loss cannot be set off with other heads.
    hp_loss = money(get_nested(five_heads, "house_property.house_property_loss"))
    if hp_loss < 0:
        buckets.normal_slab_income -= hp_loss  # add back the negative loss included earlier
        add_msg(
            messages,
            "NEW_REGIME_HP_LOSS_SET_OFF_BLOCKED",
            "warning",
            "House property loss set-off against other heads blocked under Phase-1 new regime treatment.",
            SOURCE_REFERENCES["act_section_202_new_regime"],
        )

    # Apply new-regime allowed Chapter deductions
    new_deductions = money(get_nested(deductions, "new_regime_allowed.total"))
    buckets.normal_slab_income -= new_deductions

    # Normal slab income cannot go below zero in this phase.
    buckets.normal_slab_income = max(0.0, buckets.normal_slab_income)

    normal_tax = progressive_tax(buckets.normal_slab_income, NEW_REGIME_SLABS)

    # Special-rate taxes
    stcg_equity_tax = max(0.0, buckets.stcg_equity_196) * SPECIAL_RATE_STCG_EQUITY_196

    ltcg_equity_taxable = max(0.0, buckets.ltcg_equity_198 - LTCG_EQUITY_EXEMPT_AMOUNT_198)
    ltcg_equity_tax = ltcg_equity_taxable * SPECIAL_RATE_LTCG_EQUITY_198

    ltcg_general_tax = max(0.0, buckets.ltcg_general_197) * SPECIAL_RATE_LTCG_GENERAL_197
    vda_tax = max(0.0, buckets.vda_194) * SPECIAL_RATE_VDA
    winnings_tax = max(0.0, buckets.winnings_194) * SPECIAL_RATE_WINNINGS
    patent_tax = max(0.0, buckets.patent_royalty_194) * SPECIAL_RATE_PATENT_ROYALTY
    carbon_tax = max(0.0, buckets.carbon_credit_194) * SPECIAL_RATE_CARBON_CREDIT

    tax_before_rebate = sum([
        normal_tax,
        stcg_equity_tax,
        ltcg_equity_tax,
        ltcg_general_tax,
        vda_tax,
        winnings_tax,
        patent_tax,
        carbon_tax,
    ])

    # Rebate under section 156 for resident individual under new regime.
    profile = payload.get("profile", {})
    is_resident_individual = profile.get("assessee_type", "individual") == "individual" and res_status.get("status") == "resident"

    # Rebate generally applies to tax on total income but special incomes may have restrictions.
    # Phase-1 conservative approach: apply rebate only to normal slab tax.
    total_income_for_rebate = (
        buckets.normal_slab_income
        + max(0.0, buckets.stcg_equity_196)
        + max(0.0, buckets.ltcg_general_197)
        + max(0.0, buckets.ltcg_equity_198)
        + max(0.0, buckets.vda_194)
        + max(0.0, buckets.winnings_194)
        + max(0.0, buckets.patent_royalty_194)
        + max(0.0, buckets.carbon_credit_194)
    )

    rebate = 0.0
    rebate_note = None
    if is_resident_individual:
        if total_income_for_rebate <= NEW_REGIME_REBATE_INCOME_LIMIT:
            rebate = min(normal_tax, NEW_REGIME_REBATE_MAX)
            rebate_note = "New regime resident individual rebate applied only against normal slab tax in Phase-1."
        elif normal_tax > (total_income_for_rebate - NEW_REGIME_REBATE_INCOME_LIMIT):
            # Marginal relief style rule under section 156(2)(b), conservatively against normal tax.
            excess = total_income_for_rebate - NEW_REGIME_REBATE_INCOME_LIMIT
            potential_relief = max(0.0, normal_tax - excess)
            rebate = potential_relief
            rebate_note = "New regime marginal relief style rebate applied conservatively against normal slab tax."
            add_msg(messages, "MARGINAL_RELIEF_PHASE1", "warning", "Marginal relief/rebate computation is Phase-1 simplified. Validate with CA.", SOURCE_REFERENCES["act_section_156_rebate"])

    tax_after_rebate = max(0.0, tax_before_rebate - rebate)

    surcharge = 0.0
    cess = 0.0

    if APPLY_SURCHARGE:
        add_msg(messages, "SURCHARGE_NOT_IMPLEMENTED", "warning", "Surcharge config exists but is not implemented in Phase-1.", None)
    else:
        add_msg(messages, "SURCHARGE_PARKED", "info", "Surcharge is parked for later configuration.", None)

    if APPLY_HEALTH_EDUCATION_CESS:
        cess = tax_after_rebate * HEALTH_EDUCATION_CESS_RATE
    else:
        add_msg(messages, "CESS_PARKED", "info", "Health and education cess is parked for later configuration.", None)

    final_tax_before_credits = tax_after_rebate + surcharge + cess

    return {
        "selected_regime": "new_regime_phase1",
        "old_regime_status": "parked_for_later_config",
        "taxable_buckets_after_new_regime_deductions": asdict(buckets),
        "salary_standard_deduction_applied": round(salary_std, 2),
        "chapter_deductions_applied_new_regime": round(new_deductions, 2),
        "normal_slab_tax": round(normal_tax, 2),
        "special_rate_tax": {
            "stcg_equity_196_20_percent": round(stcg_equity_tax, 2),
            "ltcg_equity_198_12_5_percent_above_125000": round(ltcg_equity_tax, 2),
            "ltcg_general_197_12_5_percent": round(ltcg_general_tax, 2),
            "vda_30_percent": round(vda_tax, 2),
            "winnings_30_percent": round(winnings_tax, 2),
            "patent_royalty_10_percent": round(patent_tax, 2),
            "carbon_credit_10_percent": round(carbon_tax, 2),
        },
        "tax_before_rebate": round(tax_before_rebate, 2),
        "rebate": round(rebate, 2),
        "rebate_note": rebate_note,
        "surcharge": round(surcharge, 2),
        "cess": round(cess, 2),
        "final_tax_before_credits": round(final_tax_before_credits, 2),
        "notes": [
            "Old regime exact comparison is parked.",
            "Surcharge, cess, and marginal relief require final configuration before public launch.",
            "Special-rate income classification must be CA validated.",
        ],
        "source": SOURCE_REFERENCES["act_section_202_new_regime"],
    }


def compute_tax_paid_and_refund(payload: Dict[str, Any], tax_estimate: Dict[str, Any]) -> Dict[str, Any]:
    t = payload.get("tax_paid", {}) or {}
    tax_paid = (
        money(t.get("tds_salary"))
        + money(t.get("tds_interest"))
        + money(t.get("tds_rent"))
        + money(t.get("tds_capital_gains"))
        + money(t.get("tds_crypto"))
        + money(t.get("tds_other"))
        + money(t.get("tcs"))
        + money(t.get("advance_tax"))
        + money(t.get("self_assessment_tax"))
    )

    final_tax = money(tax_estimate.get("final_tax_before_credits"))
    net = final_tax - tax_paid
    return {
        "tax_paid_breakup": {
            "tds_salary": money(t.get("tds_salary")),
            "tds_interest": money(t.get("tds_interest")),
            "tds_rent": money(t.get("tds_rent")),
            "tds_capital_gains": money(t.get("tds_capital_gains")),
            "tds_crypto": money(t.get("tds_crypto")),
            "tds_other": money(t.get("tds_other")),
            "tcs": money(t.get("tcs")),
            "advance_tax": money(t.get("advance_tax")),
            "self_assessment_tax": money(t.get("self_assessment_tax")),
        },
        "total_tax_credits": round(tax_paid, 2),
        "estimated_tax_payable": round(max(0.0, net), 2),
        "estimated_refund": round(max(0.0, -net), 2),
        "credit_matching_warning": "Final credit depends on AIS/Form 26AS/portal matching.",
    }


# ============================================================
# 9. FILING REQUIREMENT ENGINE
# ============================================================

def determine_filing_requirement(
    payload: Dict[str, Any],
    res_status: Dict[str, Any],
    five_heads: Dict[str, Any],
    tax_estimate: Dict[str, Any],
    messages: List[EngineMessage],
) -> Dict[str, Any]:
    profile = payload.get("profile", {})
    triggers = payload.get("filing_triggers", {}) or {}

    assessee_type = profile.get("assessee_type", "individual")
    total_income = money(tax_estimate.get("taxable_buckets_after_new_regime_deductions", {}).get("normal_slab_income"))
    # Include special bucket incomes for threshold-style view
    for v in tax_estimate.get("taxable_buckets_after_new_regime_deductions", {}).values():
        if isinstance(v, (int, float)):
            pass
    gross_total = money(get_nested(five_heads, "summary.gross_total_income_before_chapter_deductions"))

    tds_tcs_total = (
        money(get_nested(payload, "tax_paid.tds_salary"))
        + money(get_nested(payload, "tax_paid.tds_interest"))
        + money(get_nested(payload, "tax_paid.tds_rent"))
        + money(get_nested(payload, "tax_paid.tds_capital_gains"))
        + money(get_nested(payload, "tax_paid.tds_crypto"))
        + money(get_nested(payload, "tax_paid.tds_other"))
        + money(get_nested(payload, "tax_paid.tcs"))
    )

    reasons = []
    status = "filing_recommended"

    if assessee_type in {"company", "firm", "llp"}:
        status = "filing_required"
        reasons.append("Entity type generally requires return filing.")
    elif gross_total > BASIC_EXEMPTION_DEFAULT:
        status = "filing_required"
        reasons.append("Income exceeds Phase-1 basic exemption threshold.")
    elif money(get_nested(tax_estimate, "tax_paid_result.estimated_refund")) > 0:
        status = "filing_recommended"
        reasons.append("Refund appears possible.")
    else:
        status = "filing_may_not_be_required"
        reasons.append("Income appears below threshold and no major trigger found.")

    # Trigger checks
    if money(triggers.get("savings_bank_deposits")) >= HIGH_VALUE_SAVINGS_DEPOSIT_TRIGGER:
        status = "filing_required"
        reasons.append("Savings bank deposits trigger detected.")
    if tds_tcs_total >= TDS_TCS_TRIGGER_NON_SENIOR:
        # Use non-senior threshold in Phase-1, senior handling can be refined.
        status = "filing_required"
        reasons.append("TDS/TCS trigger detected.")
    if as_bool(triggers.get("foreign_travel_high_spend")):
        status = "filing_required"
        reasons.append("Foreign travel high-spend trigger reported.")
    if as_bool(triggers.get("electricity_high_spend")):
        status = "filing_required"
        reasons.append("High electricity spend trigger reported.")
    if as_bool(triggers.get("business_turnover_trigger")):
        status = "filing_required"
        reasons.append("Business turnover filing trigger reported.")
    if as_bool(triggers.get("professional_receipts_trigger")):
        status = "filing_required"
        reasons.append("Professional receipts filing trigger reported.")

    # NRI special-income-only possible exemption
    nri_special_possible = False
    if res_status.get("status") == "non_resident":
        only_special_nri_income = as_bool(triggers.get("nri_only_special_income_with_full_tds"))
        if only_special_nri_income:
            nri_special_possible = True
            status = "filing_may_not_be_required_but_review"
            reasons.append("NRI special-income-only with full TDS reported. Filing exemption may apply, but refund/eligibility should be reviewed.")

    return {
        "status": status,
        "reasons": reasons,
        "nri_special_income_exemption_possible": nri_special_possible,
        "phase1_threshold_used": BASIC_EXEMPTION_DEFAULT,
        "warnings": ["Filing requirement should be validated with final threshold/triggers and CA review."],
    }


# ============================================================
# 10. ITR FORM SELECTION ENGINE
# ============================================================

def select_itr_form(payload: Dict[str, Any], res_status: Dict[str, Any], five_heads: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    profile = payload.get("profile", {})
    assessee_type = profile.get("assessee_type", "individual")
    income = payload.get("income", {})
    flags = payload.get("flags", {}) or {}

    total_income = money(get_nested(five_heads, "summary.gross_total_income_before_chapter_deductions"))
    has_salary = money(get_nested(five_heads, "summary.salary")) > 0
    has_house = bool(get_nested(income, "house_property.properties", []))
    house_count = len(as_list(get_nested(income, "house_property.properties", [])))
    has_pgbp = as_bool(get_nested(five_heads, "pgbp.has_pgbp"))
    has_capital_gains = bool(get_nested(income, "capital_gains.transactions", []))
    has_other = money(get_nested(five_heads, "summary.other_sources_normal")) > 0 or money(get_nested(five_heads, "summary.other_sources_special")) > 0

    has_foreign_assets = as_bool(get_nested(income, "foreign_income.has_foreign_assets"))
    has_foreign_income = as_bool(get_nested(income, "foreign_income.has_foreign_income")) or money(get_nested(income, "other_sources.dividend_foreign")) > 0
    is_director = as_bool(profile.get("is_director_in_company"))
    has_unlisted_equity = as_bool(profile.get("held_unlisted_equity"))
    agricultural_income = money(get_nested(payload, "exemptions.agricultural_income"))
    has_loss_carry_forward = as_bool(flags.get("has_brought_forward_or_carry_forward_loss"))
    claimed_dtaa_ftc = as_bool(flags.get("claimed_dtaa_or_foreign_tax_credit"))
    has_deferred_esop_tax = as_bool(flags.get("has_deferred_esop_tax"))
    special_rate_income = any([
        money(get_nested(five_heads, "tax_buckets_before_deductions.vda_194")) > 0,
        money(get_nested(five_heads, "tax_buckets_before_deductions.winnings_194")) > 0,
        money(get_nested(five_heads, "tax_buckets_before_deductions.stcg_equity_196")) > 0,
        money(get_nested(five_heads, "tax_buckets_before_deductions.ltcg_general_197")) > 0,
    ])

    reasons = []
    exclusions = []

    if assessee_type == "company":
        return {"likely_form": "ITR-6_or_ITR-7", "confidence": "Medium", "reasons": ["Company selected."], "exclusions": ["Company/trust routing needs entity review."]}
    if assessee_type in {"firm", "llp", "aop", "boi"}:
        return {"likely_form": "ITR-5", "confidence": "Medium", "reasons": ["Firm/LLP/AOP/BOI selected."], "exclusions": []}
    if assessee_type not in {"individual", "huf"}:
        return {"likely_form": "needs_review", "confidence": "Needs review", "reasons": ["Unsupported assessee type."], "exclusions": []}

    # ITR-3 if business/profession
    if has_pgbp:
        if (
            as_bool(get_nested(income, "pgbp.wants_presumptive_or_special_computation"))
            and res_status.get("status") == "resident"
            and res_status.get("ordinary_status") != "RNOR"
            and assessee_type in {"individual", "huf", "firm"}
            and not any([has_foreign_assets, has_foreign_income, is_director, has_unlisted_equity, total_income > ITR_1_4_TOTAL_INCOME_LIMIT, house_count > 2, has_loss_carry_forward, claimed_dtaa_ftc, has_deferred_esop_tax])
        ):
            reasons.append("Presumptive PGBP route and no major ITR-4 exclusion detected.")
            return {"likely_form": "ITR-4", "confidence": "Medium", "reasons": reasons, "exclusions": [], "source": SOURCE_REFERENCES["rules_rule_164_itr_forms"]}
        reasons.append("Business/profession income detected.")
        return {"likely_form": "ITR-3", "confidence": "High", "reasons": reasons, "exclusions": [], "source": SOURCE_REFERENCES["rules_rule_164_itr_forms"]}

    # ITR-1 possible only for resident other than RNOR and limited income sources
    itr1_blockers = []
    if res_status.get("status") != "resident" or res_status.get("ordinary_status") == "RNOR":
        itr1_blockers.append("Not resident and ordinarily resident.")
    if has_foreign_assets:
        itr1_blockers.append("Foreign assets.")
    if has_foreign_income:
        itr1_blockers.append("Foreign income.")
    if is_director:
        itr1_blockers.append("Director in company.")
    if has_unlisted_equity:
        itr1_blockers.append("Held unlisted equity shares.")
    if total_income > ITR_1_4_TOTAL_INCOME_LIMIT:
        itr1_blockers.append("Total income exceeds ₹50 lakh.")
    if agricultural_income > 5000:
        itr1_blockers.append("Agricultural income exceeds ₹5,000.")
    if has_loss_carry_forward:
        itr1_blockers.append("Brought forward/carry-forward loss.")
    if claimed_dtaa_ftc:
        itr1_blockers.append("DTAA / foreign tax credit claim.")
    if special_rate_income:
        # ITR-1 allows only specific LTCG 198 not exceeding 125k in Rules. Keep conservative.
        ltcg_198 = money(get_nested(five_heads, "tax_buckets_before_deductions.ltcg_equity_198"))
        if not (has_capital_gains and ltcg_198 > 0 and ltcg_198 <= 125000):
            itr1_blockers.append("Special-rate/complex income.")
    if house_count > 2:
        itr1_blockers.append("More than two house properties.")

    if not itr1_blockers and not has_pgbp:
        reasons.append("Resident individual with salary/house property/other sources/simple capital gains pattern.")
        return {"likely_form": "ITR-1", "confidence": "Medium", "reasons": reasons, "exclusions": [], "source": SOURCE_REFERENCES["rules_rule_164_itr_forms"]}

    # ITR-2 for individual/HUF without business/profession
    reasons.append("Individual/HUF without business/profession but not eligible for ITR-1.")
    exclusions.extend(itr1_blockers)
    return {"likely_form": "ITR-2", "confidence": "High", "reasons": reasons, "exclusions": exclusions, "source": SOURCE_REFERENCES["rules_rule_164_itr_forms"]}


# ============================================================
# 11. DOCUMENT CHECKLIST ENGINE
# ============================================================

def build_document_checklist(
    payload: Dict[str, Any],
    res_status: Dict[str, Any],
    taxable_scope: Dict[str, Any],
    five_heads: Dict[str, Any],
    exemptions: Dict[str, Any],
    deductions: Dict[str, Any],
    itr_form: Dict[str, Any],
) -> Dict[str, Any]:
    required = ["PAN", "Aadhaar if applicable", "Bank account details", "AIS/TIS", "Form 26AS"]
    optional = []
    missing_or_review = []

    required.extend(five_heads.get("documents", []))
    required.extend(exemptions.get("documents", []))
    required.extend(deductions.get("documents", []))

    if res_status.get("status") == "non_resident":
        required.extend(["Passport and visa details", "India stay day-count working", "NRO/NRE bank statements if applicable"])
    if res_status.get("ordinary_status") == "RNOR":
        required.extend(["Previous 10-year residential history", "Previous 7-year India stay working"])
    if taxable_scope.get("has_foreign_income"):
        required.extend(["Foreign income statement", "Foreign tax paid proof if claiming FTC", "DTAA/TRC documents if applicable"])
    if taxable_scope.get("has_foreign_assets"):
        required.extend(["Foreign asset schedule details", "Foreign bank/broker statements"])
    if itr_form.get("likely_form") in {"ITR-3", "ITR-4"}:
        required.extend(["Business/professional receipts summary", "Expense summary", "Books/audit documents if applicable"])

    for w in five_heads.get("warnings", []) + exemptions.get("warnings", []) + deductions.get("warnings", []):
        if "missing" in w.lower() or "review" in w.lower() or "validate" in w.lower():
            missing_or_review.append(w)

    return {
        "required": unique(required),
        "optional": unique(optional),
        "missing_or_review": unique(missing_or_review),
    }


# ============================================================
# 12. COMPLEXITY + RECOMMENDATION ENGINE
# ============================================================

def compute_complexity(
    payload: Dict[str, Any],
    res_status: Dict[str, Any],
    taxable_scope: Dict[str, Any],
    five_heads: Dict[str, Any],
    itr_form: Dict[str, Any],
    messages: List[EngineMessage],
) -> Dict[str, Any]:
    score = 0
    reasons = []

    def add(points, reason):
        nonlocal score
        score += points
        reasons.append({"points": points, "reason": reason})

    # Base income type scoring
    if money(get_nested(five_heads, "summary.salary")) > 0:
        add(5, "Salary income.")
    if bool(get_nested(payload, "income.house_property.properties", [])):
        add(10, "House property income.")
    if bool(get_nested(payload, "income.capital_gains.transactions", [])):
        add(20, "Capital gains.")
    if money(get_nested(five_heads, "summary.pgbp")) != 0 or as_bool(get_nested(five_heads, "pgbp.has_pgbp")):
        add(30, "Business/profession income.")
    if money(get_nested(five_heads, "summary.other_sources_normal")) > 0:
        add(5, "Other sources income.")

    # Specific risk triggers
    if res_status.get("status") == "non_resident":
        add(20, "NRI/non-resident.")
    if res_status.get("ordinary_status") == "RNOR":
        add(30, "RNOR/deemed resident complexity.")
    if taxable_scope.get("has_foreign_income"):
        add(35, "Foreign income.")
    if taxable_scope.get("has_foreign_assets"):
        add(35, "Foreign assets.")
    if as_bool(get_nested(payload, "income.pgbp.has_fno_or_intraday")):
        add(35, "F&O/intraday.")
    if money(get_nested(five_heads, "tax_buckets_before_deductions.vda_194")) > 0:
        add(25, "Crypto/VDA.")
    if any((tx.get("asset_type") in {"immovable_property", "land", "building", "land_building", "house_property_sale"}) for tx in as_list(get_nested(payload, "income.capital_gains.transactions", [])) if isinstance(tx, dict)):
        add(30, "Property sale.")
    if as_bool(get_nested(payload, "flags.has_brought_forward_or_carry_forward_loss")):
        add(20, "Brought-forward/carry-forward loss.")
    if as_bool(get_nested(payload, "flags.many_not_sure_answers")):
        add(20, "Many uncertain answers.")
    if any(m.severity == "critical" for m in messages):
        add(25, "Critical review flag present.")

    if score <= 25:
        label = "Low"
    elif score <= 55:
        label = "Medium"
    else:
        label = "High"

    return {
        "score": score,
        "label": label,
        "reasons": reasons,
    }


def build_recommendation(complexity: Dict[str, Any], messages: List[EngineMessage]) -> Dict[str, Any]:
    label = complexity.get("label")
    critical = [m for m in messages if m.severity == "critical"]

    if critical:
        action = "Expert review strongly recommended"
        cta = "CA-assisted filing"
    elif label == "Low":
        action = "DIY guide suitable"
        cta = "Free DIY guide"
    elif label == "Medium":
        action = "DIY possible, expert review recommended"
        cta = "DIY with CA review option"
    else:
        action = "CA-assisted filing recommended"
        cta = "CA-assisted filing"

    return {
        "action": action,
        "cta": cta,
        "disclaimer": "This is an internal Phase-1 estimate based on user inputs. Final result depends on AIS, Form 26AS, Form 16, capital gains statements, TDS certificates, applicable documents, and CA validation.",
    }


# ============================================================
# 13. MAIN ENGINE
# ============================================================

def run_itr_engine(user_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for website/backend integration.

    Input:
        user_input: dict

    Output:
        JSON-serializable dict
    """
    messages: List[EngineMessage] = []

    add_msg(messages, "PHASE1_SCOPE", "info", "Engine is Phase-1 internal CA testing version, not final public filing engine.", None)

    res_status = determine_residential_status(user_input, messages)
    taxable_scope = determine_taxable_scope(res_status, user_input, messages)
    five_heads = compute_five_heads(user_input, messages)
    exemptions = compute_exemptions(user_input, five_heads, messages)
    deductions = compute_chapter_deductions(user_input, res_status, messages)

    tax_estimate = compute_tax_buckets_after_regime(user_input, res_status, five_heads, deductions, messages)
    tax_paid_result = compute_tax_paid_and_refund(user_input, tax_estimate)
    tax_estimate["tax_paid_result"] = tax_paid_result

    filing_requirement = determine_filing_requirement(user_input, res_status, five_heads, tax_estimate, messages)
    itr_form = select_itr_form(user_input, res_status, five_heads, messages)
    documents = build_document_checklist(user_input, res_status, taxable_scope, five_heads, exemptions, deductions, itr_form)
    complexity = compute_complexity(user_input, res_status, taxable_scope, five_heads, itr_form, messages)
    recommendation = build_recommendation(complexity, messages)

    result = EngineResult(
        engine_version=ENGINE_VERSION,
        phase=PHASE,
        residential_status=res_status,
        taxable_scope=taxable_scope,
        five_heads_summary=five_heads,
        exemptions=exemptions,
        deductions=deductions,
        tax_buckets=tax_estimate["taxable_buckets_after_new_regime_deductions"],
        tax_estimate=tax_estimate,
        filing_requirement=filing_requirement,
        likely_itr_form=itr_form,
        documents=documents,
        complexity=complexity,
        recommendation=recommendation,
        messages=[asdict(m) for m in messages],
        source_map=SOURCE_REFERENCES,
        raw_debug={
            "currency": CURRENCY,
            "config": {
                "new_regime_slabs": NEW_REGIME_SLABS,
                "standard_deduction_new": STANDARD_DEDUCTION_NEW_REGIME,
                "section_123_limit": SECTION_123_LIMIT,
                "old_regime": "parked",
                "surcharge": "parked",
                "cess": "parked unless APPLY_HEALTH_EDUCATION_CESS=True",
            },
        },
    )

    return asdict(result)


# ============================================================
# 14. SAMPLE CLI RUNNER
# ============================================================

if __name__ == "__main__":
    sample = {
        "profile": {
            "assessee_type": "individual",
            "age": 35,
            "is_indian_citizen": True,
            "is_person_of_indian_origin": False,
            "is_director_in_company": False,
            "held_unlisted_equity": False
        },
        "residency": {
            "days_in_india_current_tax_year": 35,
            "days_in_india_prev_4_years": 250,
            "days_in_india_prev_7_years": 500,
            "non_resident_9_of_prev_10_years": True,
            "left_india_for_employment_outside_india": False,
            "came_to_india_for_visit": True,
            "indian_income_excluding_foreign_sources": 900000,
            "liable_to_tax_in_another_country": True
        },
        "income": {
            "salary": {},
            "house_property": {
                "properties": [
                    {
                        "usage": "let_out",
                        "actual_rent_received_or_receivable": 360000,
                        "expected_annual_rent": 330000,
                        "municipal_taxes_paid": 10000,
                        "home_loan_interest": 120000
                    }
                ]
            },
            "pgbp": {},
            "capital_gains": {
                "transactions": [
                    {
                        "asset_type": "listed_equity",
                        "sale_value": 500000,
                        "cost_of_acquisition": 350000,
                        "transfer_expenses": 1000,
                        "holding_months": 14,
                        "stt_paid": True
                    }
                ]
            },
            "other_sources": {
                "nro_interest": 80000,
                "nre_interest": 50000,
                "nre_interest_eligible_exempt": True
            },
            "foreign_income": {
                "has_foreign_income": False,
                "has_foreign_assets": False
            }
        },
        "exemptions": {},
        "deductions": {
            "ppf": 50000,
            "health_insurance_self_family": 20000
        },
        "tax_paid": {
            "tds_interest": 25000,
            "tds_rent": 36000
        },
        "filing_triggers": {},
        "flags": {}
    }

    import json
    print(json.dumps(run_itr_engine(sample), indent=2, ensure_ascii=False))
