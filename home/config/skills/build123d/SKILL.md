---
name: build123d
description: Expert in Python CAD modeling using build123d. Use when creating 3D models, sketches, or assemblies. Emphasizes visual validation via multi-perspective screenshots and exportable formats.
category: cad
risk: low
source: community
date_added: "2026-03-01"
---

# Build123d Expert Skill

This skill provides specialized workflows for CAD modeling using the **`build123d`** Python library. It emphasizes reproducible, code-driven design and rigorous visual validation.

## Core Directives

### 1. Environment & Setup (Python Integration)
- **Always use `uv`**: Refer to the `python` skill for environment management.
- **Dependency**: Add `build123d` and `ocp` (OpenCascade) via `uv add build123d`.
- **Imports**: Use clear, idiomatic imports:
  ```python
  from build123d import *
  ```

### 2. Modeling Workflow
- **State-Based Design**: Use `BuildPart`, `BuildSketch`, and `BuildLine` contexts to define geometry.
- **Feature Layering**: Build complex models by layering sketches and boolean operations (extrude, revolve, etc.).
- **Parametric Design**: Define dimensions as variables at the top of the script for easy adjustment.

### 3. Visual Validation (Mandatory)
- **Multi-Perspective Screenshots**: After significant modeling steps, **always** take screenshots from multiple angles to verify geometry, alignment, and features.
- **Required Perspectives**:
    - **Isometric**: Overall structure and spatial relationship.
    - **Top (XY)**: Verify layout and footprint.
    - **Front (XZ)**: Verify height and vertical features.
    - **Right (YZ)**: Verify side profiles and depths.
- **Verification Tools**: If using a browser-based viewer (e.g., `ocp-vscode` in a browser), use the `browser-use` skill to capture these screenshots.

### 4. Export & Artifacts
- **Primary Export**: Export to **STEP** (`part.export_step("model.step")`) for high-fidelity geometry.
- **Secondary Export**: Export to **STL** (`part.export_stl("model.stl")`) for 3D printing and quick mesh visualization.
- **File Naming**: Use descriptive names (e.g., `v1_base_plate.step`) and maintain versioning.

## Best Practices

| Action | Recommended Approach |
| :--- | :--- |
| **New Part** | Start with `with BuildPart() as p:` |
| **Complex Profile** | Define with `with BuildSketch() as s:` then `extrude()` |
| **Fillets/Chamfers** | Apply at the end of the `BuildPart` context. |
| **Validation** | Screenshot (Iso, Top, Front, Right) + `export_step()` |

## Interaction Protocol
1. **Model Requirement**: Confirm the goal, dimensions, and critical constraints.
2. **Skeleton Strategy**: Propose the modeling steps (e.g., "Start with a 100x100 base, then extrude a cylinder...").
3. **Iterative Build**: Code a section, then **verify with screenshots** before proceeding to the next complex feature.
4. **Final Delivery**: Provide the Python script, STEP file, and the 4 mandatory perspective screenshots.
