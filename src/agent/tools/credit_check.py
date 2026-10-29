"""Real handlers for get_customer_profile and run_eligibility_check over the SQLite credit sources.

The decision is computed by `src.rules.eligibility.credit_check.evaluate`; the model never
computes or overrides it. Missing DB / SQLite errors surface as ToolUnavailable.
"""
from src.agent.tools.contracts import CustomerProfileOutput, GetCustomerProfileInput, RunEligibilityInput
from src.agent.tools.registry import ToolContext
from src.agent.tools.stubs import StubData
from src.integrations.credit_sources import SqliteCreditSources
from src.models.credit import EligibilityResult
from src.rules.eligibility.credit_check import evaluate


def make_profile_handler(sources: SqliteCreditSources):
    def handle_get_profile(input: GetCustomerProfileInput, ctx: ToolContext) -> CustomerProfileOutput:
        person = sources.person(ctx.state.customer_id)
        if person is None:
            raise ValueError("unknown customer")
        born, as_of = person.birth_date, person.as_of
        age = as_of.year - born.year - ((as_of.month, as_of.day) < (born.month, born.day))
        ctx.state.used_stubs = True
        return CustomerProfileOutput(customer_id=person.customer_id, full_name=person.full_name, age=age,
                                     simulated=True)
    return handle_get_profile


def make_eligibility_handler(sources: SqliteCreditSources, data: StubData):
    def handle_eligibility(input: RunEligibilityInput, ctx: ToolContext) -> EligibilityResult:
        app = ctx.state.application
        if app is None or app.product_code is None:
            raise ValueError("No application or product selected")
        if app.product_code not in data.eligibility_rules:
            raise ValueError(f"No eligibility rules for product {app.product_code}")
        fields = {name: value.value for name, value in app.fields.items()}
        customer_id = ctx.state.customer_id
        anaf, bureau = sources.anaf(customer_id), sources.bureau(customer_id)
        ctx.state.used_stubs = True
        return evaluate(fields, data.products[app.product_code], data.eligibility_rules[app.product_code],
                        anaf, bureau)
    return handle_eligibility
