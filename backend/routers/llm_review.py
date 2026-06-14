"""
LLM-powered compliance review for screening events.
Uses Groq (free tier, llama-3.3-70b-versatile) when GROQ_API_KEY is set.
Falls back to a structured template response otherwise.
"""

import os
import json
from fastapi import APIRouter, HTTPException
from data.loader import clean

router = APIRouter()


def _build_prompt(data: dict) -> str:
    s = data["screening"]
    a = data["account"]
    r = data["risk"]
    rc = data.get("risk_components", {})
    factors = "\n".join(f"  - {f}" for f in s.get("audit_factors", []))
    contribs = data.get("feature_contributions", [])[:6]
    top_features = "\n".join(
        f"  - {c['feature']}: importance {c['importance']:.3f}, contribution {c['contribution_pct']:.1f}%"
        for c in contribs
    )
    return f"""You are a senior AML/CFT compliance analyst. Review the following sanctions screening event and produce a concise, structured compliance assessment.

=== SCREENING EVENT ===
Screening ID: {s.get('screening_id')}
Account ID:   {s.get('account_id')}
Verdict:      {s.get('verdict')}  (AI model output)
Match Score:  {s.get('match_score', 0):.4f}
Block Prob:   {s.get('block_probability', 0)*100:.1f}%
Context:      {s.get('context')}
Screened At:  {s.get('screened_at')}

=== ACCOUNT PROFILE ===
Type:           {a.get('account_type')}
KYC Status:     {a.get('kyc_status')} (completeness {a.get('kyc_completeness', 0)*100:.0f}%)
PEP Flag:       {'YES' if a.get('is_pep') else 'No'}
Shell Co Flag:  {'YES' if a.get('shell_company_flag') else 'No'}
Complex Ownerp: {'YES' if a.get('has_complex_ownership') else 'No'}
Activity Tier:  {a.get('activity_tier')}
Account Status: {a.get('account_status')}
Country:        {a.get('country_residence')}
Override Applied: {'YES' if a.get('override_applied') else 'No'}

=== RISK SCORES ===
Overall Risk Score: {r.get('overall_risk_score', 0)*100:.1f} / 100
Risk Band: {r.get('risk_band')}
  Geographic Risk:         {rc.get('geographic_risk', 0):.3f}
  Identity/KYC Risk:       {rc.get('identity_kyc_risk', 0):.3f}
  PEP/Sanctions Risk:      {rc.get('pep_sanctions_risk', 0):.3f}
  Behavioural Risk:        {rc.get('behavioural_risk', 0):.3f}
  Relationship Network Risk: {rc.get('relationship_network_risk', 0):.3f}

=== AI MODEL NARRATIVE ===
{s.get('audit_narrative', 'N/A')}

=== AI AUDIT FACTORS ===
{factors if factors else '  (none)'}

=== TOP FEATURE CONTRIBUTIONS ===
{top_features if top_features else '  (none)'}

---

Produce your response as valid JSON with this exact structure:
{{
  "recommendation": "APPROVE" | "ESCALATE" | "BLOCK",
  "confidence": "LOW" | "MEDIUM" | "HIGH",
  "summary": "2-3 sentence executive summary of your findings",
  "key_concerns": ["concern 1", "concern 2", ...],
  "mitigating_factors": ["factor 1", ...],
  "required_actions": ["action 1", ...],
  "compliance_notes": "Any additional regulatory or procedural notes"
}}

Respond ONLY with the JSON object. No markdown, no explanation outside the JSON.
"""


def _template_response(data: dict) -> dict:
    """Rule-based fallback when no LLM is available."""
    s = data["screening"]
    verdict = s.get("verdict", "CLEAR")
    bp = s.get("block_probability", 0)
    factors = s.get("audit_factors", [])
    a = data["account"]

    if verdict == "BLOCK" or bp > 0.70:
        rec = "BLOCK"
        confidence = "HIGH"
        summary = (
            f"Account {s.get('account_id')} has been flagged for blocking with a match score of "
            f"{s.get('match_score', 0):.3f} and a {bp*100:.0f}% block probability. "
            "Multiple risk signals indicate this screening event warrants immediate action."
        )
    elif verdict == "REVIEW" or bp > 0.35:
        rec = "ESCALATE"
        confidence = "MEDIUM"
        summary = (
            f"Account {s.get('account_id')} falls in the REVIEW zone with a match score of "
            f"{s.get('match_score', 0):.3f}. "
            "Manual escalation to a Level-2 analyst is recommended before a final decision."
        )
    else:
        rec = "APPROVE"
        confidence = "HIGH"
        summary = (
            f"Account {s.get('account_id')} passes automated screening with a match score of "
            f"{s.get('match_score', 0):.3f} and a low block probability of {bp*100:.0f}%. "
            "No significant risk signals were detected."
        )

    concerns = factors[:4] if factors else ["No specific concerns identified by AI model"]
    mitigating = []
    if a.get("kyc_status") == "complete":
        mitigating.append("KYC documentation is complete")
    if not a.get("is_pep"):
        mitigating.append("No PEP designation")
    if not a.get("shell_company_flag"):
        mitigating.append("No shell company indicators")
    if not mitigating:
        mitigating = ["No significant mitigating factors"]

    actions = []
    if rec == "BLOCK":
        actions = ["Freeze account pending investigation", "File SAR/STR as required", "Notify compliance officer"]
    elif rec == "ESCALATE":
        actions = ["Escalate to Level-2 review", "Request source-of-funds documentation", "Review transaction history"]
    else:
        actions = ["Continue standard monitoring", "No immediate action required"]

    return {
        "recommendation": rec,
        "confidence": confidence,
        "summary": summary,
        "key_concerns": concerns,
        "mitigating_factors": mitigating,
        "required_actions": actions,
        "compliance_notes": "Generated by rule-based fallback (GROQ_API_KEY not configured). Set GROQ_API_KEY for LLM-powered analysis.",
        "llm_powered": False,
    }


@router.post("/screening/{screening_id}/llm-review")
def llm_review(screening_id: str):
    import data.loader as dl

    if dl.screening_merged is None or dl.accounts_enriched is None:
        raise HTTPException(503, "Data not loaded")

    rows = dl.screening_merged[dl.screening_merged["screening_id"] == screening_id]
    if rows.empty:
        raise HTTPException(404, f"Screening {screening_id} not found")

    scr = rows.iloc[0]
    account_id = scr["account_id"]

    acct_rows = dl.accounts_enriched[dl.accounts_enriched["account_id"] == account_id]
    if acct_rows.empty:
        raise HTTPException(404, f"Account {account_id} not found")
    acct = acct_rows.iloc[0]

    # Run the model to get full audit data
    from ai.model.predict import screen as run_screen

    features = {
        "account_type":               acct.get("account_type", "individual"),
        "kyc_completeness":           float(acct.get("kyc_completeness") or 0.5),
        "kyc_status":                 acct.get("kyc_status", "complete"),
        "is_pep":                     int(acct.get("is_pep") or 0),
        "has_complex_ownership":      int(acct.get("has_complex_ownership") or 0),
        "shell_company_flag":         int(acct.get("shell_company_flag") or 0),
        "activity_tier":              acct.get("activity_tier", "low"),
        "account_status":             acct.get("account_status", "active"),
        "match_score":                float(scr.get("match_score") or 0.0),
        "shares_address_with_sanctioned": int(scr.get("shares_address_with_sanctioned") or 0),
        "pep_exposure_score":         float(scr.get("pep_exposure_score") or 0.0),
        "country_risk_score":         float(scr.get("country_risk_score") or 0.0),
        "geographic_risk":            float(acct.get("geographic_risk") or 0.0),
        "identity_kyc_risk":          float(acct.get("identity_kyc_risk") or 0.0),
        "pep_sanctions_risk":         float(acct.get("pep_sanctions_risk") or 0.0),
        "behavioural_risk":           float(acct.get("behavioural_risk") or 0.0),
        "relationship_network_risk":  float(acct.get("relationship_network_risk") or 0.0),
        "overall_risk_score":         float(acct.get("overall_risk_score") or 0.0),
        "override_applied":           int(acct.get("override_applied") or 0),
    }
    model_result = run_screen(features)

    # Payload for LLM
    payload = {
        "screening": {
            "screening_id": screening_id,
            "account_id": account_id,
            "verdict": model_result["verdict"],
            "match_score": model_result["match_score"],
            "block_probability": model_result["block_probability"],
            "context": scr.get("screening_context"),
            "screened_at": str(scr.get("screening_date", "")),
            "audit_narrative": model_result["audit_narrative"],
            "audit_factors": model_result["audit_factors"],
        },
        "account": {
            "account_type": acct.get("account_type"),
            "kyc_status": acct.get("kyc_status"),
            "kyc_completeness": float(acct.get("kyc_completeness") or 0),
            "is_pep": int(acct.get("is_pep") or 0),
            "shell_company_flag": int(acct.get("shell_company_flag") or 0),
            "has_complex_ownership": int(acct.get("has_complex_ownership") or 0),
            "activity_tier": acct.get("activity_tier"),
            "account_status": acct.get("account_status"),
            "country_residence": acct.get("country_residence"),
            "override_applied": int(acct.get("override_applied") or 0),
        },
        "risk": {
            "overall_risk_score": float(acct.get("overall_risk_score") or 0),
            "risk_band": acct.get("risk_band"),
        },
        "risk_components": model_result.get("risk_components", {}),
        "feature_contributions": model_result.get("feature_contributions", []),
    }

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        result = _template_response(payload)
        return clean(result)

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        prompt = _build_prompt(payload)
        chat = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1024,
        )
        raw = chat.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        parsed["llm_powered"] = True
        parsed["model"] = "llama-3.3-70b-versatile"
        return clean(parsed)
    except json.JSONDecodeError:
        # Return raw text in summary if JSON parse fails
        result = _template_response(payload)
        result["compliance_notes"] = f"LLM returned non-JSON response. Fallback used. Raw: {raw[:300]}"
        return clean(result)
    except Exception as e:
        # Network or API error - fall back gracefully
        result = _template_response(payload)
        result["compliance_notes"] = f"LLM call failed ({type(e).__name__}: {str(e)[:200]}). Fallback used."
        return clean(result)
