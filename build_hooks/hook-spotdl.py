"""Collect data and hidden imports from spotDL's installed dependencies.

spotDL loads several providers dynamically, and some of its dependencies ship
runtime data (for example pykakasi dictionaries and ytmusicapi translations).
PyInstaller's --collect-all spotdl does not recursively collect those files.
"""

from importlib import metadata

from packaging.requirements import Requirement
from PyInstaller.utils.hooks import collect_all


datas = []
binaries = []
hiddenimports = []


def add_package(package):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package)
    except Exception:
        # Some dependencies are metadata-only or do not expose an importable
        # package under their distribution name.
        return
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)


try:
    package_map = metadata.packages_distributions()
except Exception:
    package_map = {}


def dependency_closure(root):
    pending = [root]
    visited = set()
    while pending:
        name = pending.pop()
        normalized = name.lower().replace("_", "-").replace(".", "-")
        if normalized in visited:
            continue
        visited.add(normalized)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        yield normalized, dist
        for raw_requirement in dist.requires or ():
            try:
                requirement = Requirement(raw_requirement)
                if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                    continue
                pending.append(requirement.name)
            except Exception:
                continue


for dist_name, dist in dependency_closure("spotdl"):
    if dist_name == "spotdl":
        continue  # spotDL itself is already collected by the build command/spec.

    import_names = [
        import_name
        for import_name, distributions in package_map.items()
        if any(
            distribution.lower().replace("_", "-").replace(".", "-") == dist_name
            for distribution in distributions
        )
    ]
    if not import_names:
        import_names = [dist_name.replace("-", "_")]
    for import_name in import_names:
        add_package(import_name)
