"""CLI entry point: python -m oko {pretrain,finetune,evaluate,sweep,generate-data}."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import torch


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_data(config):
    """Load data from synthetic generator or a saved .pt file."""
    from oko.synthetic.generator import SyntheticGraphGenerator
    return SyntheticGraphGenerator(config).generate()


def cmd_train(args: argparse.Namespace) -> None:
    """Run the full pretrain -> finetune -> evaluate pipeline."""
    from oko.config import load_config
    from oko.training.pipeline import ScoringPipeline

    config = load_config(args.config)
    config = _override_device(config, args)
    data = _load_data(config)

    pipeline = ScoringPipeline(config)
    scorer, metrics = pipeline.run(
        data,
        skip_pretrain=args.skip_pretrain,
        checkpoint_dir=args.output,
    )
    print(f"\nFinal test metrics:\n{metrics}")

    if args.output:
        Path(args.output).mkdir(parents=True, exist_ok=True)
        torch.save(scorer.state_dict(), Path(args.output) / "scorer_final.pt")
        print(f"Model saved to {args.output}/scorer_final.pt")


def cmd_pretrain(args: argparse.Namespace) -> None:
    """Run only pretraining."""
    from oko.config import load_config
    from oko.models.backbones import build_backbone
    from oko.models.pretrain import build_pretrain_task
    from oko.models.scorer import NoteProjection
    from oko.training.pipeline import _compute_input_dims
    from oko.training.pretrain_loop import PretrainRunner

    config = load_config(args.config)
    config = _override_device(config, args)
    data = _load_data(config)

    input_dims = _compute_input_dims(data, config)
    metadata = data.metadata()

    backbone = build_backbone(metadata, config.backbone, input_dims)
    pretrain_task = build_pretrain_task(backbone, config.pretrain, metadata)
    note_proj = NoteProjection(config.data.note_embedding_dim, config.data.projection_dim)
    runner = PretrainRunner(pretrain_task, config.pretrain, config.device, note_projection=note_proj)
    trained_backbone = runner.run(data)

    if args.output:
        Path(args.output).mkdir(parents=True, exist_ok=True)
        torch.save(trained_backbone.state_dict(), Path(args.output) / "backbone_pretrained.pt")
        print(f"Backbone saved to {args.output}/backbone_pretrained.pt")


def cmd_evaluate(args: argparse.Namespace) -> None:
    """Evaluate a saved scorer checkpoint."""
    from oko.config import load_config
    from oko.models.scorer import FraudScorer
    from oko.training.evaluate import Evaluator
    from oko.training.pipeline import _compute_input_dims

    config = load_config(args.config)
    config = _override_device(config, args)
    data = _load_data(config)

    input_dims = _compute_input_dims(data, config)
    metadata = data.metadata()

    scorer = FraudScorer(metadata, config, input_dims)
    scorer.load_state_dict(torch.load(args.checkpoint, map_location=config.device))

    evaluator = Evaluator(config.device)
    target = scorer.target_node_type
    metrics = evaluator.evaluate(scorer, data, data[target].test_mask)
    print(f"Test metrics:\n{metrics}")


def cmd_sweep(args: argparse.Namespace) -> None:
    """Run hyperparameter sweep."""
    from oko.config import load_config
    from oko.tuning.sweep import SweepRunner

    config = load_config(args.config)
    config = _override_device(config, args)
    data = _load_data(config)

    runner = SweepRunner(config, data, n_trials=args.n_trials)
    study = runner.run()
    print(f"\nBest params: {study.best_trial.params}")
    print(f"Best {config.sweep.metric}: {study.best_value:.4f}")


def cmd_generate_data(args: argparse.Namespace) -> None:
    """Generate synthetic data and save to disk."""
    from oko.config import load_config
    from oko.synthetic.generator import SyntheticGraphGenerator

    config = load_config(args.config)
    gen = SyntheticGraphGenerator(config)
    data = gen.generate()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(data, output)
    print(f"Synthetic data saved to {output}")
    print(f"  Node types: {data.node_types}")
    print(f"  Edge types: {data.edge_types}")
    for ntype in data.node_types:
        print(f"  {ntype}: {data[ntype].num_nodes} nodes, x={data[ntype].x.shape}")


def _override_device(config, args):
    """Override device from CLI args."""
    from dataclasses import replace
    if hasattr(args, "device") and args.device:
        return replace(config, device=args.device)
    return config


def main() -> None:
    parser = argparse.ArgumentParser(prog="oko", description="OKO Fraud Scoring Engine")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    # train
    p = sub.add_parser("train", help="Full pretrain + finetune + evaluate pipeline")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--output", default=None, help="Checkpoint output directory")
    p.add_argument("--skip-pretrain", action="store_true")
    p.add_argument("--device", default=None)

    # pretrain
    p = sub.add_parser("pretrain", help="Run pretraining only")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--output", default=None)
    p.add_argument("--device", default=None)

    # evaluate
    p = sub.add_parser("evaluate", help="Evaluate a checkpoint")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--device", default=None)

    # sweep
    p = sub.add_parser("sweep", help="Hyperparameter sweep")
    p.add_argument("--config", default="configs/sweep.yaml")
    p.add_argument("--n-trials", type=int, default=None)
    p.add_argument("--device", default=None)

    # generate-data
    p = sub.add_parser("generate-data", help="Generate synthetic graph data")
    p.add_argument("--config", default="configs/default.yaml")
    p.add_argument("--output", default="data/synthetic.pt")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    commands = {
        "train": cmd_train,
        "pretrain": cmd_pretrain,
        "evaluate": cmd_evaluate,
        "sweep": cmd_sweep,
        "generate-data": cmd_generate_data,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
