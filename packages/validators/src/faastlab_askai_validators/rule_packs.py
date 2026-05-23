"""Hard-coded regulatory rule packs for the multi-regulator validator.

Each pack is a list of `RuleRequirement` items the validator scores the
target document against. We deliberately keep these packs compact —
~7-10 requirements per regulator — because:

1. The validator's value is "did this doc cover the things that matter",
   not exhaustive line-by-line conformance. Compliance teams use this as
   a triage tool, not a substitute for legal review.
2. LLM cost scales linearly with requirement count; 30 requirements per
   doc is ~£0.05 of gpt-4o-mini; 200 would be ~£0.40 and slower.
3. Packs are version-pinned (`pack.version`) so customers can pin to a
   known revision; we'll add `pack.published_at` once we have a CMS.

To add a pack: define a `RulePack` and append it to `_REGISTRY`. Each
requirement should be self-contained (no cross-references to other
requirements) so the LLM can score it in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class RuleRequirement:
    """One thing the document must address."""

    id: str          # short stable code, e.g. "CD-1"
    title: str       # one-line label shown in the UI
    description: str # 1-3 sentences explaining what compliance looks like
    citation: str    # canonical regulator reference (rule number, article)
    severity: str = "must"  # 'must' (red on fail) | 'should' (amber on fail)


@dataclass(slots=True, frozen=True)
class RulePack:
    """A coherent set of requirements for one regulator/regulation."""

    id: str           # e.g. "fca-consumer-duty"
    regulator: str    # 'fca' | 'hmrc' | 'ico' | ...
    name: str         # display name
    version: str
    summary: str      # one-paragraph overview shown in the picker
    requirements: tuple[RuleRequirement, ...]


# ---- FCA Consumer Duty (PRIN 2A) ------------------------------------------

_FCA_CONSUMER_DUTY = RulePack(
    id="fca-consumer-duty",
    regulator="fca",
    name="FCA Consumer Duty (PRIN 2A)",
    version="2026.01",
    summary=(
        "The FCA's overarching standard for retail conduct: three cross-cutting "
        "rules plus four consumer outcomes. Applies to all firms providing "
        "products or services to UK retail customers."
    ),
    requirements=(
        RuleRequirement(
            id="CD-1",
            title="Cross-cutting — Act in good faith",
            description=(
                "The document evidences a commitment to acting honestly, fairly, "
                "and openly with retail customers in all interactions, including "
                "where the firm's commercial interests might conflict."
            ),
            citation="FCA Handbook PRIN 2A.2.1R",
        ),
        RuleRequirement(
            id="CD-2",
            title="Cross-cutting — Avoid causing foreseeable harm",
            description=(
                "Identifies and mitigates reasonably foreseeable harm to retail "
                "customers (including financial loss, distress, and inconvenience) "
                "arising from the firm's products, services, or conduct."
            ),
            citation="FCA Handbook PRIN 2A.2.8R",
        ),
        RuleRequirement(
            id="CD-3",
            title="Cross-cutting — Enable customer objectives",
            description=(
                "Takes reasonable steps to support retail customers in pursuing "
                "their financial objectives, including by removing unreasonable "
                "barriers and providing access to information needed to make "
                "informed decisions."
            ),
            citation="FCA Handbook PRIN 2A.2.14R",
        ),
        RuleRequirement(
            id="CD-4",
            title="Products & services outcome",
            description=(
                "Products and services are designed to meet the needs, characteristics, "
                "and objectives of a target market of retail customers, and are "
                "distributed accordingly."
            ),
            citation="FCA Handbook PRIN 2A.3",
        ),
        RuleRequirement(
            id="CD-5",
            title="Price & value outcome",
            description=(
                "Customers receive fair value, with prices that are reasonable "
                "relative to the benefits provided. Includes regular fair-value "
                "assessments."
            ),
            citation="FCA Handbook PRIN 2A.4",
        ),
        RuleRequirement(
            id="CD-6",
            title="Consumer understanding outcome",
            description=(
                "Communications support customer understanding — equipping them "
                "to make effective, timely, and properly informed decisions about "
                "financial products and services."
            ),
            citation="FCA Handbook PRIN 2A.5",
        ),
        RuleRequirement(
            id="CD-7",
            title="Consumer support outcome",
            description=(
                "Acts to support retail customers, including throughout the "
                "product lifecycle. Customers can use products as expected "
                "(no sludge practices), and post-sale support is at least as "
                "responsive as the sales process."
            ),
            citation="FCA Handbook PRIN 2A.6",
        ),
    ),
)


# ---- HMRC AML (MLR 2017 + JMLSG core obligations) -------------------------

_HMRC_AML = RulePack(
    id="hmrc-aml",
    regulator="hmrc",
    name="HMRC AML (MLR 2017 + JMLSG)",
    version="2026.01",
    summary=(
        "Core anti-money-laundering obligations under the Money Laundering "
        "Regulations 2017 for firms supervised by HMRC (estate agents, "
        "high-value-goods dealers, accountancy, trust/company services). "
        "Also relevant for FCA-supervised firms covering the same ground."
    ),
    requirements=(
        RuleRequirement(
            id="AML-1",
            title="Written risk assessment",
            description=(
                "A documented, board-approved AML risk assessment covering "
                "customer, geographic, product/service, transaction, and "
                "delivery-channel risks. Reviewed at least annually."
            ),
            citation="MLR 2017 reg.18",
        ),
        RuleRequirement(
            id="AML-2",
            title="Customer Due Diligence (CDD)",
            description=(
                "Standard CDD procedures: identify the customer, verify identity "
                "from reliable independent sources, identify beneficial owners "
                "(≥25% ownership), and understand the nature/purpose of the "
                "business relationship."
            ),
            citation="MLR 2017 reg.28",
        ),
        RuleRequirement(
            id="AML-3",
            title="Enhanced Due Diligence (EDD)",
            description=(
                "EDD applied to high-risk relationships: high-risk third countries, "
                "PEPs, complex/unusual transactions with no economic purpose, and "
                "where the firm's risk assessment indicates elevated risk."
            ),
            citation="MLR 2017 reg.33",
        ),
        RuleRequirement(
            id="AML-4",
            title="PEP and sanctions screening",
            description=(
                "Customers, beneficial owners, and counterparties are screened "
                "against PEP lists and UK/UN/EU sanctions lists at onboarding "
                "and on an ongoing basis."
            ),
            citation="MLR 2017 reg.35; UK sanctions regime",
        ),
        RuleRequirement(
            id="AML-5",
            title="Ongoing monitoring",
            description=(
                "The firm monitors customer relationships and transactions on "
                "an ongoing basis, including reviewing the consistency of "
                "transactions with the firm's knowledge of the customer."
            ),
            citation="MLR 2017 reg.28(11)",
        ),
        RuleRequirement(
            id="AML-6",
            title="Record-keeping (5-year minimum)",
            description=(
                "CDD records, transaction records, and SAR-related documents "
                "retained for at least five years after the end of the "
                "business relationship or the date of the transaction."
            ),
            citation="MLR 2017 reg.40",
        ),
        RuleRequirement(
            id="AML-7",
            title="SAR reporting and tipping-off",
            description=(
                "Documented process for raising internal suspicious activity "
                "reports, escalating to the MLRO, and onward reporting to the "
                "NCA. Staff trained on the tipping-off offence."
            ),
            citation="POCA 2002 s.330-333; MLR 2017 reg.86",
        ),
        RuleRequirement(
            id="AML-8",
            title="MLRO appointed and trained",
            description=(
                "A named Money Laundering Reporting Officer appointed at "
                "board level (or equivalent) with sufficient seniority, "
                "independence, and resources. Staff receive periodic AML "
                "training appropriate to their role."
            ),
            citation="MLR 2017 reg.21",
        ),
    ),
)


# ---- UK GDPR (data protection essentials) ----------------------------------

_UK_GDPR = RulePack(
    id="uk-gdpr",
    regulator="ico",
    name="UK GDPR (data protection essentials)",
    version="2026.01",
    summary=(
        "The data-protection principles, lawful bases, transparency, data-subject "
        "rights, and breach obligations under the UK GDPR (as amended) and the "
        "Data Protection Act 2018. Enforced by the ICO."
    ),
    requirements=(
        RuleRequirement(
            id="GDPR-1",
            title="Lawful basis documented",
            description=(
                "Each processing activity has a clearly identified lawful basis "
                "(consent, contract, legal obligation, vital interests, public "
                "task, or legitimate interests), documented in a record of "
                "processing activities (RoPA)."
            ),
            citation="UK GDPR Art.6; Art.30",
        ),
        RuleRequirement(
            id="GDPR-2",
            title="Purpose limitation & data minimisation",
            description=(
                "Personal data collected only for specified, explicit, and "
                "legitimate purposes; processing is adequate, relevant, and "
                "limited to what is necessary for those purposes."
            ),
            citation="UK GDPR Art.5(1)(b)-(c)",
        ),
        RuleRequirement(
            id="GDPR-3",
            title="Retention schedule",
            description=(
                "Documented retention schedule defines how long each category "
                "of personal data is kept and the criteria used to determine "
                "the period. Data deleted or anonymised at end of retention."
            ),
            citation="UK GDPR Art.5(1)(e)",
        ),
        RuleRequirement(
            id="GDPR-4",
            title="Security of processing",
            description=(
                "Appropriate technical and organisational measures protect "
                "personal data against accidental or unlawful destruction, "
                "loss, alteration, unauthorised disclosure, or access. Includes "
                "encryption, access control, and resilience measures."
            ),
            citation="UK GDPR Art.32",
        ),
        RuleRequirement(
            id="GDPR-5",
            title="Transparency / privacy notice",
            description=(
                "Data subjects receive clear, plain-language information about "
                "the controller, purposes, lawful basis, recipients, retention "
                "periods, their rights, and international transfers (Art.13/14)."
            ),
            citation="UK GDPR Art.13-14",
        ),
        RuleRequirement(
            id="GDPR-6",
            title="Data-subject rights process",
            description=(
                "Documented procedures handle SARs, rectification, erasure, "
                "restriction, portability, and objection requests within one "
                "calendar month (extendable by two months for complex requests)."
            ),
            citation="UK GDPR Art.15-22",
        ),
        RuleRequirement(
            id="GDPR-7",
            title="International transfer safeguards",
            description=(
                "Transfers outside the UK rely on an adequacy decision, "
                "International Data Transfer Agreement (IDTA), UK Addendum to "
                "the EU SCCs, or another Art.46 safeguard, with a transfer "
                "risk assessment where required."
            ),
            citation="UK GDPR Chapter V",
        ),
        RuleRequirement(
            id="GDPR-8",
            title="Breach notification (72-hour rule)",
            description=(
                "Personal-data breaches likely to result in a risk to "
                "individuals are reported to the ICO within 72 hours of the "
                "controller becoming aware; high-risk breaches also notified "
                "to affected individuals without undue delay."
            ),
            citation="UK GDPR Art.33-34",
        ),
    ),
)


# ---- UK debt collections letter (CONC + Consumer Duty + DISP) --------------

_UK_DEBT_COLLECTIONS_LETTER = RulePack(
    id="uk-debt-collections-letter",
    regulator="fca",
    name="UK Collections Letter Compliance (CONC + Consumer Duty)",
    version="2026.01",
    summary=(
        "Per-letter compliance check for FCA-authorised debt purchasers and "
        "collectors. Targets the CONC 7 consumer-credit collections rules, "
        "Consumer Duty cross-cutting obligations, and DISP complaint-handling "
        "signposts. Intended to triage outgoing letters before send and to "
        "evidence good-outcome decisions to the FCA."
    ),
    requirements=(
        RuleRequirement(
            id="CL-1",
            title="Firm identification and FCA reference",
            description=(
                "The letter clearly identifies the firm sending it (registered "
                "name) and provides the firm's FCA Firm Reference Number (FRN), "
                "so the recipient can verify the firm's authorisation."
            ),
            citation="FCA Handbook CONC 7.9.4R; GEN 4.3.1R",
        ),
        RuleRequirement(
            id="CL-2",
            title="Free debt advice signposting",
            description=(
                "The letter signposts the customer to free, impartial debt "
                "advice (e.g. MoneyHelper, StepChange, National Debtline, "
                "Citizens Advice) with sufficient information for the customer "
                "to access that advice."
            ),
            citation="FCA Handbook CONC 7.9.10R; CONC 7.17.4R",
        ),
        RuleRequirement(
            id="CL-3",
            title="No threatening or coercive language",
            description=(
                "The letter does not use language that is threatening, "
                "intimidating, oppressive, or designed to create unwarranted "
                "anxiety. Wording is firm but proportionate."
            ),
            citation="FCA Handbook CONC 7.9.5G; CONC 7.9.6G",
            severity="must",
        ),
        RuleRequirement(
            id="CL-4",
            title="Clear breakdown of debt",
            description=(
                "The letter sets out a clear breakdown of the amount owed: "
                "original principal, accrued interest, charges, and the "
                "current total balance. Where the debt has been assigned, the "
                "original creditor is identified."
            ),
            citation="FCA Handbook CONC 7.5.3R",
        ),
        RuleRequirement(
            id="CL-5",
            title="Complaints procedure and FOS referral",
            description=(
                "The letter explains how the customer can complain to the "
                "firm and references the customer's right to escalate to the "
                "Financial Ombudsman Service if dissatisfied with the response."
            ),
            citation="FCA Handbook DISP 1.2.1R; DISP 1.6.2R",
        ),
        RuleRequirement(
            id="CL-6",
            title="Accommodation of vulnerable customers",
            description=(
                "The letter acknowledges customers in vulnerable circumstances "
                "and offers a route for the customer to disclose vulnerability "
                "or request adjustments (e.g. alternative formats, additional "
                "time, third-party contact)."
            ),
            citation="FCA Handbook CONC 1.3.7R; FG21/1 (Vulnerable Customers)",
        ),
        RuleRequirement(
            id="CL-7",
            title="Forbearance and repayment options offered",
            description=(
                "The letter invites the customer to discuss repayment "
                "difficulties and indicates that the firm will consider "
                "appropriate forbearance options (affordable repayment plans, "
                "interest/charge freezes, temporary holds)."
            ),
            citation="FCA Handbook CONC 7.3.4R; CONC 7.3.5G; CONC 7.7.4R",
        ),
        RuleRequirement(
            id="CL-8",
            title="No undue time pressure",
            description=(
                "The letter does not impose arbitrarily short response "
                "deadlines or create undue urgency that could pressure the "
                "customer into a hasty decision."
            ),
            citation="FCA Handbook CONC 7.9.6G",
            severity="must",
        ),
        RuleRequirement(
            id="CL-9",
            title="Consumer Duty consumer-understanding outcome",
            description=(
                "The letter is written in clear, plain English appropriate to "
                "the target customer, avoids legal or industry jargon without "
                "explanation, and equips the customer to make an informed "
                "decision about how to respond."
            ),
            citation="FCA Handbook PRIN 2A.5 (Consumer understanding)",
        ),
        RuleRequirement(
            id="CL-10",
            title="Multiple accessible contact channels",
            description=(
                "The letter offers more than one way for the customer to make "
                "contact (e.g. phone, email, post, secure online portal) and "
                "states accessible hours, supporting customers who may not be "
                "able to use one channel."
            ),
            citation="FCA Handbook PRIN 2A.6 (Consumer support); CONC 7.9.4R",
            severity="should",
        ),
        RuleRequirement(
            id="CL-11",
            title="Statute-barred status warning (where applicable)",
            description=(
                "Where the debt is or may be statute-barred under the "
                "Limitation Act 1980, the letter makes the customer aware of "
                "this and does not mislead them into making an acknowledgment "
                "that would restart the limitation period."
            ),
            citation="FCA Handbook CONC 7.15.4R; CONC 7.15.8R",
        ),
        RuleRequirement(
            id="CL-12",
            title="Assignment notice for purchased debt",
            description=(
                "If the debt has been assigned to a third party (purchased), "
                "the letter contains a clear notice of assignment identifying "
                "the original creditor and the assignee, in line with Law of "
                "Property Act 1925 s.136 requirements."
            ),
            citation="FCA Handbook CONC 6.5.2R; Law of Property Act 1925 s.136",
            severity="should",
        ),
    ),
)


# ---- Registry --------------------------------------------------------------

_REGISTRY: tuple[RulePack, ...] = (
    _FCA_CONSUMER_DUTY,
    _HMRC_AML,
    _UK_GDPR,
    _UK_DEBT_COLLECTIONS_LETTER,
)


def list_packs() -> tuple[RulePack, ...]:
    """Return all bundled rule packs."""
    return _REGISTRY


def get_pack(pack_id: str) -> RulePack | None:
    """Look up a pack by id (case-insensitive)."""
    needle = pack_id.lower().strip()
    for p in _REGISTRY:
        if p.id == needle:
            return p
    return None
