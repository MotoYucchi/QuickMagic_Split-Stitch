# Split & Stitch for QuickMagicMotion

[English](README.md) | [日本語](README.ja.md)

An end-to-end processing pipeline consisting of a pre-processor (**Splitter**) that optimizes and segments input videos according to QuickMagic subscription plan limits (resolution, file size, duration, and allowed FPS), and a post-processor (**Stitcher**) that aligns and seamlessly merges exported motion clips back into a unified animation.

---

## Overview and Principles

QuickMagic is a cloud-based AI motion capture platform. However, each subscription tier (Free, Basic, Pro, Max, Studio) imposes strict boundaries on upload duration (e.g., 30s on Free), file size (e.g., 50 MB on Free), and accepted frame rates (strictly 30 fps on Free).

This project resolves these constraints through two dedicated stages:

1. **Splitter (Pre-Process)**:
   - Probes the input video's dimensions, rotation, color transfer, frame rate, and frame timeline.
   - Calculates equalized chunk durations with overlaps based on plan duration constraints and mathematical VBV capacity limits (`-maxrate` / `-bufsize`).
   - **FPS Scaling Mode (Time Stretch)**: For 60 fps or 120 fps footage targeting 30 fps plans, all original frames are retained without frame skipping by re-declaring the stream's timebase to 30 fps (effectively producing a smooth slow-motion clip with a 1:1 input-to-output frame mapping).
   - Generates an exact session manifest (`session_manifest.json`) recording frame ranges and transformation ratios.

2. **Stitcher (Post-Process)**:
   - Ingests the chunked motion files (FBX, BVH, VMD) downloaded from QuickMagic.
   - If FPS scaling was applied, re-synchronizes the animation timebase back to the original real-time playback speed.
   - Evaluates corresponding frames within overlapping regions to estimate rigid body transformations (circular mean of root Yaw and horizontal translation offsets), eliminating coordinate drift and foot sliding.
   - Bypasses boundary edge noise from the AI estimator, identifies the seam with minimum pose discontinuity, and blends the transition using Spherical Linear Interpolation (SLERP) and SmoothStep easing curves.

---

## Key Capabilities

- **Exact Frame Segmentation**:
  Managed via rational arithmetic (`Fraction`) and half-open intervals `[start, end)`. Employs `trim` filters and `setpts=N/(FPS*TB)` to guarantee zero dropped or duplicate frames.
- **A Priori Capacity Compliance**:
  Derives maximum chunk length from VBV buffer bounds to guarantee files do not exceed plan upload limits.
- **Rigid Body Alignment**:
  Automatically compensates for per-chunk coordinate resets by computing Yaw rotation and horizontal offsets across shared frame intervals.
- **Diagnostic Quality Reports**:
  Evaluates angular discrepancies, root position offsets, temporal lag, and angular acceleration spikes per seam, exported as standalone HTML and JSON reports.
- **Dual Interfaces**:
  Includes an accessible PySide6 graphical user interface and an automated command-line interface (Typer) for headless workflows.

---

## Prerequisites and Installation

### Requirements

- **Python**: 3.10 or later (3.12 recommended)
- **FFmpeg / ffprobe**: 6.0 or later (7.0 recommended, available on `PATH` or in `~/.local/bin`)
- **Operating Systems**: Windows 10/11, macOS 13+, Linux (Ubuntu 22.04+)

### Installation

```bash
# Clone repository
git clone https://github.com/MotoYucchi/QuickMagic_Split-Stitch.git
cd QuickMagic_Split-Stitch

# Setup virtual environment with uv and install dependencies
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

Ensure FFmpeg and ffprobe are installed on your system:
- Ubuntu: `sudo apt install ffmpeg`
- macOS: `brew install ffmpeg`
- Windows: `winget install Gyan.FFmpeg`

---

## Usage

### 1. Graphical User Interface (GUI)

Recommended for interactive, desktop usage:

```bash
splitstitch gui
```

#### Splitting Tab
1. Drag and drop your source video into the input field.
2. Select your QuickMagic plan tier (Free, Basic, Pro, Max, Studio).
3. Select the processing mode (Recommended: "High-Fidelity / Preserve All Frames").
4. Review the simulation card displaying chunk counts and estimated file sizes.
5. Click **Execute Video Splitting**. Slices will be saved inside the `upload/` folder.

#### Stitching Tab
1. Select the `session_manifest.json` generated during splitting.
2. Select the directory containing the motion files downloaded from QuickMagic.
3. Specify the merged output destination (e.g., `Merged_Dance_60fps.fbx`).
4. Click **Execute Motion Stitching**.

---

### 2. Command Line Interface (CLI)

Ideal for batch workflows and script integration:

```bash
# 1. Analyze video stream
splitstitch probe input_60fps.mp4

# 2. Dry-run chunk planning without encoding
splitstitch plan --input input_60fps.mp4 --plan free --mode stretch

# 3. Slice and encode video chunks
splitstitch split \
  --input input_60fps.mp4 \
  --plan free \
  --mode stretch \
  --outdir ./session_dance/

# 4. Verify encoded chunk integrity
splitstitch verify --session ./session_dance/

# 5. Stitch motion chunks back together
splitstitch stitch \
  --manifest ./session_dance/session_manifest.json \
  --motion-dir ./downloaded_motions/ \
  --output ./final_motions/Dance_Merged_60fps.bvh \
  --report ./final_motions/qc_report.html
```

---

## Supported Formats

| Format | Extension | Implementation | Timebase | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **BVH** | `.bvh` | Native parser & exporter | Arbitrary (Rational FPS) | Supports hierarchies, channels, Euler angle unwrap, and standard FPS snapping. |
| **FBX** | `.fbx` | Binary node I/O + Template substitution | Arbitrary (KTime) | Uses Chunk #1 FBX as a structural template and replaces AnimationCurve arrays (`KeyTime` / `KeyValueFloat`). Preserves meshes and rigs. |
| **VMD** | `.vmd` | Binary record I/O | Up to 60 fps | Supported up to 60 fps in MMD and compatible tools (such as MikuMikuMoving). Clips up to 60 fps are preserved directly; clips exceeding 60 fps (e.g. 120 fps) are automatically resampled to 60 fps. Supports morph expressions. |

> **Note**: Proprietary vendor presets such as 3ds Max BIP, Cinema 4D native format, or iClone RLMotion cannot be directly stitched due to unpublished container specifications. We recommend exporting as standard FBX or BVH from QuickMagic.

---

## Limitations and Technical Considerations

1. **AI Estimator Dynamics under Time Stretch**:
   - Time-stretching (e.g. slowing 60 fps to 30 fps) successfully retains all pose samples. However, if the underlying cloud model relies on strong temporal priors (such as gravity-based ground contact estimation), the character may exhibit a slight floating or low-gravity movement characteristic.
2. **Platform Terms of Service**:
   - When utilizing frame-rate scaling techniques on restricted subscription tiers, please ensure compliance with the platform's fair-use policies and service agreements.
3. **Subject Constraints**:
   - The pipeline assumes a single subject in continuous capture. Footage featuring multiple overlapping persons, abrupt camera cuts, or prolonged frame exits may lead to joint tracking discontinuity across chunk boundaries.
4. **VMD Format Frame Rate Support (Up to 60 fps)**:
   - Vocaloid Motion Data (.vmd) records keyframes using integer frame indices. MMD and compatible tools (such as MikuMikuMoving) support 60 fps motion playback. Split & Stitch preserves motion up to 60 fps (including 24, 30, and 60 fps) directly in VMD. Motions exceeding 60 fps (such as 120 fps) are automatically resampled to the 60 fps ceiling upon export (use FBX or BVH if you need to retain 120 fps natively).

---

## Directory Layout

```text
QuickMagic_Split-Stitch/
├── pyproject.toml              # Build config and dependency definitions
├── README.md                   # English documentation
├── README.ja.md                # Japanese documentation
├── docs/                       # Technical documentation
│   ├── design_plan.md          # Complete design plan
│   ├── architecture.md         # System architecture & dataflow
│   ├── fps_scaling_theory.md   # Mathematical theory of FPS scaling
│   ├── supported_formats.md    # Format specifications & codec details
│   ├── manifest_spec.md        # Session manifest specification
│   ├── cli_reference.md        # Comprehensive CLI command reference
│   └── troubleshooting.md      # Common failure cases & solutions
├── src/splitstitch/
│   ├── config/plans.yaml       # QuickMagic plan specification database
│   ├── core/                   # Slicing, probing, and encoding engine
│   ├── motion/                 # Alignment, seam selection, and blending
│   ├── codecs/                 # BVH, FBX, and VMD I/O implementations
│   ├── cli/                    # CLI commands (Typer)
│   └── gui/                    # Desktop GUI (PySide6)
└── tests/                      # Automated unit, property, and E2E tests
```

---

## Testing

Run the automated test suite with pytest:

```bash
source .venv/bin/activate
pytest -v
```

The suite includes property-based tests verifying chunk coverage invariants (Hypothesis), FFmpeg end-to-end splitting and verification, and round-trip codec tests.

---

## Author

- **MotoYucchi** ([GitHub](https://github.com/MotoYucchi))

---

## Disclaimer

This project is an independent open-source tool and is not affiliated, endorsed, or associated with QuickMagic or its parent company. The developers assume no liability for account status, subscription quotas, or output data resulting from the use of this software.
