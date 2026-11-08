"""Load acr.wrapper/v1 adapters from wrappers/<id>/wrapper.toml."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from orchestrator.config import home, load_toml
from orchestrator.contracts import ModelAdapter


def find_wrapper(wrapper_id: str, root: Path | None = None) -> dict[str, Any]:
    root = root or home()
    for mf in (root / "wrappers").rglob("wrapper.toml"):
        d = load_toml(mf)
        if d.get("id") == wrapper_id:
            d["_dir"] = mf.parent
            return d
    raise KeyError(f"unknown wrapper '{wrapper_id}'")


def load_adapter(wrapper_id: str, config: dict[str, Any], root: Path | None = None) -> ModelAdapter:
    manifest = find_wrapper(wrapper_id, root)
    if manifest.get("interface") != ModelAdapter.interface:
        raise ValueError(f"wrapper {wrapper_id} implements {manifest.get('interface')}, need {ModelAdapter.interface}")
    file, cls = manifest["entrypoint"].split(":")
    path = Path(manifest["_dir"]) / file
    mod_name = f"acr_wrapper_{wrapper_id.replace('-', '_')}"
    if mod_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
    adapter_cls = getattr(sys.modules[mod_name], cls)
    merged = {**manifest.get("defaults", {}), **{k: v for k, v in config.items() if v not in (None, "")}}
    return adapter_cls(merged)
