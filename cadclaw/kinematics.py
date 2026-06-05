"""
Kinematics Module — structural analysis from assembly geometry.

Provides beam deflection, motor torque budget, and belt tension
checks for belt-driven gantry systems. Static load math only; it does
not sweep range of motion or check clearance through travel.

Usage:
    from cadclaw.kinematics import BeamDeflection, MotorBudget
    defl = BeamDeflection(span=2.0, load_kg=3.8, I_cm4=18.0, beam_kg_per_m=2.45)
    print(f"Center sag: {defl.sag_mm:.2f} mm")
"""
import math
from dataclasses import dataclass

g = 9.81  # m/s^2


@dataclass
class DeflectionResult:
    point_load_mm: float
    self_weight_mm: float
    total_mm: float
    passed: bool
    limit_mm: float


def beam_deflection(span_m: float, point_load_kg: float,
                    I_m4: float, beam_kg_per_m: float,
                    E_Pa: float = 69e9, limit_mm: float = 0.5) -> DeflectionResult:
    """
    Simply-supported beam, point load at center + distributed self-weight.

    Args:
        span_m: Beam span in meters.
        point_load_kg: Point load at center in kg.
        I_m4: Second moment of area in m^4.
        beam_kg_per_m: Beam mass per meter in kg/m.
        E_Pa: Young's modulus in Pa (default: aluminum 6063).
        limit_mm: Pass/fail deflection limit in mm.
    """
    P = point_load_kg * g
    w = beam_kg_per_m * g  # N/m

    d_point = (P * span_m ** 3) / (48 * E_Pa * I_m4)
    d_weight = (5 * w * span_m ** 4) / (384 * E_Pa * I_m4)
    d_total = d_point + d_weight

    return DeflectionResult(
        point_load_mm=d_point * 1000,
        self_weight_mm=d_weight * 1000,
        total_mm=d_total * 1000,
        passed=d_total * 1000 <= limit_mm,
        limit_mm=limit_mm,
    )


@dataclass
class MotorResult:
    force_accel_N: float
    force_friction_N: float
    force_gravity_N: float
    force_total_N: float
    torque_required_Nm: float
    torque_available_Nm: float
    safety_factor: float
    passed: bool


def motor_torque_budget(mass_kg: float, n_motors: int,
                        pulley_radius_m: float,
                        motor_torque_Nm: float,
                        accel_m_s2: float = 0.5,
                        gravity_axis: bool = False,
                        friction_coeff: float = 0.01,
                        belt_efficiency: float = 0.95,
                        torque_derating: float = 0.7,
                        min_safety: float = 1.5) -> MotorResult:
    """
    Calculate motor torque budget for a belt-driven axis.

    Args:
        mass_kg: Total moving mass on this axis.
        n_motors: Number of motors driving this axis.
        pulley_radius_m: GT2 pulley pitch radius in meters.
        motor_torque_Nm: Motor holding torque in Nm.
        accel_m_s2: Target acceleration in m/s^2.
        gravity_axis: True if this axis fights gravity (Z-axis).
        friction_coeff: V-wheel rolling friction coefficient.
        belt_efficiency: Belt drive efficiency (0-1).
        torque_derating: Fraction of holding torque available at speed.
        min_safety: Minimum acceptable safety factor.
    """
    F_accel = mass_kg * accel_m_s2
    F_friction = mass_kg * g * friction_coeff
    F_gravity = mass_kg * g if gravity_axis else 0
    F_total = F_accel + F_friction + F_gravity

    F_per_motor = F_total / n_motors
    T_required = F_per_motor * pulley_radius_m / belt_efficiency
    T_available = motor_torque_Nm * torque_derating

    safety = T_available / T_required if T_required > 0 else float('inf')

    return MotorResult(
        force_accel_N=F_accel,
        force_friction_N=F_friction,
        force_gravity_N=F_gravity,
        force_total_N=F_total,
        torque_required_Nm=T_required,
        torque_available_Nm=T_available,
        safety_factor=safety,
        passed=safety >= min_safety,
    )


@dataclass
class BeltResult:
    tension_N: float
    breaking_N: float
    working_N: float
    safety_to_break: float
    safety_to_working: float
    passed: bool


def belt_tension(force_N: float, n_belts: int = 1,
                 breaking_N: float = 900, working_N: float = 450,
                 min_safety: float = 2.0) -> BeltResult:
    """Check belt tension against breaking and working limits."""
    per_belt = force_N / n_belts
    s_break = breaking_N / per_belt if per_belt > 0 else float('inf')
    s_work = working_N / per_belt if per_belt > 0 else float('inf')

    return BeltResult(
        tension_N=per_belt,
        breaking_N=breaking_N,
        working_N=working_N,
        safety_to_break=s_break,
        safety_to_working=s_work,
        passed=s_work >= min_safety,
    )
