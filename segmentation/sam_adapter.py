import os
import sys

import numpy as np
import SimpleITK as sitk

from .config import SAM_MED3D_DIR, SAM_CKPT


def _setup_sys_path():
    if SAM_MED3D_DIR not in sys.path:
        sys.path.insert(0, SAM_MED3D_DIR)


class SAMMed3DAdapter:
    def __init__(self, checkpoint_path: str = None, device: str = "cuda"):
        _setup_sys_path()
        os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
        self.checkpoint_path = checkpoint_path or SAM_CKPT
        self.device = device
        self._model = None
        self._loaded = False

    def load_model(self):

        if self._loaded:
            return
        import medim

        self._model = medim.create_model(
            "SAM-Med3D",
            pretrained=True,
            checkpoint_path=self.checkpoint_path,
        )
        self._model = self._model.to(self.device)
        self._loaded = True

    def ensure_loaded(self):

        if not self._loaded:
            self.load_model()

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    TILE_SIZE = 128
    STRIDE = 64
    FEATHER_RAMP = 20

    def predict_vessel_prior(
        self,
        nifti_path: str,
        num_clicks: int = 1,
    ) -> np.ndarray:

        self.num_clicks = num_clicks
        self.ensure_loaded()
        import torch
        import torchio as tio
        from utils.click_method import \
            get_next_click3D_torch_no_gt as click_fn

        img = sitk.ReadImage(nifti_path)
        subject = tio.Subject(image=tio.ScalarImage.from_sitk(img))
        subject_canonical = tio.ToCanonical()(subject)

        data_tensor = subject_canonical.image.data.float()
        total_shape = subject_canonical.spatial_shape
        D, H, W = total_shape

        full_prob = np.zeros(total_shape, dtype=np.float32)
        full_weight = np.zeros(total_shape, dtype=np.float32)

        tile = self.TILE_SIZE
        stride = self.STRIDE

        z_starts = list(range(0, D, stride))
        y_starts = list(range(0, H, stride))
        x_starts = list(range(0, W, stride))
        total_tiles = len(z_starts) * len(y_starts) * len(x_starts)
        tile_idx = 0

        for z0 in z_starts:
            for y0 in y_starts:
                for x0 in x_starts:
                    tile_idx += 1
                    z1, y1, x1 = min(z0 + tile, D), min(y0 + tile, H), min(x0 + tile, W)
                    slice_z = slice(z0, z1)
                    slice_y = slice(y0, y1)
                    slice_x = slice(x0, x1)

                    actual_shape = (z1 - z0, y1 - y0, x1 - x0)
                    pad_before = (0, 0, 0)
                    pad_after = (tile - actual_shape[0], tile - actual_shape[1], tile - actual_shape[2])

                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

                    chunk = data_tensor[:, slice_z, slice_y, slice_x].clone()
                    mean = chunk.mean()
                    std = chunk.std()
                    if std > 1e-6:
                        chunk = (chunk - mean) / std
                    if any(p > 0 for p in pad_after):
                        chunk = torch.nn.functional.pad(chunk, (0, pad_after[2], 0, pad_after[1], 0, pad_after[0]))
                    roi = chunk.unsqueeze(0).to(self.device)

                    prob_tile = self._infer_one_tile(roi, click_fn, num_clicks=self.num_clicks)

                    weight_tile = self._feather_weights_3d(actual_shape, pad_after)

                    full_prob[slice_z, slice_y, slice_x] += (
                        prob_tile[:actual_shape[0], :actual_shape[1], :actual_shape[2]]
                        * weight_tile[:actual_shape[0], :actual_shape[1], :actual_shape[2]]
                    )
                    full_weight[slice_z, slice_y, slice_x] += weight_tile[
                        :actual_shape[0], :actual_shape[1], :actual_shape[2]
                    ]

        mask = full_weight > 0
        full_prob[mask] /= full_weight[mask]
        return full_prob

    def _infer_one_tile(self, roi_image, click_fn, num_clicks=1) -> np.ndarray:

        import torch

        pe = self._model.prompt_encoder.get_dense_pe()
        with torch.no_grad():
            image_embeddings = self._model.image_encoder(roi_image)
        p_tm = torch.zeros((roi_image.shape[0], 1) + roi_image.shape[2:], dtype=torch.bool, device=roi_image.device)
        with torch.no_grad():
            prev_low_res_mask = None
            for click_i in range(num_clicks):
                coords, labels = click_fn(p_tm, roi_image, threshold=170)
                pts = coords[0].to(self.device)
                lbs = labels[0].to(self.device)
                sparse, dense = self._model.prompt_encoder(
                    points=(pts, lbs) if pts is not None else None,
                    boxes=None,
                    masks=prev_low_res_mask,
                )
                masks_low, _ = self._model.mask_decoder(
                    image_embeddings=image_embeddings,
                    image_pe=pe,
                    sparse_prompt_embeddings=sparse,
                    dense_prompt_embeddings=dense,
                    multimask_output=False,
                )
                prev_low_res_mask = masks_low
                if click_i < num_clicks - 1:
                    upsampled = torch.nn.functional.interpolate(
                        torch.sigmoid(masks_low.float()),
                        size=(self.TILE_SIZE, self.TILE_SIZE, self.TILE_SIZE),
                        mode="trilinear",
                        align_corners=False,
                    )
                    p_tm = upsampled > 0.5
            low_res_pred = prev_low_res_mask.float()
            low_res_pred = torch.sigmoid(low_res_pred)
            prob = torch.nn.functional.interpolate(
                low_res_pred,
                size=(self.TILE_SIZE, self.TILE_SIZE, self.TILE_SIZE),
                mode="trilinear",
                align_corners=False,
            )
        return prob.squeeze().cpu().numpy()

    @classmethod
    def _feather_weights_3d(cls, actual_shape, pad_after) -> np.ndarray:

        D, H, W = cls.TILE_SIZE, cls.TILE_SIZE, cls.TILE_SIZE
        aD, aH, aW = actual_shape
        r = cls.FEATHER_RAMP
        ramp = np.arange(r, dtype=np.float32) / r
        rev_ramp = ramp[::-1].copy()

        weight = np.ones((D, H, W), dtype=np.float32)

        if aD < D:
            weight[aD:, :, :] = 0.0
            if aD > r:
                weight[aD - r:aD, :, :] *= rev_ramp[:, None, None]
            else:
                weight[:aD, :, :] *= 1.0
        if aH < H:
            weight[:, aH:, :] = 0.0
            if aH > r:
                weight[:, aH - r:aH, :] *= rev_ramp[None, :, None]
        if aW < W:
            weight[:, :, aW:] = 0.0
            if aW > r:
                weight[:, :, aW - r:aW] *= rev_ramp[None, None, :]

        return weight
