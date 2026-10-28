"""Automated test runner and demonstration for Loan Pricing & Simulation scenarios.

Usage:
    python -m scripts.test_pricing_simulator
"""

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.services.pricing.models import (
    EarlyRepaymentRequest,
    ExistingLoan,
    LoanOfferRequest,
    RefinancingRequest,
)
from src.services.pricing.service import (
    calculate_loan_offer,
    compare_refinancing_options,
    simulate_early_repayment,
)


def run_pricing_tests() -> bool:
    print("=" * 80)
    print("TESTARE SIMULATOR DE PREȚ ȘI CREDITE (LOAN PRICING & SIMULATION ENGINE)")
    print("=" * 80)

    base_dir = Path("data/test_samples_pricing")
    all_passed = True

    # 1. Personal Loan Standard Offer
    print("\n--- [TEST 1] Credit de Nevoi Personale (Ofertă Standard & DAE) ---")
    p1 = base_dir / "01_personal_loan_standard_offer.json"
    data1 = json.loads(p1.read_text(encoding="utf-8"))
    req1 = LoanOfferRequest.model_validate(data1["request"])
    res1 = calculate_loan_offer(req1)

    exp1 = data1["expected_results"]
    t1_ok = (
        res1.status == "ok"
        and res1.first_monthly_payment == Decimal(exp1["first_monthly_payment"])
        and res1.dae == Decimal(exp1["dae"])
        and abs(res1.totals.total_payable - Decimal(exp1["total_payable"])) <= Decimal("0.05")
        and res1.affordability.within_limit == exp1["affordability_within_limit"]
    )
    if not t1_ok: all_passed = False
    print(f"[{'PASS' if t1_ok else 'FAIL'}] {data1['scenario_name']}")
    print(f"       Sumă: {req1.amount:,.2f} RON | Durată: {req1.term_months} luni")
    discounts_str = " - ".join(f"{d.code}: {d.percentage_points}%" for d in res1.rate.discounts)
    effective_rate = res1.rate.rate_periods[0].annual_rate
    print(f"       Dobândă anuală: {effective_rate}% (Bază {res1.rate.base_annual_rate}% | Reduceri: {discounts_str})")
    print(f"       Rată lunară: {res1.first_monthly_payment:,.2f} RON | DAE: {res1.dae}%")
    print(f"       Cost total credit: {res1.totals.total_cost_of_credit:,.2f} RON | Total de rambursat: {res1.totals.total_payable:,.2f} RON")
    print(f"       Grad de îndatorare: {res1.affordability.debt_service_ratio * 100:.2f}% (Limită BNR: {res1.affordability.limit * 100:.0f}%) -> Eligibil: {res1.affordability.within_limit}")

    # 2. Mortgage Casa Ta Simulation
    print("\n--- [TEST 2] Credit Imobiliar Casa Ta (Fix 3 Ani apoi IRCC) ---")
    p2 = base_dir / "02_mortgage_casa_ta_simulation.json"
    data2 = json.loads(p2.read_text(encoding="utf-8"))
    req2 = LoanOfferRequest.model_validate(data2["request"])
    res2 = calculate_loan_offer(req2)

    exp2 = data2["expected_results"]
    t2_ok = (
        res2.status == "ok"
        and res2.first_monthly_payment == Decimal(exp2["first_monthly_payment"])
        and res2.monthly_payment_after_fixed_period == Decimal(exp2["monthly_payment_after_fixed_period"])
        and res2.loan_to_value_percent == Decimal(exp2["loan_to_value_percent"])
        and res2.affordability.within_limit == exp2["affordability_within_limit"]
    )
    if not t2_ok: all_passed = False
    print(f"[{'PASS' if t2_ok else 'FAIL'}] {data2['scenario_name']}")
    print(f"       Sumă: {req2.amount:,.2f} RON | Durată: {req2.term_months} luni (25 ani)")
    print(f"       Perioadă fixă (3 ani): Dobândă {res2.rate.rate_periods[0].annual_rate}% -> Rată lunară: {res2.first_monthly_payment:,.2f} RON")
    print(f"       După 3 ani: IRCC {res2.rate.index_value}% + Marjă {res2.rate.margin}% = {res2.rate.index_value + res2.rate.margin}% -> Rată lunară: {res2.monthly_payment_after_fixed_period:,.2f} RON")
    print(f"       LTV: {res2.loan_to_value_percent}% (Valoare imobil: {req2.property_value:,.2f} RON)")
    print(f"       Grad de îndatorare: {res2.affordability.debt_service_ratio * 100:.2f}% (Limită prima casă: {res2.affordability.limit * 100:.0f}%) -> Eligibil: {res2.affordability.within_limit}")

    # 3. Early Repayment Prepayment (Reduce Term vs Reduce Installment)
    print("\n--- [TEST 3] Rambursare Anticipată Parțială (OUG 50/2010) ---")
    p3 = base_dir / "03_early_repayment_prepayment.json"
    data3 = json.loads(p3.read_text(encoding="utf-8"))
    loan_req = LoanOfferRequest.model_validate(data3["loan_request"])

    # Option A: reduce_term
    req3_term = EarlyRepaymentRequest(
        loan=loan_req,
        after_month=data3["simulation_parameters"]["after_month"],
        amount=Decimal(data3["simulation_parameters"]["repayment_amount"]),
        option="reduce_term",
    )
    res3_term = simulate_early_repayment(req3_term)
    exp3_t = data3["expected_results"]["reduce_term_option"]
    t3_term_ok = (
        res3_term.status == "ok"
        and res3_term.early_repayment_fee == Decimal(exp3_t["early_repayment_fee"])
        and res3_term.new_last_month == exp3_t["new_last_month"]
        and res3_term.interest_saved == Decimal(exp3_t["interest_saved"])
        and res3_term.net_saving == Decimal(exp3_t["net_saving"])
    )

    # Option B: reduce_instalment
    req3_inst = EarlyRepaymentRequest(
        loan=loan_req,
        after_month=data3["simulation_parameters"]["after_month"],
        amount=Decimal(data3["simulation_parameters"]["repayment_amount"]),
        option="reduce_instalment",
    )
    res3_inst = simulate_early_repayment(req3_inst)
    exp3_i = data3["expected_results"]["reduce_installment_option"]
    t3_inst_ok = (
        res3_inst.status == "ok"
        and res3_inst.early_repayment_fee == Decimal(exp3_i["early_repayment_fee"])
        and res3_inst.new_monthly_payment == Decimal(exp3_i["new_monthly_payment"])
        and res3_inst.net_saving == Decimal(exp3_i["net_saving"])
    )

    if not (t3_term_ok and t3_inst_ok): all_passed = False
    print(f"[{'PASS' if t3_term_ok and t3_inst_ok else 'FAIL'}] {data3['scenario_name']}")
    print(f"       Plată anticipată: {req3_term.amount:,.2f} RON în luna {req3_term.after_month} | Comision 1%: {res3_term.early_repayment_fee:,.2f} RON")
    print(f"       -> Opțiunea REDUCERE PERIOADĂ: Termenul scade de la 60 la {res3_term.new_last_month} luni (-{60 - res3_term.new_last_month} luni)")
    print(f"          Economie netă dobânzi: {res3_term.net_saving:,.2f} RON (Rata rămâne {res3_term.new_monthly_payment:,.2f} RON)")
    print(f"       -> Opțiunea REDUCERE RATĂ: Rata lunară scade de la {res3_inst.previous_monthly_payment:,.2f} la {res3_inst.new_monthly_payment:,.2f} RON (-{res3_inst.previous_monthly_payment - res3_inst.new_monthly_payment:,.2f} RON/lună)")
    print(f"          Economie netă dobânzi: {res3_inst.net_saving:,.2f} RON (Termenul rămâne 60 luni)")

    # 4. Refinancing Consolidation
    print("\n--- [TEST 4] Refinanțare & Consolidare Credite cu Extra Cash ---")
    p4 = base_dir / "04_refinancing_consolidation.json"
    data4 = json.loads(p4.read_text(encoding="utf-8"))
    req4 = RefinancingRequest.model_validate(data4["request"])
    res4 = compare_refinancing_options(req4)

    exp4 = data4["expected_results"]
    t4_ok = (
        res4.status == "ok"
        and res4.current_monthly_payment == Decimal(exp4["current_monthly_payment"])
        and res4.new_monthly_payment == Decimal(exp4["new_monthly_payment"])
        and res4.outcome == exp4["outcome"]
        and res4.early_repayment_fees_on_current_loans == Decimal(exp4["early_repayment_fees_on_current_loans"])
    )
    if not t4_ok: all_passed = False
    print(f"[{'PASS' if t4_ok else 'FAIL'}] {data4['scenario_name']}")
    print(f"       Credite refinanțate: 2 credite vechi (sold total 35.000 RON) + Extra cash {req4.extra_cash:,.2f} RON")
    print(f"       Efort lunar vechi: {res4.current_monthly_payment:,.2f} RON/lună")
    print(f"       Noua rată unificată: {res4.new_monthly_payment:,.2f} RON/lună")
    monthly_diff = res4.current_monthly_payment - res4.new_monthly_payment
    print(f"       Reducere efort lunar imediat: {monthly_diff:,.2f} RON în fiecare lună!")
    print(f"       Rezultat calitativ: {res4.outcome}")

    # 5. Rejected Boundary Cases
    print("\n--- [TEST 5] Validări Limită Reglementară & Erori Determinate ---")
    p5 = base_dir / "05_rejected_boundary_limits.json"
    data5 = json.loads(p5.read_text(encoding="utf-8"))
    t5_ok = True

    for c in data5["cases"]:
        c_type = c.get("type", "loan_offer")
        if c_type == "loan_offer":
            res_err = calculate_loan_offer(LoanOfferRequest.model_validate(c["request"]))
        else:
            loan_req_err = LoanOfferRequest.model_validate(c["loan_request"])
            res_err = simulate_early_repayment(EarlyRepaymentRequest(
                loan=loan_req_err,
                after_month=c["after_month"],
                amount=Decimal(c["repayment_amount"]),
            ))
        case_passed = (
            res_err.status == "invalid"
            and any(e.code == c["expected_error_code"] and c["expected_message_substring"] in e.message for e in res_err.errors)
        )
        if not case_passed:
            t5_ok = False
            all_passed = False
        print(f"       [{'PASS' if case_passed else 'FAIL'}] {c['test_case']} -> cod eroare: {res_err.errors[0].code} ('{res_err.errors[0].message}')")

    print("\n" + "=" * 80)
    if all_passed:
        print("[SUCCESS] Toate testele simulatorului de credite (Loan Pricing Engine) au trecut cu brio!")
    else:
        print("[WARNING] Unele teste nu au produs rezultatul așteptat.")
    print("=" * 80)
    return all_passed


if __name__ == "__main__":
    success = run_pricing_tests()
    sys.exit(0 if success else 1)
