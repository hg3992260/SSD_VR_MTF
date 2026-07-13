# SSD+VR Fusion Viewer

Figure8-style SSD+VR fused volume rendering viewer for DICOM medical imaging, with segmentation and K-edge spectral CT support.

## Features

- **12 rendering modes**: stable, HD surface, cinematic, nature channels, figure8, layered, frangi channel, bone monochrome, 2D TF (Kniss 2001), spectral, exposure render (CUDA), dual volume
- **SSD+VR fusion**: independent transfer functions with over-operator blending
- **Preprocessing**: NLM denoising, CLAHE enhancement, Frangi vesselness, distance-field periosteal aggregation, 2D transfer function surface extraction
- **Segmentation**: SAM-Med3D + nnU-Net vessel segmentation with SAM-guided prompts
- **K-edge PCCT**: multi-material spectral CT visualization (Iodine, Gadolinium, Gold, Bismuth)
- **Modern UI**: PySide6 + PyCt6 themeable widgets with dark/light mode support

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Launch viewer
python ssd_vr_viewer.py --input /path/to/dicom_folder
```

## Requirements

- Python 3.10+
- ParaView/pvpython or VTK with GPU support
- CUDA-compatible GPU (for Exposure Render and CuPy-accelerated Frangi)
- 10+ GB VRAM recommended

## Project Structure

```
.
├── ssd_vr_viewer.py      # Main application (3645 lines)
├── kedge_preprocess.py   # K-edge spectral CT preprocessing
├── extract2.py           # DICOM data extraction utilities
├── extract_html.py       # HTML report generation
├── presets.xml           # Slicer-style transfer function presets
├── segmentation/         # Vessel segmentation pipeline
│   ├── pipeline.py       # Main pipeline (QThread-based)
│   ├── preprocessor.py   # HU windowing, resampling
│   ├── postprocessor.py  # Connected components, morphological ops
│   ├── sam_adapter.py    # SAM-Med3D model interface
│   ├── nnunet_adapter.py # nnU-Net model interface
│   ├── visualizer.py     # 3D surface/volume rendering for masks
│   └── config.py         # Default parameters
├── exposure-render-master/ # ErCore CUDA path tracer (C++)
├── MC_RDenoiser-main/    # Monte Carlo denoiser
├── frame/
│   ├── nnUNet-master/    # nnU-Net v2 segmentation framework
│   └── SAM-Med3D-main/   # SAM-Med3D foundation model
├── key-paper/            # Reference papers
└── tests/
    ├── test_crash.py
    ├── test_multisample.py
    ├── test_ospray.py
    ├── test_range.py
    ├── test_segmentation.py
    ├── test_sitk_vtk.py
    └── test_viewer.py
```

## Modes

| Mode | Description |
|------|-------------|
| Stable | CPU/GPU base volume rendering |
| HD Surface | High-density bone surface emphasis |
| Cinematic | CR path-traced with 5-point lighting |
| Nature Channels | Skull microchannel visualization (PDF) |
| Figure8 | Cortical openings + marrow mosaic |
| Layered | 4-layer virtual volume (outer/inner plate + diploe) |
| Frangi Channel | Dark-tube microchannel enhancement |
| Bone Monochrome | Pure VR bone with semi-transparent marrow |
| 2D TF | Kniss 2001 interface separation |
| Spectral | CR spectral look with cyan lungs + crimson vessels |
| Exposure Render | CUDA path tracing via ErCore.dll |
| Dual Volume | Two independent threshold regions |

## License

MIT
