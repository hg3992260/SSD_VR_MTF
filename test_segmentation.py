import os
import sys
import time

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "frame", "SAM-Med3D-main"))

from segmentation.pipeline import SegmentationPipeline
from segmentation.preprocessor import Preprocessor
from segmentation.sam_adapter import SAMMed3DAdapter
from segmentation.postprocessor import Postprocessor
from segmentation.config import DEFAULT_HU_WINDOW

import SimpleITK as sitk


def read_dicom(path: str) -> sitk.Image:
    if os.path.isdir(path):
        reader = sitk.ImageSeriesReader()
        dicom_files = reader.GetGDCMSeriesFileNames(path)
        if not dicom_files:
            raise RuntimeError(f"No DICOM series found in: {path}")
        reader.SetFileNames(dicom_files)
        image = reader.Execute()
    else:
        image = sitk.ReadImage(path)
    print(f"DICOM loaded: {image.GetSize()} voxels, spacing {image.GetSpacing()}")
    return image


def main():
    dicom_path = "C:/Users/chris/Desktop/SSD+VR/18"
    print("=== SAM-Med3D Vessel Segmentation Auto Test ===")
    print(f"Data: {dicom_path}\n")

    t0 = time.time()

    print("[1/5] Reading DICOM...")
    image = read_dicom(dicom_path)

    print("[2/5] Preprocessing (HU window + resample + normalize)...")
    preproc = Preprocessor(hu_window=DEFAULT_HU_WINDOW, target_spacing=(0.8, 0.8, 0.8))
    processed = preproc.run(image)
    nifti_path = preproc.to_nifti_temp(processed, prefix="auto_test_")
    print(f"  Size after preproc: {processed.GetSize()}, spacing: {processed.GetSpacing()}")
    print(f"  Temp NIfTI: {nifti_path}")

    print("[3/5] SAM-Med3D Tiled Inference (128^3 tiles @ stride 64)...")
    sam = SAMMed3DAdapter()
    sam.load_model()

    t1 = time.time()
    vessel_prob = sam.predict_vessel_prior(nifti_path, num_clicks=1)
    t_infer = time.time() - t1
    print(f"  Inference done: {vessel_prob.shape}, time {t_infer:.1f}s ({t_infer/60:.1f}min)")
    print(f"  prob range: [{vessel_prob.min():.4f}, {vessel_prob.max():.4f}]")

    binary_mask = (vessel_prob > 0.2).astype("uint8")
    pos_voxels = int(binary_mask.sum())
    total_voxels = binary_mask.size
    print(f"  >0.2 positive voxels: {pos_voxels:,} / {total_voxels:,} ({100*pos_voxels/total_voxels:.2f}%)")

    import torch
    torch.cuda.empty_cache()

    print("[4/5] Postprocessing (connected components + closing)...")
    t2 = time.time()
    postproc = Postprocessor(min_component_size=500, closing_kernel=3)
    cleaned_mask = postproc.run(binary_mask)
    t_post = time.time() - t2

    spacing = processed.GetSpacing()
    stats = postproc.compute_stats(cleaned_mask, spacing)

    preproc.cleanup_temp(nifti_path)

    print("[5/5] Stats:")
    print(f"  Postproc time: {t_post:.1f}s")
    print(f"  Vessel volume: {stats['volume_cm3']:.1f} cm^3")
    print(f"  Voxels:        {stats['total_voxels']:,}")
    print(f"  Components:    {stats['num_components']}")
    print(f"  Largest:       {stats['largest_component']:,}")
    if stats["component_sizes"]:
        print(f"  Top 5:         {stats['component_sizes'][:5]}")

    total_time = time.time() - t0
    print(f"\n=== Test Complete ===")
    print(f"Total: {total_time:.1f}s ({total_time/60:.1f}min)")
    print(f"  - Inference: {t_infer:.1f}s")
    print(f"  - Postproc:  {t_post:.1f}s")

    out_nifti = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp", "segmentation", "auto_test_result.nii.gz")
    os.makedirs(os.path.dirname(out_nifti), exist_ok=True)
    cleaned = preproc.numpy_to_sitk(cleaned_mask, spacing, processed.GetOrigin(), processed)
    sitk.WriteImage(cleaned, out_nifti)
    print(f"Saved: {out_nifti}")

    if pos_voxels > 0 and stats["num_components"] > 0:
        print("=== SUCCESS ===")
        return 0
    else:
        print("=== WARNING: no vessels detected ===")
        return 1


if __name__ == "__main__":
    sys.exit(main())
