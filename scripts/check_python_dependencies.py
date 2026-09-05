"""Validate the installed Python graph against the curated dependency profiles."""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATHS = {
    "runtime": ROOT / "requirements/runtime.txt",
    "dev": ROOT / "requirements/dev.txt",
    "build": ROOT / "requirements/build.txt",
}
CONSTRAINTS_PATH = ROOT / "requirements/constraints.txt"
ALLOWED_TOOLING = frozenset({"pip"})


def requirement_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "-"))
    ]


def active_requirement(line: str) -> Requirement | None:
    requirement = Requirement(line)
    environment = default_environment() | {"extra": ""}
    if requirement.marker and not requirement.marker.evaluate(environment):
        return None
    return requirement


def installed_distributions() -> dict[str, metadata.Distribution]:
    return {
        canonicalize_name(distribution.metadata["Name"]): distribution
        for distribution in metadata.distributions()
        if distribution.metadata.get("Name")
    }


def resolved_closure(
    roots: set[str], installed: dict[str, metadata.Distribution]
) -> tuple[set[str], list[str]]:
    closure: set[str] = set()
    missing: list[str] = []
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in closure:
            continue
        closure.add(name)
        distribution = installed.get(name)
        if distribution is None:
            missing.append(name)
            continue
        for raw_requirement in distribution.requires or ():
            requirement = active_requirement(raw_requirement)
            if requirement is not None:
                pending.append(canonicalize_name(requirement.name))
    return closure, sorted(missing)


def validate(*, strict: bool, profiles: list[str]) -> list[str]:
    errors: list[str] = []
    installed = installed_distributions()
    direct_requirements = [
        requirement
        for profile in profiles
        for path in (PROFILE_PATHS[profile],)
        for line in requirement_lines(path)
        if (requirement := active_requirement(line)) is not None
    ]
    roots = {canonicalize_name(requirement.name) for requirement in direct_requirements}
    closure, missing_installed = resolved_closure(roots, installed)
    if missing_installed:
        errors.append("required packages are not installed: " + ", ".join(missing_installed))

    constraints = {
        canonicalize_name(requirement.name): requirement
        for line in requirement_lines(CONSTRAINTS_PATH)
        if (requirement := active_requirement(line)) is not None
    }
    missing_constraints = sorted(closure - constraints.keys())
    stale_constraints = (
        sorted(constraints.keys() - closure)
        if set(profiles) == set(PROFILE_PATHS)
        else []
    )
    if missing_constraints:
        errors.append("dependency graph is missing constraints: " + ", ".join(missing_constraints))
    if stale_constraints:
        errors.append("constraints contain unreachable packages: " + ", ".join(stale_constraints))

    mismatches: list[str] = []
    for name in sorted(closure & constraints.keys() & installed.keys()):
        specifier = constraints[name].specifier
        version = installed[name].version
        if specifier and version not in specifier:
            mismatches.append(f"{name} {version} does not satisfy {specifier}")
    if mismatches:
        errors.append("installed versions do not match constraints: " + "; ".join(mismatches))

    extras = sorted(installed.keys() - closure - ALLOWED_TOOLING)
    if strict and extras:
        errors.append("isolated environment contains undeclared packages: " + ", ".join(extras))
    elif extras:
        print("Unmanaged packages in this developer environment: " + ", ".join(extras))

    print(
        f"Dependency graph: {len(roots)} direct, {len(closure)} resolved, "
        f"{len(extras)} unmanaged installed package(s)."
    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when the environment contains packages outside the resolved graph.",
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=tuple(PROFILE_PATHS),
        help="Validate only this profile; repeat for multiple profiles. Defaults to all.",
    )
    args = parser.parse_args()
    profiles = list(dict.fromkeys(args.profile or PROFILE_PATHS.keys()))
    errors = validate(strict=args.strict, profiles=profiles)
    if not errors:
        return 0
    print("Dependency check failed:")
    for error in errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
