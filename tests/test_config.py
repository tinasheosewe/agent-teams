"""Tests for the config system."""

from pathlib import Path

from agentagent.config import CompanyConfig, InteractionMode, load_config


def test_load_software_company_config():
    config = load_config("configs/overlays/software_company.yaml")
    assert isinstance(config, CompanyConfig)
    assert config.name == "Software Engineering Studio"
    assert len(config.teams) == 6
    assert len(config.workflow) == 6


def test_team_config_structure():
    config = load_config("configs/overlays/software_company.yaml")
    mgmt = config.teams[0]
    assert mgmt.name == "management"
    assert len(mgmt.experts) == 2
    assert mgmt.experts[0].role == "strategist"
    assert InteractionMode.GENERATIVE in mgmt.preferred_modes


def test_workflow_dependencies():
    config = load_config("configs/overlays/software_company.yaml")
    steps_by_name = {s.step: s for s in config.workflow}

    # Engineering depends on design + architecture
    eng = steps_by_name["engineering"]
    assert "design_approved" in eng.depends_on
    assert "architecture_approved" in eng.depends_on

    # Design and architecture can run in parallel
    design = steps_by_name["design"]
    arch = steps_by_name["architecture"]
    assert "architecture" in design.parallel_with
    assert "design" in arch.parallel_with


def test_workflow_on_fail():
    config = load_config("configs/overlays/software_company.yaml")
    qa = next(s for s in config.workflow if s.step == "qa")
    assert qa.on_fail == "engineering"
