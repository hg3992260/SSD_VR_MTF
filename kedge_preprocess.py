#!/usr/bin/env python
"""PCCT K-edge material decomposition preprocessing pipeline.
Phase A: JPEG2000 sinogram extraction
Phase B: K-edge material decomposition (I, Gd, Au, Bi)
Phase C: FBP reconstruction → NIfTI volumes
"""
import os, struct, time, io, json
import numpy as np
import pydicom
import glymur
import nibabel as nib
from scipy.ndimage import gaussian_filter
from scipy import signal
from typing import List, Tuple

# ============================================================
# CONFIG (EDIT FOR YOUR PATHS)
# ============================================================
DICOM_DIR = r"D:\xl\00020006\00020006"
OUTPUT_DIR = r"C:\Users\chris\Desktop\SSD+VR\kedge_output"
RECON_SIZE = 1024
RECON_NX = RECON_SIZE
RECON_NY = RECON_SIZE
N_BINS = 8
N_CHANNELS = 256
N_ZROWS = 32
N_VIEWS = 124  # 62 G1 + 62 G3 interleaved

# ============================================================
# K-edge mass attenuation coefficients (tabulated)
# μ(E) for each material at reference energies (cm²/g)
# ============================================================
# Mean energies for 8 bins (keV)
BIN_ENERGIES = np.array([20.0, 30.5, 35.5, 43.0, 55.0, 71.0, 92.5, 112.0])

BIN_LOW = [10.0, 28.0, 33.0, 38.0, 48.0, 62.0, 80.0, 105.0]
BIN_HIGH = [28.0, 33.0, 38.0, 48.0, 62.0, 80.0, 105.0, 130.0]
# K-edge energies and jump ratios (tabulated)
KEDGE = {
    'I':  {'e': 33.2, 'jump': 6.4,  'p': -2.8},
    'Gd': {'e': 50.2, 'jump': 6.3,  'p': -2.6},
    'Au': {'e': 80.7, 'jump': 5.2,  'p': -2.4},
    'Bi': {'e': 90.5, 'jump': 4.8,  'p': -2.3},
}
BIN_ENERGIES = np.array([19.0, 30.5, 35.5, 43.0, 55.0, 71.0, 92.5, 117.5])

def _mu_photoelectric(E: np.ndarray) -> np.ndarray:
    return (E / 30.0) ** -3.2

def _mu_compton(E: np.ndarray) -> np.ndarray:
    return 0.5 / (1.0 + 0.02 * E) + 0.5 / (1.0 + 0.005 * E) ** 3

def _mu_material(E: np.ndarray, kedge_keV: float, jump: float, power: float) -> np.ndarray:
    """Attenuation with K-edge discontinuity."""
    base = (E / 30.0) ** power
    jump_mask = (E >= kedge_keV).astype(float)
    return base * (1.0 + (jump - 1.0) * jump_mask)

def _attenuation_coeffs(energies: np.ndarray) -> np.ndarray:
    """Compute attenuation coefficients for 6 basis materials at given energies.
    Uses proper K-edge discontinuity modeling.
    Returns shape (6, N) matrix. Basis order: Photoelectric, Compton, I, Gd, Au, Bi.
    """
    E = np.asarray(energies, dtype=np.float64)
    mu_pe = _mu_photoelectric(E)
    mu_cs = _mu_compton(E)
    mu_i = _mu_material(E, KEDGE['I']['e'], KEDGE['I']['jump'], KEDGE['I']['p'])
    mu_gd = _mu_material(E, KEDGE['Gd']['e'], KEDGE['Gd']['jump'], KEDGE['Gd']['p'])
    mu_au = _mu_material(E, KEDGE['Au']['e'], KEDGE['Au']['jump'], KEDGE['Au']['p'])
    mu_bi = _mu_material(E, KEDGE['Bi']['e'], KEDGE['Bi']['jump'], KEDGE['Bi']['p'])
    # Normalize each basis to [0, 1] range
    mats = [mu_pe, mu_cs, mu_i, mu_gd, mu_au, mu_bi]
    mats = [m / (m.max() + 1e-12) for m in mats]
    return np.vstack(mats)


def read_pcct_sinogram(dicom_path: str) -> np.ndarray:
    """Extract 8-bin sinogram from PCCT DICOM private tag.
    Returns ndarray (N_BINS, N_VIEWS, N_CHANNELS) - mean across z-rows."""
    ds = pydicom.dcmread(dicom_path, specific_tags=[0xefe11001])
    data = ds[0xefe1, 0x1001].value

    jp2c = b'jp2c'
    positions = []
    pos = -1
    while True:
        pos = data.find(jp2c, pos + 1)
        if pos == -1:
            break
        positions.append(pos)
    if not positions:
        positions = []
        pos = -1
        while True:
            pos = data.find(jp2c, pos + 1)
            if pos == -1: break
            positions.append(pos)

    # G0(0-63)=Ref A, G1(64-127)=Sino A, G2(128-191)=Ref B, G3(192-255)=Sino B
    # Active in G1: 64-71, 72-79, 80-87, 88-95, 96-103, 104-111, 112-119, 121-127 (62 active)
    group1_active = list(range(64, 72)) + list(range(72, 80)) + list(range(80, 88)) + \
                    list(range(88, 96)) + list(range(96, 104)) + list(range(104, 112)) + \
                    list(range(112, 120)) + list(range(121, 127))
    group3_active = [i + 128 for i in group1_active]  # G3 has same indices as G1

    # Decode active codestreams
    sino_bins = np.zeros((N_BINS, len(group1_active), N_CHANNELS), dtype=np.float32)
    for vi, cs_idx in enumerate(group1_active):
        start = positions[cs_idx] + 4
        end = positions[cs_idx + 1] if cs_idx + 1 < len(positions) else len(data)
        jp2k_bytes = data[start:end]
        if len(jp2k_bytes) < 100:
            continue
        tpath = os.path.join(OUTPUT_DIR, f'_tmp_{cs_idx}.jp2k')
        with open(tpath, 'wb') as fh:
            fh.write(jp2k_bytes)
        try:
            jp2 = glymur.Jp2k(tpath)
            img = jp2[:].astype(np.float32)
            # img is 256×256: 8 bins × 32 rows = 256 rows
            for b in range(N_BINS):
                row_start = b * N_ZROWS
                row_end = (b + 1) * N_ZROWS
                sino_bins[b, vi, :] = img[row_start:row_end, :].mean(axis=0)
        except Exception:
            pass
        os.remove(tpath)

    # Also decode G3 to get 60 views total
    sino_bins_g3 = np.zeros((N_BINS, len(group3_active), N_CHANNELS), dtype=np.float32)
    for vi, cs_idx in enumerate(group3_active):
        start = positions[cs_idx] + 4
        end = positions[cs_idx + 1] if cs_idx + 1 < len(positions) else len(data)
        jp2k_bytes = data[start:end]
        if len(jp2k_bytes) < 100:
            continue
        tpath = os.path.join(OUTPUT_DIR, f'_tmp_{cs_idx}.jp2k')
        with open(tpath, 'wb') as fh:
            fh.write(jp2k_bytes)
        try:
            jp2 = glymur.Jp2k(tpath)
            img = jp2[:].astype(np.float32)
            for b in range(N_BINS):
                row_start = b * N_ZROWS
                row_end = (b + 1) * N_ZROWS
                sino_bins_g3[b, vi, :] = img[row_start:row_end, :].mean(axis=0)
        except Exception:
            pass
        os.remove(tpath)

    # Interleave G1 and G3
    n_views = len(group1_active) + len(group3_active)
    min_views = min(len(group1_active), len(group3_active))
    n_views = 2 * min_views
    sino = np.zeros((N_BINS, n_views, N_CHANNELS), dtype=np.float32)
    for b in range(N_BINS):
        sino[b, 0:n_views:2] = sino_bins[b, :min_views]
        sino[b, 1:n_views:2] = sino_bins_g3[b, :min_views]
    return sino


def compute_kedge_weights(sino: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """K-edge material decomposition on 8-bin sinogram.
    Uses Tikhonov-regularized least squares to stabilize the ill-posed inversion.
    Returns 4 material sinogram weights: I, Gd, Au, Bi (each same shape as sino[0])."""
    n_views = sino.shape[1]
    n_ch = sino.shape[2]
    total = n_views * n_ch

    A = _attenuation_coeffs(BIN_ENERGIES)  # (6, 8)

    # Tikhonov regularization: A @ A.T + λI
    reg_lambda = 0.02
    I_reg = np.eye(6)
    I_reg[0, 0] = 0.001  # PE: nearly no penalty
    I_reg[1, 1] = 0.001  # CS: nearly no penalty
    AAT_reg = A @ A.T + reg_lambda * I_reg  # (6, 6)

    try:
        inv_AAT = np.linalg.solve(AAT_reg, np.eye(6))
    except np.linalg.LinAlgError:
        inv_AAT = np.linalg.pinv(AAT_reg)

    # Reshape sino to (total_pixels, 8)
    S = sino.reshape(N_BINS, total).T  # (total, 8)
    # c = (A·Aᵀ + λI)⁻¹ · A · s
    coeffs = S @ A.T @ inv_AAT.T  # (total, 6)

    # Extract material weights (columns 2-5)
    c_i = coeffs[:, 2].reshape(n_views, n_ch)
    c_gd = coeffs[:, 3].reshape(n_views, n_ch)
    c_au = coeffs[:, 4].reshape(n_views, n_ch)
    c_bi = coeffs[:, 5].reshape(n_views, n_ch)

    return c_i, c_gd, c_au, c_bi


def fbp_reconstruct(sinogram: np.ndarray, output_shape: Tuple[int, int],
                    sdd: float = 1040.0, sad: float = 570.0,
                    detector_pitch: float = 0.2114,
                    n_views: int = 124, n_det: int = 256,
                    n_slices: int = 1) -> np.ndarray:
    """Filtered back-projection reconstruction with optional CuPy GPU acceleration."""
    try:
        import cupy as cp
        _ = cp.array([1.0])
        return _fbp_gpu(sinogram, output_shape, n_views, n_det, n_slices, detector_pitch)
    except Exception:
        return _fbp_cpu(sinogram, output_shape, n_views, n_det, n_slices, detector_pitch)


def _fbp_cpu(sinogram: np.ndarray, output_shape: Tuple[int, int],
             n_views: int, n_det: int, n_slices: int,
             detector_pitch: float) -> np.ndarray:
    """CPU version — single-slice Ram-Lak + backprojection loop."""
    nx, ny = output_shape
    n_slices_actual = min(n_slices, sinogram.shape[0] if sinogram.ndim >= 3 else 1)
    reco = np.zeros((n_slices_actual, nx, ny), dtype=np.float32)
    d_theta = 2.0 * np.pi / n_views
    ramp = np.fft.ifftshift(np.abs(np.fft.fftfreq(n_det * 2, 1.0)) * 2.0)
    det_half_mm = n_det * detector_pitch / 2.0
    cx, cy = nx // 2, ny // 2
    max_radius = min(cx, cy) - 2
    x_grid, y_grid = np.meshgrid(np.arange(nx) - cx, np.arange(ny) - cy, indexing='ij')
    mask = (x_grid ** 2 + y_grid ** 2) <= (max_radius ** 2)
    mask_f = mask.astype(np.float32)
    np_sin = np.sin
    np_cos = np.cos

    for sl in range(n_slices_actual):
        proj = sinogram[sl] if sinogram.ndim >= 3 else sinogram
        if proj.ndim == 1:
            proj = proj.reshape(1, -1)
        proj = np.ascontiguousarray(proj[:, :n_det], dtype=np.float32)

        proj_pad = np.zeros((n_views, n_det * 2), dtype=np.float32)
        proj_pad[:, n_det // 2:n_det // 2 + n_det] = proj
        filtered = np.fft.ifft(np.fft.fft(proj_pad, axis=-1) * ramp, axis=-1).real
        filtered = np.ascontiguousarray(filtered[:, n_det // 2:n_det // 2 + n_det])

        _reco = np.zeros((nx, ny), dtype=np.float32)
        for vi in range(n_views):
            angle = vi * d_theta
            t = x_grid * np_cos(angle) + y_grid * np_sin(angle)
            tn = np.clip((t / det_half_mm + 1.0) * (n_det - 1) * 0.5, 0, n_det - 1.001)
            ti = tn.astype(np.int32)
            v = filtered[vi]
            _reco += (v[ti] * (1.0 - tn + ti) + v[ti + 1] * (tn - ti)) * mask_f
        reco[sl] = _reco * d_theta / np.pi
        if (sl + 1) % 200 == 0 or sl == n_slices_actual - 1:
            print(f"    FBP CPU [{sl+1}/{n_slices_actual}]")
            import sys; sys.stdout.flush()
    return reco


def _fbp_gpu(sinogram: np.ndarray, output_shape: Tuple[int, int],
             n_views: int, n_det: int, n_slices: int,
             detector_pitch: float) -> np.ndarray:
    """GPU-accelerated FBP. Processes single or batched materials simultaneously.
    sinogram shape: (n_slices, n_views, n_det) for single, or (n_mats, n_slices, n_views, n_det) for batch.
    """
    import cupy as cp
    nx, ny = output_shape
    is_batch = sinogram.ndim >= 4
    if is_batch:
        n_mats = sinogram.shape[0]
        n_slices_actual = min(n_slices, sinogram.shape[1])
    else:
        n_mats = 1
        n_slices_actual = min(n_slices, sinogram.shape[0] if sinogram.ndim >= 3 else 1)
    d_theta = 2.0 * np.pi / n_views
    det_half_mm = n_det * detector_pitch / 2.0
    cx, cy = nx // 2, ny // 2

    x = cp.arange(nx, dtype=cp.float32) - cx
    y = cp.arange(ny, dtype=cp.float32) - cy
    xx, yy = cp.meshgrid(x, y, indexing='ij')
    mask = ((xx ** 2 + yy ** 2) <= (min(cx, cy) - 2) ** 2).astype(cp.float32)

    angles = cp.arange(n_views, dtype=cp.float32) * d_theta
    cos_a = cp.cos(angles)[:, None, None]
    sin_a = cp.sin(angles)[:, None, None]

    ramp = cp.fft.ifftshift(cp.abs(cp.fft.fftfreq(n_det * 2, 1.0)) * 2.0)

    reco = cp.zeros((n_mats, n_slices_actual, nx, ny), dtype=cp.float32)
    for sl in range(n_slices_actual):
        if is_batch:
            proj = cp.asarray(sinogram[:, sl, :, :n_det], dtype=cp.float32, order='C')
        else:
            p = sinogram[sl] if sinogram.ndim >= 3 else sinogram
            if p.ndim == 1: p = p.reshape(1, -1)
            proj = cp.asarray(p[:, :n_det], dtype=cp.float32, order='C')[None, :, :]

        # Batched Ram-Lak: (n_mats, n_views, n_det) → pad+filter → (n_mats, n_views, n_det)
        proj_pad = cp.zeros((n_mats, n_views, n_det * 2), dtype=cp.float32)
        proj_pad[:, :, n_det // 2:n_det // 2 + n_det] = proj
        filtered = cp.fft.ifft(cp.fft.fft(proj_pad, axis=-1) * ramp, axis=-1).real
        filtered = filtered[:, :, n_det // 2:n_det // 2 + n_det]  # (n_mats, n_views, n_det)

        t_all = xx * cos_a + yy * sin_a
        tn = cp.clip((t_all / det_half_mm + 1.0) * (n_det - 1) * 0.5, 0, n_det - 1.001)
        ti = tn.astype(cp.int32)
        frac = tn - ti

        _reco = cp.zeros((n_mats, nx, ny), dtype=cp.float32)
        for vi in range(n_views):
            v = filtered[:, vi, :]  # (n_mats, n_det)
            _reco[:, :, :] += (v[:, ti[vi]] * (1.0 - frac[vi]) + v[:, ti[vi] + 1] * frac[vi]) * mask
        reco[:, sl, :, :] = _reco * d_theta / cp.pi

        if (sl + 1) % 200 == 0 or sl == n_slices_actual - 1:
            print(f"    FBP GPU [{sl+1}/{n_slices_actual}] {'batch' if is_batch else ''}")
            import sys; sys.stdout.flush()

    cp.cuda.Stream.null.synchronize()
    return cp.asnumpy(reco)


def process_all_slices():
    """Full pipeline: extract sinograms → decompose → FBP → save NIfTI."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    files = sorted(os.listdir(DICOM_DIR))
    n_total = len(files)
    print(f"Found {n_total} DICOM files in {DICOM_DIR}")

    # Read first file for geometry (needed regardless of cache)
    ds0 = pydicom.dcmread(os.path.join(DICOM_DIR, files[0]))
    try:
        px = float(ds0.PixelSpacing[0])
    except Exception:
        px = 0.2114
    try:
        sdd = float(ds0.DistanceSourceToDetector)
        sad = float(ds0.DistanceSourceToPatient)
    except Exception:
        sdd, sad = 1040.0, 570.0
    sl_thick = float(getattr(ds0, 'SliceThickness', 0.274))
    sl_spacing = float(getattr(ds0, 'SpacingBetweenSlices', 0.137))
    fov_mm = float(getattr(ds0, 'ReconstructionDiameter', 433))
    vox_mm = fov_mm / RECON_SIZE

    sino_path = os.path.join(OUTPUT_DIR, 'sinogram_8bins.npy')
    t0 = time.time()
    if os.path.exists(sino_path):
        print(f"发现已有 sinogram 缓存: {sino_path}，跳过 Phase A")
        sino_batch = np.load(sino_path, mmap_mode='r')
        n_sino = sino_batch.shape[1]
        n_loaded = n_sino
    else:
        n_sino = len(files)
        n_views = N_VIEWS
        n_ch = N_CHANNELS
        t0 = time.time()

        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        n_workers = max(1, min(6, os.cpu_count() or 4))
        print(f"Phase A: {n_sino} files, {n_workers} threads (ThreadPool, zero-copy)")

        sino_batch = np.zeros((N_BINS, n_sino, n_views, n_ch), dtype=np.float32)
        lock = threading.Lock()
        done, failed = 0, 0

        def _process_one(fi_fname):
            fi, fname = fi_fname
            try:
                sino = read_pcct_sinogram(os.path.join(DICOM_DIR, fname))
                nv = min(sino.shape[1], n_views)
                return fi, True, sino[:, :nv, :n_ch]
            except Exception as e:
                return fi, False, str(e)

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_process_one, (fi, fname)): fi for fi, fname in enumerate(files)}
            for future in as_completed(futures):
                fi, ok, data = future.result()
                if ok:
                    sino_batch[:, fi, :, :] = data[:, :, :]
                    with lock:
                        done += 1
                else:
                    with lock:
                        failed += 1
                with lock:
                    total = done + failed
                if total % 100 == 0 or total == n_sino:
                    elapsed = time.time() - t0
                    rate = total / elapsed if elapsed > 0 else 0
                    eta = (n_sino - total) / rate if rate > 0 else 0
                    print(f"  Sinogram [{total}/{n_sino}] {total/n_sino*100:.0f}%  "
                          f"{elapsed:.0f}s  ETA {eta:.0f}s  failed={failed}")
                    import sys; sys.stdout.flush()

        np.save(sino_path, sino_batch)
        print(f"Sinogram extraction complete: {done}/{n_sino} OK, {failed} failed, "
              f"{time.time() - t0:.0f}s")
    # After cache hit or fresh extraction, ensure n_sino is set
    n_sino = len(files)
    n_views = N_VIEWS
    n_ch = N_CHANNELS

    n_views = min(n_views, sino_batch.shape[2])

    # K-edge decomposition
    print("\nPerforming K-edge material decomposition...")
    t_phase_start = time.time()
    mats = ['iodine', 'gadolinium', 'gold', 'bismuth']
    sinos = {m: np.zeros((n_sino, n_views, n_ch), dtype=np.float32) for m in mats}

    for fi in range(n_sino):
        if fi % 100 == 0 or fi == 0 or fi == n_sino - 1:
            elapsed = time.time() - t_phase_start
            pct = (fi / n_sino) * 100
            rate = fi / elapsed if elapsed > 0 else 0
            eta = (n_sino - fi) / rate if rate > 0 else 0
            print(f"  Decompose [{fi}/{n_sino}] {pct:.0f}%  {elapsed:.0f}s  ETA {eta:.0f}s")
            import sys; sys.stdout.flush()
        sino_slice = sino_batch[:, fi, :, :]
        i, gd, au, bi = compute_kedge_weights(sino_slice)
        sinos['iodine'][fi] = i
        sinos['gadolinium'][fi] = gd
        sinos['gold'][fi] = au
        sinos['bismuth'][fi] = bi

    print(f"K-edge decomposition complete: {time.time() - t_phase_start:.0f}s")

    # FBP reconstruction for each material
    print("\nFBP reconstruction...")
    t_phase_start = time.time()

    # Batch reconstruct all missing materials simultaneously
    missing_mats = [(mi, m) for mi, m in enumerate(mats)
                    if not os.path.exists(os.path.join(OUTPUT_DIR, f'{m}.nii.gz'))]
    if not missing_mats:
        print("  所有物质已存在，跳过 FBP")
    else:
        n_missing = len(missing_mats)
        batch_sinos = np.zeros((n_missing, n_sino, n_views, n_ch), dtype=np.float32)
        for bi, (mi, mat_name) in enumerate(missing_mats):
            sinogram = sinos[mat_name]
            proj_mean = sinogram.mean(axis=1)  # (n_sino, n_ch)
            batch_sinos[bi] = np.tile(proj_mean[:, np.newaxis, :], (1, n_views, 1))

        print(f"  Batch FBP: {n_missing} materials ({[m[1] for m in missing_mats]})")
        volumes = fbp_reconstruct(batch_sinos, (RECON_NX, RECON_NY),
                                  sdd=sdd, sad=sad, detector_pitch=px,
                                  n_views=n_views, n_det=n_ch,
                                  n_slices=n_sino)

        for bi, (mi, mat_name) in enumerate(missing_mats):
            volume = volumes[bi]
            try:
                import cupy as cp
                vol_gpu = cp.asarray(volume, dtype=cp.float32)
                from cupyx.scipy.ndimage import gaussian_filter as cp_gaussian
                vol_gpu = cp_gaussian(vol_gpu, sigma=1.0)
                vol_max = float(cp.abs(vol_gpu).max())
                vol_norm_gpu = vol_gpu / max(vol_max, 1e-8)
                vol_int16 = cp.asnumpy((vol_norm_gpu * 32767).astype(cp.int16))
                del vol_gpu, vol_norm_gpu
            except Exception:
                volume = gaussian_filter(volume, sigma=1.0)
                vol_norm = volume / (np.abs(volume).max() + 1e-8)
                vol_int16 = (vol_norm * 32767).astype(np.int16)
            nii = nib.Nifti1Image(vol_int16, np.diag([vox_mm, vox_mm, sl_spacing, 1]))
            outpath = os.path.join(OUTPUT_DIR, f'{mat_name}.nii.gz')
            nib.save(nii, outpath)
            print(f"    Saved {mat_name}: {outpath}")
            print(f"    FBP batch [{bi+1}/{n_missing}] complete ({time.time()-t_phase_start:.0f}s)")
            import sys; sys.stdout.flush()

    total_elapsed = time.time() - t0
    print(f"\n{'='*50}")
    print(f"ALL COMPLETE. Total time: {total_elapsed:.0f}s = {total_elapsed/60:.1f}min")
    print(f"Output: {OUTPUT_DIR}/{{iodine,gadolinium,gold,bismuth}}.nii.gz")
    print(f"{'='*50}")


if __name__ == '__main__':
    process_all_slices()
