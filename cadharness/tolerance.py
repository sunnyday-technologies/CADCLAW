"""
Tolerance Stacking Gate — the feature manufacturers pay $50K/year for.

Computes tolerance accumulation along assembly chains. Supports three
analysis methods:
  - Worst-case: sum of all tolerances (conservative, guaranteed)
  - RSS (Root Sum Square): statistical combination (typical, 99.7%)
  - Monte Carlo: random sampling from distributions (realistic)

A tolerance chain is a sequence of dimensions that add up to a critical
result (e.g., the gap between a motor face and a bracket). If the
accumulated tolerance exceeds the functional requirement, the design
fails — before you build it.

Usage:
    from cadharness.tolerance import ToleranceChain, StackResult

    chain = ToleranceChain("motor_alignment")
    chain.add("beam_length", nominal=1000.0, plus=0.5, minus=0.5)
    chain.add("shim", nominal=4.0, plus=0.1, minus=0.1)
    chain.add("plate", nominal=5.0, plus=0.2, minus=0.2)
    chain.add("motor_offset", nominal=-1009.0, plus=0.3, minus=0.3)

    result = chain.analyze(target=0.0, tolerance=0.5)
    print(f"Worst case: {result.worst_case_range}")
    print(f"RSS (3-sigma):   {result.rss_range}")
    print(f"Cpk:        {result.cpk}")
"""
import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Dimension:
    """A single dimension in a tolerance chain."""
    name: str
    nominal: float       # mm
    plus: float          # + tolerance (positive number)
    minus: float         # - tolerance (positive number, stored as positive)
    distribution: str = "normal"  # "normal", "uniform", or "triangular"
    direction: float = 1.0  # +1 or -1 (add or subtract in chain)

    @property
    def bilateral(self) -> float:
        """Average bilateral tolerance (for RSS calculation)."""
        return (self.plus + self.minus) / 2.0

    @property
    def mean(self) -> float:
        """Mean dimension (shifted if asymmetric tolerance)."""
        return self.nominal + (self.plus - self.minus) / 2.0

    def sample(self, rng: random.Random = None) -> float:
        """Draw a random sample from this dimension's distribution."""
        r = rng or random
        if self.distribution == "uniform":
            return r.uniform(self.nominal - self.minus,
                             self.nominal + self.plus)
        elif self.distribution == "triangular":
            return r.triangular(self.nominal - self.minus,
                                self.nominal + self.plus,
                                self.nominal)
        else:  # normal (3-sigma = tolerance band)
            sigma = self.bilateral / 3.0
            return r.gauss(self.mean, sigma)


@dataclass
class StackResult:
    """Result of a tolerance stack analysis."""
    chain_name: str
    nominal_result: float
    target: float
    tolerance: float          # functional requirement

    # Worst case
    worst_case_min: float
    worst_case_max: float
    worst_case_range: float
    worst_case_passed: bool

    # RSS (Root Sum Square, 3-sigma)
    rss_min: float
    rss_max: float
    rss_range: float
    rss_passed: bool

    # Monte Carlo
    mc_mean: float
    mc_std: float
    mc_min: float
    mc_max: float
    mc_yield_pct: float       # % of samples within tolerance
    mc_passed: bool

    # Process capability
    cpk: float                # Cpk index (>1.33 = capable)

    # Individual contributions
    contributors: List[dict] = field(default_factory=list)

    def __str__(self):
        lines = [
            f"TOLERANCE STACK: {self.chain_name}",
            f"  Nominal result:  {self.nominal_result:+.3f} mm (target: {self.target})",
            f"  Tolerance:       +/-{self.tolerance} mm",
            "",
            f"  WORST CASE:      [{self.worst_case_min:+.3f}, {self.worst_case_max:+.3f}] "
            f"range={self.worst_case_range:.3f}  {'PASS' if self.worst_case_passed else 'FAIL'}",
            f"  RSS (3-sigma):        [{self.rss_min:+.3f}, {self.rss_max:+.3f}] "
            f"range={self.rss_range:.3f}  {'PASS' if self.rss_passed else 'FAIL'}",
            f"  MONTE CARLO:     mean={self.mc_mean:+.3f} s={self.mc_std:.3f} "
            f"yield={self.mc_yield_pct:.1f}%  {'PASS' if self.mc_passed else 'FAIL'}",
            f"  Cpk:             {self.cpk:.2f}  {'CAPABLE' if self.cpk >= 1.33 else 'NOT CAPABLE'}",
            "",
            "  CONTRIBUTORS (by % of total variance):",
        ]
        for c in sorted(self.contributors, key=lambda x: -x['variance_pct']):
            bar = '#' * int(c['variance_pct'] / 2)
            lines.append(f"    {c['name']:20s} +/-{c['tolerance']:.3f}  "
                         f"{c['variance_pct']:5.1f}%  {bar}")
        return '\n'.join(lines)


class ToleranceChain:
    """
    Define and analyze a tolerance chain.

    A chain is a sequence of dimensions that accumulate to produce
    a critical result (gap, alignment, fit). The chain can be analyzed
    for worst-case, statistical (RSS), and Monte Carlo outcomes.

    Args:
        name: Human-readable name for this chain.
    """

    def __init__(self, name: str):
        self.name = name
        self.dimensions: List[Dimension] = []

    def add(self, name: str, nominal: float, plus: float, minus: float = None,
            distribution: str = "normal", direction: float = 1.0):
        """Add a dimension to the chain.

        Args:
            name: Dimension label (e.g., "beam_length")
            nominal: Nominal value in mm
            plus: Plus tolerance (positive number)
            minus: Minus tolerance (positive number, defaults to same as plus)
            distribution: "normal", "uniform", or "triangular"
            direction: +1 to add, -1 to subtract in chain
        """
        if minus is None:
            minus = plus
        self.dimensions.append(Dimension(
            name=name, nominal=nominal, plus=plus, minus=minus,
            distribution=distribution, direction=direction,
        ))
        return self  # fluent API

    def analyze(self, target: float = 0.0, tolerance: float = 0.5,
                mc_samples: int = 100000, seed: int = 42) -> StackResult:
        """
        Run worst-case, RSS, and Monte Carlo analysis.

        Args:
            target: Target value for the chain result (e.g., 0.0 for a gap)
            tolerance: Functional requirement — result must be within
                       [target - tolerance, target + tolerance]
            mc_samples: Number of Monte Carlo samples (default 100K)
            seed: Random seed for reproducibility
        """
        # =============================================
        # Nominal
        # =============================================
        nominal_result = sum(d.direction * d.nominal for d in self.dimensions)

        # =============================================
        # Worst case
        # =============================================
        wc_plus = sum(
            d.plus if d.direction > 0 else d.minus
            for d in self.dimensions
        )
        wc_minus = sum(
            d.minus if d.direction > 0 else d.plus
            for d in self.dimensions
        )
        wc_max = nominal_result + wc_plus
        wc_min = nominal_result - wc_minus
        wc_range = wc_max - wc_min
        wc_passed = (wc_min >= target - tolerance and wc_max <= target + tolerance)

        # =============================================
        # RSS (Root Sum Square, assumes 3-sigma = tolerance)
        # =============================================
        rss_total = math.sqrt(sum(d.bilateral ** 2 for d in self.dimensions))
        rss_max = nominal_result + rss_total
        rss_min = nominal_result - rss_total
        rss_range = 2 * rss_total
        rss_passed = (rss_min >= target - tolerance and rss_max <= target + tolerance)

        # =============================================
        # Monte Carlo
        # =============================================
        rng = random.Random(seed)
        samples = []
        for _ in range(mc_samples):
            result = sum(d.direction * d.sample(rng) for d in self.dimensions)
            samples.append(result)

        mc_mean = sum(samples) / len(samples)
        mc_std = math.sqrt(sum((s - mc_mean) ** 2 for s in samples) / len(samples))
        mc_min = min(samples)
        mc_max = max(samples)

        in_spec = sum(1 for s in samples
                      if target - tolerance <= s <= target + tolerance)
        mc_yield = 100.0 * in_spec / mc_samples
        mc_passed = mc_yield >= 99.73  # 3-sigma equivalent

        # =============================================
        # Cpk (Process Capability Index)
        # =============================================
        if mc_std > 0:
            cpu = (target + tolerance - mc_mean) / (3 * mc_std)
            cpl = (mc_mean - (target - tolerance)) / (3 * mc_std)
            cpk = min(cpu, cpl)
        else:
            cpk = float('inf')

        # =============================================
        # Contributor analysis (variance decomposition)
        # =============================================
        total_variance = sum(d.bilateral ** 2 for d in self.dimensions)
        contributors = []
        for d in self.dimensions:
            var = d.bilateral ** 2
            pct = 100.0 * var / total_variance if total_variance > 0 else 0
            contributors.append({
                'name': d.name,
                'nominal': d.nominal,
                'tolerance': d.bilateral,
                'variance_pct': pct,
            })

        return StackResult(
            chain_name=self.name,
            nominal_result=nominal_result,
            target=target,
            tolerance=tolerance,
            worst_case_min=wc_min,
            worst_case_max=wc_max,
            worst_case_range=wc_range,
            worst_case_passed=wc_passed,
            rss_min=rss_min,
            rss_max=rss_max,
            rss_range=rss_range,
            rss_passed=rss_passed,
            mc_mean=mc_mean,
            mc_std=mc_std,
            mc_min=mc_min,
            mc_max=mc_max,
            mc_yield_pct=mc_yield,
            mc_passed=mc_passed,
            cpk=cpk,
            contributors=contributors,
        )


def auto_stack_from_assembly(parts: list, label_fn, axis: str = 'Z',
                              tolerances: dict = None) -> ToleranceChain:
    """
    Automatically build a tolerance chain from assembly parts along an axis.

    Scans all parts, sorts by position along the specified axis, and
    builds a chain of dimensions between adjacent parts. Uses the
    tolerances dict to assign +/- values per label.

    Args:
        parts: List of CadQuery solids from load_and_dedup()
        label_fn: Function mapping solid → label string
        axis: 'X', 'Y', or 'Z'
        tolerances: Dict of label → +/-tolerance in mm
                    e.g. {"cbeam": 0.5, "shim": 0.1, "plate": 0.2}
    """
    if tolerances is None:
        tolerances = {}

    axis_idx = {'X': 0, 'Y': 1, 'Z': 2}[axis.upper()]

    # Get part positions and dimensions along axis
    entries = []
    for s in parts:
        bb = s.BoundingBox()
        mins = [bb.xmin, bb.ymin, bb.zmin]
        maxs = [bb.xmax, bb.ymax, bb.zmax]
        dim = maxs[axis_idx] - mins[axis_idx]
        pos = mins[axis_idx]
        label = label_fn(s)
        tol = tolerances.get(label, 0.1)  # default +/-0.1mm
        entries.append((pos, dim, label, tol, s))

    entries.sort(key=lambda e: e[0])

    chain = ToleranceChain(f"auto_{axis}_stack")
    for pos, dim, label, tol, s in entries:
        chain.add(label, nominal=dim, plus=tol, minus=tol)

    return chain
