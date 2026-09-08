"""Validate the synthetic v1 examples and demonstrate the data-only strategy interface."""

import json
from pathlib import Path

from buffetbot.contracts import (
    ExecutionAuditEvent,
    PortfolioTargets,
    Strategy,
    StrategyContext,
    validate_targets,
)
from buffetbot.experiments import (
    ExperimentManifest,
    ExperimentSpecification,
    experiment_id,
    new_run,
    validate_context,
)


class AllCashDemo:
    def generate_targets(self, context: StrategyContext) -> PortfolioTargets:
        return PortfolioTargets(
            schema_version=1,
            run_id=context.run_id,
            experiment_id=context.experiment_id,
            strategy_name=context.strategy.name,
            strategy_version=context.strategy.version,
            decision_at=context.decision_at,
            feature_cutoff=context.decision_at,
            execution_at=context.execution_at,
            expires_at=context.target_expires_at,
            weights=(),
            reason_codes=("contract_demo",),
        )


def main():
    directory = Path(__file__).parent
    spec = ExperimentSpecification.model_validate_json((directory / "experiment.json").read_text())
    context = StrategyContext.model_validate_json((directory / "context.json").read_text())
    manifest = ExperimentManifest(
        schema_version=1,
        run_id=context.run_id,
        created_at="2026-09-07T00:00:00Z",
        experiment_id=experiment_id(spec),
        specification=spec,
    )
    validate_context(manifest, context)
    target = PortfolioTargets.model_validate_json((directory / "targets.json").read_text())
    validate_targets(context, target)
    ExecutionAuditEvent.model_validate_json((directory / "execution-event.json").read_text())
    policy: Strategy = AllCashDemo()
    generated = validate_targets(context, policy.generate_targets(context))
    first, second = new_run(spec), new_run(spec)
    assert first.experiment_id == second.experiment_id and first.run_id != second.run_id
    print(
        json.dumps(
            {
                "status": "passed",
                "schema_version": 1,
                "origin": "synthetic",
                "experiment_id": first.experiment_id,
                "run_ids": [str(first.run_id), str(second.run_id)],
                "demo_cash_weight": str(generated.cash_weight),
                "portfolio_equity_usd": str(context.portfolio.equity_usd),
                "spendable_cash_usd": str(context.portfolio.spendable_cash_usd),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
