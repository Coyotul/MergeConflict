"""Load and validate versioned synthetic configuration before accepting calls."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, SecretStr

from src.core.errors import DomainError
from src.models.banking import Actor, Customer, Loan, PolicySource, Product, Role
from src.models.common import Money, WireModel


class ProductConfiguration(WireModel):
    version: str
    products: list[Product]


class RuleConfiguration(WireModel):
    version: str
    debt_ratio_threshold: Money = Field(gt=0, le=100)
    early_repayment_fee_percent: Money = Field(ge=0, le=100)
    refinancing_annual_rate: Money = Field(ge=0, le=100)
    refinancing_fee: Money = Field(ge=0)
    refinancing_min_months: int = Field(ge=1, le=600)
    refinancing_max_months: int = Field(ge=1, le=600)


class PolicyConfiguration(WireModel):
    sources: list[PolicySource]


class DemoAccount(WireModel):
    actor: Actor
    email: str
    password: SecretStr


class FixtureConfiguration(WireModel):
    accounts: list[DemoAccount]
    customers: list[Customer]
    loans: list[Loan]
    default_reviewer_id: str


@dataclass(frozen=True)
class Catalogue:
    products: tuple[Product, ...]
    policies: tuple[PolicySource, ...]
    rules: RuleConfiguration
    fixtures: FixtureConfiguration

    @classmethod
    def load(cls, root: Path) -> "Catalogue":
        products = ProductConfiguration.model_validate_json(
            (root / "config/products/demo.json").read_text(encoding="utf-8")
        )
        rules = RuleConfiguration.model_validate_json(
            (root / "config/rules/demo.json").read_text(encoding="utf-8")
        )
        policies = PolicyConfiguration.model_validate_json(
            (root / "data/synthetic/policies/demo.json").read_text(encoding="utf-8")
        )
        fixtures = FixtureConfiguration.model_validate_json(
            (root / "data/synthetic/applications/backend-fixtures.json").read_text(encoding="utf-8")
        )
        identifiers = [p.id for p in products.products]
        if len(set(identifiers)) != len(identifiers) or not identifiers:
            raise ValueError("Synthetic products must have unique IDs.")
        policy_ids = [p.id for p in policies.sources]
        if len(set(policy_ids)) != len(policy_ids):
            raise ValueError("Synthetic policy sources must have unique IDs.")
        for product in products.products:
            if product.min_amount > product.max_amount or product.min_months > product.max_months:
                raise ValueError("Invalid synthetic product range.")
            if not product.required_documents or len(set(product.required_documents)) != len(product.required_documents):
                raise ValueError("Product evidence requirements must be nonempty and unique.")
            source = next((p for p in policies.sources if p.id == product.policy_id), None)
            if source is None or source.version != product.policy_version or source.product_id != product.id:
                raise ValueError("Product configuration must reference its matching policy version.")
            if product.policy_version != products.version:
                raise ValueError("Product catalogue versions are inconsistent.")
        if rules.refinancing_min_months > rules.refinancing_max_months:
            raise ValueError("Invalid synthetic refinancing range.")
        if any(p.version != rules.version for p in policies.sources):
            raise ValueError("Policy and rule versions are inconsistent.")
        customer_ids = {c.id for c in fixtures.customers}
        actors = {a.actor.id: a.actor for a in fixtures.accounts}
        if len(actors) != len(fixtures.accounts) or len(customer_ids) != len(fixtures.customers):
            raise ValueError("Synthetic identities must have unique IDs.")
        if any(c.id not in actors or actors[c.id].role != Role.CUSTOMER for c in fixtures.customers):
            raise ValueError("Every fixture customer needs a customer account.")
        reviewer = actors.get(fixtures.default_reviewer_id)
        if reviewer is None or reviewer.role != Role.REVIEWER:
            raise ValueError("A synthetic assigned reviewer is required.")
        if any(loan.customer_id not in customer_ids for loan in fixtures.loans):
            raise ValueError("Every synthetic loan needs an owner.")
        return cls(tuple(products.products), tuple(policies.sources), rules, fixtures)

    def product(self, product_id: str) -> Product:
        product = next((p for p in self.products if p.id == product_id), None)
        if product is None:
            raise DomainError("NOT_FOUND", "Synthetic product not found.", 404)
        return product.model_copy(deep=True)