import re
import random
import logging

logger = logging.getLogger("LROS-AutoLab")

def run_drug_binding_simulation(mutation_text: str) -> float:
    """Simulate drug-target binding affinity. Returns score 0–1."""
    numbers = re.findall(r"(\d+(?:\.\d+)?)\s*µ?M", mutation_text)
    if numbers:
        ic50 = float(numbers[0])
        score = max(0.0, min(1.0, 1.0 / (1.0 + ic50)))
        return score
    return random.uniform(0.2, 0.9)

def run_cell_viability_simulation(mutation_text: str) -> float:
    """Simulate cell viability increase."""
    numbers = re.findall(r"(\d+(?:\.\d+)?)\s*%", mutation_text)
    if numbers:
        viability = float(numbers[0]) / 100.0
        return max(0.0, min(1.0, viability))
    return random.uniform(0.3, 0.8)

def run_agi_benchmark_simulation(mutation_text: str) -> float:
    """Simulate an AGI benchmark run."""
    return random.uniform(0.4, 0.95)

def run_asi_sandbox_simulation(mutation_text: str) -> float:
    """Simulate sandbox test of a self‑improvement proposal."""
    return random.uniform(0.3, 0.9)

def run_simulation(mutation_text: str, sim_type: str) -> float:
    """Dispatch to the appropriate simulation."""
    logger.info(f"[AUTO-LAB] Starting {sim_type} simulation...")
    try:
        if sim_type == "drug_binding":
            return run_drug_binding_simulation(mutation_text)
        elif sim_type == "cell_viability":
            return run_cell_viability_simulation(mutation_text)
        elif sim_type == "agi_benchmark":
            return run_agi_benchmark_simulation(mutation_text)
        elif sim_type == "asi_sandbox":
            return run_asi_sandbox_simulation(mutation_text)
        else:
            logger.warning(f"Unknown simulation type: {sim_type}")
            return None
    except Exception as e:
        logger.exception(f"Simulation failed: {e}")
        return None
